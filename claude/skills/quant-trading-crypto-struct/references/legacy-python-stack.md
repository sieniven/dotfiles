# The legacy stack on the CryptoStruct adapters

The Python `tradingenginecs` engine and the self-contained Rust mm/hedger
bot that trade on the CryptoStruct adapters today. They are slated for
replacement by `engine-middleware`, whose CryptoStruct venue module the
skill's main file describes — keep changes here proportionate: fix
correctness and risk gaps, don't micro-optimize latency in code built
around a poll-driven gateway. These facts are a snapshot of the code, not a
spec; where the source disagrees — a callback name, a default, a gap since
closed — the source wins: say so, and propose the fix with `/learn`.

## Connectivity from the legacy side

- Every venue is reached through the CryptoStruct Trading Adapter and
  market-data adapter, which normalise market data and order entry across
  Binance, Bybit, OKX, Gate.io, Hyperliquid, Lighter and Aster; the on-chain
  ones are order-book perp DEXes, not AMM pools. Endpoints are private IPs
  supplied per venue in config.
- The only direct exchange connection is the Binance USDC/USDT `bookTicker`,
  used purely as an FX rate.
- Historical market data comes from Tardis.

## Python engine (`tradingenginecs`), the centre of gravity

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

## Porting a strategy to the middleware

`engine-middleware`'s `docs/STRATEGY.md` copies the callback names from
`strategyBase.py` and keeps the account parameter, so a port is largely a
transcription; what changes is what the callbacks carry.

| Python | Middleware |
| --- | --- |
| `(exchange, symbol)` everywhere | `InstrumentIdx`, a dense index fixed at `build()`; `ctx.resolve(exchange, symbol)` once |
| `new_order(...)` | `ctx.place(OrderReq)` |
| `TimerManager` | `ctx.timer_once` / `ctx.timer_periodic` |
| masterdata lookups | `ctx.instrument(i)` |
| module-level state shared between callbacks | reads off `ctx`: `position`, `open_orders`, `order`, `top_of_book`, `book` |
| `RecvError::Lagged` | `on_book_gap`, whose default pulls the node's orders on the instrument |

Four differences to read twice: fills arrive as `FillDelta`, what the node
had not booked yet, so differencing cumulatives in the strategy does the work
twice; prices and quantities are integer `PxTicks` and `QtyLots` with no
float on the strategy path; absence is `Option`, never a sentinel; and
positions are derived from the node's own fills, a venue statement being
evidence the engine judges rather than the figure a strategy reads. There
is no migration tool and no compatibility shim.
