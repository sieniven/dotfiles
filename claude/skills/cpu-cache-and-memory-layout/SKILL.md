---
name: cpu-cache-and-memory-layout
description: Cache- and memory-aware design for hot paths, with the Rust specifics. The cache hierarchy and what a miss at each level costs, which caches cores and SMT siblings share and how to read the topology, cache lines, true and false sharing between threads and how padding and alignment remove it (CachePadded, repr(align), why 128 bytes on x86-64 and aarch64), what a ring or a published cell costs per hop, data layout (hot and cold split, field order, struct of arrays, index width, dense arrays over pointer chasing), hardware prefetchers and when a software prefetch pays, branch and code layout hints, keeping a rarely taken path warm, the TLB, huge pages, page faults, memory locking and pre-faulting, NUMA first touch, last-level cache contention, and how to measure it (perf stat events, perf c2c, perf mem). Use when designing or reviewing a hot data structure, a ring, a shared cell or a struct layout, when a profile shows cache or TLB misses or a contended line, or when choosing which cores should share a cache.
---

# CPU cache and memory layout

What the hardware does with a program's data, and how to arrange the data
so the hot path stays in the nearest cache and no two threads fight over a
line. Thread placement is `low-latency-threading`; the cores themselves
are `linux-cpu-isolation`; the measurement contract and the profiling
order of attack are `systems-benchmarking`; allocation rules are in
`~/.claude/rules/rust.md`.

Figures below are orders of magnitude for a recent x86-64 server core.
Read the host's own topology and measure before quoting one.

## The hierarchy

| Level | Shared by | Typical size | A load costs about |
| --- | --- | --- | --- |
| L1 data, L1 instruction | one core (both SMT threads) | 32 to 48 KiB each | 1 ns |
| L2 | one core (both SMT threads) | 1 to 2 MiB | 3 to 5 ns |
| L3, the last level | a group of cores: a socket, or a cluster within it | megabytes per core | 10 to 20 ns |
| Memory | the NUMA node | | 60 to 100 ns, more across nodes |
| A line another core holds modified | | | an L3 miss or worse: it is fetched from that core |

- A hot path's working set (code, the structures it touches per message,
  its stack) decides which row it pays. Staying inside L1 and L2 is the
  goal; every structure sized "to be safe" pushes toward the next row.
- SMT siblings share L1 and L2: whatever runs on the sibling evicts the
  pinned thread's data. Cores share the last-level cache: a neighbour
  streaming through memory evicts everyone's.
- On some CPUs the last-level cache is per cluster of cores, not per
  socket. Two threads that exchange records on cores in different
  clusters pay a slower transfer than two in the same one.

Read it, never assume it:

```sh
lscpu -C                                           # caches: level, size, ways, line size, sharing
grep . /sys/devices/system/cpu/cpu2/cache/index*/{level,type,size,shared_cpu_list,coherency_line_size}
```

In a guest the topology is what the hypervisor chose to report.

## Lines, and sharing them

Caches move memory in lines of 64 bytes (128 on some CPUs). A core must
own a line exclusively to write it; every other core's copy is invalidated
and the next reader fetches it back.

- **True sharing**: two threads use the same datum, as a ring's producer
  and consumer use its indices. The transfer is the cost of talking; the
  design goal is one transfer per message, or per batch, and no more.
- **False sharing**: two threads use different data that happen to sit on
  one line. Each write by one costs the other a miss. It appears as a
  thread slowing down when an unrelated thread gets busy, with no lock
  and no shared variable in the source.

Rules for anything two threads touch:

- Each field written by a different thread gets its own line. A field one
  thread writes and another reads gets a line apart from fields the reader
  writes.
- Per-thread or per-CPU slots in an array are padded per slot.
- Read-mostly data shared by many threads is kept away from anything
  written often; a single counter beside a lookup table makes every lookup
  a miss.
- A reference count is a write. Cloning or dropping an `Arc` on the hot
  path writes a line every other holder reads.
- Batch the shared writes: publish an index once per burst, and keep a
  private copy of the other side's index, re-read only when the private
  copy says full or empty.

Detection, the ring patterns and the fixes are in
`references/false-sharing.md`.

## Padding and alignment in Rust

- `crossbeam_utils::CachePadded<T>` aligns and pads `T` to 128 bytes on
  x86-64, aarch64 and powerpc64, and to 64 on most other targets. The 128
  on x86-64 is deliberate: the adjacent-line prefetcher pulls lines in
  pairs, so data 64 bytes apart can still interfere.
- `#[repr(align(64))]` on a type of one's own sets the alignment and
  rounds the size up to it. Choose 64 or 128 knowingly and say which.
- Rust reorders struct fields. Where the order is the point (hot fields
  first, a writer's fields apart from a reader's, a record shared with
  another process), use `#[repr(C)]` and pin the layout with compile-time
  assertions on size, alignment and `offset_of!`.
- An allocation honours its type's alignment; a byte buffer reinterpreted
  as a struct does not unless it was allocated that way.
- Padding is not free: a padded one-byte flag occupies two lines of L1.
  Pad what two threads contend for, nothing else.

## Layout for the thread that owns the data

- **Hot and cold apart.** Fields read on every message together at the
  front; diagnostics, names and rarely used configuration in a separate
  struct or behind a pointer.
- **Dense over linked.** An array indexed by a small integer beats a map
  keyed by a string or a chain of pointers: the address is computed, not
  loaded, so loads do not wait on each other and the prefetcher can help.
  Resolve names to indices once, at the boundary.
- **Small indices and narrow fields.** `u32` or `u16` where the range
  allows doubles what fits in a line. Check enum sizes: an enum is as
  large as its largest variant.
- **Struct of arrays for scans.** A loop that reads one field of many
  records should find those fields adjacent.
- **Fixed capacity.** A structure that never grows never reallocates and
  never moves; its address stays in the TLB and its lines stay warm.
- **One indirection at most** between the entry point and the data. Each
  `Box`, `Vec` of `Vec`, or trait object adds a load that must complete
  before the next can start.

## Prefetching

- Hardware prefetchers follow sequential and constant-stride access
  within a page and fetch the adjacent line. They cannot follow a pointer
  chain or a hash probe.
- So the first tool is making access sequential: sort, batch, walk arrays.
- A software prefetch pays only when the address is known well before the
  data is needed and the load would otherwise miss: the next element of a
  batch of independent lookups, the far end of a window about to be
  walked. Too early or too late it is wasted; too many compete for memory
  bandwidth and evict useful lines.
- In Rust, `core::arch::x86_64::_mm_prefetch` with a locality hint is
  stable; the portable `core::hint::prefetch_*` functions were still
  unstable in late 2026. A prefetch is a hint and never faults.
- A prefetch is added with a benchmark that shows the miss before and the
  gain after, and is removed when the gain is inside the noise.

## Branches and code

- A mispredicted branch costs several nanoseconds, about an L2 load. The
  predictor learns patterns, so benchmark inputs are cycled from a trace
  or the bench measures a branch the predictor has memorised.
- Keep the rare path out of line: `#[cold]` and `#[inline(never)]` on
  error and slow paths; `std::hint::cold_path()` (stable since 1.95)
  inside a branch. `likely` and `unlikely` were unstable in late 2026.
  `std::hint::select_unpredictable` (1.88) asks for a branch-free select
  where the condition is data-dependent.
- Hot code competes for the instruction cache too. Heavy inlining and
  many monomorphised copies can make the hot loop larger than L1i.

## A path that runs rarely

An order path that fires once a second finds its code and data evicted,
its branches forgotten and, if the core idled, the core slow. Pinning to
an isolated core with an idle sibling removes most of the eviction. What
remains is addressed by keeping the path's working set small, or by
exercising the real path on a schedule up to the last step before the
wire. The second is a decision for the user: it needs a structural
guarantee that a warming pass can never send, and it shows up in every
profile.

## Pages

Translation, faults and placement are their own layer under the caches:

- The TLB covers a few megabytes with 4 KiB pages and gigabytes with
  2 MiB pages; a miss is a page walk of several dependent loads.
- A page touched for the first time is a fault, microseconds on the hot
  path. Lock memory and touch every page of every buffer, ring and stack
  before the loop starts.
- Memory lands on the NUMA node of the thread that first touches it. Pin,
  then allocate and touch.
- Transparent huge pages help the TLB and bring a daemon that scans,
  collapses and compacts. Decide per process, not by the host's default.

All of it is in `references/pages-tlb-numa.md`.

## Neighbours on the last-level cache

Isolation gives a thread its core, not its cache. Other tenants of the
same last-level cache, and of memory bandwidth, slow it without appearing
in any scheduler trace. On dedicated hardware with support, the kernel's
`resctrl` interface can allocate cache ways and bandwidth per group of
tasks or CPUs. Without it, the levers are fewer neighbours and a smaller
working set.

## The desk's code

`engine-middleware` at `b2bc835`:

- `pgd_runtime::StateCell` is a `CachePadded<AtomicU8>`: every published
  cell owns its line; a publish is one release store and the hot read one
  relaxed load.
- The metrics store and the lanes pad each shared atomic
  (`Box<[CachePadded<AtomicI64>]>`, padded ring indices). With
  crossbeam-utils 0.8 that is 128 bytes a cell on x86-64.
- The mirror's slot is laid out by cache line: the active word and the
  first copy on one line, the second copy starting a line of its own.
- `assert_pod_layout!`, `assert_abi!` and `assert_enum_abi!` pin a
  record's size, alignment and every field offset at compile time.
- `docs/BENCHMARKS.md` budgets one ring hop between cores at 50 ns and
  reports the same-thread push and pop beside it as a floor, since on one
  core both index lines stay exclusive.

## Measuring

Counters first, then the line, then the instruction:

```sh
perf stat -e cycles,instructions,cache-misses,L1-dcache-load-misses,LLC-load-misses,dTLB-load-misses,branch-misses -- <cmd>
perf c2c record -- <cmd> && perf c2c report        # contended lines, by HITM count
```

Low instructions per cycle with high cache misses is a memory problem;
high branch misses is control flow. Events, `perf c2c` and `perf mem`
output, and instruction-level counting are in `references/measuring.md`.
A profile is a separate run from the one whose latency is reported.

## Gotchas

1. Two atomics written by different threads declared next to each other.
2. A counter array indexed by thread with no padding per slot.
3. A hot struct that grew a `String` or a `Vec` field in the middle.
4. `Arc::clone` in the hot loop.
5. A benchmark on eight cache-resident records presented as the cost per
   message.
6. A prefetch added without a before and after.
7. Padding everything, and falling out of L1.
8. An SMT sibling doing "just logging".
9. Memory allocated before the thread was pinned, on the wrong node.
10. First touch of a buffer on the first order of the day.
