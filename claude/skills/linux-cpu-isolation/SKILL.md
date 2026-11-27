---
name: linux-cpu-isolation
description: Isolating CPU cores on a Linux host for pinned, busy-spinning threads, and keeping the kernel's housekeeping off them. What each boot parameter buys and costs by kernel version (isolcpus with its domain, nohz and managed_irq flags, nohz_full, rcu_nocbs, irqaffinity), choosing parameters per core by what its thread does, boot-time isolation versus cgroup v2 cpuset isolated partitions, the boot CPU, SMT siblings and the housekeeping set, IRQ routing and irqbalance, the residual noise sources and the knob for each (workqueues, watchdogs, vmstat, timers, huge-page and NUMA daemons), idle and frequency states, clocksource, bootloader mechanics (GRUB drop-ins, grubby and BLS, systemd-boot), systemd and cgroup interplay, virtual hosts, and the discipline for a script that changes a host (dry run, refuse before the first write, idempotent, undo, read back after the reboot). Use when planning, scripting, reviewing or debugging core isolation, a kernel command line, IRQ affinity or host tuning for a low-latency node.
---

# Linux CPU isolation

Giving a core to one thread: taking it out of the scheduler's balancing,
stopping its tick, and moving the kernel's own work elsewhere. The thread
that runs there is `low-latency-threading`; proving the result is
`os-jitter-diagnosis`; where NIC interrupts go is `low-latency-network-io`.

Kernel statements were read from the kernel tree (its `Documentation/` and
source) at v6.8, v6.12, v6.18, v7.0 and mainline in November 2026. A
statement with no version held at all of them. A host's own kernel decides:
read its `/boot/config-*` and its documentation before promising a feature.

## What isolation is

Noise on a core is either asynchronous (interrupts, timers, the scheduler
tick, kernel threads and workqueues that preempt) or synchronous (the
thread's own syscalls and page faults). Housekeeping is the kernel work
that must run somewhere. Isolation deals with it in three ways:

- **Move it**: work bound to no CPU (unbound workqueues, kernel threads,
  timers) goes to the housekeeping cores.
- **Offload it**: work tied to the CPU is handed to a thread elsewhere, as
  RCU callbacks are, at a cost in locking.
- **Shut it down**: what cannot move is disabled for that CPU, as the
  lockup watchdog is.

At least one core stays housekeeping, more on a large host, one per NUMA
node where there are several. Isolation trades quiet cores for overhead on
the housekeeping ones and on every kernel entry from an isolated one.

## The boot parameters

| Parameter | Buys | Costs and limits | Read back |
| --- | --- | --- | --- |
| `isolcpus=domain,<list>` | out of load balancing: nothing lands there or leaves unless affined; unbound workqueues, kernel threads and timers leave too | fixed until the next boot; every process starts on the housekeeping cores | `/sys/devices/system/cpu/isolated` |
| `isolcpus=managed_irq,<list>` | kernel-managed device interrupts prefer housekeeping cores | best effort: no effect on a queue whose mask holds only isolated cores | `/proc/irq/N/effective_affinity_list` |
| `nohz_full=<list>` | the tick stops while exactly one task is runnable; RCU callbacks offloaded; vmstat and watchdog leave | needs `CONFIG_NO_HZ_FULL`; the boot CPU is forced out; every kernel entry and exit costs more; a 1 Hz tick runs remotely; no POSIX CPU timers; needs a stable clocksource | `/sys/devices/system/cpu/nohz_full` |
| `rcu_nocbs=<list>` | RCU callbacks run in `rcuo` kernel threads instead of softirq on the core | needs `CONFIG_RCU_NOCB_CPU`; implied by `nohz_full` for its list | `rcuo*` threads exist |
| `irqaffinity=<list>` | the default mask for device interrupts | a default only: drivers and irqbalance can override | `/proc/irq/default_smp_affinity` |

`isolcpus` flags combine in one list (`isolcpus=managed_irq,domain,2-5`),
and each parameter takes its own list, so cores of different kinds can get
different treatment. Per-parameter detail, the neighbouring parameters
(`rcu_nocb_poll`, `nohz=`, `nosoftlockup`, `skew_tick`, `tsc=`, `nosmt`,
idle-state limits) and what changed between versions are in
`references/kernel-parameters.md`.

## Parameters per kind of core

What a core's thread does decides what pays.

| The core runs | Domain and IRQ isolation | `nohz_full` |
| --- | --- | --- |
| one thread that stays in user space (a ring consumer) | yes | yes: this is the case it was built for |
| one thread that enters the kernel every turn (a socket poller) | yes | a measurement: no tick, against a dearer entry and exit on every read |
| several threads that take turns | yes | does nothing while more than one is runnable; the dearer entry stays |

The kernel's own guidance for a tickless core is one task and no kernel
calls. Applying one list to every isolated core is the simple default and a
defensible one; splitting the lists is a host change that is proposed with
a measurement (`os-jitter-diagnosis`, the quiet-hop bench) and decided by
the user, never made on reading alone.

## Choosing the cores

- Core 0 stays housekeeping: the kernel keeps timekeeping on the boot CPU
  and removes it from `nohz_full`.
- An SMT sibling shares the pinned thread's execution units and its L1 and
  L2. Isolate the sibling too and leave it idle, or boot with `nosmt`.
  Siblings come from `topology/thread_siblings_list`, never from id
  arithmetic.
- Leave housekeeping enough for the kernel, the host's services and the
  node's own unpinned threads. One core is the floor, not the target.
- Prefer isolated cores that share a last-level cache and a NUMA node with
  each other and with the NIC (`cpu-cache-and-memory-layout`).
- A host that already isolates other cores is changed as a whole, never
  merged into: one command line names every isolated core.

## Boot time versus runtime

- A cgroup v2 cpuset with `cpuset.cpus.partition = isolated` takes its CPUs
  out of load balancing and out of unbound workqueues, and can be made and
  undone on a running host.
- It does not stop the tick and does not move managed interrupts. At every
  version read, a tickless core needs `nohz_full=` on the command line and
  a reboot.
- Through v6.18 the `isolcpus` entry carried "Deprecated - use cpusets
  instead". Mainline has dropped the tag and documents both: cpusets where
  runtime change is wanted, the boot parameter where it is not. CPUs
  isolated with `isolcpus` can only be used in an isolated partition.
- `tuned`'s `cpu-partitioning` profile is a cross-check of the full set: it
  writes `nohz_full=` and `rcu_nocbs=` for the isolated cores, restricts
  systemd's own affinity and the workqueue masks to the rest, bans the
  cores in irqbalance, and uses `isolcpus=` only for cores it is told not
  to balance.

## Interrupts

- **Device interrupts with a writable mask** move through
  `/proc/irq/N/smp_affinity_list`; `irqaffinity=` sets their default at
  boot. A move made at runtime lasts until the driver, irqbalance or a
  reboot changes it.
- **Managed interrupts** (multi-queue storage and some NIC drivers) have
  kernel-owned masks; a write is refused. Only `isolcpus=managed_irq`
  steers them, at boot.
- **Per-CPU interrupts** cannot be moved: the local timer, rescheduling and
  function-call IPIs, TLB shootdowns, NMIs. They go quiet when their cause
  does (one runnable task, no memory-map churn in the process, no perf
  sampling on the core).
- irqbalance must be told to keep off the isolated cores
  (`IRQBALANCE_BANNED_CPULIST`) or it puts interrupts back.
- `effective_affinity_list` is where an interrupt fires; `smp_affinity_list`
  is where it is allowed to.
- Putting a NIC queue's interrupt on the core of the thread that reads it
  is a real design, at odds with moving every interrupt away. It is chosen
  on purpose in `low-latency-network-io`, never by accident.

## What still runs there

| Source | Behaviour on an isolated core | Knob |
| --- | --- | --- |
| Unbound workqueues | leave with domain isolation | `/sys/devices/virtual/workqueue/cpumask`, `workqueue.unbound_cpus=` |
| Per-CPU kernel threads (`ksoftirqd/N`, `kworker/N:*`, `migration/N`) | stay, and sleep unless work is queued on that CPU | remove the cause: interrupts, softirqs, syscalls that queue per-CPU work |
| vmstat update | deferred on a tickless core | `vm.stat_interval` |
| Lockup watchdogs | `nohz_full` cores are excluded by default | `kernel.watchdog_cpumask`, `nosoftlockup`, `nowatchdog` |
| Timers | migrate to housekeeping | `kernel.timer_migration` |
| Writeback | a workqueue with its own mask | `/sys/bus/workqueue/devices/writeback/cpumask` |
| Huge-page daemon, compaction, KSM, automatic NUMA balancing | cause faults and TLB-shootdown IPIs in the process | `transparent_hugepage`, `kernel.numa_balancing`, KSM off |
| Machine-check polling | a timer per CPU | `machinecheck*/ignore_ce` (accepting the lost reports) |
| Firmware (SMI) and the hypervisor | invisible to the kernel | BIOS settings; a different host |

Idle states, frequency scaling and the clocksource are in
`references/power-and-clock.md`. The service manager's part (affinity of
everything else, the unit that runs the node, cgroups) is in
`references/systemd-and-cgroups.md`.

## Changing a host

Host isolation edits the boot configuration and needs a reboot. A script
that does it keeps these rules, and a review holds it to them:

- **Read-only by default.** Status, check and dry-run modes need no root
  and change nothing. An agent runs only those unless the user asks for the
  change in so many words.
- **Refuse before the first write.** Every precondition is checked first: a
  core that is offline, core 0, a sibling left out, an isolation already
  configured differently, a bootloader it does not know. A refused run and
  a repeated run both change nothing.
- **Own what it writes.** A marked drop-in or marked lines, a backup of any
  file it edits, and an undo that removes exactly those.
- **Say what is pending.** The running command line against the next
  boot's; "a reboot is pending" is a state the tool reports.
- **Read back after the reboot**, before anything starts: the sysfs lists
  against the request, every interrupt's effective mask, what last ran on
  the cores.
- **Never reboot a host that runs a node.**

Bootloader specifics (GRUB drop-ins and their order, `update-grub`, grubby
and BLS entries, systemd-boot) are in `references/bootloaders.md`.

## Virtual hosts

- Guest parameters shape the guest kernel only. The hypervisor still takes
  the physical CPU; it shows as steal time and as hardware noise that no
  guest setting removes.
- The topology a guest sees (siblings, caches, NUMA) is the hypervisor's
  account of it. Check it before trusting a sibling list.
- Idle-state and frequency control exist only on instance types that
  expose them.
- Numbers from a guest compare configurations with each other. A tail
  claim needs dedicated hardware.

## Reading it back

```sh
cat /proc/cmdline
cat /sys/devices/system/cpu/{online,isolated,nohz_full}
cat /sys/devices/system/cpu/cpu2/topology/thread_siblings_list
grep -E 'NO_HZ_FULL|RCU_NOCB_CPU|CPU_ISOLATION' /boot/config-$(uname -r)
for i in /proc/irq/[0-9]*; do echo "${i##*/} $(cat $i/effective_affinity_list)"; done
```

`os-jitter-diagnosis` has the rest: what ran on the cores, counters over a
window, and tracing.

## Gotchas

1. `nohz_full` on a core that runs two threads: the tick is back and the
   entry cost stays.
2. `isolcpus=managed_irq,<list>` without `domain`: nothing is taken out of
   balancing and `isolated` reads empty.
3. An interrupt moved at runtime and put back by irqbalance.
4. An isolated core's SMT sibling left to the rest of the host.
5. A cpuset isolated partition expected to stop the tick.
6. A second isolation merged into the first by hand.
7. Core 0 named for isolation.
8. A kernel built without `CONFIG_NO_HZ_FULL` silently ignoring the
   parameter.
9. The command line edited and the bootloader's generated file not
   rebuilt, or rebuilt and the host not rebooted.
10. A guest's quiet counters read as a quiet physical core.
