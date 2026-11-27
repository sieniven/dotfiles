# The Linux calls behind a pinned thread, from Rust

Companion to `SKILL.md`. Semantics that bite, and the rules for the
`unsafe` that reaches them. Confirm a flag or an error code against the
man page of the target system before relying on it.

## Affinity

- `sched_setaffinity(pid, len, mask)`: `pid` 0 is the calling thread, not
  the process. A thread id sets one thread; the process id sets the main
  thread only.
- `sched_getaffinity(getpid(), ..)` reads the main thread's mask, which is
  the process's permitted set as long as nothing pins the main thread.
  Read it once, before any thread is pinned, and keep it.
- A child created by `fork` or by `pthread_create` inherits the creator's
  mask; a mask is preserved across `execve`. That is what lets a launcher
  set the mask and `exec`, and what puts a pinned thread's children on its
  core.
- `EINVAL` when the mask holds no CPU the caller may run on (offline, or
  outside its cpuset). A cpuset silently narrows a wider mask, so success
  is not proof: read the mask back and compare.
- `CPU_SET` indexes a fixed bitmap of `CPU_SETSIZE` (1024) bits. Check the
  index against it before the macro; an id past it is not a core.
- `sched_getcpu()` says where the caller is running now; the last-CPU
  field of `/proc/PID/task/TID/stat` says where another thread last ran.
- A core id is the kernel's logical CPU number. Sibling and cache
  relations come from sysfs topology, never from arithmetic on ids.

## Timer slack

- `prctl(PR_SET_TIMERSLACK, ns)` sets the calling thread's current slack;
  0 restores its default. New threads copy the creator's current value, so
  one call on the main thread before any spawn covers the process.
- `/proc/TID/timerslack_ns` reads or sets one task; under `/proc/PID` it is
  the main thread alone, and threads already running keep their own value.
  A service started with systemd's `TimerSlackNSec=` has it in every
  thread.
- Not applied to threads under a real-time policy.

## Scheduling policy

- `sched_setscheduler` with `SCHED_FIFO` needs `CAP_SYS_NICE` or an
  `RLIMIT_RTPRIO` allowance (systemd: `LimitRTPRIO=`).
- Through v6.11, real-time tasks are throttled to
  `kernel.sched_rt_runtime_us` out of `kernel.sched_rt_period_us` (950 000
  of 1 000 000 µs by default): a spinning real-time thread is stopped for
  50 ms of every second.
- From v6.12, unless the kernel is built with `CONFIG_RT_GROUP_SCHED`, a
  fair server instead gives runnable normal tasks, the core's kernel
  workers included, up to 50 ms a second. A real-time spinner is preempted
  whenever such work is queued, and not otherwise.
- Either way the per-CPU kernel threads of that core wait behind the
  spinner, for up to a second, to do what they were queued to do.

## Memory

- `mlockall(MCL_CURRENT | MCL_FUTURE)` locks what is mapped and what will
  be; without `MCL_ONFAULT` it also faults the current mappings in. Needs
  `CAP_IPC_LOCK` or an `RLIMIT_MEMLOCK` that covers the process (systemd:
  `LimitMEMLOCK=`).
- With `MCL_FUTURE` and without `MCL_ONFAULT`, memory mapped later is
  faulted in as it is mapped: an `mmap`, heap growth, and the whole stack
  of every thread spawned afterwards, which is resident memory per thread.
  Under `MCL_ONFAULT`, or without locking, pre-fault buffers, rings and
  each thread's stack by writing them once.
- Details and huge pages: `cpu-cache-and-memory-layout`, the pages
  reference.

## Names

A thread's kernel name (`comm`) holds 15 bytes. Rust's
`thread::Builder::name` truncates a longer name and glibc's
`pthread_setname_np` refuses it, so tools that find a thread by name (a
host check that looks for `engine`) depend on names that fit and stay
distinct in their first 15 bytes. Name every thread: an unnamed one keeps
its creator's name, so a helper the `engine` thread starts unnamed reads
`engine` too.

## Signals

- A process-directed signal is delivered to any one thread that does not
  block it. Block the asynchronous ones (`SIGTERM`, `SIGINT`, `SIGHUP`,
  `SIGUSR*`) in every pinned thread with `pthread_sigmask`, inherited from
  a main thread that blocks them before spawning, and receive them on one
  cold thread.
- Synchronous faults (`SIGSEGV`, `SIGBUS`, `SIGILL`, `SIGFPE`) arrive on
  the faulting thread and cannot be routed away.
- A handler may only call async-signal-safe functions: `write`, not
  `println!`; no allocation, no lock. Fill any message beforehand.
- A blocking call returns `EINTR` when a handler ran. A loop that never
  blocks never sees it; a cold thread retries.

## Unsafe rules for these calls

- One module owns each family of calls behind a safe API (affinity, the
  shared mapping, the signal handler, socket options). No other module
  names `libc`.
- Every block carries `// SAFETY:` naming the invariant: the length passed
  is the buffer's, the index is below the set size, the pointer outlives
  the call.
- Return values are checked and turned into `io::Error::last_os_error()`
  at once; `errno` is thread-local and the next call overwrites it.
- A call that only exists on Linux sits behind `cfg(target_os = "linux")`
  with a sibling that refuses loudly elsewhere. A pin that cannot be made
  is an error, never a silent no-op.
- Miri cannot execute these calls. Their tests run on a Linux host with
  the cores they need and skip, visibly, on one without; a skip is not a
  pass in a report.
- Zeroed C structs (`cpu_set_t`, `sigset_t`, `msghdr`) are initialised
  with `mem::zeroed` only where all-zero is a valid value, and the comment
  says so.

## Sources

`sched_setaffinity(2)`, `sched_setscheduler(2)`, `sched(7)`, `prctl(2)`,
`mlock(2)`, `pthread_setname_np(3)`, `signal(7)`, `signal-safety(7)`;
`Documentation/scheduler/sched-rt-group.rst`; systemd's `systemd.exec(5)`.
