---
name: strategy-validation
description: Quant developer (QD) practice for taking a strategy from research to production on an HFT / market-making / crypto-perp desk — backtest fidelity (fill rule, queue position, feed and order latency, cancel-fill races, venue matching semantics, fee and rebate tiers, funding), the mandatory optimism audit, backtest-to-live parity and determinism, purged walk-forward and parameter-plateau robustness, transaction cost analysis and markout reconciliation, shadow/paper/canary promotion gates and pre-registered kill criteria. Use when implementing or backtesting a strategy or signal, judging whether a backtest is believable, reviewing a parameter sweep or optimizer output, or deciding whether a strategy is ready for paper or live — even when the user only asks "does this backtest look right".
---

# Strategy validation practice

The quant developer's job is the gap between "the backtest says" and "this
makes money live": build on the engine, prove the backtest is believable,
gate promotion. Research statistics live in `quant-research`; engine and
execution conventions in `trading`; the platform's backtester facts in
`crypto-struct`.

## Fidelity ladder

- Rank evidence: (1) live fills or shadow trading on the real feed; (2)
  replay with a queue and latency model calibrated against live fill rates;
  (3) replay with default models; (4) signal-only IC and markouts. Say which
  rung every number came from. Never claim maker profitability from (3) or
  (4) alone.
- A maker backtest must state its assumption for each of: fill rule (touch /
  trade-through / queue position); queue position and cancels ahead of you;
  feed latency; order-entry and response latency for submit, amend and cancel
  separately; partial fills; cancel-fill races; venue matching semantics
  (post-only reject, IOC/FOK, amend loses priority, self-trade prevention);
  fee and rebate tier; funding on the quantity held at settlement; own market
  impact (usually unmodelled — hence start small live).
- Fill rules: fill-on-touch (resting order fills when the opposite best
  reaches it) is the optimistic bound; trade-through (fill only when a trade
  prints through the price) is the pessimistic bound; truth is queue
  position. Volume-only queue rules ignore cancels and are far too
  pessimistic deep in the queue; probabilistic queue models (the hftbacktest
  ProbQueueModel family) need calibration against live fill rates before they
  mean anything. Mid-price execution is never acceptable when edge < 2× spread.
- Latency: keep exchange and local timestamps on every event; declare a
  latency profile (p50/p95/p99 for feed, submit, amend, cancel). Promotion
  uses p95, stress uses p99; engine hot-path budgets still use p999 per
  `trading`. An alpha whose half-life is shorter than the
  order round trip is optimistic until shadow-validated.
- Cancel-fill race: live, the fill can arrive after the cancel was sent; a
  backtest that cancels instantly hides adverse fills on stale quotes. Model
  cancel latency at least equal to submit latency.

## Optimism audit (before any verdict)

- List every optimistic default in the run — fill-on-touch, 100% maker fill,
  zero latency, no partials, no impact, flat fee, no funding — and re-run the
  pessimistic variant of each. If the edge vanishes under trade-through fills
  or realistic latency it is a fill-model artifact, not alpha. Report both.
- Sensitivity table: edge vs fill probability, vs latency, vs fee tier
  including loss of the rebate. "Profit is the rebate" is a finding to state,
  not to bury.
- Decompose PnL: spread capture, rebate, funding, adverse selection
  (markout), inventory mark-to-market, fees. A fat residual is broken
  attribution, not hidden alpha.

## Parity and determinism

- Same code path: the strategy class that runs live is the one that runs in
  the backtest. A research-only reimplementation is a parity gap by
  construction. Keep the decision core pure — `(market snapshot, risk
  snapshot, params) → decision` — callable from both, with a golden-fixture
  parity test that fails on drift.
- Deterministic replay: seeded RNG with named substreams; deterministic
  event ordering (tie-break on timestamp, event-type priority, sequence);
  pinned data snapshot (path and hash), code (commit) and config. Same inputs
  → byte-identical artifacts; any diff is a bug.
- First parity check live vs backtest is the fill rate by distance from the
  touch and by side, then the markout curve of fills, then the fee tier and
  funding actually paid — before PnL. PnL agreement with fill-rate
  disagreement is coincidence.
- Log each decision with the inputs that produced it, so a live fill can be
  replayed offline.

## Robustness

- Walk-forward: forward-only folds with purge ≥ label or settlement horizon
  and an embargo. Accept only if the out-of-sample edge is sign-consistent
  across folds and the fold IR (mean/std) clears the bar; one sign-flipped
  fold fails. Report in-sample vs out-of-sample; out-of-sample below half of
  in-sample is overfit.
- Plateau, not argmax: report the metric surface around the chosen point;
  ±20% on any parameter must not flip the sign. The sweep size feeds the
  deflated Sharpe.
- Never sweep or optimise risk parameters (position and notional caps, loss
  limits, kill thresholds). Risk policy sets them.
- Breadth: other symbols, venues and windows, including a stress window (vol
  spike, outage, listing or delisting, funding extreme). Folds must not
  straddle listing or liquidity-regime events.
- Regime slices by vol, spread, session and funding sign. A strategy that
  works in one regime needs a regime gate written as a rule, not a hope.

## TCA and markouts

- A backtest assumes a cost; TCA measures one. Implementation shortfall =
  paper − realised, decomposed into delay, spread and impact, fees, and
  opportunity cost of the unfilled quantity.
- Markout curve per fill at roughly 100 ms, 1 s, 5 s, 30 s, 5 min, by side,
  size bucket, session and regime. Realised spread = effective spread − price
  impact. Live markout worse than backtest means the queue or latency model
  is too optimistic, or the flow is toxic.
- Reconcile live vs sim per fill: fill-rate ratio by depth, latency
  distribution, reject and cancel-fail rates, fee tier, funding. Attribute
  the discrepancy before touching a parameter.

## Promotion gates and kill criteria

- Ladder: backtest → shadow (live data, orders suppressed, decisions diffed
  against replay of the same tape) → paper or canary (small size or one
  symbol, pre-registered success metric and duration) → scale. Align fill
  rate and markout at small size before scaling; impact grows with size.
- Pre-register before deployment: acceptance ranges (live metrics inside the
  backtest CI), duration, and kill criteria — drawdown beyond k × backtest
  max drawdown, markout or hit rate worse than the trailing baseline by a set
  margin, fill-rate drift, inventory-limit breaches, latency p99 regression.
- Governance: new behaviour ships disabled by default; config changes in
  their own PR; every parameter change carries its evidence; anything that
  changes order state, position or risk limits is flagged to the user.
- A failed or demoted strategy goes into the trial log with the reason.

## Report standard

- Verdict first (READY-FOR-PAPER / NEEDS-WORK / REJECT) with the fidelity
  rung; fill, queue, latency, fee and funding assumptions; optimism-audit
  table (optimistic vs pessimistic); parity and determinism status;
  walk-forward table; parameter surface; PnL decomposition; residual risks;
  the live evidence that would change the verdict.
