# Measuring cache and memory behaviour

Companion to `SKILL.md` and to `systems-benchmarking`'s profiling
reference. Which counter answers which question, and what a result means.
Event names vary by CPU and kernel: `perf list` shows what the host has,
and a guest often exposes few or none.

## The topology first

```sh
lscpu -C
lscpu -e                       # cpu, core, socket, node, cache ids per logical CPU
grep . /sys/devices/system/cpu/cpu*/cache/index3/shared_cpu_list | sort -u -t: -k2
numactl -H
```

`shared_cpu_list` at index 3 groups the CPUs that share a last-level
cache. `coherency_line_size` is the line size. `lstopo` draws the same.

## Counters: what kind of time

```sh
perf stat -e cycles,instructions,branches,branch-misses \
          -e cache-references,cache-misses \
          -e L1-dcache-loads,L1-dcache-load-misses,LLC-loads,LLC-load-misses \
          -e dTLB-loads,dTLB-load-misses,iTLB-load-misses \
          -e page-faults,context-switches,cpu-migrations -- <cmd>
```

| Reading | Suggests |
| --- | --- |
| instructions per cycle well under 1 with high cache misses | waiting on memory: layout, working-set size, pointer chasing |
| high `L1-dcache-load-misses`, low `LLC-load-misses` | the working set is past L1 but inside L2 or L3: tighten the hot fields |
| high `LLC-load-misses` | data comes from memory or from another core: size, or sharing |
| high `dTLB-load-misses` | the working set is spread over too many pages: contiguity, huge pages |
| high `iTLB-load-misses` or front-end stalls | hot code too large or scattered |
| high `branch-misses` | data-dependent control flow |
| misses that rise only when another thread runs | sharing: go to `perf c2c` |
| `page-faults` above zero in steady state | memory not pre-faulted, or changing under the process |

Divide by messages processed. A miss count means nothing without the rate
per message, and one last-level miss per message at a million messages a
second is most of a core.

Count on the pinned thread (`-t TID`) or its core (`-C N`), in a run of
its own. `perf stat` counting is light; sampling is not.

## Which lines: perf c2c and perf mem

```sh
perf c2c record -t $TID -- sleep 10      # or: perf c2c record -- <cmd>
perf c2c report --stdio
perf mem record -- <cmd> && perf mem report --sort=mem,symbol
```

- `perf c2c report` lists cache lines by HITM count, local and remote,
  and under each line the offsets accessed, the threads and CPUs, and the
  source locations. Two writers at different offsets of one line is false
  sharing; one offset is true sharing.
- `perf mem` attributes sampled loads to the level that served them (L1,
  L2, L3, memory, another core's cache) and to the data symbol.
- Both need precise memory sampling from the CPU. See `false-sharing.md`
  for where it exists.

## Instruction-level counts

Simulated counts are deterministic and survive shared CI, at the price of
a model in place of the machine:

- Cachegrind and the Gungraun benches (`systems-benchmarking`) report
  instructions, first-level and last-level misses per function for a
  single-threaded run. Good for "did this change add a miss per message";
  blind to sharing between threads, to the TLB and to prefetchers.
- `perf annotate` on a sampled profile shows which instruction waited;
  the instruction after a load usually carries the blame for it.

## Sizes and layouts in Rust

- `std::mem::size_of`, `align_of` and `offset_of!` in a `const` assertion
  pin a layout so a later edit cannot move it silently. They are also the
  quickest way to learn a type's size: a failing assertion prints both
  numbers.
- An enum's size is its largest variant plus a tag unless a niche absorbs
  it; `Option<Box<T>>` and `Option<NonZeroU64>` are one word.
- `cargo asm` (or `--emit=asm`) shows whether a hot loop loads through an
  extra pointer or was vectorised.
- Type-size listings from the compiler exist behind an unstable flag;
  the stable toolchain's answer is the assertion.

## Benchmarks that can see cache effects

- Inputs larger than the cache level under test, cycled from a recorded
  trace; eight warm records measure L1 hits and the predictor's memory.
- Both threads running and pinned, for anything shared. Name the cores,
  and whether they share an L2 (siblings) or a last-level cache.
- The same-thread figure beside the cross-core one.
- A cold-start figure where the path runs rarely: the first call after
  the working set was evicted, reported separately from steady state.
- One change per measurement, the baseline interleaved, per
  `systems-benchmarking`.

## What a guest hides

Performance counters, memory sampling and the real cache topology are
often absent or synthetic in a virtual machine. A cache claim made from a
guest says so, and names what could not be measured.

## Sources

`tools/perf/Documentation/` in the kernel tree (`perf-stat.txt`,
`perf-c2c.txt`, `perf-mem.txt`, `perf-list.txt`);
`Documentation/ABI/testing/sysfs-devices-system-cpu` (the cache attribute
files); Valgrind's Cachegrind manual.
