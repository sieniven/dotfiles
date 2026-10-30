---
name: quant-trading-crypto-struct
description: >-
  The CryptoStruct venue: the internal market-data adapter (SBE over WebSocket
  or Unix socket, one feed per exchange) and Trading Adapter (JSON frames, one
  per account, holding the exchange keys) that front Binance, Bybit, OKX,
  Gate.io and the perp DEXes, and how engine-middleware's `cryptostruct` venue
  module integrates them: one source per exchange (`CsOkx`, `CsBitget`, …),
  the `sources` document block, one market-data agent per source and its
  band, per-account login answers and brackets, strangers, batched cancels,
  per-account send windows, the position poll and metadata check, cancel on
  disconnect as a backstop, the venue sim, issue #386. Also the legacy stack
  trading on the same adapters today (the Python tradingenginecs engine and its StrategyBase
  callbacks, engine-backtesting parity, the Rust mm/hedger bot, money
  conventions). Use when working in the engine/, strategy/, monitor/ or
  system/ repos under ~/dev, or on anything naming the cryptostruct feature
  or a connectivity.cryptostruct block.
---

# CryptoStruct venue and the platform on it

CryptoStruct is not an exchange: it is the pair of internal adapters every
crypto venue is reached through. Two consumers speak to them. The Rust
middleware's venue module, `crates/connectivity/src/cryptostruct/` in
`engine-middleware`, is on main since #285 (2026-10-20) and became one
source per exchange with the stack #636–#640 (2026-10-30); `docs/venues/
CRYPTOSTRUCT.md` is the one description of it. The legacy Python `tradingenginecs` engine and the Rust mm/hedger
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

**Shape.** Feature `cryptostruct`, the sim behind `cryptostruct-sim`, both
forwarded by `pgd-node`; trace target `pgd::connectivity::cryptostruct`. **One
source per exchange**: a `ConnectivitySource` variant each (`CsBinanceUsdt`,
`CsBitget`, `CsBybit`, `CsGateioFuture`, `CsGateioSpot`, `CsHashkeyGlobal`,
`CsHashkeyHk`, `CsHashkeyMena`, `CsHyperliquid`, `CsKrakenSpot`,
`CsKucoinSpot`, `CsMexc`, `CsOkx`, discriminants 4–16 after `Mock`, `Apex`,
`TradingTechnologies`), each wired from one entry of
`node.connectivity.cryptostruct.sources.<Cs*>` with its own liveness word,
rings, ledger, feed, Trading Adapter, duty thread and `Up`; an exchange the
build does not carry is refused by name at load. `cryptostruct::Venue` maps
the variant to the `exchange:` spelling an engine instrument writes (`okx`,
`hashkey_exchange`, `gateio_spot`, …), and an instrument whose `exchange`
is not its source's spelling is refused. The builder declares `MARKET_DATA`
where the entry has `market_data` and `ORDER_EXECUTION` where it has
`order_entry`; `build` opens nothing and the first slice dials. Either leg
may be omitted but not both; `instruments` is required.

**Threads, per source.** The duty thread owns the order-entry connections,
the ledger and the cell word, and is the source lane's only producer; a
refused push there is a real fault that ends the slice `Fatal`. The
market-data agent (`MdAgent`, a `pgd_runtime::Agent` driven by the same
`drive` loop as the duty) owns the one feed and the ring's sender and runs
one bounded `do_work`: the duty's snapshot asks taken, the link polled, at
most one read, the decode to 64 messages or 1 024 records, at most eight
subscribes, the unheard books aged, the word stored on its edge, the
heartbeat, at most one write. Where `market_data.core` is named it is pinned
there and busy-spins (required under a dedicated profile, refused under the
shared one, and a core two entries name is refused), otherwise it idles
under a 50 µs backoff; a `GapMarker` in its guard gaps every book if it ends
unasked, and its death is `Fatal` until a process restart. One HTTP side
thread (`<instance>-<source>-http`) serves the position poll and the
metadata check through one ring of tagged asks (`Poll`, `Metadata`) and one
of tagged answers, one check request a turn with at most one waiting poll
between two of them. Dials run on unpinned connector threads. Sockets are
read directly and non-blocking, at most 32 account reads a slice; the
stopping slice alone waits, retrying cancel writes for up to 250 ms so the
drain's cancels leave before the sockets close, then writes `Down`.

**Market data.** One feed per source; an iteration's decode ends at 64
messages or 1 024 records. The
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
mode are unsupported and spot is refused for execution. Positions and
balances carry venue stamps and are stated last before `Up`, because the
push precedes the fill it holds. A `PENDING_AMEND` row restates the order as
working and answers nothing.

**Egress.** Cancels on one instrument and account batch up to
`cancel_batch_max` (10); a place or an amend is one entry per frame. `Gtc` → `GOOD_TILL_CANCEL`, `Ioc` → `IMMEDIATE_OR_CANCEL`,
`Fok` → `FILL_OR_KILL`, `PostOnly` → GTC with `postOnly: true`; `DAY` is never
sent. `postOnly`, `reduceOnly`, `closeOnly` and `wallet_type` are written
explicitly on every place; a place goes out only as a limit order with a
time in force, wallet and (for an amend) amend capability the login listed,
and a login with no `capabilities` lists nothing. The backend's instrument
state, read on the metadata check, is the one status word (`Status` shut or
open once per recovery). An exchange-side timeout refuses a cancel `InDoubt` and an
amend `Unknown` and keeps a place's binding, all **without** the `Down` the
contract pairs with `InDoubt`, because a `Down` here re-dials every account
and may fire the disconnect cancel; a kept place unheard past the bracket
hold's bound (`tentative_reject_secs` + 2 × `heartbeat_secs`, 13 s) has its
account re-dialled, counted `place_timeouts_redialed`, a ~14 s `Down`. A
cancel refused `ORDER_NOT_FOUND`
before its order confirmed is answered `UnknownOrder` and sent once more on
the order's next word; `ACCESS_DENIED` reads as `UnknownOrder`.

**Identity.** The engine's client id never reaches the venue: an own order's
uuid is spelled from the wire id, the instance's 16-bit discriminator and the
source's discriminant (8 bits), with the amend counter (20 bits) in
`clientOrderId`, so two sources of one node never spell one id and two nodes
on one account are safe only with different instance names; the discriminant
is therefore on the venue wire and a new exchange appends, nothing renumbers; `ORDER_ID_DUPLICATE` counts `id_collisions`, as
do two live orders whose exchange ids fold alike (`007`/`7`), dropped and never
merged. The run second is taken on the first slice whose clock reads;
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
the market-data agent alive, the metadata check passed and every executed
pair and wallet stated. `Fatal` on a
refused login or status, a question given up after two asks, a full source
lane, an unreadable position, an order-entry message larger than
`recv_buffer_bytes`, a metadata disagreement, a feed login lost twice or a
depth subscribe refused eight times, or the market-data agent ending; a
`Start` clears the login and feed-login verdicts by re-dialling and asks the
backend afresh. On `Fatal` the source closes order entry to
fire the adapter's disconnect cancel — the backstop, never the mechanism,
covering no adopted stranger; whether it fires, and on what scope, is
unconfirmed.

**Recovery and anchoring.** Each account's recovery is its login, or an OK
status after a not-OK one, bracketed per account so what the answer omits
is closed; the bracket stays open while places on that connection are
unconfirmed, bounded by `tentative_reject_secs` plus twice `heartbeat_secs`.
Two asks per question, then `Fatal`. A lost feed restarts recovery without
asking order entry again. The link's backoff starts over only when an answer
is taken whole; a connection gone before its answer doubles it and spends an
ask (`drops_unanswered`). Down to up is about 14 s; the worst case for the
login question, about 84 s at the defaults (1 s and 2 s backoffs, then the
settle hold), is held inside the engine's 90 s dwell by a build-time check.
The position poll (`position_poll_secs`, off unless the document sets it)
through the adapter's HTTP API is the one anchor while `Up`; `poll_misses_down`
misses take the source `Down` without a relogin. The metadata check runs
before each `Up` where `metadata_url` is set (tick, lot, currency, asset ids;
a disagreement is `Fatal`, a silent backend `metadata.unverified`); its
deadline is outside the recovery worst case. An order an answer omits while it still
rests is closed `NotAtVenue` and keeps resting with no record anyone can
cancel, an engine-side re-open tracked in issue #386.

**Rate limits.** Each account has its own one-second window of
`sends_per_second` (100): a place or an amend stops at 75, a cancel may
spend all 100, and a test pins that no burst of places or amends can spend
the cancels' share. A `rateLimitLoad` push is counted unknown and read no
further (no exchange lists the capability). A `retryTimeNs` holds that account's
places and amends until it passes, at most 60 s; one on a cancel is ignored
and counted. A cancel the window refuses is restored by the engine and not
sent again, so a stop drain past the window leaves the excess resting until
`drain_timeout` (#386).

**Instruments and accounts.** Every instrument on a `Cs*` source has exactly
one entry under its source's `instruments`, matched by `symbol`: the venue
`id` (unique across exchanges), `kind` (`spot`, `perpetual` or `future`),
`wallet_type` (`account` by default), `topics`, `tob_coalescing`; its `tick`
and `lot` are the venue's, checked against the backend where `metadata_url`
is set. One quantity unit per instrument: orders, fills and positions are
all read in the configured `lot`. Each entry's `order_entry.accounts` names
the engine `idx`, `name` and the venue's numeric `id` per account, at most 32;
an account belongs to one source (an `idx`, a name or a venue id two entries
declare is refused by both locations); accounts × executed instruments stays
within half the source lane (2 048) per source.

**Document block** (`node.connectivity.cryptostruct`): a prelude every
source shares, then `sources`, one entry per `Cs*` variant the instruments
name (an entry nothing names, or a named variant with no entry, is refused).

| Key | Default | Note |
| --- | --- | --- |
| `application` | `pgd-connectivity` | every feed login's application name |
| `organization` | required with any `market_data` | every feed login's organization |
| `dial_timeout_secs` | 5 | connect, handshake and `welcome`; not the resolver |
| `metadata_url` | absent | the backend; each source checks its own instruments |
| `assets` | `{}` | engine asset → venue `underlyingId` |
| `sources.<Cs*>.market_data.url` | required for a fed source | the exchange's market-data adapter |
| `sources.<Cs*>.market_data.heartbeat_secs` | 5 | `ws://` only |
| `sources.<Cs*>.market_data.core` | absent | the pinned, busy-spinning market-data core; one per source |
| `sources.<Cs*>.market_data.recv_buffer_bytes` | 4 MiB | at least 2 424 870 |
| `sources.<Cs*>.order_entry.url` | required for a trading source | the exchange's Trading Adapter |
| `sources.<Cs*>.order_entry.accounts[]` | required | `{ idx, name, id, wallets }`, at most 32 |
| `sources.<Cs*>.order_entry.heartbeat_secs` | 5 | per account connection |
| `sources.<Cs*>.order_entry.login_timeout_secs` | 30 | above the adapter's 28 s; capped by the dwell check |
| `sources.<Cs*>.order_entry.sends_per_second` | 100 | 0 unmetered |
| `sources.<Cs*>.order_entry.cancel_batch_max` | 10 | 1 to 16 |
| `sources.<Cs*>.order_entry.recv_buffer_bytes` | 4 MiB | the largest answer an account can take |
| `sources.<Cs*>.order_entry.pending_out_bytes` | 64 KiB | unsent bytes per account; undersized costs latency |
| `sources.<Cs*>.order_entry.stall_ms` | 250 | unsent bytes older than this tear the connection down |
| `sources.<Cs*>.order_entry.tentative_reject_secs` | 3 | the adapter's `tentative_reject_timeout_s` |
| `sources.<Cs*>.order_entry.api_url`, `position_poll_secs`, `poll_misses_down` | absent, 0, 3 | the position poll over the adapter's HTTP API |
| `sources.<Cs*>.instruments[]` | required | `symbol`, `id`, `kind`, `wallet_type`, `topics`, `tob_coalescing`; no `exchange`, the variant is the exchange |

Floors, ranges and counts are checked by the venue's own constructors;
coordinates are `!env` references resolved while the source is wired, so an
unset one is refused by name before anything is built.

**Observability.** Series: `venue_requests_total{kind, outcome}` by `place`,
`cancel`, `amend` and `sent`, `refused`, `not_sent`, `ambiguous`;
`session_state` and `reconnects_total` per leg (`order`, `market`), every
series labelled `source=<Cs*>` and `ring_depth{lane}` as `<cs*>.md` /
`<cs*>.account` (lowercased); the six `wire_ids_*`; `md_skipped_total`;
`md_books_unheard`; `node.status` and the recorder's health list one row per
source. `SourceCounters` such as
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
both protocols itself. The offline tiers run against the in-process **sim**
(`pgd_connectivity::cryptostruct::sim`, feature `cryptostruct-sim`,
forwarded by `pgd-node` so a strategy repo's tests can drive it): the
market-data leg serves scripted books, the order-entry leg plays the Trading
Adapter per account with scripted rows, fills, positions and statuses,
deterministic stamps and a recorded log of every frame. The example node
trades two sources; `.env` names `CS_ORGANIZATION`, `CS_MD_BINANCE_USDT`,
`CS_MD_BYBIT`, `CS_TA_BINANCE_USDT`, `CS_TA_BYBIT`, `CS_ACCOUNT_BINANCE_USDT`,
`CS_ACCOUNT_BYBIT`, `CS_BACKEND_URL` and `PGD_CONTROL_TOKEN`; the example's
instrument `id`s are placeholders to replace from the deployment's instrument
list. `node.yaml` ships `dry_run: true`; going live takes the document saying
`false` and an operator's `node.start`, and `--start` gives up the second key.
The live suite is `crates/connectivity/tests/cryptostruct_live.rs`,
`#[ignore]`d and read from `CS_LIVE_*` (and `CS_LIVE2_*` for the two-source
run): each test ends with a fresh login finding nothing resting, and the
harness cancels what it placed on stop and on unwind.

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
never-adopted strangers are not booked; an order that finishes while its
account is down comes back as nothing (no executions question); an omitted
resting order is closed `NotAtVenue` and then judged `Buried`; the metadata
check's deadline is outside the recovery worst case; the HTTP client's
resolver has no timeout; whether the adapter cancels by `ownOrderId` alone
before any statement is unproven; every order-entry socket is read every
slice. One PR per item, ticked in #386, the venue document moving with it.

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
The backtester that runs these strategies on recorded data, its fill-model
defaults and the Tardis feeds are `quant-trading-backtesting`'s.

## References

| File | Read it when |
| --- | --- |
| [references/legacy-python-stack.md](references/legacy-python-stack.md) | Working in a `tradingenginecs` strategy, `engine-backtesting`, the Rust mm/hedger bot, or a monitor on the legacy stack; porting a strategy to the middleware |
