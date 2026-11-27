# Idle strategies

Companion to `SKILL.md`. What a ladder is made of, how to set its numbers,
what the kernel does at each rung, and what other runtimes ship.

## Anatomy of a backoff ladder

A ladder has three counters and two bounds: spins, yields, then parks that
double from a minimum to a cap. Work resets it to the first rung.

- **Spins** cover the gap between two messages of one burst. Ten spin hints
  are well under a microsecond; they cost nothing a sharing thread notices.
- **Yields** are worth a rung only where every thread beside this one is
  idle and unpinned work may want the core. On a pinned shared core set
  them to zero: beside a busy thread a yield waits out that thread's slice,
  and beside idle threads it returns immediately and buys nothing.
- **The park's minimum** is small (1 µs) so the first sleep after a burst is
  short; the kernel adds the timer slack to it.
- **The park's cap** is the design number. It is the longest a message can
  wait for this thread when the thread has gone quiet, before slack. Derive
  it from the message: a cancel that must leave within 100 µs caps the park
  near 50 µs at default slack.

A ladder's state is three integers on the runner's stack. It is reset by
work, and only by work: a turn that polled and found nothing escalates.

## The kernel at each rung

- **Spin.** `std::hint::spin_loop` emits `PAUSE` on x86-64 and `ISB` on
  aarch64 and never enters the kernel. `PAUSE` length differs several-fold
  between CPU generations, so a spin count is not a time: bound spins by a
  clock when the duration matters.
- **Yield.** `sched_yield` takes the runqueue lock, calls the class's yield
  hook and schedules. For the fair class, with one runnable task it returns
  at once. Otherwise the caller gives up its turn: through v6.18 its
  deadline moves one slice out, and from v6.19 a caller that is still
  eligible also forfeits the rest of its slice. Either way a neighbour
  that keeps running is picked ahead of it, for about that neighbour's
  slice (`yield_task_fair`). The kernel's own comment says never to use
  yield as a progress guarantee. Under `SCHED_FIFO` a yield only lets
  equal-priority tasks run.
- **Park.** `thread::sleep` and `park_timeout` arm an hrtimer. The timer
  may fire late by up to the thread's slack; the wake-up makes the sleeper
  runnable with an early deadline, which normally preempts a thread that
  has been running. A park therefore reaches the core faster than a yield
  does when a neighbour is busy.
- **Timer slack.** Two values per thread, default and current; a new
  thread takes its creator's current value as both. `init`'s is 50 000 ns.
  It applies to `nanosleep`, `clock_nanosleep`, `futex` timeouts, `poll`,
  `select` and `epoll_wait` timeouts, and not to real-time threads. Setting
  1 ns before spawning workers gives every later thread 1 ns.
- **Tick.** A core with more than one runnable task keeps its scheduler
  tick, whatever the boot parameters say. A core where the others are
  parked has one runnable task between wakes.

## The desk's measurements

From `engine-middleware`'s `docs/BENCHMARKS.md`; read it for the hosts and
the method before quoting a number.

| The reader's core | p50 | p99 |
| --- | --- | --- |
| alone, busy-spinning | 0.15 µs | 0.41 µs |
| alone, parks capped at 50 µs | 54 µs | 108 µs |
| beside two idle threads on the same ladder | 55 µs | 114 µs |
| the same, 1 ns timer slack | 30 µs | 60 µs |
| beside one busy-spinning thread, ladder with a yield rung | 1.1 ms | 2.2 ms |
| beside one busy-spinning thread, no yield rung (second VM) | 64 µs | 3.1 ms |

What they establish: a parked reader pays the park plus the slack; idle
neighbours add microseconds; a yield rung beside a busy thread costs a
scheduler slice where a park costs the park; a spinner on a shared core
leaves the tail in milliseconds either way.

## What other runtimes ship

- **Agrona / Aeron.** `Agent.doWork()` returns a work count that feeds an
  `IdleStrategy`. `BackoffIdleStrategy` spins, yields, then parks doubling
  to a maximum; its defaults are 10 spins, 5 yields, 1 µs to 1 ms, and its
  documentation notes the 50 µs timer-slack window. Aeron's low-latency
  configuration gives each driver agent its own thread with a busy-spin or
  no-op idle; its shared modes put all agents on one thread, the composite
  shape.
- **crossbeam `Backoff`.** For retrying a lock-free operation, not for
  idling a loop: `spin()` backs off exponentially up to 2^6 hints,
  `snooze()` yields past that, and `is_completed()` after step 10 tells the
  caller to block.
- **The Rust `disruptor` crate.** Busy-spin wait strategies, a sleep
  strategy it documents as not for latency-sensitive use, and per-processor
  core pinning.

## Waking instead of polling

A consumer that blocks needs a wake-up: a futex or an eventfd write, a
syscall on the producer's side every time the consumer might be asleep. On
a hot producer that is a kernel entry per message. Keep polling for hot
consumers; where a cold consumer blocks, let the producer check a
"sleeping" flag first so the wake is paid only when needed, and accept the
missed-wake race by bounding the consumer's sleep.

## Sources

- Kernel: `kernel/sched/fair.c` (`yield_task_fair`), `kernel/sched/syscalls.c`
  (`do_sched_yield`, the `yield()` comment), `init/init_task.c`
  (`timer_slack_ns`), `Documentation/timers/no_hz.rst`.
- `prctl(2)` (`PR_SET_TIMERSLACK`), `sched_yield(2)`, `nanosleep(2)`.
- Rust: `library/core/src/hint.rs` (`spin_loop`).
- Agrona: `org.agrona.concurrent.BackoffIdleStrategy`, `Agent`,
  `AgentRunner`; Aeron's configuration options page.
- crossbeam: `crossbeam-utils/src/backoff.rs`.
