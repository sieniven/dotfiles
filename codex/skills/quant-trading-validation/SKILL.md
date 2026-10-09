---
name: quant-trading-validation
description: "Quant developer (QD) practice for taking a strategy from research to production on an HFT / market-making / crypto-perp desk \u2014 the fidelity ladder that ranks backtest evidence, the mandatory optimism audit, backtest-to-live parity, purged walk-forward and parameter-plateau robustness, transaction cost analysis and markout reconciliation, shadow/paper/canary promotion gates and pre-registered kill criteria. Use when implementing or backtesting a strategy or signal, judging whether a backtest is believable, reviewing a parameter sweep or optimizer output, or deciding whether a strategy is ready for paper or live \u2014 even when the user only asks \"does this backtest look right\". Building or calibrating the simulator itself lives in quant-trading-backtesting."
---

# Strategy validation practice

The quant developer's job is the gap between "the backtest says" and "this
makes money live": build on the engine, prove the backtest is believable,
gate promotion. Research statistics live in `quant-trading-research`;
engine and execution conventions in `quant-trading`; how the simulator
works, its fill, queue and latency models, the platform's backtester facts
and how to read a backtest in `quant-trading-backtesting`.

## Fidelity ladder

- Rank evidence: (1) live fills or shadow trading on the real feed; (2)
  replay with a queue and latency model calibrated against live fill rates;
  (3) replay with default models; (4) signal-only IC and markouts. Say which
  rung every number came from. Never claim maker profitability from (3) or
  (4) alone.
- A maker backtest states its assumption for each of: fill rule, queue
  position, feed and order latency (submit, amend and cancel separately),
  partial fills, the cancel-fill race, venue matching semantics, fee and
  rebate tier, funding, own impact. What each assumption means, which
  choices are the optimistic and pessimistic bounds, and how to calibrate
  the models against live are `quant-trading-backtesting`'s; the verdict
  needs them stated.
- Latency percentiles for the verdict: promotion uses p95, stress uses p99;
  engine hot-path budgets still use p999 per `quant-trading`. An alpha whose
  half-life is shorter than the order round trip is optimistic until
  shadow-validated.

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

## Parity

- Same code path: the strategy class that runs live is the one that runs in
  the backtest. A research-only reimplementation is a parity gap by
  construction. Keep the decision core pure — `(market snapshot, risk
  snapshot, params) → decision` — callable from both, with a golden-fixture
  parity test that fails on drift.
- Deterministic replay is the simulator's job (`quant-trading-backtesting`);
  the verdict requires the rerun to be byte-identical and the data, code and
  config pinned. A run that cannot be reproduced is not evidence.
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
  table (optimistic vs pessimistic); parity status;
  walk-forward table; parameter surface; PnL decomposition; residual risks;
  the live evidence that would change the verdict.
