# The platform's backtester and data

`engine-backtesting` (`~/dev/engine/engine-backtesting`, package
`backtestingengine`) runs `tradingenginecs` strategies unchanged on recorded
data, and Tardis is the data. These facts are a snapshot of the code, not a
spec; where the source disagrees, a default or a class since renamed, the
source wins: say so, and propose the fix to this file with `/learn`.

## Data

- Tardis feeds in `data/feeds/tardis_csv.py`: `TardisBookSnapshot25Feed`
  (`book_snapshot_25`, one 25-level snapshot per row, emitted as an
  `orderbook_snapshot` event), `TardisDerivativeTickerFeed` (funding rate,
  with `mark_price` and `index_price` forwarded so basis and premium can be
  reconstructed) and `TardisTradesFeed`. Each feed takes `(path,
  exchange_code, symbol)` triples; the exchange code must match what the
  strategy queries (`binance_swap`, not `binance`).
- The book is a sampled 25-level snapshot stream: no deltas, no order ids.
  Fill-on-touch against it misses touches between samples, and queue
  position cannot be computed, only assumed.
- Rows carry the exchange `timestamp` and `local_timestamp`; decide on local
  time. `clock.py` notes the WebSocket sub-streams can arrive slightly out
  of order and keeps callbacks in file order.
- `pipeline/`: `fetch_tardis_bulk.py` downloads, `tardis_ingestor.py` and
  `ensure_data.py` lay the files out (`docs/data_layout.md`),
  `extract_settlements.py` builds the funding settlement series,
  `fetch_cmc.py` pulls reference data.
- `data/quality/validators.py` and `report.py` write `data_quality.json`.
- Research notebooks live in `research/quant-research`; backtest drivers in
  each strategy repo's `backtest_runs/`, never in the engine repo.

## Timeline and determinism

- `timeline.py` sorts every event by `(timestamp_ns, EVENT_PRIORITY
  [event_type], sequence)` and heap-merges the per-feed sorted streams.
  Priority puts the book first and the clock last: `orderbook_snapshot` 0,
  `orderbook_update` 1, `top_of_book` 2, `trade` 3, `mark_price` and
  `index_price` 4, `funding_rate` 5, `liquidation` 6, `instrument_state` 7,
  klines 8, `scheduled_tick` 9; unknown and `custom_*` types get 5. A
  scheduled decision therefore sees the latest book of its nanosecond.
- `BacktestConfig.seed` roots a `RandomSource` (`utils/rng.py`) whose named
  substreams derive from `(namespace, root seed, name)`: same seed and name
  give the same sequence, different names are independent, so the draw
  order of one component cannot shift another's. Same config and data give
  byte-identical artifacts.

## Execution

- `SimulatedOrderManager` (`execution/sim_order_manager.py`) and
  `SimulatedMarketDataManager` (`execution/sim_md_manager.py`, with a
  `_SimpleOrderBook`) implement the engine's manager protocols, which is
  what lets a strategy run unchanged. Both expose `set_latency_monitor`;
  the monitor observes, it does not delay. **There is no latency model and
  no queue-position model.** Orders act on the book of the event that
  triggered them.
- `FillModel` (`execution/fill_models/base.py`) hooks: `simulate_fill`,
  `notify_trade_for_order`, `check_timeout`, `notify_cancel`; per-order
  state lives on `order.extra`. Models: `orderbook.py`, `immediate.py`,
  `bar.py`, `router.py`.
- `OrderBookFillModel` defaults: `allow_partial=True`,
  `optimistic_maker_fill=True`, `maker_fill_price="limit"` (or `"mid"`),
  `maker_fill_probability=1.0`, `rng_seed=42` (its own RNG, outside the
  `RandomSource`), `use_trades_for_maker_fill=False`,
  `maker_order_timeout_seconds=60.0`, `maker_taker_fallback=True`.
  - A crossing order is a taker and walks the recorded depth to a VWAP;
    depth does not deplete.
  - A non-crossing limit under the default fills **in full, at once, at its
    own limit price**: the optimistic bound, chosen so a synchronous
    strategy that waits for a fill inside a callback can make progress.
    `maker_fill_price="mid"` prices that fill at the mid instead, for
    paired-leg strategies whose limit-priced fills would manufacture basis.
  - `optimistic_maker_fill=False`: no fill until the book crosses, retried
    on later book events; trade-through, the pessimistic bound of what this
    platform can express.
  - `use_trades_for_maker_fill=True`: the order waits for trades at its
    price and fills cumulatively by trade quantity, with no queue position,
    and after `maker_order_timeout_seconds` fills as a **taker against the
    latest book** when `maker_taker_fallback=True`, else is cancelled
    silently. A pessimistic maker run needs `maker_taker_fallback=False` or
    a timeout matched to the quote lifetime.
  - Order types it does not implement raise `UnsupportedOrderTypeError` at
    submission rather than degrade to a limit.
- Slippage (`execution/slippage_models/`): `FixedBpsSlippage`,
  `NoSlippageModel`. Fees (`execution/fee_models/`): `FixedFeeModel`,
  `TieredFeeModel(FeeTable)`.
- Risk (`execution/risk_gates/`): a chain returning `Allow`, `Reject` or
  `ReduceTo`, forbidden from mutating portfolio state; built-ins
  `PositionLimitGate`, `LeverageGate`, `DailyLossGate`, `KillSwitch`. The
  reference pattern for any new pre-trade check.

## Metrics and artifacts

- `analysis/metrics.py` `BacktestMetrics`: `total_pnl`, `total_return_pct`,
  `annualized_return`, `sharpe_ratio`, `sortino_ratio`, `calmar_ratio`,
  `max_drawdown`, `max_drawdown_duration_days`, `volatility_annualized`,
  `total_trades`, `win_rate`, `profit_factor`, `avg_trade_pnl`,
  `avg_holding_period_hours`, `turnover_usdt`, `total_fees`,
  `total_slippage`, `total_funding`, `fee_to_gross_ratio`, plus attribution
  by symbol. Sharpe and Sortino are computed on daily-resampled equity.
  **No markouts, adverse selection, fill rate by depth, quote uptime or
  inventory statistics**: compute those from the fills artifact against the
  book feed.
- `analysis/trade_matcher.py` builds FIFO round trips (fills that grow the
  absolute position open, fills that shrink it close, flips split) for win
  rate, profit factor, average trade PnL and holding period.
- `analysis/artifacts.py` and `report.py` write `metrics.json` (the
  canonical output), charts and the report; `reporting/run_writer.py` with
  `run_schema.py` writes the run record and `strategy_registry.py` names the
  strategy.
- `experiment/sweep.py` `ParameterSweep`: grid or random cells, per-cell
  seeds derived deterministically, `SweepResult` of `CellResult`s with
  flattened metrics.

## In-house precedent

- `strategy-arb-funding`: `backtest/gates/oos_gate.py` (purged, embargoed,
  anchored walk-forward), `backtest/parity/` with `test/backtest/parity/`
  (golden-fixture live-against-backtest parity),
  `backtester/leakage_gate.py`, and `optimizer/search.py`, which refuses
  risk-tier keys in any grid. Reuse the pattern before writing a new one.
- Repo-local agents in `.claude/agents/`, to prefer inside those repos over
  the global `quant-trading-researcher` and `quant-trading-developer`
  because they know the local data: `strategy-mm-sigma` (`quant-researcher`,
  `researcher`, `signal-reviewer`, `attribution-validator`,
  `quote-flow-tracer`, `risk-gate-checker`, `reporter`),
  `strategy-arb-funding` (`research-planner`, `basis-researcher`,
  `execution-cost-analyst`, `pnl-attribution-analyst`,
  `funding-universe-screener`, `log-analyzer`), `strategy-arb-funding-rwa`
  (`calibration-analyst`), `engine-trading-cs` (`order-flow-tracer`).

## What the platform cannot do today

No latency model, no queue model, a sampled book with no deltas or order
ids, no liquidity consumption for takers, no markouts in the metrics, maker
fills immediate at the limit by default, and a trade-driven mode whose
timeout falls back to taker fills. A maker result from this platform is at
best rung 3 of `quant-trading-validation`'s ladder, and its markouts and
fill rate by depth are computed outside it. Each of these is a candidate
change to the engine, not a convention to build on.
