---
name: deterministic-simulation-testing
description: Deterministic simulation testing for stateful, concurrent and distributed code, after Unmesh Joshi's article. The gap it fills beside unit and integration tests, when a system can take it, the sources of nondeterminism, a single-threaded tick loop with tick-counted timeouts and run-to-completion handlers, the seam with simulated and production clock, network and storage, message versus byte boundaries, the six coding rules and their automated check, scripted fault scenarios versus seeded fault injection with a logged fault schedule, fast-forward, a client-visible history with safety and liveness checks, and simulated storage that drops unsynced writes on a crash. References translate it to Rust (traits, a non-Send core, clippy disallowed lists, turmoil, madsim, shuttle, loom, proptest), to a market maker or hedger against a simulated venue, and differential testing against a reference. Use when building or extending a simulator, or testing stateful, concurrent or venue-facing logic under faults.
---

# Deterministic simulation testing

Follows one source, Unmesh Joshi's "Deterministic Simulation Testing"
(martinfowler.com, 17 November 2026; link under Sources). Points marked as the
article's are its; the Rust, trading and differential material in
`references/` is ours. Injected traits are required by `rules/rust.md`,
backtest seeding is in `quant-trading-backtesting`, and the pure decision core
is in `quant-trading-validation`.

## The gap it fills

- The article's framing: unit tests validate local logic and integration
  tests validate interactions between components, but neither shows "what
  clients observe when part of the system fails while requests are in
  flight". The hard bugs live where partial failures overlap live traffic.
- Gray failures are the target: a one-way partition, a small drop rate, a
  message delayed just past one node's timeout, a process pause, a slow
  fsync. Ordinary tests cannot produce these on demand.
- Available is not correct. Chaos engineering asks whether the system stays
  up under faults; the article asks whether what clients saw is consistent
  with the semantics the system claims, as Jepsen does by recording a
  client-visible history and checking it.
- Live fault injection does not reproduce: the fault schedule is unseeded,
  and even the same faults land on different in-flight messages each run.
- It is an addition to unit and integration tests, never a replacement. They
  pin a function or a contract and name the line that broke; simulation
  finds the interleaving that no one thought to write down.

## When it fits

- The article is plain that it "cannot be added as an afterthought": a
  single-threaded core, asynchronous I/O interfaces and no thread-heavy
  libraries have to be designed in from the start.
- Fits: a new core (an engine, a session layer, a replicator, a node
  component), or an existing pure decision core that can be put behind clock,
  network and storage interfaces.
- Does not fit: a system that cannot be restructured. The article's
  alternative is hypervisor-level simulation, which runs unmodified code under
  a deterministic hypervisor that virtualizes time and schedules threads.
  Name it and stop; do not half-simulate a core that still reads the OS.
- Cost, per the article: handlers never block or run long CPU work, and
  scaling means more independent processes, not a shared thread pool.

## Sources of nondeterminism

Four outside the program, each changing when an event becomes visible:
the **clock** (timeouts and retries against a reading that varies and jumps),
**thread scheduling** (which handler runs first), **network timing** (send
order is not arrival order) and **disk timing** (when a write becomes
durable). Two inside it, **random choices** and the **iteration order of
unordered collections**, are handled by coding rules, not by simulation.

## The model

- Nothing progresses on its own. One loop on one thread calls `tick()` on
  each component (clocks, network, clients, servers) in a fixed order; a
  component's state changes only inside its tick. The clock reads what the
  loop advanced it to; the network delivers only when ticked; a write
  becomes durable only when the disk is ticked.
- Timeouts are counted in ticks: a timeout of 10 expires after exactly ten
  ticks, whatever the wall clock did (etcd-raft's election and heartbeat
  timeouts work the same way). In production a tick is a fixed interval.
- Handlers run to completion and never block. Talking to another process
  means sending a message; the reply arrives as another message some ticks
  later. In-flight requests sit in a waiting list, each with its own tick
  timeout. A slowdown is a delay of a few ticks, so gray failures become
  ordinary test inputs.

## The seam

- Clock, network and storage (and the ID or random source) are interfaces
  the core receives at construction and never creates. Each has a simulated
  implementation for tests and a production one.
- The constraints bind only on the deterministic side. Production adapters
  may use background threads, executors, non-blocking sockets and the system
  clock, as long as their results come back onto the loop as events handled
  during a tick.
- Choose the boundary. A message-level simulator (the article's,
  TigerBeetle's) covers loss, delay, partitions, timeouts and retries but
  never runs the code that turns bytes into messages, so a frame split across
  two reads or a connection dying mid-frame cannot appear; a byte-level one
  (FoundationDB's) runs the real framing. With messages, cover framing with
  the fuzz and capture tests in `venue-protocols`.

## The six coding rules

The article's rules for the deterministic side:

1. No system clock calls: time comes from the simulated clock or the tick.
2. No unseeded randomness: random choices and IDs come from the injected
   seeded generator.
3. No threads, executors or standard futures in the core.
4. No direct network or disk I/O: everything goes through the interfaces.
5. No iteration over unordered collections; lookups are fine.
6. No cross-thread callbacks across the seam: an adapter's thread never
   completes a future or calls into the core; it queues the completion for
   the loop to drain on its next tick.

One clock read or hash-map walk in a handler silently breaks replay the day a
rare fault sequence reaches it, so the article enforces the rules with an
automated check on every build, not by review: a static architecture test for
rules 1 to 5, a runtime owner-thread check for rule 6, and the seeded
simulation itself as the system-wide check. The Rust equivalents are in
`references/rust.md`.

## Scripted scenarios and seeded faults

- **Scripted**, for known fault interactions: choose timeouts and delays,
  inject the exact fault, and advance with a "tick until condition, with a
  tick cap" helper that fails at the cap. Never sleep. The outcome depends
  only on numbers the test chose, so every run takes the same path.
- **Seeded**: one seeded generator, reached through one decisions object,
  decides whether to issue a request, whether to inject a fault, which kind,
  which target, how long, and when to heal. The same seed gives the same
  faults and the same client-visible results.
- Log the fault schedule (`tick=12 isolate athens`) and the process and
  network events of every tick. The article finds this often enough to see
  the interleaving without a debugger; tick-stamped logs also suit an LLM.
- Assert that the run injected at least one fault, as the article's test
  does, so a misconfigured run cannot pass on a quiet network.

## Fast-forward

A tick is one loop iteration, not real time: a 100-tick wait is 100
iterations at CPU speed, so a run that takes hours live takes seconds. Replay
fixes a found bug; fast-forward finds it, by trying thousands of seeds.

## Correctness checking

- Record a client-visible history: an invoke event per operation, then ok,
  fail or timeout (Jepsen's shape).
- Safety: check the history against the claimed semantics while faults are
  active (the article checks linearizability of a register).
- Liveness: after the fault phase, stop injecting, heal everything, tick a
  bounded number of times, and assert that replicas converge and new
  operations succeed. A deadlock or livelock fails here.
- A violation comes with its seed, which replays the exact tick sequence.

## Simulated storage

- Storage sits behind an asynchronous interface (read, write, sync, size,
  truncate) whose operations complete during a tick.
- The simulated file keeps two images: what is written, including unsynced
  writes, and what is durable. Reads and writes use the first; sync copies it
  to the second; a crash throws the unsynced part away. A completed write
  means visible to later reads; only a completed sync means durable.
- This tests a write-ahead log and recovery across crashes; the real
  engine's sync modes stay with the crash tests in `embedded-storage`.

## House practice (not from the article)

A seed that found a bug is kept in the repo as a regression test, with the
invariant it broke. TigerBeetle reproduces a run from the seed and the commit
together, so once the code moves a stored seed may stop reaching the bug;
when the cause is understood, pin the interleaving as a scripted scenario
too.

## References

| File | Read when |
|---|---|
| [references/rust.md](references/rust.md) | Writing the core, the seam traits, the tick loop or the build-time check in Rust; choosing turmoil, madsim, shuttle, loom or proptest |
| [references/trading.md](references/trading.md) | Simulating a venue for a market maker or hedger: faults, history, invariants, liveness |
| [references/differential.md](references/differential.md) | Comparing an implementation with a reference or recorded truth |

## Sources

- Unmesh Joshi, "Deterministic Simulation Testing", 17 November 2026:
  https://martinfowler.com/articles/deterministic-simulation-testing.html
- TigerBeetle, VOPR simulator notes:
  https://github.com/tigerbeetle/tigerbeetle/blob/0aeb306561365e21b97775c729bfc439f6c16d72/docs/internals/vopr.md
