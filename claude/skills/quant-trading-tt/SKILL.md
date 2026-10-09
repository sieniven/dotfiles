---
name: quant-trading-tt
description: >-
  The TradingTechnologies (TT) venue: TT FIX 4.4 order routing, market data
  and drop copy (session types, logon and sequence rules, ClOrdID scope,
  ExecutionReport semantics, MDEntryType values, 100 ms coalescing, no replay
  of lost book updates, per-order cancel-on-disconnect) and TT REST 2.0 (ttid
  token flow, ttaccount, ttmonitor, ttledger, environments, rate plans), and
  how engine-middleware's `tt` and `tt-rest` modules integrate them: vendored
  dictionary, borrow-only codec, session machine, order ledger, in-flight
  ladder, REST position poller, what 'proven offline, not wireable' means,
  issue #383 and the roadmap's live path. Use when working in
  crates/connectivity/src/tt of engine-middleware, on anything that names the
  tt or tt-rest feature or TradingTechnologies, or with TT's FIX or REST
  documentation.
---

# TradingTechnologies venue

Facts about TT and the `tt` venue module of `engine-middleware`, so they are
not rediscovered each session. Domain principles live in `quant-trading`;
inside the middleware repo its `CLAUDE.md` and `docs/venues/TT.md` are
authoritative and this skill is their compression plus the vendor facts
they do not carry.

Snapshot: `engine-middleware` main at `1ad03f45` (2026-10-09). Vendor facts
were read from `library.tradingtechnologies.com` on 2026-10-09, with a few
pages from a 2026-09-08 copy; the vendored dictionary is stamped
`TT FIX Version: UAT 2026-08-03`, matching the UAT schema TT publishes. These
are a snapshot, not a spec: where the source disagrees, the source wins —
say so, and propose the fix to this skill with `/learn`.

## The venue in one paragraph

TT is a broker-neutral platform in front of listed-derivatives exchanges
(CME, ICE, Eurex, SGX, HKEX, JPX and others). A client speaks TT FIX, a
documented subset of FIX 4.2 or 4.4 in which sending an undocumented tag
"can produce unexpected results", over SSL-wrapped TCP with server
certificates only, one session type per service: order routing, market data
(which also carries security definitions and status), drop copy, inbound
drop copy and a non-persistent recovery service. Sessions are persistent and
reset on Saturday at 22:00 UTC by default; certification in UAT, including
sequence-mismatch tests, precedes production. TT REST 2.0 lives at
`https://ttrestapi.trade.tt/<service>/<env>` with `ext_uat_cert` and
`ext_prod_live`. On a reconnect TT replays every unsent execution report
with fresh sequence numbers and ends the replay with a News message; market
data lost during a disconnect is never replayed.

## Middleware integration, as built

**Shape.** Feature `tt`; `tt-rest` adds the account service and brings
`reqwest`, `serde` and the runtime under it; `ConnectivitySource::
TradingTechnologies`; trace target `pgd::connectivity::tt`. Three hand-rolled
pieces: the dictionary TT publishes, vendored at
`crates/connectivity/dictionaries/TT-FIX44.xml` (649 fields) and reparsed by
a test against the generated table in `tt/fix/dictionary.rs`; a borrow-only
framing codec; and a session machine. `TtBuilder` declares
`MARKET_DATA | ORDER_EXECUTION | ACCOUNT_MANAGER`, overridable through
`provides`, and is handed its `Transport` already made. **There is no
document block**, so `wanted()` refuses the venue outside a test with "no
document block; it is reachable only from a test", although `pgd-node`
forwards both features; every `impl Transport` in the workspace is a test
double, and nothing in the builder opens a socket (the `tt-rest` poller
holds a real HTTP client, but nothing outside a test constructs it).

**Threads.** `TtSource` overrides none of `publishes_md`, `states_venue` or
`install_bindings`: it decodes on the duty thread, pushes market data
through the `IngressWriter`, states everything on the source lane and never
takes the venue half. `tt-rest` adds a `SnapshotSource` over the identity,
account and monitor HTTP services, driven by a poller on an unpinned thread
of its own with an `Instant` clock and an allocating channel (a #383
departure), feeding the same never-drop account lane. `RestConfig` takes a
base, an `Environment` (`UatCert` → `ext_uat_cert`, `ProdLive` →
`ext_prod_live`) and an interval with a 5 s floor; `DEFAULT_ROOT` is
`https://ttrestapi.trade.tt`, the per-request timeout 15 s, the token is
renewed 60 s before the venue says it expires, a listing follows at most 64
pages, and positions are asked in contracts.

**Market data.** The decoder reads direct depth only; implied prices,
trades and session statistics sharing an `MDEntryType` are counted and
dropped. One frame may interleave several instruments' entries, so the
decoder groups them per instrument in place and publishes each run whole; a
run the ring refuses, or an unreadable entry (no side, off-grid price,
off-step size), is owed to its instrument. Records are stamped with the
node's clock at decode, not the venue's (a departure). A FIX sequence gap
writes `Down` until the resend closes it, because TT does not replay the
book records lost in it; `request_snapshot` does nothing, so a gapped book
heals only on the next session. The inbound path is proven allocation-free
once warm; the outbound path allocates.

**Account truth and identity.** Every statement rides the source lane in
venue order; an order event's `ts` is the venue's `TransactTime` (a
departure: it should be receipt). A venue-made cancel carries
`VenueInitiated`. `OrderLedger` is the live-order table — no decisions, no
risk, no position — read by the in-flight ladder, the cancel sweep (TT has
no mass cancel) and the reconnect diff. The venue states no id floor, so
`RunId`, the unix second the builder was made, gives each run its own id
space; TT refuses duplicates per request, so a fresh wire id is minted for
every request that changes an order. A terminal's binding stays resolvable
through a bounded graveyard; an aged-out own id counts
`wire_ids_unmapped_total`, a foreign one is forwarded by the venue's id and
counts `wire_ids_foreign_total`. No `Bound` is stated and `install_bindings`
returns `false`, so nothing survives a restart and the engine discards every
survivor only a binding could have named.

**Liveness.** `VenueSession::apply` is the sole mutation point.
`SessionState` carries its data per state: `Connecting { attempt }`,
`AwaitingLogon { since }`, `Recovering { from }`, `Active`,
`Down { reconnect, reason }`. The source goes `Fatal` once three retryable
disconnects have fallen since its last accepted logon;
`DisconnectReason::Divergence` never retries, since reconnecting into a
state neither side agrees on would trade on a fiction; otherwise it retries.
**No reconnect delay is applied today**: `BACKOFF_MIN` (125 ms),
`BACKOFF_MAX` (60 s) and `VenueSession::backoff()` are `#[cfg(test)]`, a
modelled policy no production path reads, so the live transport must pace
its own reconnects; the venue document's "doubles from 125 ms towards 60 s"
describes that model. The heartbeat defaults to 30 s, the logon
resets sequence numbers, empty comp ids are refused, and the source answers
the venue's test request but sends no heartbeat of its own.

**Recovery.** `recover` sends the logon once and waits on `Active` — the
logon accepted with no gap, or the gap refilled. `Up` follows once every
order the venue named before the drop has been restated, answered unknown,
or asked about five times five seconds apart and left open without a
verdict: about 26 s for eight silent survivors, and around 140 fill the
engine's 90 s dwell. It waits on neither the ledger's remaining questions
nor the poller's first position statement (a departure); after the last ask
the engine settles a request in doubt as lost without the venue's word.

**Proving.** The codec, session machine, ledger and in-flight ladder are
unit-tested in the module; `crates/tests/tests/tt_components/` drives the
real source through the protocol rig in `crates/tests/tests/venue_rig/`
under a test clock; `crates/tests/tests/alloc_free/tt.rs` proves the inbound
path. There is no end-to-end suite and no live suite.

## What "proven offline, not wireable" means

Six things stand between the module and a live session, all designed and
none started, sequenced after APEX's live verification: a production
`Transport` over TLS with no plaintext variant; a market-data subscription
request and a call site for it; a session watchdog; frame capture; an answer
to `request_snapshot` (a resubscribe of the gapped instrument's request id,
or the REST book); and an `Up` that waits on the ledger's questions and the
first position statement. The document block waits on all of that; its
shape is an entry in `ConnectivityConfig` beside the APEX one. The other
departures — `ts` from `TransactTime`, market data stamped at decode, the
allocating outbound path, the poller's own thread and clock, no `Bound` —
are bugs tracked as checkboxes in issue #383, one PR each.

## TT facts the module leans on

The venue document carries none of these; the reference file has the rest
with its source pages.

- **Logon.** Tag 49 is the session's Remote Comp Id and TT echoes it in its
  own 56; 56 is fixed per session; 57 is required when Setup names a Target
  Sub Id; the password goes in 96 `RawData` (553/554 in 4.4 only) and never
  expires; 98=0; 141=Y with 34=1 is mandatory on market-data and recovery
  sessions and optional on order routing, where a lower 34 than expected
  gets a Logout. A second logon on the same session logs the first out unless
  Setup disables forceful logout.
- **Sequence rules.** Never replay an order: a D, G, AB or AC with 43=Y is
  rejected with a Business Message Reject. Gap-fill instead. After a
  reconnect TT delivers every unsent execution report with incrementing
  sequence numbers, also after a 141=Y relogon, and News (35=B) marks the
  replay complete; a Resend Request is honoured; executions lost together
  with the sequence state are recovered over REST.
- **Order routing.** `ClOrdID` is at most 20 characters, unique since the
  last reset plus any GTC/GTD order still working; a duplicate is a Business
  Message Reject; 41 must name the order's *current* 11, and 37 is TT's
  constant key. Account (1) is case-sensitive; 116 names the user when
  several share an account. Unsolicited cancels are normalised: IOC and FOK
  leftovers as 39=4/150=4, everything else including end-of-day expiry as
  39=4/150=C. Instrument identification by 48 with 22=96 (the TT id, which
  exceeds `i64::MAX`, so parse as `u64` or text) is unambiguous; a lookup
  matching more than one instrument is rejected. Fills may arrive
  aggregated in `FillsGrp` unless the session option splits them; for HKEX,
  OSE, SGX, TOCOM and others exchange fill updates arrive as Trade Capture
  Reports unless an option converts them. Pending acks from the OM API
  markets (HKEX, JPX, SGX) come as 150=D, 39=A, 378=9002.
- **Cancel-on-disconnect.** Per order, `18=o 2` (or `o S` for a held order)
  asks TT to make **one** cancel attempt on logout or TCP loss; it is not
  honoured if the TT FIX server itself crashes. Exchange-level
  cancel-on-disconnect exists per market (CME, ICE, Eurex, SGX supported;
  LME and Coinbase not; OSE offers it per order but TT does not support it). No mass-cancel message and no FIX message-rate
  limit are documented; an IFOA timeout (30 s) blocks a route for new orders
  until a test request succeeds.
- **Market data.** One V per subscription with 262, 263 (0 snapshot, 1
  snapshot plus updates, 2 unsubscribe), 264 depth (0 full, 1 top, N levels),
  265 (0 repeated W, 1 one W then X), 266=Y only. Implied prices are flagged
  by entry types Y and Z alone. Incremental updates are coalesced at 100 ms
  and full refreshes at 1 s on multi-tenant servers; uncoalesced data is a
  paid dedicated option. X groups lead with 279 and 290 gives the position
  *before* the message; there is no 83 `RptSeq`, so a per-instrument gap
  cannot be detected, and lost updates are not recoverable — TT recommends
  redundant live-live sessions.
- **REST.** `x-api-key` on every call plus `Authorization: Bearer <token>`
  from `POST /ttid/<env>/token` with form body
  `grant_type=user_app&app_key=<key>:<secret>`; the reply carries
  `seconds_until_expiry` and no refresh grant, and the numeric lifetime is
  undocumented. Every request needs `requestId=<app>-<company>--<guid>`,
  fresh each time. Plans allow 3, 5, 10 or 25 requests a second; POST
  pacing is stated inconsistently (one per ten seconds, or 20 items with a
  1 s pause). `ttmonitor /position?accountIds=…&scaleQty=0` is the position
  source; `ttledger /orders` takes at most 50 accounts and returns at most
  1 000 with no paging, `/fills` pages by `minTimestamp` in epoch
  nanoseconds; neither is a real-time feed.

## Open questions and known gaps

- **Cancel-on-disconnect is unstated.** TT offers `18=o`, the venue
  contract requires cancel-on-disconnect "armed and stated where the venue
  offers it", and `docs/venues/TT.md` never mentions it. A candidate
  checkbox for #383.
- The REST token lifetime is undocumented; the 60 s renewal margin rests on
  each reply's `seconds_until_expiry` alone.
- The reconnect delay the venue document describes is test-only; the live
  path needs a real one, and it is not among the roadmap's six items.
- `RunId`'s one-second granularity is justified in `ids.rs` by TT permitting
  one live session per `SenderCompID`; TT's Setup has a toggle that allows
  two concurrent sessions, under which the uniqueness argument breaks.
- The admin dispatch has no arm for News (35=B), which TT documents as the
  end of a replay; `Active` is reached through logon and gap-fill alone.
- Not confirmed by any TT page: FIX message-rate throttles, market-data
  subscription limits, whether market data must be resubscribed after a
  reconnect (assume yes), a reset schedule specific to market-data sessions,
  the maximum sessions per company, price formats and fractional ticks, and
  the per-exchange order-type and TIF matrix in the Setup help.
- The #383 departures listed above, plus "`Up` before the poller has asked
  anything" and the in-flight ladder forcing a terminal on a request the
  venue never answered.

## Rules when changing the module

- Keep the dictionary vendored and its reparse test green; a build that
  reaches the network is not reproducible.
- The codec stays borrow-only and the inbound path allocation-free; a change
  to the outbound path should reduce its allocations, never add to them.
- Every `impl Transport` outside a test is a design change: it belongs to
  the live path in `docs/roadmap/TT_ROADMAP.md`, not to a fix.
- A sequence gap on market data is `Down`, never a silent resync; a
  `Divergence` is never retried.
- A change in described behaviour changes `docs/venues/TT.md` in the same
  PR; open work is a checkbox in #383.
- On this machine the test-running rules in `~/.claude/CLAUDE.local.md` and
  the repo's own `CLAUDE.local.md` decide how a test binary may run; pass
  `--all-features` explicitly so `tt` and `tt-rest` compile in, and treat a
  refused binary as unverified, not failing.

## References

| File | Read it when |
| --- | --- |
| [references/tt-fix-and-rest.md](references/tt-fix-and-rest.md) | Encoding or decoding a message; designing the live transport, the subscription request or the watchdog; mapping a reject or an `ExecType`; the hosts, ports and environments; the REST endpoints and their limits |
