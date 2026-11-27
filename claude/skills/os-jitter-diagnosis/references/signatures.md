# Noise signatures

Companion to `SKILL.md`. For each class of interruption: what it looks
like, what confirms it, what refutes it, and where the remedy lives.
Durations are orders of magnitude; the host's own trace is the authority.

## The scheduler tick

- **Looks like**: stalls of a few microseconds at a fixed period (1 ms at
  `HZ=1000`, 4 ms at 250).
- **Confirms**: `LOC` on that core rises by `HZ` a second; `tick_stop`
  reports a dependency.
- **Refutes**: `LOC` rises by about one a second.
- **Causes**: no `nohz_full` for the core; a second runnable task (a
  neighbour thread, a kernel worker with queued work, the osnoise thread);
  a POSIX CPU timer; perf sampling.
- **Remedy**: `linux-cpu-isolation` for the parameter;
  `low-latency-threading` for the second task.

## A device interrupt

- **Looks like**: irregular stalls of microseconds to tens of
  microseconds, tracking I/O.
- **Confirms**: the device's row rises in the core's column; its
  `effective_affinity_list` names the core.
- **Refutes**: every effective mask excludes the core and no device row
  moves.
- **Causes**: a runtime move undone by irqbalance or a driver reset; a
  managed interrupt whose queue mask is only isolated cores; a queue count
  equal to the CPU count, one per core.
- **Remedy**: the interrupts section of `linux-cpu-isolation`;
  `low-latency-network-io` when it is the NIC.

## Softirq and kernel workers

- **Looks like**: stalls after interrupts or syscalls, sometimes long.
- **Confirms**: `/proc/softirqs` rises in the core's column;
  `sched_switch` shows `ksoftirqd/N` or `kworker/N:*`;
  `workqueue_execute_start` names the function.
- **Causes**: network receive processing for a socket the core's own
  thread reads; timers armed from that core; per-CPU work queued by a
  syscall the thread made.
- **Remedy**: remove the cause. A per-CPU worker cannot be moved; it stops
  running when nothing queues work for it.

## IPIs

- **`RES`** (reschedule): a wake-up of a task whose CPU is this one. On a
  one-thread core, look for what else has that core in its mask.
- **`CAL`** (function call) and **`TLB`**: another CPU asks this one to
  run something, most often to flush translations after the process
  unmapped or re-protected memory, or after the kernel collapsed, split
  or migrated its pages.
- **Confirms**: the per-CPU row rises; `irq_vectors` events name the
  vector.
- **Remedy**: no `munmap`, `mprotect` or allocator trimming after
  start-up; huge-page and NUMA daemons off for the process
  (`cpu-cache-and-memory-layout`, the pages reference).

## Preemption by a task

- **Looks like**: stalls of a scheduler slice, hundreds of microseconds to
  milliseconds.
- **Confirms**: involuntary switches rise; time waited rises;
  `sched_switch` names the other task.
- **Causes**: a second pinned thread that spins or runs a long turn; a
  helper thread that inherited the mask; a foreign process that asked for
  the core.
- **Remedy**: `low-latency-threading` (placement, the idle ladder, where
  helpers start).

## The thread's own blocking

- **Looks like**: stalls of any length with voluntary switches.
- **Confirms**: voluntary switches rise on a thread that should never
  block; `perf trace` shows the call.
- **Causes**: a contended lock, a blocking socket, a synchronous log
  write, a page fault that waited for I/O.
- **Remedy**: the loop's rules in `low-latency-threading`.

## Page faults

- **Looks like**: stalls of a microsecond (minor) to milliseconds (major,
  or a huge-page allocation that compacts memory first).
- **Confirms**: the fault counters rise during steady state.
- **Causes**: memory first touched on the hot path; a growing heap or
  stack; copy-on-write after a fork; a file-backed mapping written after
  the kernel cleaned it.
- **Remedy**: lock and pre-fault; fixed-size structures.

## Idle exit and frequency

- **Looks like**: the first message after a quiet spell is slow by tens
  to hundreds of microseconds; a burst is fast.
- **Confirms**: `turbostat` shows deep-state residency on the core that
  wakes; latency falls when the state is disabled for that core.
- **Refutes**: the core spins and never idles.
- **Remedy**: `linux-cpu-isolation`, the power reference.

## Hardware and hypervisor

- **Looks like**: gaps from tens of microseconds to milliseconds with no
  switch, interrupt or fault behind them.
- **Confirms**: `rtla hwnoise` reports noise; steal is above zero;
  `turbostat` counts SMIs.
- **Remedy**: firmware settings on metal; a different instance or
  dedicated hardware in the cloud. Nothing in the guest.

## Cache and memory effects

- **Looks like**: every percentile drifts up while something else on the
  host is busy; no event on the core.
- **Confirms**: cache-miss counters rise with the neighbour's load; the
  drift follows an SMT sibling's or a last-level-cache neighbour's
  activity.
- **Remedy**: `cpu-cache-and-memory-layout`; idle siblings; fewer
  neighbours on the shared cache.

## The application

- **Looks like**: a gap in the loop's own histogram with nothing in the
  kernel's trace.
- **Confirms**: the longest single turn, timed on its own, is that long.
- **Remedy**: a profile of the code, per `systems-benchmarking`.
