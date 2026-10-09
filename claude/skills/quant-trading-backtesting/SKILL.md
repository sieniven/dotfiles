---
name: quant-trading-backtesting
description: >-
  Backtesting framework expertise for an HFT / market-making / crypto-perp
  desk: event-driven replay design, L1/L2/L3 data and what each permits, book
  reconstruction and queue-position models (exact by order id on L3,
  estimated on L2), venue matching semantics, the three latencies (feed,
  order entry, order response) with jitter and the cancel-fill race, the
  closed loop that calibrates a simulator against live fills, and
  benchmarking: markout curves, fill ratio, PnL decomposition, quote uptime,
  baselines and the optimistic-to-pessimistic bracket. Also the platform's
  backtester (engine-backtesting) and data (Tardis) facts, and what
  hftbacktest and NautilusTrader do. Use when writing or wiring a backtest or
  driver, choosing or calibrating a fill, queue or latency model, picking
  data granularity, reading backtest output, comparing runs, or benchmarking
  a strategy. Promotion gates and the believability verdict live in
  quant-trading-validation.
---

# Backtesting practice

How to build, configure and read a simulator that a market maker can trust.
Statistics (effective N, deflated Sharpe, PBO, purged folds) live in
`quant-trading-research`; the promotion process (fidelity rungs, optimism
audit, parity against live, gates, kill criteria) in
`quant-trading-validation`; engine conventions in `quant-trading`. The
platform's backtester and data facts are in
[references/platform-backtester.md](references/platform-backtester.md); what
hftbacktest and NautilusTrader do, as the reference implementations of the
models below, in [references/oss-backtesters.md](references/oss-backtesters.md).

## Simulator architecture

- Event-driven replay on the local clock: every event is applied at the time
  the strategy would have seen it, and the engine advances time. A callback
  never blocks waiting for a fill; a strategy that waits inside a callback
  forces an immediate fill model on everyone.
- Two timestamps on every event, exchange and local. Features and decisions
  see the local one; matching uses the exchange one. A feed with only one
  timestamp has had its latency thrown away.
- Deterministic ordering: a total order of events by (timestamp, event-type
  priority, sequence), per-feed sorted streams merged by that key, so two
  events in the same nanosecond resolve the same way on every run. Never by
  arrival order or dict iteration.
- Seeded randomness: one root seed, named substreams derived from it, so a
  draw in one component cannot shift another's. Pin the data snapshot (path
  and hash), code (commit) and config. Same inputs produce byte-identical
  artifacts; any diff is a bug, and a rerun test should assert it.
- One code path: the strategy class that runs live runs in the simulator,
  against manager protocols the simulator implements. No research-only
  branch, no engine-only dependency in strategy logic.
- Timers and scheduled events ride the same timeline as market data.
- Artifacts with a schema: fills, orders with their lifecycle, equity
  snapshots, metrics, data quality, config and seed. Runs that cannot be
  diffed cannot be compared.

## Data levels and the book

- L3 (market by order): individual orders with ids; queue position is
  measured, orders ahead minus cancels ahead. L2 (market by price): size
  per level; queue position is estimated. L1: the touch only; depth and
  queue are assumptions. Trades: a print proves liquidity existed for an
  instant, not that it remained. Bars: no intrabar order, spread or depth;
  signal screening only.
- Granularity cannot be upgraded. L3 can be aggregated down to L2 and L1,
  which is also how to measure what an L2 estimator gets wrong: build L2
  from L3 and run both.
- A sampled snapshot stream (the platform's 25-level book) hides touches
  between samples, so fill-on-touch against it is more optimistic than
  against deltas, and queue position cannot be computed from it at all.
- Rebuild the book from deltas in sequence. A sequence gap is corruption,
  not a missing level: mark the book gapped until the next snapshot and
  never match across the gap. Verify the rebuilt book against the venue's
  own snapshots; unit-test matching, priority, cancels, partial fills and
  sweeps.
- Point-in-time metadata: tick, lot, contract multiplier, fee tier, funding
  schedule and listing state as of each event, never today's values.

## Queue position

- L3: a FIFO per price level by order id. Your order joins the tail at its
  arrival time, after order-entry latency, advances as orders ahead cancel or
  fill, and fills when a trade consumes through it or the opposite best
  crosses it. Truth at small size.
- L2: an estimate, and the estimator's shape is the assumption. The
  risk-averse rule (advance only on trades at your price, every cancel is
  behind you) is the pessimistic bound. The probabilistic family splits each
  size decrease at your level before and after you by a function f of your
  relative position x: f(0) = 0 (at the head every decrease is behind you),
  f(1) = 1 (at the tail every decrease is ahead); power and log shapes
  differ in how fast the middle moves, and log(1 + x) depends on the level's
  size. Subtract the trade quantity at the level before applying the book
  decrease, or trades count twice.
- Volume-only rules ignore cancels and are too pessimistic deep in the
  queue; a rule that ignores cancels ahead at the touch of a fast market is
  wrong the other way.
- Calibrate or do not quote the result: fit the family parameter on live
  fill rate by distance from the touch, per venue and instrument class, and
  state the fitted value with every number.
- Amend semantics are the venue's: a price change or size-up loses
  priority; a size-down keeps it on some venues. Model the rule of the
  venue being simulated.

## Matching semantics

- Replay cannot move the market. The book is frozen, there is no impact,
  and the simulation holds only while your size is small against the level
  and your flow is a small share of volume. Taker fills walk recorded depth
  that does not deplete; track consumed size per level until fresh data
  arrives, or every simulated order sees the full displayed size.
- Encode the venue's rules: price-time or pro-rata; post-only rejected (or
  repriced) when it would cross; IOC and FOK; self-trade prevention;
  reduce-only; minimum notional and lot rounding at the boundary. An order
  type the simulator does not implement is refused at submission, never
  degraded to a limit order.
- Partial fills by the remaining trade quantity when at the head. A
  no-partial model fills whole or not at all; both errors have a sign, and
  the bracket must include both.
- Funding is charged on the position held at the settlement timestamp from
  the recorded rate, not averaged across the interval.
- Fees by maker and taker tier, rebates as negative fees, the tier the live
  account would hold, and the tier change mid-run if the run crosses one.

## Latency and jitter

- Three latencies: feed (exchange timestamp to local receipt), order entry
  (send to the matching engine) and order response (matching engine to
  local receipt; a fill notification rides this one too). Each is measured
  separately and declared with every result.
- Decision time: the strategy sees an event at local time t, computes for c,
  sends at t + c; the order reaches the book at t + c + entry and is matched
  against the book as of that exchange time, not against the book that
  triggered the decision. Measure c on the live system and replay it; a
  slow strategy acts on a stale book, and the simulator must let it.
- Replay distributions, not means: sample each order's latencies from the
  measured p50, p95 and p99 with a seeded draw, or interpolate a recorded
  latency series by time, which also carries intraday and load regimes.
  Jitter is the point: the tail is what fills against you. Latency rises
  under load, exactly when quotes are most stale, so a state-dependent model
  beats a stationary one.
- A cancel is an order. It pays its own entry latency, at least the
  submit's, and a fill can land between the cancel's send and its arrival.
  Model the cancel as a venue-delayed event, never as instant. A cancel sent
  while the order is in flight means the same thing in the simulator as live:
  it waits for the order, then acts.
- The order state machine is where toxic fills live: pending new, resting,
  pending amend, pending cancel, cancelled with a partial, filled, rejected.
  The simulator emits the same states, and the same ordering of fill against
  cancel acknowledgement, that the venue would.
- A latency offset corrects a feed recorded somewhere other than where the
  strategy runs.
- Accelerated or single-loop modes that skip response latency and queue
  fills are for screening. No number from one reaches a verdict.

## The closed loop

Calibrating the simulator against the live system, and keeping it there.

1. Measure. Feed latency from your own recording, never a vendor's clock.
   Order latency by logging live order actions, or by submitting
   unexecutable orders away from the mid and cancelling them on a schedule,
   recording request, exchange and response timestamps per order.
2. Feed the measured distributions and the strategy's compute time back into
   the simulator, seeded.
3. Compare live against simulated in this order: fill rate by distance from
   the touch and by side, time to fill, then the markout curve of fills, then
   reject and cancel-fail rates, then fees and funding paid, then PnL. PnL
   agreement with fill-rate disagreement is coincidence.
4. Tune the queue parameter on the fill-rate gap by depth bucket. A gap that
   persists in fast regimes is cancel latency or level refill, not the queue
   parameter.
5. Align at small size first, then grow while watching the gap; impact
   appears as size grows and the replay cannot show it.
6. Plot live and simulated equity, position, quotes and signal on one chart
   before any of the above; most discrepancies are visible there.

The same loop prices infrastructure: lower the latency inputs artificially
and the simulator says what a colocation, tier or code upgrade buys.

## Fill and cost models

- The ladder, optimistic to pessimistic: fill on touch at the limit price;
  fill on touch with a probability; trade-through (fill only when a print
  goes through your price); trade-driven at the head; an L2 queue model; L3
  FIFO. Say which rung produced every number.
- Every number travels with its fill rule, queue model, latency profile, fee
  tier and funding treatment. Run the optimistic and the pessimistic variant
  and report the bracket, not the point.
- Silent fallbacks are poison: a maker order that becomes a taker after a
  timeout must be off, or the timeout matched to the quote lifetime, or the
  maker PnL contains taker fills nobody asked for.
- Partial fills on. Slippage in basis points is a taker concept; for a maker,
  slippage is the queue.
- Mid-price fills are never acceptable when the edge is under twice the
  spread.

## Benchmarking and reading a backtest

Market-making diagnostics first, portfolio statistics second. Every figure
is sliced by symbol, venue, session, volatility and spread regime, and
reported over rolling windows, never one pooled number.

- **Markout curve** per fill at about 100 ms, 1 s, 5 s, 30 s and 5 min, by
  side and size bucket. Sub-second markouts read latency and quote response;
  1 to 10 s read information. A stable negative pattern by venue, symbol or
  counterparty is informed flow; a single point is noise. Realised spread is
  the effective spread less the markout.
- **Fill ratio against markout** is a tradeoff, not two metrics: tightening
  buys fills from the most informed flow. Profit per fill is half-spread less
  expected adverse selection less fee; a rising fill ratio with worsening
  markouts means the quotes are too tight.
- **PnL decomposition**: spread capture, rebate, funding, adverse selection
  (markout), inventory mark-to-market, hedging friction, fees. A fat residual
  is broken attribution, not hidden alpha. "The profit is the rebate" is a
  finding to state.
- **Quote quality**: uptime, time at the touch, share of two-sided time,
  requote rate, orders to fills, cancels to fills, rejects and post-only
  mismatches, rate-limit load.
- **Inventory**: distribution, maximum, time at the limit, half-life, and
  inventory PnL against spread PnL.
- **Portfolio**: Sharpe, Sortino and Calmar on per-period returns with the
  effective N and a block-bootstrap CI, maximum drawdown and its duration,
  profit factor and win rate by round trip, turnover, tail ratio, and the
  capacity curve (edge against size).
- **Baselines and ablations**: a symmetric quoter at a fixed spread, a
  zero-signal quoter with the same inventory control, a random signal with
  the same execution. The strategy must beat them after costs; ablate each
  component to attribute the edge to it.
- **Comparing runs**: same data snapshot, seed, window and fee tier, or the
  comparison is of the inputs. A sweep reports the metric surface around the
  chosen point, never the argmax, and its size counts toward the trials the
  research skill deflates by.
- **Red flags**: an edge that survives only under fill on touch; PnL
  concentrated in a few prints; a markout still improving past 5 min
  (drift, not edge); fills at prices never traded through; a simulated fill
  rate above the live venue's at the same depth; a Sharpe quoted without
  its fill rule.

Verdicts, promotion rungs and kill criteria are `quant-trading-validation`'s.

## What a framework must expose

- A latency model answering order entry and order response per order at a
  timestamp, and feed latency through the two timestamps on the data.
- A pluggable queue model with per-order hooks (new order, trade at the
  level, depth change, fill, cancel) and an L3 path by order id.
- A fill model whose assumptions are explicit in its config and named in the
  artifact, with partial fills and liquidity consumption.
- Order lifecycle events with the venue's semantics, including a cancel that
  can lose the race to a fill.
- Fee, funding and slippage models by tier and settlement schedule.
- A deterministic timeline with a stated tie-break, seeded substreams,
  pinned inputs, and a test that reruns to byte-identical artifacts.
- A decision log (inputs to decision) so a live fill can be replayed offline.
- Data-quality validators (gaps, crossed books, out-of-order and duplicate
  events) that write a report and refuse a corrupt window unless told.
- A parameter sweep that derives per-cell seeds and writes one metrics file.
- An accelerated mode labelled as screening, if one exists at all.

## References

| File | Read it when |
| --- | --- |
| [references/platform-backtester.md](references/platform-backtester.md) | Wiring a backtest on `engine-backtesting`; choosing its fill model or reading its metrics; locating Tardis feeds, the gate precedent, or a repo-local research agent |
| [references/oss-backtesters.md](references/oss-backtesters.md) | Implementing or calibrating a latency or queue model; choosing L2 against L3; comparing the platform with hftbacktest or NautilusTrader |
