# Profiling a hot path

Companion to `SKILL.md` and the `hot-path-optimizer` agent. Measure first
(the skill's reporting contract), then profile in a separate run, then change
one thing, then measure again against the same baseline.

## Order of attack

1. **Where the time goes**: a sampling profile of the benchmark or a replay
   at production rate. `samply record <cmd>` (macOS and Linux, opens a Firefox
   Profiler view), `cargo flamegraph --bench <name> -- --bench <filter>`,
   `perf record -F 999 -g --call-graph dwarf -- <cmd>` then `perf report`.
   Build with symbols (`[profile.bench] debug = true`, or `debug = 1` on the
   release profile for the run) and the production optimisation flags, or the
   profile describes a different binary.
2. **What kind of time**: `perf stat -e cycles,instructions,cache-misses,branch-misses,context-switches,cpu-migrations,page-faults`.
   Low IPC with high cache misses is a memory problem; high branch misses is
   a data-dependent-control-flow problem; context switches and migrations on
   a pinned thread mean the environment, not the code.
3. **Allocation**: `dhat` (`dhat-rs` feature) or `heaptrack` on Linux; count
   allocations per message, not bytes. One allocation per market-data event
   at a million events a second is the whole budget.
4. **Contention**: `perf c2c` for false sharing; `perf sched` or bcc `runqlat`
   for scheduling delay; `perf lock` where available. A lock that is never
   contended still costs an atomic; a lock held across an `await` costs the
   runtime.
5. **Syscalls and I/O**: `strace -c -f` or `perf trace` to count them; any
   syscall on the hot path is a finding (logging, time reads through the vDSO
   excepted, allocation that grows the heap).
6. **Instruction level** only when the above is clean: `perf annotate`,
   `cargo asm` or `--emit=asm` on the function, Gungraun (formerly iai-callgrind) for an
   instruction-count baseline that is stable in CI.

## Changes that usually pay, in order of safety

- Remove allocation: preallocated buffers, `ArrayVec` or `SmallVec` for
  bounded collections, borrowed decoding, `Cow` only where a copy is rare.
- Remove indirection: monomorphise a `dyn` call on the hot path, inline small
  functions that the compiler did not (`#[inline]` with a measured reason).
- Fix layout: group fields touched together, pad or align to cache lines
  (`#[repr(align(64))]`) between writer and reader fields, struct-of-arrays
  for scans, fixed-width keys for lookups.
- Batch: amortise a lock, a syscall or a channel send across a burst; a
  bounded batch with a stated maximum latency cost.
- Replace the data structure: a range-indexed vector over a map for a book
  window, a ring buffer over a `VecDeque` with growth, a perfect-hash or
  index over a string-keyed map.
- Branch shaping: hoist the rare case out, order comparisons by likelihood,
  `likely`-style hints only with a measured gain.
- SIMD and unsafe last, each with a `// SAFETY:` comment and a benchmark that
  covers the boundary cases.

## Rules

- One change per measurement. Two changes in one run cannot be attributed.
- The baseline is the same commit, host and runner, from the same session;
  interleave old and new runs.
- A gain inside the noise floor is "no measurable change" and is reverted
  unless it is also simpler.
- Never trade a correctness property (ordering, determinism, bounded memory,
  a risk check) for speed without naming the trade in the report and getting
  it accepted.
- The optimised path keeps its tests, and gains a test for any boundary the
  change introduced (buffer full, batch cut, alignment).
- Record the before and after in the repo's benchmarks doc with host and
  commit.
