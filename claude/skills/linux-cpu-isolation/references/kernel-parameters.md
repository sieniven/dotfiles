# Kernel parameters for isolation

Companion to `SKILL.md`. One entry per parameter: what the kernel's own
documentation says, the versions it was read at, and what to check on the
host. Source paths are in the kernel tree. "All versions read" means v6.8,
v6.12, v6.18, v7.0 and mainline (7.4-rc, November 2026).

## isolcpus=[flag-list,]<cpu-list>

`Documentation/admin-guide/kernel-parameters.txt`. Flags, default `domain`
when none is given:

- **`domain`**: isolates from SMP balancing and scheduling. Irreversible
  until reboot. A process is moved onto or off such a CPU only by the
  affinity syscalls or a cpuset. At boot the kernel moves `init` to the
  housekeeping set, and every process inherits that mask, which is why
  nothing starts on an isolated core.
- **`nohz`**: the same as naming the list in `nohz_full=`. The residual
  1 Hz tick is offloaded to workqueues, which follow the housekeeping set
  when `domain` is also given.
- **`managed_irq`**: keeps managed interrupts whose mask spans isolated and
  housekeeping CPUs on the housekeeping ones. Best effort. A queue whose
  mask is only isolated CPUs is unaffected, though it then fires only for
  I/O submitted from those CPUs.

Giving any flag turns the default off: `isolcpus=managed_irq,7` does not
isolate CPU 7 from the scheduler. Tagged "[Deprecated - use cpusets
instead]" from v6.8 through v6.18; mainline removed the tag and points to
`Documentation/admin-guide/cpu-isolation.rst` for the choice.

## nohz_full=<cpu-list>

`kernel-parameters.txt`, `Documentation/timers/no_hz.rst`, and in mainline
`Documentation/admin-guide/cpu-isolation.rst`. All versions read:

- Needs `CONFIG_NO_HZ_FULL=y`; without it the parameter is ignored.
- The boot CPU is forced out of the list to keep timekeeping.
- CPUs in the list have their RCU callbacks offloaded as if named in
  `rcu_nocbs=`.
- The tick stops only while one task is runnable on the CPU. With several,
  "adaptive-ticks does not do anything", even when one of them is
  `SCHED_FIFO`.
- User/kernel transitions cost more, POSIX CPU timers keep the tick on,
  and scheduler statistics are computed slightly differently.
- A 1 Hz residual tick is run on a housekeeping CPU on the isolated one's
  behalf.
- Mainline's guide adds the constraints in so many words: a single task,
  no calls to the kernel from the isolated CPU, no POSIX CPU timers, a
  clocksource that needs no watchdog.

The stop reason is traceable: the `tick_stop` tracepoint reports the
dependency that kept the tick (`SCHED`, `POSIX_TIMER`, `PERF_EVENTS`,
`CLOCK_UNSTABLE`, `RCU`, `RCU_EXP`).

## rcu_nocbs[=<cpu-list>] and rcu_nocb_poll

- `rcu_nocbs=` needs `CONFIG_RCU_NOCB_CPU=y`. Callbacks of the listed CPUs
  are invoked by `rcuo` kernel threads instead of in softirq context on the
  CPU. Those threads are unbound; check where they run
  (`ps -eLo psr,comm | grep rcuo`) and bind any that sit on an isolated
  core to the housekeeping set.
- With no list, no CPU is offloaded at boot but the mode can be toggled at
  runtime through cpusets (text present at all versions read).
- `rcu_nocb_poll` makes the `rcuo` threads poll instead of being woken by
  the offloaded CPU: one less thing the isolated CPU does, paid for by
  periodic wake-ups on the housekeeping side.

## irqaffinity=<cpu-list>

Sets the default interrupt affinity mask. It does not bind a driver that
sets its own, and not a managed interrupt.

## Workqueues

- `workqueue.unbound_cpus=<cpu-list>` restricts unbound workqueues at boot;
  by default every online CPU is available to them.
- At runtime: `/sys/devices/virtual/workqueue/cpumask`, and per workqueue
  for those exported to sysfs.
- Domain isolation, by either interface, already excludes its CPUs.

## Watchdogs

- `kernel.watchdog_cpumask` controls where the watchdog runs. With
  `nohz_full=`, those cores are excluded by default.
- `nosoftlockup` disables the soft-lockup detector; `nowatchdog` disables
  both detectors. Either removes a diagnostic for a hung kernel: a change
  to propose, not to slip in.

## Tick, time and SMT

- `skew_tick=1` offsets the periodic tick per CPU so they do not fire
  together; documented as for jitter-sensitive workloads, at a power cost.
- `tsc=reliable` skips the TSC's stability checks; `tsc=nowatchdog`
  disables the clocksource watchdog, documented for strict latency
  requirements. Both remove a safety check: only where the TSC is known
  good.
- `nosmt` disables SMT at boot (the kernel's own full-isolation example
  uses it). The alternative is isolating siblings and leaving them idle.
- `kernel.timer_migration` (sysctl): migrate timers from nohz-isolated to
  housekeeping CPUs; on by default.

## Idle and preemption

- `intel_idle.max_cstate=`, `processor.max_cstate=` cap the idle states
  the drivers use. `idle=poll` never halts: no wake-up latency, full power
  on every idle CPU, and it takes turbo headroom from the busy ones.
  Per-CPU, runtime alternatives are in `power-and-clock.md`.
- `preempt=none|voluntary|full|lazy` selects the preemption model on a
  kernel built with `CONFIG_PREEMPT_DYNAMIC`. It governs when kernel code
  can be preempted; it does not change what runs on an isolated core.
- `threadirqs` forces interrupt handlers into threads, which then have a
  priority and an affinity like any thread.

## Reading the host's state

| File | Holds |
| --- | --- |
| `/proc/cmdline` | what this boot was given |
| `/sys/devices/system/cpu/isolated` | CPUs out of load balancing (`isolcpus=` domain) |
| `/sys/devices/system/cpu/nohz_full` | CPUs in full-dynticks mode |
| `/sys/devices/system/cpu/housekeeping` | the housekeeping set; present only on kernels from late 2025 on |
| `/boot/config-$(uname -r)` | whether the features were built |
| `/proc/sys/kernel/watchdog_cpumask` | where the watchdog runs |

An absent boot argument reads as an empty line or `(null)` in these files;
both mean the empty list.

## The housekeeping types (mainline)

`Documentation/core-api/housekeeping.rst` names four: `HK_TYPE_DOMAIN`
(scheduler domains, unbound workqueues and timers; `isolcpus=domain` or an
isolated cpuset partition), `HK_TYPE_KERNEL_NOISE` (remote tick, vmstat,
lockup watchdog; `nohz_full=` or `isolcpus=nohz`), `HK_TYPE_MANAGED_IRQ`
(`isolcpus=managed_irq`), and `HK_TYPE_DOMAIN_BOOT` (the boot-time part
alone). Only the first can be changed at runtime, by cpusets.

## A reference configuration to compare with

`tuned`'s `cpu-partitioning` profile (its `tuned.conf`): command line
`nohz=on nohz_full=<isolated> rcu_nocbs=<isolated> intel_pstate=disable
nosoftlockup`, with `isolcpus=` only for cores listed as not to be
balanced; sysfs workqueue and writeback masks set to the housekeeping
cores; machine-check `ignore_ce`; systemd's CPU affinity set to the
housekeeping cores; irqbalance told to ban the isolated ones. It includes
the `network-latency` profile. Useful as a checklist; not something to
apply beside a script that owns the same settings.
