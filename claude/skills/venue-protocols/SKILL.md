---
name: venue-protocols
description: Venue connectivity practice for market data and order entry. FIX session discipline (persist before send, sequence and gap handling, resend and gap fill, heartbeat and test request, logout handshake, dictionaries and repeating groups), FIX order entry and market-data semantics (ClOrdID chains, ExecType and OrdStatus, cancel and fill races, snapshot and incremental refresh), binary codecs (SBE headers, groups, var-data and extension rules, length-prefixed exchange feeds, fixed-point prices), borrow-only decoding with bounds checks and fuzzing, WebSocket feed lifecycle (keepalive, limits, auth renewal) and per-venue book maintenance from snapshot plus diff, and the session state machine with reconnect, resubscribe, reconcile and bounded hand-off to the engine. Use when implementing or reviewing a venue adapter, codec, feed handler or session layer.
---

# Venue protocols

Protocol practice that holds across venues. The desk's venue-specific facts
and the middleware modules that use them are in `quant-trading-tt`,
`quant-trading-apex` and `quant-trading-crypto-struct`; read the one the
task names. Domain rules (backpressure policy, cancel path, rate budgets,
reconnect reconciliation) are in `quant-trading`; Rust conventions in
`~/.claude/rules/rust.md`. Tag tables, header layouts, per-venue book rules,
libraries and the primary references are in
`references/fix-sbe-websocket.md`.

## Session discipline, any protocol

- Explicit states: disconnected, connecting, logging in, subscribing, live,
  degraded, recovering, logging out. Every transition is a function of state
  and event, every state has a timeout, and the machine is unit-tested with an
  injected clock.
- Reconnect with exponential backoff, full jitter and a cap, reset only after
  a connection has stayed healthy for a while, inside the venue's
  connection-attempt limits. On reconnect: re-authenticate, resubscribe,
  rebuild books from fresh snapshots, reconcile open orders and positions
  from the venue, and only then allow trading.
- One thread owns a session's I/O; frames reach the engine through a bounded
  queue whose overflow policy is stated per stream (market data: drop and
  force a resnapshot; order responses: never drop). Receive timestamps are
  taken in the I/O thread before any parsing.
- Metrics per session: gaps, resnapshots, reconnects, decode errors by kind,
  queue depth and drops, message age, and latency percentiles from receive
  to engine and from send to acknowledgement.

## FIX session layer

- Field order is fixed (`8`, `9`, `35` first; `10` last); body length and
  checksum are computed over bytes. Sender, target and begin string are
  validated on every inbound message.
- Heartbeats after the agreed interval of silence; a test request when
  nothing arrives for the interval plus a margin; disconnect when the test
  request goes unanswered.
- Sequence numbers increment per outbound message. Inbound below expected
  without the possible-duplicate flag is fatal; above expected triggers a
  resend request. Resent messages carry the duplicate flag, the original
  sending time and their original sequence number.
- **Persist before send**: the outgoing message and the next sender sequence
  are written to the store before the bytes reach the socket, and the
  inbound expected sequence after processing. A lost store is a negotiated
  reset, never a silent restart at one.
- Replay only application messages; gap-fill over administrative ones, and
  check whether an order is still wanted before replaying a stale new-order
  message. The sequence-reset flag that discards the replay window is used
  only for a deliberate, agreed reset.
- Dictionaries are vendored and extended by copy; repeating groups are
  parsed by the dictionary's order with the count field first and the
  delimiter field first in each instance. Drop-copy sessions are receive
  only and carry duplicates by design.

## FIX order entry

- Each order carries a client order id; each cancel or replace carries a new
  id plus the original. The whole chain maps to one internal order until a
  terminal execution report arrives.
- Execution reports are the truth: cumulative and leaves quantities over
  summed last quantities, deduplicated by execution id. A cancel reject
  ("too late", "unknown order") is not a terminal state; an order is live
  until its terminal report, and never marked dead on send.
- Unsolicited cancels and expirations arrive without a request and are
  handled by the state machine; a mass-cancel report says what the venue
  accepted, individual reports still follow.

## FIX market data

- Snapshot then incremental refresh; apply entries in order within a
  message; coalesced venues may carry several changes per level.
- There is no data-level sequence: a session gap means the book is dropped,
  the instrument marked stale, the subscription renewed, and quoting resumed
  only after a fresh snapshot. Venues that do not replay lost book updates
  make this the only correct path.

## Binary codecs

- SBE messages start with a header (block length, template id, schema id,
  version); fields come first, then groups, then var-data, read forward only.
  Extensions append fields with a since-version; an older decoder skips by
  block length, a newer one checks the acting version before reading an added
  field. Per-type null values mark absent optionals.
- Length-prefixed exchange feeds (ITCH-style) are fixed-width big-endian with
  implied-decimal prices and a transport sequence for gap detection; a packet
  sequence gap triggers the recovery feed.
- SBE and fixed-layout formats give fixed offsets and predictable latency;
  varint or offset-table formats cost decoding or indirection. Choose by the
  latency budget, not by convenience.

## Codec rules

- Decode as a borrow of the input bytes with accessor methods; no owned
  strings, vectors or boxes on the hot path; copy out only what outlives the
  buffer.
- Every length, count and offset is bounds-checked with checked arithmetic
  before indexing; malformed input returns a typed error that is counted and
  dropped, never a panic.
- Endianness is explicit per format; prices are integer mantissas with a
  per-instrument scale, never floats; timestamps carry their clock domain
  and precision; sentinels (null values, undefined prices) are handled before
  arithmetic.
- Each decoder has a fuzz target seeded with captured frames and a golden
  test over real captures, byte-exact on encode and field-exact on decode;
  the capture that exposed a bug stays in the suite.

## WebSocket feeds

- Keepalive and limits are venue-specific and counted against you: ping and
  pong cadence, maximum connection age, messages per second including
  control messages, streams per connection, connection attempts per window,
  authentication renewal. A reconnect storm without jittered backoff ends in
  a ban.
- Book maintenance follows the venue's snapshot-plus-diff alignment rule
  exactly (buffer, snapshot, align the first diff, apply, resnapshot on any
  mismatch) and verifies checksums over the venue's raw price and size
  strings. Quiet symbols are not stale; connection health comes from the
  venue heartbeat, book health from per-symbol age.
- Server time and receive time are both recorded; ordering across venues
  uses receive time. Decimal strings parse straight into scaled integers.
- Order entry: idempotent client order ids within the venue's format,
  request ids correlated to responses, weight headers tracked against a
  budget with a reserve for cancels, cancel-on-disconnect enabled as a
  backstop only, and a REST reconciliation of open orders and positions
  before quoting resumes after any reconnect.

## Testing

Recorded captures replayed through the real decoder and state machine; a
venue double that misbehaves on demand; and scripted chaos: half-open
connections, duplicates, skipped or out-of-order sequence numbers, truncated
and split frames, a logout mid-resend, and a store reload after a crash
between persist and send.

## Gotchas

1. Send before persist, and the sequence collision that follows.
2. Replayed administrative messages, or a stale new-order replayed as new.
3. A reset flag used to make a sequence error go away.
4. A cancel reject treated as terminal; fills summed without execution ids.
5. A FIX market-data gap patched instead of resubscribed.
6. A diff applied to a snapshot it does not align with.
7. A checksum computed over reformatted numbers.
8. Control messages counted against a venue rate limit nobody tracked.
9. A float on the price path; an unhandled sentinel.
10. A decoder that indexes before it checks.
