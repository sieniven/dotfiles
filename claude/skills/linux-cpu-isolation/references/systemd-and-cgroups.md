# systemd, cgroups and an isolated host

Companion to `SKILL.md`. The service manager starts almost everything on a
host, so its settings decide what can reach an isolated core and what the
node's process is allowed to do.

## Where processes start

- With `isolcpus=domain`, the kernel moves `init` to the housekeeping
  cores at boot. Every service inherits that mask, so nothing starts on an
  isolated core without asking.
- Without boot-time domain isolation (a tickless-only or cpuset design),
  `CPUAffinity=` in `/etc/systemd/system.conf` gives the manager and every
  unit a housekeeping mask instead. A unit can override it with its own
  `CPUAffinity=`.
- Asking is cheap: any process may set its own affinity to any CPU its
  cpuset allows. Isolation keeps accidents out, not a process that names
  the core. Two nodes naming the same core is prevented by the launcher,
  not by the kernel.

## The mask a pinned process needs

A process that pins threads to isolated cores needs those cores in its
process mask, plus a housekeeping core for its unpinned threads. Either the
launcher widens the mask before `exec`, or the unit sets `CPUAffinity=` to
the same list. One place owns it. A launcher that computes the mask from
the node's own configuration cannot drift from what the node pins.

## cpusets

- `AllowedCPUs=` on a unit or slice is a cpuset: a hard limit that
  `sched_setaffinity` cannot exceed. A pin outside it fails, or the mask
  is silently narrowed, which is why a launcher reads its mask back.
- A cpuset anywhere above the unit applies to it. `systemctl show -p
  AllowedCPUs -p EffectiveCPUs <unit>` and the unit's
  `cpuset.cpus.effective` file tell what it has.
- systemd owns the cgroup tree. A cpuset or an isolated partition made by
  hand under `/sys/fs/cgroup` can be overridden by it; make one inside a
  subtree delegated for the purpose, and read `cpuset.cpus.partition` back
  for `isolated` rather than `isolated invalid (...)`.
- Containers get a cpuset and often a CPU quota. A quota throttles a
  spinning thread for the rest of each period: a pinned node runs with no
  quota.

## Unit properties that matter for a pinned node

| Property | Effect |
| --- | --- |
| `CPUAffinity=` | the process's starting mask |
| `TimerSlackNSec=` | timer slack for the unit's processes, inherited by every thread |
| `LimitMEMLOCK=` | how much the process may lock; `infinity` for `mlockall` |
| `LimitRTPRIO=`, `CPUSchedulingPolicy=` | real-time scheduling, only where that was decided |
| `LimitNOFILE=`, `LimitCORE=` | descriptors; whether a crash leaves a core file |
| `TimeoutStopSec=`, `KillSignal=` | how long a drain may take before the kill |
| `RefuseManualStop=` | nothing but the node's own operator path stops it |
| `Environment=`, `EnvironmentFile=` | the only environment the process gets |

A service sees nothing of the shell that started it. A transient unit
(`systemd-run -p ...`) takes the same properties as a unit file.

Memory limits (`MemoryMax=`, `MemoryHigh=`) make the kernel reclaim inside
the unit when it nears them, which is a stall on whichever thread
allocates. Give a pinned node no memory limit it can reach.

## The rest of the host

- irqbalance reads `/etc/default/irqbalance` (Debian family) or
  `/etc/sysconfig/irqbalance` (RHEL family); `IRQBALANCE_BANNED_CPULIST`
  keeps it off the isolated cores. Restart it after the change.
- A tuning daemon (`tuned`) that owns the command line, the workqueue
  masks and irqbalance will fight a script that sets the same things. One
  owner per setting.
- Timers and maintenance jobs (package updates, log rotation, a monitoring
  agent's burst) run on housekeeping cores and still cost shared caches,
  memory bandwidth and the hypervisor's attention. Know what the host runs
  beside the node.
- An unattended upgrade that restarts services or installs a kernel is a
  change to a trading host made by nobody. Decide its policy explicitly.

## Reading it back

```sh
systemctl show -p CPUAffinity -p AllowedCPUs -p TimerSlackNSec -p LimitMEMLOCK <unit>
grep -E 'Cpus_allowed_list|voluntary' /proc/<pid>/status
cat /proc/<pid>/timerslack_ns
cat /sys/fs/cgroup/<unit's path>/cpuset.cpus.effective
```
