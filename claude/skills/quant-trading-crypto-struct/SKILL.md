---
name: quant-trading-crypto-struct
description: The current CryptoStruct-based trading stack — internal WS gateway to all venues, Python tradingenginecs engine and its StrategyBase callbacks, engine-backtesting parity, the self-contained Rust mm/hedger bot, money normalization conventions, dry_run and RiskGate patterns, MetricSpec observability. Use when working in the existing engine/, strategy/, monitor/, or system/ repos under ~/dev.
---

# CryptoStruct platform stack

Facts about the current platform under `~/dev`, so they aren't rediscovered
each session. Domain principles live in the `quant-trading` skill. This stack is
slated for replacement by an in-house low-latency Rust engine — keep changes
here proportionate: fix correctness and risk gaps, don't micro-optimize
latency in code built around a poll-driven gateway.

## Connectivity

- All venue connectivity goes through the internal **CryptoStruct Trading
  Adapter** — one WS gateway normalizing market data and order entry across
  venues (Binance, Bybit, OKX, Gate.io, Hyperliquid, Lighter, Aster; the
  on-chain ones are order-book perp DEXes, not AMM pools). Endpoints are
  private IPs supplied per venue in config.
- The only direct exchange connection is the Binance USDC/USDT `bookTicker`,
  used purely as an FX rate.
- Historical market data comes from Tardis.

## Python engine (`tradingenginecs`) — the center of gravity

- Strategies subclass `MarketStrategyBase` / `TradingStrategyBase` and
  override callbacks: `on_orderbook`, `on_trades`, `on_top_of_book`,
  `on_mark_price`, `on_funding_rate`, `on_order_update_view`,
  `on_position_update_view`, etc. **Fills arrive via `on_order_update_view` —
  there is no `on_tick` and no `on_fill`.** Check `strategyBase.py` before
  naming a callback.
- `engine-strategy-manager` (ESM) is a control plane only (lifecycle, hot
  param updates); it is deliberately not in the trading execution path.
- **Backtest parity is a hard invariant:** `engine-backtesting` runs
  `tradingenginecs` strategies with zero code changes via protocol-compatible
  managers. Determinism is first-class — seeded `RandomSource` with named
  substreams; same config → byte-identical artifacts. Don't break either.
- The backtester's `RiskGate` chain (`Allow` / `Reject(reason)` /
  `ReduceTo(qty, reason)`; gates chained and forbidden from mutating portfolio
  state) is the reference pattern for new pre-trade checks.

## Rust mm/hedger bot (`strategy-exchange-mm-hedger-bot`)

- Self-contained; does not depend on the engine repos. No strategy trait —
  concrete structs with a `run()` loop: `tokio::select!` over broadcast fill
  events and a requote poll timer. Market data is read from shared globals at
  poll time; requoting is threshold-gated (`requoteThresholdBps`).
- On `broadcast::RecvError::Lagged`, force a full requote (existing
  convention).
- **Crash-and-restart failure model:** first task to exit kills the process;
  state rebuilds from the venue on reconnect. Preserve this — no in-process
  recovery that can leave half-rebuilt state.
- Never remove or bypass `dry_run` guards at order-send sites. `reduceOnly`
  and max-notional checks are load-bearing.
- Known gaps (candidates to fix, not conventions to copy): the hedger lacks
  the MM bot's kill switch; there is no rate limiter, fat-finger price check,
  or daily-loss gate on the Rust side.

## Money conventions

- `Decimal` for all strategy arithmetic (`rust_decimal` / `decimal.Decimal`);
  `f64` only at the wire/feed boundary, converted at ingress.
- Everything is normalized to **USDT**; USDC legs convert via the live Binance
  USDC/USDT mid. Quantities are base-asset units, converted to venue contracts
  via `contractMultiplier` at send time.
- Round with `priceDecimals` / `quantityDecimals` at order send. Signals are
  expressed in bps (`BPS = 10_000`).

## Observability and conventions

- Monitors are Prometheus + Grafana. `MetricSpec` is the single source of
  truth that codegens exporters, dashboards, and alerts — add metrics through
  it, never hand-rolled.
- Repos are independent git remotes (kebab-case names, one-word Python package
  names), distributed via internal PyPI. Bilingual docs (`README_EN`/`_CN`)
  are the norm; several repos use `openspec/` as spec ground truth.

## Research and backtesting stack

- Historical data is Tardis: `book_snapshot_25` (L2, 25 levels) and
  `derivative_ticker` (funding rate, with `mark_price` / `index_price`
  forwarded so basis and premium can be reconstructed) through
  `TardisBookSnapshot25Feed` / `TardisDerivativeTickerFeed` in
  `engine-backtesting`; `pipeline/fetch_tardis_bulk.py` downloads. Rows carry
  exchange `timestamp` and `local_timestamp` — decide on local time. Research
  notebooks live in `research/quant-research`; backtest drivers live in each
  strategy repo's `backtest_runs/`, never in the engine repo.
- `OrderBookFillModel` defaults to `optimistic_maker_fill=True`,
  `maker_fill_price="limit"`, `maker_fill_probability=1.0`: every non-crossing
  limit order fills in full at its own price. That is the optimistic upper
  bound for any maker strategy. The pessimistic variants are
  `optimistic_maker_fill=False` (fill only when the book crosses) and
  `use_trades_for_maker_fill=True` (trade-driven). The latter defaults to
  `maker_taker_fallback=True`, which crosses the book as a taker after
  `maker_order_timeout_seconds` (60 s) — a real maker would cancel, so a
  pessimistic maker run needs `maker_taker_fallback=False` or a timeout
  matched to the quote lifetime, or it gets silent taker fills. There is **no
  queue-position model and no latency model** — `QueuePositionFillModel`
  appears only in a docstring example. Slippage is `FixedBpsSlippage` /
  `NoSlippageModel`; fees are `FixedFeeModel` / `TieredFeeModel(FeeTable)`.
- `BacktestMetrics` covers Sharpe, Sortino, Calmar, drawdown, win rate,
  profit factor, fees, slippage and funding, but **no markouts or adverse
  selection** — compute those from `trades.csv` against the book feed.
  `ParameterSweep` derives per-cell seeds deterministically and `metrics.json`
  is the canonical sweep output; `BacktestConfig.seed` gives bit-identical
  artifacts. Data-quality validators (monotonic, duplicate, book invariant,
  price jump, gap) write `data_quality.json`.
- In-house precedent for validation gates lives in `strategy-funding-arb`:
  `backtest/gates/oos_gate.py` (purged, embargoed, anchored walk-forward with
  sign-consistent OOS edge), `backtest/parity/` (golden-fixture live-vs-
  backtest decision parity), `backtester/leakage_gate.py` (greppable leakage
  tripwire) and `optimizer/search.py` (refuses risk-tier keys in any grid).
  Reuse the pattern before writing a new one.
- Repo-level research agents exist and shadow global agents of the same name:
  sigma's `quant-researcher` (corpus claim filter), `signal-testing`,
  `backtest-report-writer`; funding-arb's `execution-cost-analyst`,
  `pnl-attribution-analyst`, `basis-researcher` (all over mcp-trades). Use
  them inside those repos.
