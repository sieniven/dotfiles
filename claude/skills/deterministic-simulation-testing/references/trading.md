# Simulating a venue for a market maker or hedger

Companion to `SKILL.md`. This mapping is ours; the article's example is a
quorum key-value store. Domain rules (money arithmetic, risk, quoting) are in
`quant-trading`; session and order-entry semantics are in `venue-protocols`.

A simulator never touches live trading state: no live keys, no live
endpoints, no production databases.

## The mapping

- The venue plays the article's network and remote process together: a
  simulated venue on the tick loop owns a matching model, the order states and
  the delivery queue for acknowledgements, fills and market data.
- The engine's decision core, order manager, position keeper and risk checks
  are the deterministic side. The venue client, clock and storage are the
  seam traits from `references/rust.md`.
- A hedger adds a second simulated venue. Both sit on one loop, so a fill on
  one and the hedge on the other interleave in an order the seed decides.
- One seeded decisions object drives market data, order flow from the
  strategy's own triggers, and every fault below; the fault schedule is
  logged per tick like any other.

## Venue gray failures to inject

- Late acknowledgement: the order rests and may fill before the engine
  hears it was accepted.
- Duplicate fill: the same execution id delivered twice.
- Fill before its acknowledgement.
- Partial fill, then a cancel reject ("too late") for the rest.
- Cancel racing a fill: the cancel is sent, a fill for the full size
  arrives, then the cancel reject.
- Disconnect with an order in flight: sent, no acknowledgement, session
  drops.
- Stale book: market data stops updating while the session stays up.
- Sequence gap on the feed or the order session.
- Rate-limit reject on a new order or a cancel.
- Clock skew: venue timestamps drift against the engine's clock.

Each is a delay, a duplicate, a reorder or a drop at the message level, so
the simulated venue needs no knowledge of the wire format.

## History to record

Every client-visible event, with its tick: order sent, acknowledged,
rejected, filled (with execution id, price and quantity), cancel sent,
cancelled or cancel-rejected; the position after each fill; reconnects and
reconciliations. The venue side records its own truth (resting orders, fills
issued) so the checker can compare both.

## Safety invariants

Checked over the history, while faults are active:

- Position equals the sum of fills, deduplicated by execution id.
- The engine's open-order set reconciles with the venue's after every
  reconciliation point.
- No order, and no position reachable by fills of open orders, beyond a risk
  limit.
- Own quotes never cross: no bid at or above an own ask on one instrument.
- Money arithmetic exact: integer ticks and lots or fixed-point, so the
  checker compares with `==`.

## Liveness after faults heal

Stop injecting, heal every link and the feed, then tick a bounded number of
times and assert: the session reconnected, open orders and positions were
reconciled with the venue, quoting resumed within the bound, and no orphan
order remains (live at the venue, unknown to the engine).

## Beside the existing skills

- `quant-trading-backtesting` owns market replay: one root seed with named
  substreams, a total event order and byte-identical reruns. Use the same
  seeding discipline here; a fault simulator is not a backtester and makes no
  PnL claim.
- `quant-trading-validation` asks for a pure decision core with a
  golden-fixture parity test; that core is what sits on the tick loop.
- `venue-protocols` owns the byte level: fuzz targets, golden captures and a
  venue double with scripted chaos (split frames, truncated messages). A
  message-level simulator never runs that code, so those tests stay.
