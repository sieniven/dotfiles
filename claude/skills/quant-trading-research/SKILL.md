---
name: quant-trading-research
description: Quant researcher (QR) practice for an HFT / market-making / crypto-perp desk — hypothesis-first research loop, tick and L2 data hygiene, microstructure signal construction (book imbalance, microprice, order-flow imbalance, cross-venue lead-lag, funding and basis), evaluation by markout curves and IC under autocorrelation-aware statistics, multiple-testing discipline (trial log, deflated Sharpe, PBO, purged walk-forward), cost-first reporting. Use for alpha or signal research, "is this edge real", feature studies on order-book or trade data, funding or basis studies, and any analysis notebook or script under a research repo — even when the user only says "look into" or "check whether" some market effect.
---

# Quant research practice

How to find and validate short-horizon edges. Engine and execution mechanics
live in `quant-trading`; the simulator, its fill, queue and latency models,
backtest benchmarking and the platform's data and backtester facts live in
`quant-trading-backtesting`; promotion gates in `quant-trading-validation`.

## Research loop

- Hypothesis before data. Write down the phenomenon, **who is on the other
  side and why they pay** (inventory constraint, latency disadvantage, forced
  flow such as liquidations or funding arbitrage, a lagging venue), the inputs,
  the horizon, the expected sign and size, and the kill criterion. If it
  cannot be falsified it is not a hypothesis.
- Pre-register the primary metric, horizon and pass threshold before looking
  at out-of-sample data. Changing the horizon after seeing the result is a
  new trial, not a refinement.
- Keep a trial log: every variant, parameter set, universe and window tried,
  abandoned ones included. The count feeds the deflated Sharpe and PBO;
  without it no significance claim is valid.
- Feature analysis first (markouts, IC, conditional returns); a full backtest
  is the last step, not a research tool — every backtest run is one more
  trial. Kill weak ideas early and record why, so the dead end is not
  re-tried.

## Data hygiene (tick / L2)

- Two clocks: exchange `timestamp` vs local receive `local_timestamp`. A
  decision may use only what had arrived locally; a feature computed on
  exchange time is look-ahead. Align venues on local time.
- A datum is usable at max(event time, publication time, processing
  completion). Funding, mark/index, settlement and OI publish with lag.
- Point-in-time everything: symbol universe (delisted perps are survivorship
  bias), tick and lot size, fee tier, funding interval, contract multiplier.
  A universe ranked on today's liquidity leaks.
- Validate before modelling: monotonic timestamps, sequence gaps, duplicates,
  crossed or empty books, snapshot-vs-delta consistency, outages. Report the
  missing-data share and drop gap windows from evaluation; never interpolate
  through them.
- Bars: stamp at bar end; set volume or dollar-bar thresholds from trailing
  history, not the full sample. Do not evaluate on bars what will trade on
  ticks — bar IC overstates tick IC.
- Label after latency and cost: forward return from the price obtainable at
  decision time plus latency, not the mid at decision time.

## Signal construction

- Catalogue: book imbalance `I = Qb/(Qb+Qa)` at the touch and depth-weighted;
  microprice (Stoikov 2018 — the martingale fair value conditional on
  imbalance and spread, estimated from the empirical mid-transition table;
  the size-weighted mid is not it); order-flow imbalance (Cont-Kukanov-
  Stoikov 2014 — signed best-quote changes; `ΔP ≈ β·OFI` with β inversely
  proportional to depth); signed trade flow and runs; queue depletion and
  replenishment; cross-venue lead-lag (lagged cross-correlation on local time,
  per pair and regime); basis and funding (premium index, predicted funding
  into settlement, mark-index gap); liquidation flow (one-sided OFI with
  depth pulled).
- Normalise by spread, depth or volatility so a feature compares across
  symbols and regimes; state its unit (ticks, bps).
- Every feature must be computable causally in the hot path from inputs the
  strategy actually receives (callbacks, book state). Something the engine
  cannot supply is an engine ticket before it is a signal.
- Plot the effect against horizon (100 ms to minutes). The peak sets holding
  period and quote lifetime. An effect that only grows with horizon is trend
  contamination, not microstructure alpha.

## Evaluation

- For maker-style edge the primary metric is the **markout curve**: signed
  mid move after the (hypothetical) fill at several horizons, sliced by side,
  size bucket, session and regime. Edge per fill = half-spread captured −
  adverse-selection markout − fee (a rebate is a negative fee). Sharpe comes
  after.
- For signals: IC and rank IC per horizon and their decay; IC_IR (mean/std
  across time slices); hit rate; conditional return by signal decile; PnL per
  unit turnover after cost. Compute over time slices, never one pooled number.
- Effective sample: ticks and overlapping labels are autocorrelated. With
  H-step overlap effective N ≈ N/H; use Newey-West/HAC errors with lag ≥ H−1,
  or non-overlapping windows. A t-stat from raw tick counts is wrong.
- Report with context: effect in bps, horizon, venue, symbol, window, N and
  effective N, block-bootstrap CI. Never a naked Sharpe or IC.
- Stability: same sign and similar size across time halves, symbols, venues
  and vol/spread regimes. One sign-flipped fold is the strongest overfit tell.
- Suspect first: an IC that looks too good → leakage; in-sample Sharpe more
  than 2–3× out-of-sample → overfit; IC rising monotonically with horizon →
  drift.

## Multiple testing and overfitting

- Hurdle: after hundreds of variants, t > 3 (Harvey-Liu-Zhu), not 2. Or the
  deflated Sharpe (Bailey-López de Prado) on the per-period, non-annualised
  SR with N trials, the variance of SR across trials, skew and kurtosis; DSR
  below 0.95 fails. Correlated trials count as fewer than M independent
  ones; a common approximation is `N_eff ≈ ρ̄ + (1−ρ̄)·M`.
- PBO by CSCV over the trial matrix: split time into S blocks, take every
  C(S, S/2) in/out-of-sample combination, PBO = share where the in-sample best
  configuration ranks below the out-of-sample median. Above 0.05 is a reject
  under the strict rule; above 0.4 is certainly overfit. Never optimise PBO.
- Cross-validation is purged, embargoed and forward-only (purge ≥ label
  horizon; embargo ≥ 2× horizon or one funding/settlement cycle), or CPCV for
  a distribution of out-of-sample paths. Never shuffle time; never fit a
  scaler or threshold on the full sample.
- Degrees of freedom include the implicit ones: universe, dates, bar size,
  horizon, cost assumption. Count them.
- Plateaus, not peaks: show the metric surface around the chosen parameters;
  ±20% on each must not kill the edge.
- Expect decay: assume at least half of an in-sample or published edge is
  gone live, and set the hurdle accordingly.

## Costs and capacity

- Cost first: state the edge after fee tier, expected adverse selection and
  maker fill probability at that depth. A rebate can be the whole edge —
  report PnL split into spread capture, rebate, funding, markout, inventory.
- A maker edge computed at fill-on-touch is an upper bound; the fill
  assumption must travel with the number (see
  `quant-trading-backtesting`).
- Capacity: the size at which own flow moves the microprice or exhausts the
  queue. Edges in illiquid perps often fail at the minimum lot.

## Crypto perp specifics

- Funding: interval is per instrument (8h / 4h / 1h; Hyperliquid pays
  hourly); payment = rate × size × mark price (Binance) or oracle price
  (Hyperliquid). The premium index is sampled every few seconds, so funding is
  largely predictable into settlement and settlement is a flow event.
- Mark vs index vs last: liquidations key off mark. Hyperliquid's mark is a
  median of oracle-adjusted mid, its own book and CEX prices (Binance
  heaviest), so DEX liquidations follow CEX prices with seconds of lag.
- 24/7 but seasonal: volume, spread and vol vary by UTC session, weekend and
  funding timestamp. Slice by session.
- Delistings, tick/lot changes and fee-tier changes are routine —
  point-in-time metadata is mandatory.

## Reporting standard

- Verdict; pre-registered hypothesis, metric and threshold; data (venue,
  symbol, window, N, effective N, gaps); results table with CI by horizon;
  trial count and hurdle applied; cost-adjusted edge in bps with the fill
  assumption; what would falsify it; hand-off spec (inputs, formula, horizon,
  parameters and their plateau) for implementation.
- Mark each number as measured here vs cited; simulated vs live;
  pre-registered vs post hoc. Every number traces to a script output.
