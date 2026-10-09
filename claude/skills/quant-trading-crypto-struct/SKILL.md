---
name: quant-trading-crypto-struct
description: >-
  The CryptoStruct venue: the internal market-data adapter (SBE over WebSocket
  or Unix socket, one feed per exchange) and Trading Adapter (JSON frames, one
  per account, holding the exchange keys) that front Binance, Bybit, OKX,
  Gate.io and the perp DEXes, and how engine-middleware's `cryptostruct` venue
  module on PR #285 integrates them: document block, the one market-data
  thread and its band, per-account login answers and brackets, strangers,
  batched cancels, per-account send windows, cancel on disconnect as a
  backstop, the venue double, issue #386. Also the legacy stack trading on the
  same adapters today (the Python tradingenginecs engine and its StrategyBase
  callbacks, engine-backtesting parity, the Rust mm/hedger bot, money
  conventions) and the Tardis research data and engine-backtesting fill-model
  defaults. Use when working in the engine/, strategy/, monitor/, system/ or
  research/ repos under ~/dev, or on anything naming the cryptostruct feature
  or a connectivity.cryptostruct block.
---

# CryptoStruct venue and the platform on it

CryptoStruct is not an exchange: it is the pair of internal adapters every
crypto venue is reached through. Two consumers speak to them. The Rust
middleware's venue module, `crates/connectivity/src/cryptostruct/` in
`engine-middleware`, arrives on PR #285 (`feat/cs-connectivity`, head
`9f024893`); on main at `1ad03f45` the wiring key is refused at boot until it
lands, while `docs/venues/CRYPTOSTRUCT.md` there already describes the
module. The legacy Python `tradingenginecs` engine and the Rust mm/hedger
bot trade on the same adapters today; their facts are in
[references/legacy-python-stack.md](references/legacy-python-stack.md),
with a short summary below. Domain principles live in `quant-trading`.

These facts are a snapshot of the code and the venue document, not a spec.
Where the source disagrees — a key, a default, a gap since closed — the
source wins: say so, and propose the fix to this skill with `/learn`. A
question only a live deployment can answer stays a question here.

## The adapters

- **The market-data adapter (MDA)**: one connection per exchange feed, in
  SBE (schema 1, version 6, little-endian) over `ws://host:port/api/v6/sbe`
  or `unix:///path`. The login states an `organization` and an
  `applicationName`; admission is by address, so there is no secret. Topics
  are `depth`, `top_of_book`, `trades` and `mark_price`; a login lists the
  capabilities it serves per topic, each with its `eventIdType`, and deltas
  chain by event id. A subscription cannot limit depth. A subscribe's
  `ERROR` is free text, so a transient cause cannot be told from a permanent
  one, nor a feed loss from a delisting.
- **The Trading Adapter (TA)**: one connection per account, in JSON text
  frames over `ws://host:3000/api/v2` or `unix:///path` (the reworked
  domain-socket codec, 2.24.0 or later, with
  `api.use_legacy_domain_socket_codec` unset). It greets with `welcome` and
  a `protocolVersion`, holds the exchange keys and takes an `accountId`
  alone. A login answer lists the account's open orders (omitting
  `PENDING_NEW`) and positions, and its `capabilities`: time-in-force and
  order-type lists, wallets, whether amends are allowed, `rateLimitLoad`
  keys. `accountStatus` moves between OK, `EXCHANGE_BUSY`, `BLOCKED`,
  `DISCONNECTED`, `BANNED`, `UNASSIGNED`, `MANUAL_SHUTDOWN` and
  `EMERGENCY_SHUTDOWN`; a minimal reconnect mode says orders absent from the
  message may be assumed gone. The normalised protocol has **no order, fill
  or position query**: a login or a status is the whole answer, and
  positions are pushed only on a change, before the fill they contain. Its
  own clocks: `tentative_reject_timeout_s` (3), `account_login_timeout_s`
  (28), `unused_account_disconnect_delay_m`. It is to cancel a session's
  resting orders on client disconnect; whether that fires, and on what scope,
  nobody has confirmed. Exchange-side
  timeouts (`HTTP_REQUEST_TIMEOUT`, `HTTP_REQUEST_FAILED`,
  `UNEXPECTED_RESPONSE`) mean it could not tell what the exchange did. It
  names an own order by `ownOrderId` (uuid) and `clientOrderId`, the
  exchange's by `exchangeOrderId`, takes batched requests (ten is Bybit's
  documented batch size; whether a larger batch is split is open), and
  answers a refused place or amend with `retryTimeNs`.
  Derivatives sit in exchange-specific wallets (`derivatives`, `inverse`,
  `cross_margin`…), the document's to get right.
- **Framing**: on a `unix://` connection every message is prefixed by a
  big-endian `u32` whose top bit marks text; a `ws://` connection uses
  ordinary WebSocket frames. On both, order entry writes text and market data
  binary. TLS is not spoken (`wss://` is refused); it is terminated in front
  of the node.
- Historical data is Tardis, not the adapters.

## Middleware integration, as built

**Shape.** Feature `cryptostruct`, the double behind `cryptostruct-double`,
both forwarded by `pgd-node`; `ConnectivitySource::CryptoStruct`; document
block `node.connectivity.cryptostruct`; trace target
`pgd::connectivity::cryptostruct`. The builder declares
`MARKET_DATA | ORDER_EXECUTION`; `build` opens nothing and the first slice
dials. Either leg may be omitted but not both; `instruments` is required.

**Threads.** The duty thread owns every order-entry connection, the order
ledger and the cell word, and is the source lane's only producer; a refused
push there is a real fault that ends the slice `Fatal`. One market-data
thread serves every feed and is the ring's only producer; where
`market_data.core` is named it is pinned there and busy-spins (required
under a dedicated profile, refused under the shared one), otherwise it idles
under a 50 µs backoff. Its death is `Fatal` until a process restart. Dials
run on unpinned connector threads, one per account and feed. Sockets are
read directly and non-blocking, at most 32 account reads a slice; the
stopping slice alone waits, retrying cancel writes for up to 250 ms so the
drain's cancels leave before the sockets close, then writes `Down`.

**Market data.** A feed's turn ends at 64 messages or 1 024 records. The
subscription cannot limit depth, so a snapshot is narrowed to a **band**: the
first 510 levels of a side that arrives best first, otherwise the levels
within `min(roi_ticks, 510)` ticks of each best; a delta outside it is
dropped (`levels_outside_band`), and a best within a quarter of the kept
span of its bound recentres by resubscribe, gapping the book under a
cooldown doubling 1 s to 60 s. An off-grid level or off-step size is skipped
and gaps the book; an update over 1 023 levels is dropped whole. `TopOfBook`
is published for `l1` instruments alone, so a strategy on an L2 book hears
no `on_top_of_book` here. `Reference` carries the last trade and the mark
but no limits, and no `MarketStats` exists, so the `venue_limits` gate
bounds nothing on this venue. A refused subscribe is retried for ever, 1 s
doubling to 60 s, warned once per instrument per login; an L2 book without
a snapshot stays gapped, so readiness refuses `Start`. A feed-loss `ERROR`
holds the source `Down` until the instrument leaves the document.
`md_books_unheard` counts a book silent 30 s after its subscribe.

**Account truth.** Every statement rides the source lane in the adapter's
order; `venue_seq` is `None` and out-of-order rows are counted, never
reordered. `venue_ts` is the row's `exchangeTimestampNs` where a row gives
one. A fill's `cum_qty` is the source's own, the larger of what rows stated
and fills summed; a fill landing after the `orderUpdate` that already
stated it is booked as an implied lot at the limit and then priced, so each
lot books once in either order. **Strangers** — orders another tool placed
on the account — are forwarded by the venue's id and adopted, because they
are exposure; a stranger that is not `LIMIT`, or whose ids exceed 40 bytes,
goes out without a price and is never adopted. A **teardown** answers each
cancel and amend by what the socket took: a frame that never left is
`SessionDown`, one cut mid-frame or unanswered is `InDoubt`; a place whose
frame never left is `SessionDown`, and one written or cut keeps its binding
for the next login's answer. **Positions** are
`long − short` per pair, folded per account from pushes; isolated and hedge
mode are unsupported and spot is refused for execution. The `Up` slice
waits `position_settle_ms` (1 000) past each figure's receipt because the
push precedes the fill it holds.

**Egress.** Cancels on one instrument and account batch up to
`cancel_batch_max` (10); places and amends batch the same way only under
`batch_places`. `Gtc` → `GOOD_TILL_CANCEL`, `Ioc` → `IMMEDIATE_OR_CANCEL`,
`Fok` → `FILL_OR_KILL`, `PostOnly` → GTC with `postOnly: true`; `DAY` is never
sent. `postOnly`, `reduceOnly`, `closeOnly` and `wallet_type` are written
explicitly on every place; a place goes out only as a limit order with a
time in force, wallet and (for an amend) amend capability the login listed,
and a login with no `capabilities` lists nothing. There is no instrument
status gate. An exchange-side timeout refuses a cancel `InDoubt` and an
amend `Unknown` and keeps a place's binding, all **without** the `Down` the
contract pairs with `InDoubt`, because a `Down` here re-dials every account
and may fire the disconnect cancel. A cancel refused `ORDER_NOT_FOUND`
before its order confirmed is answered `UnknownOrder` and sent once more on
the order's next word; `ACCESS_DENIED` reads as `UnknownOrder`.

**Identity.** The engine's client id never reaches the venue: an own order's
uuid is spelled from the wire id and the instance's discriminator, with the
amend counter in `clientOrderId`, so two nodes on one account are safe only
with different instance names, and `ORDER_ID_DUPLICATE` (`id_collisions`) is
the backstop. The run second is taken on the first slice whose clock reads;
a run second past 30 bits is `Fatal`. A venue id is the exchange's id where
decimal and its FNV-1a hash otherwise; an own order the venue has not yet
named carries the synthetic `wire | 1 << 63` toward the engine. Bindings
live in a ring, four slots per order slot of the executed instruments; a
full ring refuses a place `Backpressure`. The last 32 768 `ownFillId` hashes
are remembered for the process's life, the venue having no day turn.

**Liveness.** A WebSocket leg pings every `heartbeat_secs` (5), takes any
inbound frame as liveness, and is found dead within twice that once the peer
has spoken the control protocol, otherwise only at EOF; a Unix socket has no
heartbeat and a hung live peer is never found. Per account: `Down`,
`LoggingIn`, `Ready { status }`, `Refused { code }` over the link's `Idle`,
`Dialing`, `Open`, `Stuck`; per feed `Down`, `Connected`, `LoggingIn`,
`Subscribing`, `Up`. `Up` is written as the last step of `do_work`, once
every account's answer is whole and `Ready` with status OK, every feed up,
the market-data thread alive and every executed pair stated. `Fatal` on a
refused login or status, a question given up after two asks, a full source
lane, an unreadable position, an order-entry message larger than
`recv_buffer_bytes`, or the market-data thread ending; a `Start` clears the
login verdicts by re-dialling. On `Fatal` the source closes order entry to
fire the adapter's disconnect cancel — the backstop, never the mechanism,
covering no adopted stranger; whether it fires, and on what scope, is
unconfirmed.

**Recovery and anchoring.** Each account's recovery is its login, or an OK
status after a not-OK one, bracketed per account so what the answer omits
is closed; the bracket stays open while places on that connection are
unconfirmed, bounded by `tentative_reject_secs` plus twice `heartbeat_secs`.
Two asks per question, then `Fatal`. A lost feed restarts recovery without
asking order entry again. Down to up is about 14 s; the worst case for the
login question, about 83 s at the defaults, is held inside the engine's
90 s dwell by a build-time check. There is **no position poll** and no sync
point: pushes on change are the only anchor, so nothing bounds the age of
the last statement while `Up`. An order an answer omits while it still
rests is closed `NotAtVenue` and keeps resting with no record anyone can
cancel, an engine-side re-open tracked in issue #386.

**Rate limits.** Each account has its own one-second window of
`sends_per_second` (100): a place stops at 75, an amend at 87, a cancel may
spend all 100, and a test pins that no burst of places or amends can spend
the cancels' share. `rateLimitLoad` pushes are indicative gates: a place is
refused at a place or cancel load of 0.75, an amend at 0.875, never a
cancel; the keys differ by exchange. A `retryTimeNs` holds that account's
places and amends until it passes, at most 60 s; one on a cancel is ignored
and counted. A cancel the window refuses is restored by the engine and not
sent again, so a stop drain past the window leaves the excess resting until
`drain_timeout` (#386).

**Instruments and accounts.** Every instrument on the venue has exactly one
entry with the venue `id` (unique across exchanges), `exchange`, `symbol`,
`kind` (`perpetual` or `future` where executed; `spot` refused),
`wallet_type` (`account` by default), `topics`, `tob_coalescing`; its
`tick` and `lot` are taken as the venue's, since the login states no
metadata and nothing fetches it (#386). One quantity unit per instrument:
orders, fills and positions are all read in the configured `lot`.
`order_entry.accounts` names the venue's numeric id per engine account, in
order, at most 32; accounts × executed instruments stays within half the
source lane (2 048).

**Document block** (`node.connectivity.cryptostruct`):

| Key | Default | Note |
| --- | --- | --- |
| `application` | `pgd-connectivity` | the market-data login's application name |
| `dial_timeout_secs` | 5 | connect, handshake and `welcome`; not the resolver |
| `market_data.organization` | required | the login's organization |
| `market_data.feeds` | required | map of exchange key to `{ url }`, at most 15, one per fed exchange and none spare |
| `market_data.heartbeat_secs` | 5 | `ws://` only |
| `market_data.core` | absent | the pinned, busy-spinning market-data core |
| `market_data.recv_buffer_bytes` | 4 MiB | at least 2 424 870 |
| `order_entry.url` | required | the Trading Adapter |
| `order_entry.accounts` | required | numeric ids per engine account, at most 32 |
| `order_entry.heartbeat_secs` | 5 | per account connection |
| `order_entry.login_timeout_secs` | 30 | above the adapter's 28 s; capped at 33 by the dwell check |
| `order_entry.sends_per_second` | 100 | 0 unmetered |
| `order_entry.batch_places` | `false` | batch places and amends like cancels |
| `order_entry.cancel_batch_max` | 10 | 1 to 16 |
| `order_entry.recv_buffer_bytes` | 4 MiB | the largest answer an account can take |
| `order_entry.pending_out_bytes` | 64 KiB | unsent bytes per account; undersized costs latency |
| `order_entry.stall_ms` | 250 | unsent bytes older than this tear the connection down |
| `order_entry.tentative_reject_secs` | 3 | the adapter's `tentative_reject_timeout_s` |
| `order_entry.position_settle_ms` | 1000 | not below the largest `drift_skew_ms` |
| `instruments[]` | required | `exchange`, `symbol`, `id`, `kind`, `wallet_type`, `topics`, `tob_coalescing` |

Floors, ranges and counts are checked by the venue's own constructors;
coordinates are `!env` references resolved while the source is wired, so an
unset one is refused by name before anything is built.

**Observability.** Series: `venue_requests_total{kind, outcome}` by `place`,
`cancel`, `amend` and `sent`, `refused`, `not_sent`, `ambiguous`;
`session_state` and `reconnects_total` per leg (`order`, `market`); the six
`wire_ids_*`; `md_skipped_total`; `md_books_unheard`. `SourceCounters` such as
`own_ids_reused`, `strangers_full`, `id_collisions`, `post_only_mismatch`,
`place_timeouts_kept`, `rows_out_of_order` and `up_held_past_bound` reach
only a rig. `RUST_LOG=info,pgd::connectivity::cryptostruct=debug` shows the
venue's side of a run; the venue document lists the lines a healthy start
writes and the warnings a first run meets.

## Running against the venue

| Tier | Recipe | Needs | Reaches the venue |
| --- | --- | --- | --- |
| Offline | `just test` | nothing | no |
| End to end | `just e2e` | nothing | no |
| Node, dry | `just cryptostruct-example-dry` | `.env` | no |
| Node | `just cryptostruct-example` | `.env`, both adapters | yes; trades once `dry_run` is off |

No vendor library, container or credential is needed: the module speaks
both protocols itself. The offline tiers run against the in-process
**double** (`pgd_connectivity::cryptostruct::double`, feature
`cryptostruct-double`, forwarded by `pgd-node` so a strategy repo's tests
can drive it): the market-data leg serves scripted books, the order-entry
leg plays the Trading Adapter per account with scripted rows, fills,
positions, statuses and loads, deterministic stamps and a recorded log of
every frame. `.env` names `CS_ORGANIZATION`, one `CS_MD_<FEED>` per feed,
`CS_TA_URL`, `CS_ACCOUNTS` and `PGD_CONTROL_TOKEN`; the example's instrument
`id`s are placeholders to replace from the deployment's instrument list.
`node.yaml` ships `dry_run: true`; going live takes the document saying
`false` and an operator's `node.start`, and `--start` gives up the second
key. **There is no live suite**: every assumption below is the double's
reading of the venue, and issue #386 tracks the live run.

## Open questions and known gaps (issue #386)

Only a live deployment can answer the first group; the module fails safe.

- Whether the Trading Adapter's cancel on disconnect fires, and on what
  scope: socket or session. Scoped to the socket, every re-dial cancels that
  account's resting orders.
- What both adapters do on the control protocol: pongs, pings, idle timeouts,
  what an idle Unix socket carries, whether `welcome` is sent on the domain
  socket.
- What the reconnect answers contain: row shapes of `orders[]` and
  `instrumentPositions[]`, what the minimal status mode lists, whether an OK
  follows `EXCHANGE_BUSY` or `BLOCKED`, whether a slow login's figure is
  computed at send time, and whether fills during initialisation are
  published again afterwards (counted twice if so).
- How executions are accounted: one unit per instrument, the order of a
  fill and its position push, pushes only on change, how a closed position
  is sent, which fills follow a gap.
- How an order is named: `exchangeOrderId` on the first `CONFIRMED` row, the
  uniqueness scope of `ownOrderId`, whether a finished id is reused.
- Amends and cancels in flight: the id a `PENDING_AMEND` row carries, the id
  a refused amend echoes, whether another session's order can be acted on,
  whether a cancel batch past the exchange's size is split.
- Whether each exchange honours post-only; the login lists no bit for it.

Departures still open on the module side: fills of `type: OTHER` and of
never-adopted strangers are not booked; no position poll anchors an account
while `Up`; a rate-refused cancel is never re-sent; an omitted resting order
is closed `NotAtVenue` and then judged `Buried`; no venue metadata is
checked; every order-entry socket is read every slice; three links go
unwatched. One PR per item, ticked in #386, the venue document moving with
it.

## Legacy stack, trading today

The Python `tradingenginecs` engine is the centre of gravity: strategies
subclass `MarketStrategyBase` / `TradingStrategyBase` and override callbacks
(`on_orderbook`, `on_trades`, `on_top_of_book`, `on_mark_price`,
`on_funding_rate`, `on_order_update_view`, `on_position_update_view`); fills
arrive via `on_order_update_view`, and there is no `on_tick` or `on_fill`.
`engine-backtesting` runs the same strategies unchanged, deterministically.
The self-contained Rust mm/hedger bot (`strategy-exchange-mm-hedger-bot`)
has no strategy trait, a crash-and-restart failure model and load-bearing
`dry_run`, `reduceOnly` and max-notional checks. Everything is `Decimal`,
normalised to USDT, rounded at order send. Monitors codegen from
`MetricSpec`. The replacement is `engine-middleware`, whose strategy document
copies the callback names so a port is a transcription with four
differences: fills as deltas, integer ticks and lots, `Option` for absence,
positions derived from own fills. The full facts, gaps and the porting table
are in [references/legacy-python-stack.md](references/legacy-python-stack.md).

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
  limit order fills in full at its own price, the optimistic upper bound for
  any maker strategy. The pessimistic variants are
  `optimistic_maker_fill=False` (fill only when the book crosses) and
  `use_trades_for_maker_fill=True` (trade-driven), which defaults to
  `maker_taker_fallback=True` and crosses the book as a taker after
  `maker_order_timeout_seconds` (60 s) — a pessimistic maker run needs
  `maker_taker_fallback=False` or a timeout matched to the quote lifetime, or
  it gets silent taker fills. There is **no queue-position model and no
  latency model**. Slippage is `FixedBpsSlippage` / `NoSlippageModel`; fees
  are `FixedFeeModel` / `TieredFeeModel(FeeTable)`.
- `BacktestMetrics` covers Sharpe, Sortino, Calmar, drawdown, win rate,
  profit factor, fees, slippage and funding, but **no markouts or adverse
  selection** — compute those from `trades.csv` against the book feed.
  `ParameterSweep` derives per-cell seeds deterministically; `metrics.json`
  is the canonical sweep output; `BacktestConfig.seed` gives bit-identical
  artifacts; data-quality validators write `data_quality.json`.
- In-house precedent for validation gates lives in `strategy-funding-arb`:
  `backtest/gates/oos_gate.py` (purged, embargoed, anchored walk-forward),
  `backtest/parity/` (golden-fixture live-vs-backtest parity),
  `backtester/leakage_gate.py` and `optimizer/search.py` (refuses risk-tier
  keys in any grid). Reuse the pattern before writing a new one.
- Repo-level research agents exist in `.claude/agents/` of two repos: sigma's
  `quant-researcher`, `signal-testing`, `backtest-report-writer`;
  funding-arb's `execution-cost-analyst`, `pnl-attribution-analyst`,
  `basis-researcher`. Inside those repos, prefer them over the global
  `quant-trading-researcher` — they know the local data.

## References

| File | Read it when |
| --- | --- |
| [references/legacy-python-stack.md](references/legacy-python-stack.md) | Working in a `tradingenginecs` strategy, `engine-backtesting`, the Rust mm/hedger bot, or a monitor on the legacy stack; porting a strategy to the middleware |
