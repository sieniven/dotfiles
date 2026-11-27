# io_uring and kernel bypass

Companion to `SKILL.md`. Two ways to change how a loop talks to the
network stack, and how to decide whether either is worth it. io_uring
facts are from the `io_uring_setup(2)` and `io_uring_register_napi(3)` man
pages in liburing.

## io_uring for one pinned thread

| Flag | Effect | Since |
| --- | --- | --- |
| `IORING_SETUP_SINGLE_ISSUER` | only one thread submits; lets the kernel skip locking | 6.0 |
| `IORING_SETUP_DEFER_TASKRUN` | completion work runs only when the thread calls in to collect events, never as an interruption; requires `SINGLE_ISSUER` | 6.1 |
| `IORING_SETUP_COOP_TASKRUN` | completion work is not forced by an IPI | 5.19 |
| `IORING_SETUP_SQPOLL` | a kernel thread polls the submission queue so submitting needs no syscall; it sleeps after `sq_thread_idle` and then needs a wake-up call | unprivileged since 5.13 |
| `IORING_SETUP_SQ_AFF` | binds that kernel thread to `sq_thread_cpu` | with `SQPOLL` |

- `SINGLE_ISSUER` with `DEFER_TASKRUN` is the shape for a duty-cycle loop:
  nothing runs on the core except when the loop asks.
- `SQPOLL` is a second spinning thread. It needs a core of its own; put on
  the loop's core it is a second runnable task, and put elsewhere it is a
  cross-core hop.
- `io_uring_register_napi` registers busy polling for the ring: a
  busy-poll time and a prefer flag, the io_uring counterpart of the socket
  options.
- Multishot receive and provided buffers remove per-read submission; with
  them one call can collect many completions.

What it does not do: for a loop reading one or a few sockets with a
non-blocking read a turn, the kernel entry per turn stays (to collect
completions) unless a second thread does the polling. Measure against the
plain loop before adopting it, and count the complexity: buffer
lifetimes, cancellation, and error paths all change.

## Kernel bypass

- **AF_XDP** delivers raw frames from a NIC queue to a user-space ring;
  the driver may support zero-copy.
- **DPDK** takes the device away from the kernel and polls it from user
  space.
- **Vendor stacks** on specific NICs offer sockets implemented in user
  space.

All of them hand the application raw packets or a different stack. A TCP
venue then needs a TCP implementation in the process (retransmission,
congestion control, reassembly), and a TLS venue needs TLS above it. The
kernel's stack and its diagnostics no longer see the flow.

## Deciding

1. What is socket wait today, at the median and the tail? If it is small
   against the network path, stop.
2. Is the remaining time interrupt delivery and cross-core hand-off? Busy
   polling (design B) removes those inside the kernel's stack.
3. Is it the per-read kernel entry? Only then does a bypass or `SQPOLL`
   address it, at the price of a core or a stack.
4. Is the peer on the same host or LAN, where the path is short enough
   for host microseconds to matter, or across the internet, where it is
   not?
5. Does the instance and driver support it? Check the driver's own
   documentation for the kernel in use; in a cloud guest the answer
   differs by instance type.

A change of I/O model is a decision for the user, proposed with the
measurement that motivates it and the operational cost it adds.
