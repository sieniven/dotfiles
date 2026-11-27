---
name: low-latency-threading
description: Thread design for pinned, latency-critical loops on Linux, in Rust. The duty cycle (one bounded non-blocking do_work a turn, its work count fed to an idle strategy), what each idle rung costs (spin hint, sched_yield, timed park and timer slack), choosing busy-spin, backoff or a blocking wait per thread, running several tasks on one core (kernel time-sharing with parks versus one composite thread), pinning mechanics (sched_setaffinity, masks inherited by child threads and across exec, cpusets, the pin handshake), keeping helper and library threads off pinned cores, what a spinning loop must never do, real-time priority and why it is not the default, shutdown and signals, and how to prove a placement with a measurement. Also the desk's runtime as built (Agent, drive, IdleStrategy, spawn_pinned, the dedicated profile) and its recorded numbers. Use when writing or reviewing a thread, runner, idle or wait strategy, core placement or affinity code, or when a latency tail points at scheduling rather than code.
---

# Low-latency threading

How a thread that must answer in microseconds is built and placed. The host
side (which cores exist for it and what the kernel still runs there) is
`linux-cpu-isolation`; proving a core is quiet is `os-jitter-diagnosis`; how
the loop reads a socket is `low-latency-network-io`; what its data costs in
cache and TLB misses is `cpu-cache-and-memory-layout`; the measurement
contract is `systems-benchmarking`. Rust conventions are in
`~/.claude/rules/rust.md`.

Kernel statements here were read from the kernel tree at v6.8, v6.12, v6.18,
v7.0 and mainline in November 2026; the desk's runtime from
`engine-middleware` main at `b2bc835` (2026-11-27). Where a number is the
desk's own measurement it says so, with the host.

## The duty cycle

- A long-running job is an agent with one method: do the work that is ready,
  without blocking, and return how many items were done. A runner loops
  `do_work` then `idle(work)`. Zero work escalates the idle strategy; any
  work resets it. Topology then becomes configuration: the same agent runs
  alone on a core, beside others, or unpinned.
- `do_work` is bounded, and the bound is a number: at most N messages, one
  read, one write. The bound is what lets a stop flag be seen, lets other
  agents on the thread run, and makes the worst turn a budget that a bench
  can check.
- The stop flag is checked before each call, never inside a blocking wait:
  there is none. A turn that can take unbounded time is a bug even when it
  usually does not.
- One writer per piece of state; threads talk through bounded rings and
  published cells. The policy of a full ring is stated per stream, as
  `quant-trading` requires.

## What each idle rung costs

| Rung | What happens | Cost to the waiter | Cost to others |
| --- | --- | --- | --- |
| Spin hint (`std::hint::spin_loop`) | `PAUSE` on x86-64, `ISB` on aarch64; no kernel | none: the next poll is tens of nanoseconds away | holds the core and heats the SMT sibling |
| Yield (`thread::yield_now`) | `sched_yield`: alone on the runqueue it returns at once; with another runnable thread the caller's deadline moves one slice out | queued behind a busy neighbour for that neighbour's whole slice, milliseconds | none while the neighbour runs |
| Timed park (`thread::sleep`, `park_timeout`) | an hrtimer and two context switches; the wake preempts whoever runs | the park plus timer slack, 50 µs by default, on every message that lands mid-park | gives the core up |
| Blocking wait (futex, condvar, `epoll_wait`) | off the core until woken | a wake-up from another thread, a syscall the producer pays | none |

- Timer slack: a thread's timed waits may fire up to its slack late, never
  early. The default is 50 µs, inherited from the creating thread and across
  `exec`; it is not applied under a real-time policy. Set it with
  `prctl(PR_SET_TIMERSLACK)`, `/proc/PID/timerslack_ns`, or systemd's
  `TimerSlackNSec=` on the service. A 50 µs park with default slack is a
  100 µs worst case.
- A yield is not a hand-off. The kernel may pick the caller again, and a
  thread that yields stays runnable, so it never lets a core idle and never
  lets the tick stop. A ladder for a shared core goes from spinning straight
  to parking.
- A producer that wakes a blocked consumer pays the wake on its own hot path.
  Use a blocking wait only for cold threads; a hot consumer polls.
- A core that parks may drop into an idle state whose exit takes longer than
  the park. `linux-cpu-isolation` covers limiting idle states.

Ladder parameters, the kernel's yield code and prior art (Agrona, crossbeam)
are in `references/idle-strategies.md`.

## Choosing a strategy per thread

| Thread | Strategy |
| --- | --- |
| Alone on an isolated core, on the hot path | busy-spin, nothing else |
| Pinned to a core other pinned threads share | a few spins, then parks capped at what its slowest tolerable message may wait; no yield rung |
| Unpinned, on housekeeping cores | backoff with a larger cap; it shares with the whole host |
| Cold: control server, exporter, dialer, logger | block on its queue, socket or timer |

A thread that spins is pinned and alone. One spinner on a shared core costs
every other thread there a scheduler slice per message.

## Several tasks on one core

Three shapes, in order of latency:

1. **One composite thread.** One runner round-robins several agents and
   keeps spinning. No park, no context switch, one runnable task so the
   kernel can stop the tick; the price is that one slow `do_work` delays all
   of them, so each bound is a measured budget. Needs agents that can be
   driven by a shared loop.
2. **Kernel time-sharing.** Several threads pinned to one core, each backing
   off to a park. Each message that lands mid-park waits for the park and
   its slack; the tick stays on while more than one is runnable. Right when
   the tasks tolerate tens of microseconds and cannot share a loop.
3. **Never:** two spinners on one core, or spin-then-yield beside a busy
   thread.

Choose by the wait each task's messages tolerate and by whether the tasks
can be bounded. Which threads of a trading node deserve a core of their own
is in `references/placement.md`.

## Pinning

- Pin from inside the new thread, before its work starts, and have the
  spawner wait for the result: the closure never runs unpinned. A refused
  pin is an error that stops the launch; pinned never degrades to unpinned
  quietly.
- A thread created by a pinned thread inherits its one-core mask, and a mask
  survives `exec`. Every helper a pinned thread starts (a resolver, a
  runtime's blocking pool, a vendor library's callbacks, an allocator's
  background thread) lands on its core unless given a mask of its own. Start
  helpers before pinning, or set their mask as their first act and read it
  back.
- An unpinned thread takes the process's cores less the reserved and less
  the isolated ones. The kernel never balances a thread off an isolated
  core, so one that lands on a spare isolated core stays there, often beside
  a pinned thread's SMT sibling.
- Read the process's permitted set from the process, not from the calling
  thread: a pinned parent sees one core. Validate configured core ids
  against that set before spawning anything.
- A cpuset narrows what `sched_setaffinity` grants, and the kernel refuses a
  mask with no permitted core. Set, then read back, then compare.
- The launcher sets the process mask before `exec` and nothing moves a
  running thread afterwards.

The calls, their error cases and the unsafe rules for them are in
`references/linux-syscalls.md`.

## Inside a spinning loop

- No blocking call, lock wait, allocation or formatted log. Logging is
  deferred to a ring and written by a cold thread.
- No page fault: memory is locked and touched before the loop starts
  (`cpu-cache-and-memory-layout`, the pages reference).
- As few kernel entries as the job allows. On a tickless core each entry
  costs more than elsewhere and invites deferred kernel work onto the core.
  A loop that owns a socket makes its one read a turn by design; anything
  else that enters the kernel there is a finding. Time comes from the TSC
  or the vDSO, never a real syscall.
- State another thread reads is published with one store to a cell on its
  own cache line.

## Real-time priority

`SCHED_OTHER` on an isolated core with nothing else runnable is the default,
and it is enough when isolation holds. `SCHED_FIFO` on a spinner starves the
per-CPU kernel threads of that core, runs into real-time throttling (950 ms
of every second by default), and is a symptom treatment for a core that is
not quiet. Reach for it only after `os-jitter-diagnosis` names a kernel
thread that preempts the loop and isolation cannot remove it, and put the
change to the user as a decision.

## Shutdown, faults and signals

- A raised stop line ends the loop within one bounded turn. Join in the
  order the data flows: the producer of cancels before the thread that
  writes them to the wire.
- A thread's death is reported by a guard that runs on return and on
  unwind; a dropped join handle detaches the thread instead of stopping it.
- A process-directed signal runs on any thread that does not block it.
  Block signals on pinned threads and take them on a cold one. A handler
  does only what is async-signal-safe.

## The desk's runtime

`pgd-runtime` holds the pieces: `Agent::do_work`, `drive`, `IdleStrategy`
(`BusySpin` or `Backoff(BackoffIdle)`), `spawn_pinned` with its pin
handshake, `spawn_unpinned` (permitted less reserved less isolated, read
back), `process_cores` and `isolated_cores`.

- `engine.profile: shared` runs every thread unpinned on a backoff.
  `!dedicated { engine, connectivity }` pins the engine alone on `engine`,
  busy-spinning, and each connectivity thread on the core its source names.
  A core named once is that thread's and it spins; a core named more than
  once is time-shared and every thread on it backs off.
- The default ladder is 10 spins, 20 yields, parks from 1 µs to 1 ms. A
  duty's ladder is 10 spins, no yields, parks from 1 µs to 50 µs, because
  that park is what an outbound order waits through.
- Recorded on a 4 vCPU cloud VM (`docs/BENCHMARKS.md`, "A cancel reaching a
  quiet duty"): a cancel reaches a spinning duty in 0.15 µs at the median;
  a duty on the backoff in 54 µs (p99 108 µs); the same with 1 ns timer
  slack in 30 µs (p99 59 µs); beside one spinning thread in about 1.1 ms.
  The node sets no slack, locks no memory and sets no socket busy-poll
  option today.
- Each source has its own thread; a composite runner over several agents
  does not exist, and `Engine::run` consumes the engine.
- Pinning is Linux-only and refuses elsewhere. `just pinned-tests` and
  `just quiet-hop` run the pinned targets on a Linux host with four cores
  or more.

## Proving it

- A change to an idle ladder, a placement or a pin is a latency claim: it
  carries a before and after from the same host and session, open loop,
  percentiles with sample counts, per `systems-benchmarking`. The quiet-hop
  bench is the shape: one writer on its own core, records spaced with
  jitter so arrivals never phase-lock to the park, the reader stamps the
  pop.
- Read the placement back from the running process: each thread's mask,
  last CPU, time waited for its core and context-switch counts
  (`os-jitter-diagnosis`).
- A cloud VM compares cases against each other; it does not give a host's
  tail.

## Gotchas

1. A yield rung on a shared core: the thread waits out its neighbour's
   slice.
2. A helper thread spawned from a pinned thread sits on the pinned core.
3. Default timer slack doubles a short park's worst case.
4. Two threads spinning on one core.
5. A pin that fails quietly and runs the loop on a housekeeping core.
6. The process's cores read from a pinned thread: one core.
7. An unbounded `do_work`: the stop flag and every other agent wait on it.
8. `SCHED_FIFO` used to hide a core that is not isolated.
9. A blocking wake-up paid by the hot producer.
10. A number from an unpinned or virtual host reported as the production
    tail.
