# Placing a trading node's threads on cores

Companion to `SKILL.md`. Which thread earns a core of its own, which may
share one, and what evidence moves a thread from one to the other.

## The path and its hops

A market-making node's hot path crosses threads at fixed points:

```
wire -> NIC queue -> socket -> feed thread -> ring -> engine -> ring -> order thread -> socket -> wire
```

Each arrow that crosses a thread is a hop with a cost that depends on what
the receiving thread was doing:

| Receiver's state | A record waits |
| --- | --- |
| spinning on its own core | the ring hop: tens of nanoseconds plus one cache-line transfer |
| parked on a shared core | the rest of its park plus timer slack: tens of microseconds |
| runnable behind a busy thread | that thread's scheduler slice: milliseconds |
| on a core that was idle in a deep state | the idle state's exit latency on top |

Tick-to-trade is the sum over the path, so one parked hop outweighs every
nanosecond saved in the code around it.

## Who earns a core

Rank the threads by what a microsecond of their wait costs the strategy,
then hand out isolated cores from the top:

1. **The engine**: every decision passes through it. Alone, spinning,
   never shared.
2. **The feed that drives pricing** (the fair price, the maker venue's own
   book): alone, spinning, when its socket wait and the strategy's results
   show it pays.
3. **Order entry**: the cancel path. A parked order thread delays every
   cancel by the park. It shares a core only where orders go out in bursts
   the strategy already spaces wider than the park, and that trade is
   written down next to the configuration.
4. **Secondary feeds, drop copies, a stock reference feed**: share one core
   on a backoff.
5. **Everything else** (control server, exporter, dialers, HTTP polls,
   logging): unpinned, on housekeeping cores.

A thread moves up only on evidence: its socket-wait histogram, a quiet-hop
measurement of its park, and the strategy's fill and markout numbers before
and after. A thread moves down when the core is needed more elsewhere and
the same evidence says the wait is tolerable.

## Counting cores

- Isolated cores needed = threads that spin + cores that are time-shared.
- With SMT, each isolated core takes its sibling with it; the sibling is
  isolated and left idle, or SMT is off. A sibling that runs anything
  shares the pinned thread's execution units and its L1 and L2.
- Housekeeping keeps core 0, at least one core for the kernel and the rest
  of the host, and room for this process's unpinned threads. A node whose
  named cores plus the isolated ones cover every permitted core has nowhere
  to run them and is refused.
- Threads that hand records to each other belong on cores that share a
  last-level cache and a NUMA node (`cpu-cache-and-memory-layout`). The NIC
  queue's node counts too.
- Two processes never share a pinned core: each build decides which of its
  own threads spin.

## Vendor and library threads

A library started from a pinned thread puts its threads on that core. Decide
it on purpose:

- A callback thread that must wake fast can live beside a spinning duty on
  the duty's own core: the spin keeps the core hot, at the price of a
  context switch per callback and the tick while both are runnable.
- A pool that does background work (a resolver, a TLS session cache, an
  allocator's purge thread) is started before the pin or given the unpinned
  mask.
- A core that carries such threads is named by no other thread.

## Adding a thread: the checklist

1. What does a message wait for it in each state: spinning, parked, behind
   a neighbour? Which of those can the path tolerate?
2. Which core, and who else names it? Does that turn a spinning neighbour
   into a time-sharing one?
3. Does it start helpers? Where do they run?
4. What does it publish, to whom, on which cache line?
5. How is it stopped, in what order relative to the threads it feeds?
6. Which measurement proves the placement, on which host?
7. Does the host isolate the core, and does the launcher's preflight see
   it? A document that names a core is a host change request.
