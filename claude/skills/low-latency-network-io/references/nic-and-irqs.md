# The NIC: queues, steering and interrupts

Companion to `SKILL.md`. What to read and what to set on the device, and
how it meets core isolation. Every `ethtool` change is a host change: read
freely, write only when asked. Source for the steering mechanisms:
`Documentation/networking/scaling.rst`.

## Read the device

```sh
ethtool -i eth0            # driver and version
ethtool -l eth0            # channels (queues): current and maximum
ethtool -c eth0            # interrupt coalescing (moderation)
ethtool -x eth0            # RSS indirection table and hash key
ethtool -n eth0            # flow rules (ntuple), where supported
ethtool -k eth0            # offloads: GRO, LRO, TSO
ethtool -S eth0            # per-queue counters and drops
grep eth0 /proc/interrupts # one row per queue: which CPU takes each
cat /sys/class/net/eth0/queues/rx-0/rps_cpus
cat /sys/class/net/eth0/queues/tx-0/xps_cpus
cat /sys/class/net/eth0/{napi_defer_hard_irqs,gro_flush_timeout,threaded}
cat /sys/class/net/eth0/device/numa_node
```

## Steering: which queue, which CPU

- **RSS**: the NIC hashes each packet's addresses and ports and uses an
  indirection table to pick a receive queue. One TCP connection always
  lands on one queue. `ethtool -X` rewrites the table (for example, to
  spread only over the queues on housekeeping cores).
- **Flow rules** (`ethtool -N ... action <queue>`), where the driver
  supports them, pin a named flow to a queue: the way to give a reader
  its own queue.
- **RPS** hands protocol processing from the interrupt's CPU to another
  by IPI, chosen by a per-queue CPU mask. Off when the mask is zero.
- **RFS** extends RPS to choose the CPU where the consuming thread last
  ran. Good for throughput; on an isolated host it delivers softirq work
  to pinned cores. Keep its table at zero unless design C is the intent.
- **Accelerated RFS** does the same in the NIC, by moving the flow's
  queue.
- **XPS** maps transmitting CPUs to transmit queues, which decides where
  transmit completions are handled.

## Queues and interrupts

- Drivers create a queue per CPU by default, and route each queue's
  interrupt to a different CPU, isolated ones included. After isolation
  either reduce the channel count to the housekeeping cores
  (`ethtool -L`) or route the surplus queues' interrupts to them.
- Changing the channel count resets the device briefly and rebuilds the
  RSS table. Not on a host that is trading.
- Whether a queue's interrupt is managed (the kernel owns its mask)
  depends on the driver; a write to `smp_affinity_list` that is refused
  says so.
- Check `effective_affinity_list` after every change and after any driver
  reset.

## Moderation

- `rx-usecs` and `rx-frames` hold an interrupt back until a time or a
  count is reached; `adaptive-rx` lets the driver vary them with load.
- For latency: adaptive off and the delays at zero, which raises the
  interrupt rate and the CPU the housekeeping core spends on it.
- With busy polling in prefer mode the interrupt is masked while the
  reader polls, and moderation matters only when it stops.

## Design C on purpose

Routing one queue's interrupt to a reader's core (or its sibling) puts the
hard interrupt and the softirq a few hundred nanoseconds from the reader
and keeps the payload in its caches. It costs an interruption per packet,
kernel time on an isolated core, and a second runnable context that brings
the tick back while it runs. Compare with design B, which gets the same
locality without the interrupt.

## ENA, from the driver's own guide

Amazon's ENA driver repository carries a best-practices document. Its
latency advice: keep the CPU out of deep idle states; consider enabling
busy polling; consider running the program on the same vCPU as the
interrupt that processes its traffic; keep the vCPUs that take ENA
interrupts free of unrelated load; disable interrupt moderation. It also
notes that receive moderation defaults differ by instance type (off on
some, adaptive on others), that the queue count is set with
`ethtool -L`, and that an interface supports up to 32 queues.

Its third point is design C and conflicts with moving every interrupt
away; say which design a host follows.

## Where the interrupt core sleeps

Under design A the housekeeping core that takes the NIC's interrupt is
part of the hot path. If it idles deeply, each quiet-time packet waits for
it to wake. Limit that one core's idle states
(`linux-cpu-isolation`, the power reference) before reaching for anything
more invasive.

## Things that go wrong

1. A queue per CPU left in place: interrupts on isolated cores after the
   next driver reset.
2. The RSS table spreading flows onto a queue whose interrupt is on an
   isolated core.
3. RFS enabled by a tuning profile.
4. Channel count changed on a live host.
5. Moderation tuned for throughput by default on a latency host.
6. The NIC on one NUMA node, the reader on another.
