---
name: quant-trading-apex
description: >-
  The APEX venue (Asia Pacific Exchange): its CTP-style C++ SDK (TraderAPI and
  MdUserAPI, two sessions with two logins and flow directories, name servers,
  topics and resume types, 12-char local ids compared as text,
  GFD/FAK/FOK/market, modify as absolute price plus signed volume) and how
  engine-middleware's `apex` venue module and `pgd-apex-sys` integrate it:
  document block, vendor callback threads and the session queue, five-level
  whole snapshots, status mapping, id series, recovery ladder, the seat's send
  budget with its cancel reserve, UAT tiers, live-safety rules and the open
  questions in issue #382. Use when working in crates/connectivity/src/apex or
  crates/apex-sys of engine-middleware, in a strategy or monitor repo that
  names the apex feature or a connectivity.apex block, on an APEX UAT or
  production run, or with the vendor SDK and documents under
  ~/dev/apex/connectivity.
---

# APEX venue

Facts about APEX and the `apex` venue module of `engine-middleware`, so they
are not rediscovered each session. Domain principles live in `quant-trading`;
the engine's own conventions live in that repo's `CLAUDE.md`, which loads
when working inside it, and its `docs/venues/APEX.md` is the as-built
description this skill compresses. Outside that repo — a strategy repo
naming the `apex` feature, a monitor over the venue, a UAT run — this skill
is what a session has.

Snapshot: `engine-middleware` main at `1ad03f45` (2026-10-09), which
includes PR #402's cancel interval. Vendor documents are the
PerpetualContracts set — TradeAPI v1.08, MdUserAPI v1.02, Development Guide
v1.4, Conformance v1.15 — which match the vendored SDK 1.3.1. These are a
snapshot of the code and the documents, not a spec. Where the source
disagrees, the source wins: say so, and propose the fix to this skill with
`/learn`. A question only the venue can answer stays a question here.

## The venue in one paragraph

A Singapore derivatives exchange (gold perpetuals `AUP1`, `AUP10`, `AUP100`
on UAT) reached through FTD/CTP-style C++ libraries rather than a wire
protocol: there is nothing to encode, every request is a foreign call and
every reply a callback on a thread the library owns. Order entry
(`libapextraderapi.so`) and market data (`libapexmduserapi.so`) are separate
libraries with separate logins and separate flow directories, and streaming
quotes cannot be had from the order-entry session. Gateways are registered
as **name servers**, never as a front: a front takes priority, silently
defeats failover, and the venue deprecates it. Vocabulary: member =
participant, seat = user, client id = account; the seat is the unit the
per-second send quota is counted against, and one seat trades several
clients. The libraries are Linux x86-64 ELF against glibc and GNU libstdc++,
so on a Mac everything that loads them runs in the `linux/amd64` container,
emulated on Apple silicon — fine for "does it work", worthless for "how
fast". Two data centres in Singapore, Equinix SG3 primary and Singtel KC2 for
DR; production has four name servers, two primary and two DR.

## Middleware integration, as built

**Shape.** Feature `apex`, forwarded by `pgd-node`; `ConnectivitySource::Apex`;
document block `node.connectivity.apex`; trace target
`pgd::connectivity::apex`. `pgd-apex-sys` is the foreign boundary: the venue's
structs with every offset pinned, its enums and error table, a C++ shim and a
loader; it names no workspace crate and is one of the two crates allowed
`unsafe`. The libraries are opened by name at runtime, never linked, from
`sdk_dir`, and each leg is certified against its version string
(`ApexTraderAPI Lnx64 v1.3.1 L3K`, `ApexMdAPI Lnx64 v1.3.1 L3K`;
`standin::VERSION` admits the offline stand-in). `lib/apex` vendors the build
with its hashes; 1.3.1 is the only build with `AF_Modify`, and moving builds
moves vtable slots, which is why the version is certified at open. `build`
creates the flow directories, loads and certifies, registers gateways, sets
the heartbeat and subscribes; the libraries' `init`, which opens sockets,
runs on the first slice, which is what keeps `--dry-boot` safe. One flow
directory for both sessions, an empty instrument directory or an `md` block
resolving to no topic is refused at build.

**Threads.** One vendor thread per session dispatches callbacks through a
trampoline into `&mut dyn Sink` or `&mut dyn MdSink`, the one `dyn` call on
the record path. What only the duty thread may touch crosses as records on an
SPSC ring of 8 192 `SessionEvent`s; a record the ring cannot hold is counted,
never blocked on. Callbacks on slots nothing consumes are counted per slot
and said once a second. Nothing in a callback waits or allocates in steady
state; the one thing that can hold the vendor thread is a `tracing` line at
an enabled level, and a node at `trace` writes one per depth snapshot. Each
slice takes every waiting cancel first, then at most 64 places and amends per
instrument and 32 session records; the market-data queue drains to empty.

**Market data.** Topics are the exchange's: `100` is level 1, `111` all five
levels a side; subscribing both duplicates and adds no depth. Every depth
callback is a whole snapshot of at most thirteen records — `Reference`,
`MarketStats`, `Clear`, ten levels — so an instrument is `book: l2` and no
`TopOfBook` is published. `Reference` carries the static `LowerLimitPrice`
and `UpperLimitPrice`, about ten percent either side of the previous
settlement and fixed for the day; `MarketStats` carries the dynamic
`BandingLowerPrice` and `BandingUpperPrice`, ten percent either side of
`ReferencePrice`, which moves with the best bid and ask. Only BTC contracts
carry a band. `f64::MAX` is the venue's absent sentinel and NaN an unset
limit; both read as absent, and mapping either to zero is refused. The only
gap signal is the per-topic package sequence, which names no instrument, so
a missed package gaps every book; a refused ring push gaps its own.
`request_snapshot` does nothing: every tick is a snapshot and a feed login
restates every book. Decode runs on the vendor thread into a buffer sized at
build, under a 2 µs median budget (`apex_decode`), with no allocation proof.
`md_skipped_total{reason}` counts what a snapshot could not read
(`bad_stamp` is an empty `CalendarDate` or `UpdateTime`);
`md_books_unheard` counts books still silent 30 s after a feed login.

**Account truth.** Every venue statement rides the venue lane from the
vendor thread; the duty states synthetic refusals, positions, bindings and
funds on the source lane. Status mapping: a queueing status is `Ack` the
first time for an id this run minted and `Statement` after; canceled or
not-queueing is `Canceled`, carrying the traded volume; all-traded is a
`Statement` whose cumulative completes the record. The six statuses have no
suspended value; if the venue states a suspended order as not-queueing it
reads as `Canceled`, which the venue has not said (V2). A refusal
arrives as a reply with the venue's error code mapped to a `RejectCode`.
Every order carries `hedge_flag` ('1', speculation, by default), `label` in
`BusinessUnit` and `auto_suspend` as `IsAutoSuspend`; a statement no binding
answers whose echoed label matches carries `OrderEvent::OURS`. Venue times
go on `venue_ts`, composed as UTC+8 by analogy with depth and unchecked
against a live fill. Positions have one owner and two triggers — the ladder
once per login, a timer every `position_poll_secs` (5) while `Up` — asked
over the member, assembled in a fold and stated per pair on the source lane;
a `NET` row is read with the venue's sign, which the seat has only ever
answered flat. Funds are per member (`ReqQryPartAccount`), summed into one
`AccountEvent::Funds` in millionths of a currency the venue does not name.

**Egress.** The venue accepts four order types: `GFD` (`Tif::Gtc`; the venue
closes it at end of day), `FAK` (`Ioc`), `FOK`, and `MARKET`, to which no
`Tif` maps, so the engine never sends one; `PostOnly` has no mapping and
comes back a reject. Prices leave as tick × count, a lot is a contract, and a
quantity above `i32::MAX` lots saturates. Admission on a place: `dry_run`,
the instrument gate, the id series seeded, then the rate token before the
mint. The library's return is classified: queue-full and too-fast (local -2
and -3) are provably unsent and map to `RateLimited`; not-connected is
unknown, and since one order cannot be asked about, an unknown return
publishes `Down` and restarts the ladder keeping the binding. A cancel or an
amend names its order by the 12-digit local id, which exists before the venue
answers, so a cancel can beat the ack. An order this run did not mint is
named by `OrderSysID`, kept on the `Strangers` ring. Modify takes an absolute
price and a **signed volume difference** against the total the venue holds;
the source converts the engine's new total at send. There is no `AmendAck`:
the answer to a modify is a statement of the new total.

**Identity.** One series serves orders and actions; a `LocalId` is exactly
twelve digits because the venue compares ids as text; it is seeded from the
floor (`MaxOrderLocalID`) the login returns and only rises, so a restart
resumes above everything the venue has seen. An id the venue refuses as stale
forces a fresh login, `Down`, and a ladder.

**Liveness.** `Up` is the verdict of both sessions; a feed drop takes the
source `Down` as a whole. The libraries reconnect the link themselves and
never re-authenticate, so a login is owed on every link-up: a deferred login
(code 45) retries after 1 s doubling to 15 s; a refused login is `Fatal` on
order entry and a deferral on the feed. Heartbeat: the module sets 19 s
unless the document says otherwise (the library itself defaults to 10 s when
nothing is set; the venue's floor is 4 s and it recommends 10 to 30); the
library warns at half the timeout (`heartbeat_warnings`, moves nothing) and
drops the link at the timeout, and that drop is the `Down`, so a dead link
reads `Up` for one heartbeat timeout. Drop reasons: `0x1001` and `0x1002`
read and write failure, `0x2001` and `0x2002` heartbeat receive and send
timeout, `0x2003` error message.

**Recovery.** The ladder asks instruments first — one query per document
instrument, the tick compared and the multiplier where the document states
one; a mismatch or an unlisted
instrument is `Fatal` until the document is fixed — then orders, trades and
positions in that order, orders before trades because order rows carry the
cumulative. Each question waits 10 s and is asked three times under fresh id
runs; a question given up on is `Fatal`. Ordinary recovery is a login retry
of at most 15 s, a 1 s quiet period and four answers at the venue's pace; the
worst case, 120 s, runs past the engine's 90 s dwell, after which the node
stops and an operator's `Start` restarts the ladder. The private stream is
subscribed in resume mode, so every login replays order and trade returns
from the flow directory's position. `orders_resync: whole` (the default) asks
for every order of the day and closes what the answer omits; `changed` asks
since the sync point, right only if the venue filters on update time, which
is open.

**Rate budget.** The venue blocks silently past the seat's quota, so the
count is kept here: `sends_per_second` (50 by default, the figure of a
standard seat as issued, which no vendor document states; 0 unmetered) on a
fixed one-second window, a quarter reserved for cancels, so the default
places and amends at 37 and keeps 13. The token is taken before an id is
minted; a refused request is a synthetic `RateLimited` at once. Recovery
questions, the position poll and the funds question draw on no budget;
whether the seat's quota counts them is question V4. The cancel interval is
`cancel_retry` = 250 ms (PR #402): the UAT cancel round trip measured 44.8 ms
at p50 and 53.2 ms at worst, so 250 ms leaves nearly five worst cases;
`engine.cancel_retry_ms` overrides it.

**Instruments and accounts.** The directory holds at most 64 instruments,
the most one login asks about; each needs a `tick`, a `multiplier` is
optional and must be a positive integer where stated, and a lot is a
contract. The gate has three settings — open,
day-limit-only in the pre-open auction (`GFD` only), shut — and every status
but continuous trading and the pre-open shuts it; a change reaches the
engine as `AccountEvent::Status`. `clients` names the venue's client id for
each of `engine.accounts` in order; an order for an account with no client is
a synthetic `Reject` before any token or id is spent.

**Document block** (`node.connectivity.apex`; no container default, so the
required keys have no fallback):

| Key | Default | Note |
| --- | --- | --- |
| `sdk_dir` | required | directory holding both `.so`; an uncertified version is refused |
| `flow_dir`, `md.flow_dir` | required | distinct, created if missing, must outlive the process |
| `name_servers`, `md.name_servers` | empty | `tcp://host:port`, primaries first, at most 4 |
| `credentials` | required | `user` (seat), `participant` (member), `password` (`SecretRef`) |
| `clients` | required | one client id per `engine.accounts` entry, at most 64 |
| `md.topics` | required with `md` | a block resolving to no topic is refused |
| `heartbeat_secs` | 19 | floor 4 |
| `scope` | `single` | `manager` selects the member's private stream |
| `position_poll_secs` | 5 | 0 never asks |
| `sends_per_second` | 50 | 0 unmetered; several nodes on one seat split it |
| `orders_resync` | `whole` | or `changed` |
| `label` | absent | at most 20 printable ASCII, echoed in `BusinessUnit` |
| `hedge_flag` | `speculation` | `arbitrage`, `hedge`, `market_maker` |
| `auto_suspend` | `false` | semantics unknown; a switch for probing |

Widths, floors and counts are checked by the venue's own constructors with
the venue's message; a password longer than its field is truncated silently.
Coordinates and secrets are `!env` or `!file` references, never values.

**Observability.** Series: `session_state` and `reconnects_total` per leg
(`main` is order entry, `market` the feed), `venue_polls_total{outcome}`,
`account_funds{kind}`, `wire_ids_foreign_total`, `md_skipped_total`,
`md_books_unheard`. `SourceCounters` — logins, drops, deferrals, refusals,
unhandled callbacks, rollbacks, heartbeat warnings, bindings refused and the
rest — reach only a rig. `RUST_LOG=pgd::connectivity::apex=trace` prints
every depth snapshot with both price pairs.

## Running against the venue

| Tier | Recipe | Needs | Reaches the venue |
| --- | --- | --- | --- |
| Offline | `just apex-offline` | nothing | no |
| Vendor | `apex.yml` in CI | the vendored SDK | no |
| Live | `just apex-uat` | Docker, credentials | yes |
| Node, dry | `just apex-example-dry` | Docker, credentials | no |
| Node | `just apex-example` | Docker, credentials | yes; trades once `dry_run` is off |

Run them in that order. `.env`, git-ignored and copied from `.env.example`,
is the single source of every coordinate: `APEX_TRADING_GATEWAY`,
`APEX_MD_GATEWAY`, `APEX_PARTICIPANT`, `APEX_USER`, `APEX_PASSWORD`,
`APEX_CLIENTS`, `APEX_MD_TOPIC`, `PGD_CONTROL_TOKEN`, and `APEX_SDK_DIR` only
to check a candidate build. Live-safety facts to hold onto:

- **A missing required variable makes the live suite skip and report green.**
  A silent pass means "did not run", not "worked".
- `node.yaml` ships `dry_run: true`. Going live takes two keys: the document
  saying `false`, and an operator's `start` over the control API. Launching
  with `--start` gives up the second key.
- The one test that fills runs only with `APEX_ALLOW_FILLS=1`; every other
  order rests one percent (`EDGE_BPS` = 100) below the best bid, or below
  `Reference::anchor()` where the venue quotes nothing, one lot, and is
  cancelled; the rig's `Drop` sweeps what is left even through a panic. A
  `SWEEP:` line names an order to go and look at.
- UAT quotes nothing: every instrument reads the absent sentinel on both
  sides, and a price is taken from `Reference::anchor()`. The UAT clock runs
  about 35 s slow and keeps drifting.
- The venue document's `cargo test -p pgd-apex-sys --test vendor --
  --ignored --nocapture` line is the local run inside the amd64 image, while
  CI runs `apex.yml` natively; on this machine the test-running rules in
  `~/.claude/CLAUDE.local.md` and the repo's own `CLAUDE.local.md` decide
  how a test binary may run, and a refused binary is unverified, not failing.
- Read a run with `--nocapture`: the venue's error code appears only in the
  log, and `pgd_apex_sys::lookup` holds the table.

## Open questions and known gaps (issue #382)

Only the venue can answer the first group; the module fails closed meanwhile.

- The position answer has only ever been flat, so the `NET` sign is
  unverified; if it is wrong, every position reads inverted.
- `IsAutoSuspend`: does the venue suspend on disconnect, how is a suspended
  order stated, is there any cancel-on-disconnect? No disconnect protection
  is armed; orders left resting when the process dies stay at the venue.
- The market-data topic id, and whether the seat is Single Trade or Manage
  Trade (`SubscribeUserTopic` against `SubscribePrivateTopic`; the wrong one
  returns no orders and no trades, with no error).
- Whether the order query's `time_start` reads insert or update time, which
  decides `orders_resync: changed`.
- The venue has said amend is unsupported in production (V11); the node reads
  that as an amend going unchecked against limits and band, so the engine's
  `venue_limits` gate holds amends to both pairs.
- Whether the quota counts queries (V4), what the library's own -2 and -3
  limits are (V5), whether a price-only modify keeps queue priority (V3),
  what an empty book's snapshot says after a re-login (V6), whether
  production is NTP-disciplined (V9), and which request restates every book
  without a login (V10: `ReqSubscribeTopic` with `SequenceNo` -1).

Contract departures still open on the module side: a venue-ring drop flaps
`Fatal` and `Up` instead of stopping the node; a full source lane is logged,
not `Fatal`; the feed's session-queue loss count is never read; an
unreadable timer answer leaves the source `Up` unbounded; a place is sent
the slice it is popped whatever the word says; replayed rows carry neither
`RECONCILED` nor `POSSIBLE_DUPLICATE`; no egress count is a series. One PR per
item: fix it, tick it in #382, and move the venue document with it.

## Rules when changing the module

- `build` opens no socket; the first slice does. Never link the libraries,
  never register a front, never share a flow directory between sessions.
- `dry_run` first on every kind of request; the rate token before the id;
  places and amends stop at the cancel reserve, and cancels may spend it.
- Every id across the seam is a `NonZeroU64` under a restart-stable mapping;
  a wire id is bound before the send and resolvable after a terminal.
- A callback never waits, never allocates in steady state, and never logs
  per record at `debug`. Market data is decoded on the arriving thread.
- `Down` at the first sign, `Fatal` only when the source cannot recover
  alone, `Up` only when both legs are logged in and positions are stated.
- A change in described behaviour changes `docs/venues/APEX.md` in the same
  PR; open work is a checkbox in #382, never a roadmap entry.
- Tests: the module's unit tests, `crates/tests/tests/apex_components.rs`
  against the stand-in, the vendor check in CI, and the live suite under
  `crates/tests-e2e/tests/e2e_apex/`, `#[ignore]`d. There is no e2e double
  and no allocation proof for the decode path.

## Where the vendor documents and the module disagree

Both readings are recorded; neither is resolved here.

| Topic | Vendor documents | Module |
| --- | --- | --- |
| Heartbeat default | 10 s when `SetHeartbeatTimeout` is never called | 19 s unless the document sets it; the venue doc calls 19 "the venue's own default" |
| Seat quota | a per-second quota exists, excess is blocked in the network, ask the exchange for the figure | 50 a second by default, the issued figure |
| Trader library name | `APEXtraderapi.so` (TradeAPI p.7) | `libapextraderapi.so`, the file shipped in `lib/apex` |
| Modify | new in TradeAPI v1.08; Conformance 3.4.1 tests it while 3.6.16 says unsupported | sent as `AF_Modify`; the venue says unsupported in production |
| `BusinessUnit` | echoed on acks and trades per the appendix, "not used" in the struct comments | read back as the `OURS` label |
| `VolumeTraded` on an order return | "not used" in the struct, while p.16 says it reflects fills | the cumulative every order report carries |
| `HedgeFlag` | insert accepts only '1' | the document offers all four |
| Second login | code 106 "duplicated session", while the guide says the first session is force-disconnected | a refused login is `Fatal` |

## References

| File | Read it when |
| --- | --- |
| [references/vendor-api.md](references/vendor-api.md) | Touching the foreign boundary or a callback; mapping an error code; reading a conformance case; the login, query, topic and resume semantics; the network and DR facts |
