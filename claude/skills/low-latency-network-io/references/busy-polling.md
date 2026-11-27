# Busy polling

Companion to `SKILL.md`. Busy polling lets the reading thread run the
NIC queue's packet processing itself instead of waiting for an interrupt
on another core. Source: `Documentation/networking/napi.rst`,
`Documentation/admin-guide/sysctl/net.rst`, `include/net/busy_poll.h`,
`net/ipv4/tcp.c`, `net/core/sock.c` in the kernel tree.

## The three loops

The kernel's own description of how packets get processed:

1. hard interrupt, softirq, NAPI poll: plain interrupt delivery;
2. timer, softirq, NAPI poll: deferred interrupt processing;
3. the application's call, busy poll, NAPI poll: busy looping.

Loop 3 only takes over from loop 1 when the device defers its interrupts
(`gro_flush_timeout` and `napi_defer_hard_irqs` set). Without them the
interrupt fires anyway and busy polling merely sometimes gets there first.

## The pieces and their versions

| Piece | What it does | Since |
| --- | --- | --- |
| `SO_BUSY_POLL` (socket option, microseconds) | a read or poll on this socket busy-polls its NAPI queue when the socket queue is empty | long-standing; needs `CONFIG_NET_RX_BUSY_POLL` |
| `net.core.busy_read` (sysctl) | the default `SO_BUSY_POLL` for every socket | long-standing |
| `net.core.busy_poll` (sysctl) | busy-poll time for `poll` and `select` on sockets that have `SO_BUSY_POLL`, and for every `epoll_wait` on the host whatever its sockets set | long-standing |
| `SO_PREFER_BUSY_POLL` | the application promises to keep polling; the driver keeps the interrupt masked until `gro_flush_timeout` passes without a poll | 5.11 |
| `SO_BUSY_POLL_BUDGET` | packets per busy poll | 5.11 |
| `napi_defer_hard_irqs`, `gro_flush_timeout` (per device in sysfs; per NAPI by netlink on recent kernels) | how many empty polls to wait, and for how long, before re-enabling the interrupt | `napi_defer_hard_irqs` 5.8; `gro_flush_timeout` long-standing |
| `EPIOCSPARAMS` on an epoll descriptor | per-epoll busy-poll time, budget and prefer flag | 6.9 (absent from the v6.8 headers) |
| `irq-suspend-timeout` (per NAPI, netlink) | interrupts stay masked while `epoll_wait` keeps returning events | 6.13 (absent at v6.12) |
| Threaded NAPI (`/sys/class/net/<dev>/threaded`) | NAPI polls run in `napi/<dev>-<id>` kernel threads that can be pinned | 5.12 |
| Threaded NAPI busy poll (netlink `"threaded": "busy-poll"`) | a kernel thread polls one queue continuously | 7.0 (absent at v6.18) |

The entries were checked against the tree's sources and headers at the
versions named. Confirm on the target kernel before depending on one.

## What a read does

At v6.18, `tcp_recvmsg` busy-polls when the socket has a busy-poll time,
its receive queue is empty and the connection is established. A blocking
read loops until data arrives or the time is up; a non-blocking read
(`MSG_DONTWAIT`, or a socket set non-blocking) runs the queue's poll once
and returns. The poll runs with the socket's prefer flag and budget.

For a loop that already makes a non-blocking read every turn, the option
turns that read into "process my queue, then tell me what arrived".

## Privilege

- `SO_BUSY_POLL`: none from v6.4 on; before that, raising it took
  `CAP_NET_ADMIN`.
- `SO_PREFER_BUSY_POLL`, and raising `SO_BUSY_POLL_BUDGET`:
  `CAP_NET_ADMIN`.
- The device settings and sysctls: root.

## Preconditions

1. The socket has a NAPI id: it is fed by a NIC queue whose driver
   supports busy polling. Read it with `SO_INCOMING_NAPI_ID` after the
   first packet. Loopback, Unix sockets and tunnels without one get
   nothing.
2. The flow arrives on one queue, and that queue is not shared with flows
   this thread should not be processing.
3. All descriptors in one epoll set share a NAPI id, where epoll is used.
4. The interrupt is deferred, or the design accepts that it still fires.

## Choosing the timeouts

- `gro_flush_timeout` too large delays packets whenever the application
  is not polling; too small lets the interrupt and softirq interfere with
  the poller. With a thread that polls every few hundred nanoseconds, a
  small value is safe.
- `irq-suspend-timeout` covers one application processing cycle and is
  much larger than `gro_flush_timeout`; it is a safety net for a stalled
  application.
- The global sysctls change every application on the host. Prefer the
  per-socket and per-epoll forms.

## What it costs

- Protocol processing for the queue now runs on the reader's core, inside
  the reader's turn. The turn gets longer and its bound must account for a
  full poll budget.
- More kernel time on a core that may be tickless, where each entry
  already costs more.
- A reader that stops polling (a long turn, a stall) leaves the queue
  unserved until the timeout hands it back to the interrupt.

## Verifying

- Socket wait before and after, same load, same host.
- The queue's interrupt count over a window: with prefer mode and
  deferral working it stops rising while the reader polls.
- The `NET_RX` softirq count on the old interrupt core falls; time in the
  kernel on the reader's core rises.
