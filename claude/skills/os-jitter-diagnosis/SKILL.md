---
name: os-jitter-diagnosis
description: Proving that a pinned core is quiet and attributing a latency stall to its source on Linux. The method (read-only triage, attribute before changing, one change, re-measure with the same instrument), the read-backs that need no privilege (the command line against the sysfs isolation lists, per-thread masks, last CPU, schedstat run delay and context-switch counts, /proc/interrupts and softirqs deltas), the tracing instruments (the tick_stop, sched_switch, irq and workqueue tracepoints, rtla osnoise, timerlat and hwnoise, perf sched and perf trace, turbostat), in-application gap histograms, a table of noise signatures by period and duration, and how to read results on a virtual machine. Use when checking an isolated host before a node starts, when a pinned thread shows a tail, a preemption, a migration or an unexpected interrupt, or when a host or threading change must be shown to have worked.
---

# OS jitter diagnosis

Finding out what interrupted a thread that was supposed to be left alone.
What isolation should have removed is `linux-cpu-isolation`; how the thread
is built is `low-latency-threading`; the measurement contract and profiling
of the code itself are `systems-benchmarking`.

## Method

1. **State the symptom as a number**: which thread, which percentile, how
   long a stall, how often, since when. "It feels slow" is not a start.
2. **Read before touching.** Everything in the first two levels below is
   read-only and needs no privilege. Collect it, with the kernel, the
   command line and the time, before anyone changes a setting.
3. **Attribute.** Name the class of the interruption (tick, device
   interrupt, IPI, preemption by a task, page fault, the thread's own
   blocking, hardware or hypervisor) from evidence, and say what evidence
   would refute it.
4. **One change, proposed.** A host change is the user's decision and
   usually a reboot. Say what it should move and by how much.
5. **Re-measure with the same instrument**, same window, same load. A
   different tool after the change proves nothing.
6. **Report what was not measured.** A counter that reads zero because the
   kernel does not keep it is not a clean result.

A quiet core is a claim about a window. State the window.

## Level 0: what the host is

No privilege, no perturbation.

```sh
cat /proc/cmdline
cat /sys/devices/system/cpu/{online,isolated,nohz_full}
uname -r; grep -E 'NO_HZ_FULL|RCU_NOCB_CPU|^CONFIG_HZ=' /boot/config-$(uname -r)
for i in /proc/irq/[0-9]*; do echo "${i##*/} $(cat $i/effective_affinity_list)"; done
ps -eLo pid,tid,psr,cls,rtprio,comm | awk '$3==2'      # everything last seen on core 2
```

Per thread of the node, under `/proc/PID/task/TID/`:

| File | Read |
| --- | --- |
| `status` | `Cpus_allowed_list` (one core means pinned), `voluntary_ctxt_switches`, `nonvoluntary_ctxt_switches` |
| `stat` | field 39, the last CPU; fields 14 and 15, user and system ticks |
| `schedstat` | nanoseconds on CPU, nanoseconds waiting for a CPU, timeslices |
| `comm` | the thread's name |

A pinned spinner on a quiet core shows a one-core mask, a last CPU equal to
it, no growth in either switch count and no growth in time waited.

## Level 1: counters over a window

Sample twice, a known time apart, and subtract.

- `/proc/interrupts`, the column of each isolated core: device rows, and
  the per-CPU rows (`LOC` local timer, `RES` rescheduling IPI, `CAL`
  function-call IPI, `TLB` shootdowns, `NMI`, `PMI`, `MCP`).
- `/proc/softirqs`, the same columns: `TIMER`, `NET_RX`, `SCHED`, `RCU`.
- The per-thread files above: switches, time waited, timeslices.
- `/proc/stat`, the `cpuN` lines: the eighth figure is steal.
- `perf stat -e context-switches,cpu-migrations,page-faults -t TID -- sleep 10`
  where perf is allowed. Counting mode adds little; sampling mode does not
  belong on a core being judged.

An isolated, tickless core with one spinning thread shows `LOC` rising by
about one a second or less and nothing else. A core that shows `LOC` at the
kernel's `HZ` has its tick.

## Level 2: tracing

Needs root or tracing rights, and it perturbs: ask before running it on a
host that trades. It is the only level that names the interrupter.

- **Tracepoints** under `/sys/kernel/tracing/events/`: `sched/sched_switch`
  (who took the core), `irq_vectors/*` and `irq/irq_handler_entry` (which
  interrupt), `irq/softirq_entry`, `workqueue/workqueue_execute_start`
  (which work item), `timer/hrtimer_expire_entry`, and `timer/tick_stop`
  (why the tick could not stop). Read one core's buffer from
  `per_cpu/cpuN/trace`.
- **`rtla osnoise`**: a kernel thread per CPU spins reading the clock and
  reports, per period, the noise total, the largest single noise, the
  share of CPU it kept, and counts of hardware, NMI, interrupt, softirq
  and thread interference. It is a stand-in for the workload: run it on an
  isolated core before the node starts, not beside a spinning thread.
- **`rtla timerlat`**: a periodic timer and a thread measure wake-up
  latency at the interrupt and at the thread, and can stop the trace at a
  threshold with the cause in the buffer. The instrument for a thread that
  parks.
- **`rtla hwnoise`**: osnoise with interrupts off, so only NMIs and
  hardware or hypervisor noise remain.
- **`perf sched timehist`, `perf trace -t TID`**: scheduling delay per
  wake-up; the syscalls a thread really makes.

Commands and how to read each output are in `references/instruments.md`.

## Level 3: the application as its own detector

A spinning loop reads a clock every turn. Keep the largest gaps between
consecutive turns in a preallocated histogram, exported as a metric, and
the node reports its own stalls with timestamps that can be matched to a
trace. A gap is everything: the kernel, the hardware, and the loop's own
longest turn; time the turn separately to tell them apart.

For a socket reader, the kernel's receive timestamp against the read time
is the same idea applied to I/O (`low-latency-network-io`).

## Signatures

| Looks like | Usually is |
| --- | --- |
| a stall every tick period, a few microseconds, `LOC` rising at `HZ` | the scheduler tick: a second runnable task, or the core is not tickless |
| once a second | the residual tick, vmstat, or a per-second timer |
| a device row rising on the core | an interrupt routed there: check its effective affinity and irqbalance |
| `RES` rising | wake-ups aimed at the core: another thread lives there, or something wakes one of the node's own |
| `CAL` or `TLB` rising | function-call IPIs and TLB shootdowns: the process changes its memory map, or huge-page and NUMA daemons do it for it |
| involuntary switches rising | preempted by a task: a kernel worker, a stray thread, a neighbour that spins |
| voluntary switches on a spinner | it blocked: a lock, a blocking call, a fault that slept |
| minor faults rising | memory touched for the first time, or pages split and merged under it |
| time waited rising on a shared core | a neighbour holds the core: a spinner or a long turn |
| the thread's last CPU changes | its mask is wider than one core |
| the first message after quiet is slow, the rest are not | idle-state exit, frequency ramp, or cold caches |
| gaps with no kernel event behind them; steal above zero; hardware noise in osnoise | the hypervisor, or firmware interrupts |

More rows, with the confirming and the refuting evidence for each, are in
`references/signatures.md`.

## Virtual machines

The guest's counters describe the guest. A stall with no interrupt, no
switch and no fault behind it is the host taking the physical CPU: it shows
as steal and as hardware noise, and no guest setting removes it. On a VM
compare one configuration with another, interleaved, and report tails as
that VM's.

## The desk's host check

`strategy-deployment`'s `scripts/isolate-cores.sh --check [--pid PID]`
(`just isolate-check`, `just check-node <strategy>`) is levels 0 and 1 in
one command: the sysfs lists against the request, every interrupt's
effective mask, each pinned thread's core and whether it is alone or
time-shared, anything else last seen on the cores, and one second of
interrupt and scheduler deltas. It does not trace. Read its `FAIL` and
`warn` lines as the attribution's starting evidence, not as the verdict.

## Report

- **Verdict** first: QUIET over the stated window, NOISY with the class
  named, or UNDETERMINED with what could not be read.
- The host: kernel, command line, isolation lists, virtual or not.
- Per core: what is pinned there, the deltas, the largest gap.
- The attribution with its evidence, and what would refute it.
- The change proposed, what it should move, how it will be re-measured.

## Gotchas

1. A tracer or a sampling profiler left running on the core being judged.
2. osnoise run beside the node's spinning thread: two tasks, the tick
   returns, and the tool reports the node as noise.
3. A zero from a kernel that does not keep the statistic.
4. A one-second window offered as proof against a stall that happens once
   a minute.
5. The allowed mask read instead of the effective one.
6. Guest counters read as the physical core's.
7. Two changes between two measurements.
8. The loop's own longest turn blamed on the kernel.
