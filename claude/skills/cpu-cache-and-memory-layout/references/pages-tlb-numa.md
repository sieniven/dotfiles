# Pages, the TLB and NUMA

Companion to `SKILL.md`. The layer under the caches: how virtual memory
turns into latency, and what a process does about it before its hot loop
starts.

## Faults

- Memory from the allocator or `mmap` is a promise. The first write to
  each page takes a fault: the kernel finds a page, zeroes it and maps it,
  about a microsecond when memory is free and much more when it must
  reclaim or compact first.
- Other faults on memory already touched: copy-on-write after a `fork`, a
  page the kernel swapped or reclaimed, a file-backed page written again
  after the kernel cleaned it.
- A fault is synchronous noise: no isolation setting removes it. It is
  removed by not faulting.

Before the loop starts:

1. Allocate everything the loop will use, at its final size.
2. `mlockall(MCL_CURRENT | MCL_FUTURE)`: nothing is swapped or reclaimed,
   and without `MCL_ONFAULT` current mappings are faulted in by the call.
3. Write every page of every buffer, ring and arena that was allocated
   after the lock or might not be populated; reading is not enough for
   anonymous memory. `MAP_POPULATE` does it at `mmap` time.
4. Touch each pinned thread's stack to the depth it will use, from that
   thread.
5. Never free or shrink afterwards: an allocator that returns memory to
   the kernel unmaps it, which shoots down the TLB on every core running
   the process and faults on reuse.

Locked memory needs `RLIMIT_MEMLOCK` (or `CAP_IPC_LOCK`) to cover the
process. Check `VmLck` in `/proc/PID/status` against `VmRSS`.

## The TLB

- Each core caches translations. A first-level data TLB holds on the
  order of a hundred entries, a second level one to two thousand: a few
  megabytes of 4 KiB pages. Past that a load pays a page walk, several
  dependent memory accesses that are themselves cache hits or misses.
- A working set spread thinly over many pages misses the TLB even when
  its lines would fit in L2. Keep hot data contiguous.
- 2 MiB pages multiply the reach by 512; 1 GiB pages again.
- Changing a mapping (unmap, protect, the kernel migrating or collapsing
  pages) interrupts every other core that runs the process to flush its
  TLB. That interrupt is the `TLB` row in `/proc/interrupts`.

## Huge pages

Two mechanisms:

- **Transparent huge pages.** `/sys/kernel/mm/transparent_hugepage/enabled`
  is `always`, `madvise` or `never`; `defrag` chooses how hard an
  allocation tries (`always`, `defer`, `defer+madvise`, `madvise`,
  `never`). Kernels from 6.8 add per-size controls under
  `hugepages-<size>kB/`. The `khugepaged` daemon scans and collapses
  small pages into huge ones later.
  - With `always`, any large anonymous region may get huge pages, and may
    stall in direct compaction to get them, on whichever thread faults.
  - With `madvise`, only regions the program marks (`MADV_HUGEPAGE`) do.
    Mark the hot arenas at start-up, fault them in, and the daemon has
    nothing left to do to them.
  - A collapse or a split under a running thread costs it a fault and
    every core a TLB flush.
- **Explicit huge pages (hugetlbfs).** Reserved at boot or by sysctl,
  never swapped, never split, mapped with `MAP_HUGETLB` or from a
  hugetlbfs mount. Predictable, and a fixed reservation the host must be
  sized for.

For a pinned process the choice that surprises least is `madvise` for the
host, the hot arenas marked and pre-faulted, and nothing changing after
start-up. Whether huge pages pay at all is a measurement: `dTLB` misses
before and after, and the latency they explain.

`AnonHugePages` in `/proc/PID/smaps` shows what a mapping actually got.

## NUMA

- On a host with more than one memory node, a page is allocated on the
  node of the CPU that first touches it. A buffer allocated and zeroed by
  the main thread lives on the main thread's node, wherever the thread
  that uses it is pinned.
- So: pin first, then allocate and touch from the pinned thread, or bind
  the allocation explicitly.
- Automatic NUMA balancing (`kernel.numa_balancing`) samples access by
  unmapping pages so that touches fault, and migrates pages toward their
  users. For a pinned process whose memory is already placed it is pure
  noise: faults and TLB flushes. Turn it off for the host or exclude the
  process.
- A remote-node access costs more than a local one and competes for the
  interconnect. The NIC has a node too
  (`/sys/class/net/<dev>/device/numa_node`); the thread that reads it
  belongs there.
- `numactl -H` shows nodes and distances; `/proc/PID/numa_maps` shows
  where each mapping's pages are; `numastat -p PID` summarises.
- Single-node hosts and most small cloud instances have one node and none
  of this applies. Check before designing for it.

## The allocator

- The hot path does not allocate (`~/.claude/rules/rust.md`). What
  remains is what the allocator does in the background of a process that
  allocated at start-up.
- General-purpose allocators may return freed memory to the kernel on a
  timer or from a background thread, and that thread inherits the mask of
  whoever started it. Configure it not to, or start it before pinning.
- Arenas per thread avoid lock contention and can leave a thread's memory
  on its node; they also multiply reserved memory.
- Freeing on a different thread from the one that allocated moves
  ownership of the block's lines between cores. Return buffers to their
  owner through a ring instead.

## Other background memory work

Kernel same-page merging, compaction and reclaim all walk or move pages.
On a host sized so that memory is never short, with merging off and huge
pages decided explicitly, none of them has anything to do to a locked
process.

## Reading it back

```sh
grep -E 'VmRSS|VmLck|VmHWM' /proc/$PID/status
grep -E 'AnonHugePages|Locked' /proc/$PID/smaps | sort | uniq -c | sort -rn | head
cat /sys/kernel/mm/transparent_hugepage/{enabled,defrag}
perf stat -e page-faults,minor-faults,major-faults,dTLB-load-misses -p $PID -- sleep 10
numactl -H; numastat -p $PID
```

Faults during steady state should be zero. Any other number is a finding
with a location: `perf record -e page-faults -g -p $PID`, in a run that is
not the one being reported.

## Sources

`mlock(2)`, `mmap(2)`, `madvise(2)`;
`Documentation/admin-guide/mm/transhuge.rst`,
`Documentation/admin-guide/mm/hugetlbpage.rst`,
`Documentation/admin-guide/sysctl/kernel.rst` (`numa_balancing`),
`Documentation/timers/no_hz.rst` (page faults and TLB shootdowns as
remaining jitter) in the kernel tree.
