---
name: trading
description: Quant trading domain expertise — market-making and quoting discipline, low-latency engine design, hot-path and backpressure rules, money arithmetic, exchange boundary handling, determinism and backtest parity, pre-trade risk. Use for market making, trading engine, execution, market data, or quant strategy work.
---

# Quant trading domain practice

Domain expertise that holds regardless of stack. Language conventions live in
the `rust` skill; the current CryptoStruct-based platform's specifics live in
the `crypto-struct` skill.

## Market making

- The quote lifecycle is the product: place → monitor → cancel/replace. The
  **cancel path deserves the same care as the place path** — a stale quote is
  the main way a market maker loses money. Pulling quotes fast matters more
  than placing them fast.
- Market making is cancel-heavy: expect orders-to-fills ratios far above 1 and
  design order handling, rate budgets, and monitoring around that.
- Inventory is risk. Skew quotes against position (Avellaneda-Stoikov style),
  and treat inventory limits as first-class strategy inputs, not afterthoughts.
- Requoting needs a threshold or budget — quoting on every tick burns rate
  limits and exchange goodwill for no edge.

## Low-latency engine design

- Identify the hot path first: market data ingest → signal → order
  place/cancel. Everything else — config, reporting, reconciliation, admin —
  is cold and should stay simple.
- On the hot path: no heap allocation, no locks held across work, no syscalls.
  Preallocate, reuse buffers, pass by reference. Logging on the hot path must
  be deferred (ring buffer / async writer), never a blocking write.
- Budget in explicit terms — memory, CPU cycles, syscalls, network round
  trips — and say which one a change spends.
- Latency claims require measurement at percentiles (p50/p99/p999), never
  means. Tail latency is what fills against you.
- Design for determinism from day one: same input stream → same decisions.
  Determinism buys replay debugging, backtest parity, and regression tests
  that actually bind. No unseeded randomness, wall-clock reads, or
  iteration-order dependence in decision logic.

## Backpressure and load

- Choose a policy per stream and state which one:
  - **Market data** — shed load and coalesce. A stale tick is worse than a
    dropped one; the latest book is what matters.
  - **Orders and fills** — never drop. Block or fail loudly; a lost fill is a
    position error.
- A slow consumer must never stall the ingest path.

## Money and arithmetic

- No floating point for prices, sizes, or balances in decision or accounting
  logic. Integer ticks/lots or fixed-point/decimal types; floats only at wire
  boundaries, converted at ingress.
- Audit every arithmetic op on price, size, quantity, and notional for
  overflow. Checked or saturating ops wherever the input came from outside.
- Rounding is a decision, not a default. State the direction and who it
  favors; round at the venue boundary, not mid-calculation.

## Exchange boundary

- Treat everything from a venue as untrusted: missing fields, out-of-order
  sequence numbers, duplicate messages, reconnect gaps, absurd prices.
  Sanity-clamp market data before it reaches pricing.
- Reconnect and resubscribe paths need the same care as the happy path — they
  run precisely when things are already going wrong. On reconnect, reconcile
  order and position state from the venue; never trust local state alone.
- Respect venue rate limits as a budgeted resource shared between quoting and
  cancels — reserve headroom for pulling quotes in a storm.

## Risk

- Pre-trade risk checks are mandatory and structural: a chained gate model
  (allow / reject / reduce) that cannot be bypassed by any strategy, with a
  kill switch that flattens or freezes. Latency is not a reason to skip them —
  make them cheap, not absent.
- Anything that changes order state, position, or risk limits is a decision to
  flag to the user, not an implementation detail to bury.

## Engines are a platform

- The strategy API serves the quant research team: it is a stable contract.
  Any breaking change to callbacks, data shapes, or lifecycle is a breaking
  change for researchers — flag it and version it.
- Strategies must be runnable against recorded data (backtest/sim) without
  code changes. Keep engine-only dependencies out of strategy logic.
- Where multiple approaches exist, name the latency/throughput/complexity
  tradeoff rather than picking silently.
