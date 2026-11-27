---
name: low-latency-network-io
description: How a pinned thread reads and writes sockets on Linux without giving up its core. The receive path from NIC queue to socket (hard interrupt, NAPI softirq, socket queue, wake-up) and which core each stage runs on once cores are isolated, reading by non-blocking polling versus epoll versus a blocking read, the busy-poll family (SO_BUSY_POLL, the busy_read and busy_poll sysctls, SO_PREFER_BUSY_POLL, epoll parameters, IRQ suspension, threaded NAPI) with the kernel version of each, NIC queues and steering (RSS, RPS, RFS, XPS, queue counts, interrupt moderation), kernel receive timestamps and the socket-wait metric, TCP options that matter for small messages, loopback and Unix sockets, io_uring for a single-threaded loop, and when kernel bypass is and is not worth it. Use when writing or reviewing a feed or order-entry I/O loop, deciding where NIC interrupts go relative to a pinned core, tuning a NIC, or explaining the time a message spent between the wire and the read.
---

# Low-latency network I/O

The stretch between the wire and the thread that reads it. Protocols and
sessions are `venue-protocols`; the thread is `low-latency-threading`; the
cores and their interrupts are `linux-cpu-isolation`; attributing a stall
is `os-jitter-diagnosis`.

Kernel statements were read from the kernel tree at v6.8, v6.12, v6.18,
v7.0 and mainline in November 2026, and name a version where it matters.

## Measure first: where the time is

- A venue across the internet is milliseconds away with a tail to match.
  Host tuning moves microseconds. Know the split before spending effort:
  the venue's stamp against the kernel's receive stamp is the network; the
  kernel's stamp against the read is the host; the read against the
  decision is the code.
- The kernel stamps each received segment when asked (`SO_TIMESTAMPING`
  with software receive stamps). Stamp minus read time, as a histogram per
  socket, is **socket wait**: the one number every change in this skill is
  judged by.
- Wire claims need wire timestamps (`systems-benchmarking`).

## The receive path and its cores

```
NIC queue -> hard interrupt -> NAPI poll (softirq) -> TCP -> socket queue -> the reader
```

- The hard interrupt fires on the CPU its queue's interrupt is routed to.
  The NAPI poll and protocol work normally run in softirq context on that
  same CPU, or in `ksoftirqd`, or in a NAPI kernel thread when threaded
  NAPI is on.
- The reader runs on its own core. If that differs from the interrupt's,
  each message crosses cores: the socket's lines and the payload move
  between caches.
- A reader that blocks is woken by the softirq side, a scheduler wake-up
  on top. A reader that polls needs no wake.

After isolation every interrupt has been moved to housekeeping cores, so
packets for a pinned reader are processed on a housekeeping core that also
serves the rest of the host, and that may be idle and slow to wake.

## Three coherent designs

| Design | Path | Fits |
| --- | --- | --- |
| **A. Poll the socket** | interrupt and softirq on a housekeeping core; the reader spins on non-blocking reads | the default: nothing on the reader's core but the reader; pays a cross-core hand-off and depends on the housekeeping core's wake-up |
| **B. Poll the queue** | the reader's own read drives the NIC queue (busy polling); the queue's interrupt is deferred or masked | removes the hand-off and the other core; needs the flow on a queue the reader owns, and kernel work on the reader's core every turn |
| **C. Interrupt beside the reader** | the queue's interrupt routed to the reader's core or its sibling | the NIC vendor's usual advice; puts interrupt and softirq time on an isolated core, at odds with moving them all away |

Choosing B or C is a host and application change together. Propose it with
socket-wait numbers before and after; do not arrive at it by leaving one
interrupt behind.

## Reading

- **Non-blocking read in the loop**: one `recv` a turn, `WouldBlock` is
  the idle case. One kernel entry a turn is the price of design A and B
  alike. Bound it: at most one read and one write a turn, so the loop's
  other duties are never starved.
- **`epoll_wait` with a zero timeout** adds a call and pays off only with
  many sockets on one thread.
- **A blocking read** gives up the core and comes back after a wake-up:
  for cold threads.
- Size the receive buffer for the largest burst between two reads; a full
  buffer stalls the sender or drops, and both look like the venue's fault.
- Take the receive stamp in the I/O thread, before parsing.

## Busy polling

Verified in v6.18's source: with `SO_BUSY_POLL` set to a non-zero value, a
TCP read that finds the socket queue empty runs the NAPI poll for the
socket's queue in the caller's context first. A blocking read keeps
polling for up to the value in microseconds; a non-blocking read polls
once. So a spinning non-blocking reader with the option set drives its NIC
queue from its own core.

- Works only for a socket fed by a NIC queue (it needs a NAPI id; read it
  with `SO_INCOMING_NAPI_ID`). Loopback and Unix sockets have none: the
  option does nothing there.
- `SO_BUSY_POLL` itself needs no privilege from v6.4 on.
  `SO_PREFER_BUSY_POLL` and a larger `SO_BUSY_POLL_BUDGET` need
  `CAP_NET_ADMIN`.
- `net.core.busy_read` sets the default for every socket on the host;
  prefer the per-socket option.
- To keep the interrupt from firing as well, the device's
  `napi_defer_hard_irqs` and `gro_flush_timeout` must be set, and the
  application promises to keep polling with `SO_PREFER_BUSY_POLL`; the
  promise lapses when no poll arrives within the timeout.
- The flow has to arrive on a queue this reader is meant to drive, or the
  reader does another flow's protocol work.

Versions, the epoll form, IRQ suspension and threaded NAPI are in
`references/busy-polling.md`.

## The NIC

- One TCP flow hashes to one receive queue (RSS). Which queue, and
  therefore which interrupt and core, is decided by the hash unless a
  filter pins the flow.
- Software steering (RPS, RFS) moves protocol work to other CPUs by IPI.
  RFS in particular sends it to the CPU where the reader runs: on an
  isolated host that is softirq work arriving on the pinned core.
- Interrupt moderation batches interrupts to save CPU and adds its delay
  to every quiet-time packet. Adaptive moderation changes with load.
- A queue per CPU is the driver's default; fewer queues, all on
  housekeeping cores, is the usual isolated layout.
- Offloads that batch (GRO, LRO) trade per-packet latency for throughput.

Commands and the ENA driver's own guidance are in
`references/nic-and-irqs.md`.

## Writing

- `TCP_NODELAY` on every order and control socket: Nagle's algorithm holds
  a small segment back while earlier data is unacknowledged.
- A non-blocking write can be partial or refused. The remainder is kept
  and retried next turn in order; an order is never dropped or reordered
  to make room (`quant-trading`, backpressure).
- One write a turn, coalescing what is ready, bounds the turn. Say what
  the batch may delay and by how much.
- The send path's interrupt and completion work lands on the queue chosen
  by XPS or the hash, not necessarily a housekeeping core. Check it.

## Loopback and Unix sockets

A local peer's `send` does the receive-side work on the sender's core,
normally before the call returns, so the data is then in the reader's
queue. There is no NIC queue, no device interrupt and nothing to
busy-poll. Socket wait
on such a link is the reader's polling gap and the sender's scheduling.

## io_uring and bypass

- For one thread that owns its ring, `IORING_SETUP_SINGLE_ISSUER` with
  `IORING_SETUP_DEFER_TASKRUN` (6.1 on) runs completions only when the
  thread asks. `SQPOLL` adds a kernel thread that spins on a core of its
  own. io_uring does not remove the kernel entry for a loop that polls a
  few sockets; it pays when there are many, or with registered buffers and
  multishot receives.
- Kernel bypass (AF_XDP, DPDK, vendor stacks) moves packets to user space
  and leaves TCP, and TLS, to the application. For TCP venues reached
  across the internet that is rarely worth owning a TCP stack.

`references/io-uring-and-bypass.md` has the flags and the decision.

## The desk's I/O

`engine-middleware` reads its sockets directly and non-blocking from each
source's thread, bounded per turn. It asks for software receive stamps
through `pgd-runtime`'s `enable_rx_stamps` and `recv_stamped`
(`market_data.kernel_rx_stamps`, `ws://` links only) and publishes
`pgd_socket_wait_seconds{source, lane}`. It sets no busy-poll option
today, and its interrupts follow the host script: everything on
housekeeping cores, design A.

## Gotchas

1. Tuning the host while the path's milliseconds are in the network.
2. A pinned reader whose NIC interrupt wakes a housekeeping core out of a
   deep idle state.
3. RFS steering softirq work onto an isolated core.
4. Busy polling set on a loopback or Unix socket.
5. `SO_PREFER_BUSY_POLL` without the device's deferral settings: the
   interrupt still fires.
6. Adaptive interrupt moderation changing the latency with the load.
7. Nagle left on for orders.
8. A partial write treated as sent.
9. A receive buffer sized for the average burst.
10. Socket wait reported from a stamp taken after parsing.
