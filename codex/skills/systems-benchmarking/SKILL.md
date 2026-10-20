---
name: systems-benchmarking
description: Benchmark methodology for low-level and trading systems. What to measure (throughput, latency percentiles, instruction counts) and which regression a benchmark must catch, open-loop load and coordinated omission, HdrHistogram reporting of p50/p99/p99.9/max with sample counts, environment control (pinning, governor, SMT, NUMA, huge pages), run-to-run variance and baselines, microbenchmark pitfalls (black_box, setup outside the loop, dead-code elimination, warmup, timer overhead), criterion, divan, Gungraun (formerly iai-callgrind) and hyperfine, profiling only after measuring, tick-to-trade and wire timestamps. Also the desk's bench shape (criterion estimates with single-call p50/p99 printed beside them, percentile files, a budget in the bench doc) and the named-bench runner this machine requires. Use when writing, running, reading or comparing a benchmark, or when a latency or throughput claim needs evidence.
---

# Systems benchmarking

Measurement practice for engines, codecs, books, storage and strategies. The
domain budgets (hot-path rules, percentiles not means) are in `quant-trading`;
strategy PnL benchmarking (markouts, fill ratio) is in
`quant-trading-backtesting` and is a different thing. Tool commands and the
primary references are in `references/tooling.md`.

## Decide the question first

- State the metric and the decision it drives before writing code: ops per
  second for a throughput ceiling, a latency percentile for a hot path, an
  instruction count for a CI regression gate. A benchmark without a named
  regression to catch is decoration.
- Pick the level: microbenchmark (one function, cache-resident), component
  (a queue, a book, a codec on a recorded trace), end to end (tick to trade
  through the real engine). Each answers a different question; say which.
- Service time is not response time. Response time includes queueing, and
  queueing is what a stall shows up as.

## The desk's bench shape

This is the default template; follow it unless the repo's own benches differ.

- A `[[bench]]` target with `harness = false` and a module doc that states the
  **budget** ("200 ns for one in-window level") and lists the cold paths that
  are reported beside the number but never against it.
- criterion for the batch estimate (`warm_up_time`, `measurement_time`,
  `sample_size` set explicitly in a `config()` function), `black_box` on the
  input and the result, inputs cycled from a committed or recorded trace so the
  branch predictor does not learn one value.
- Beside criterion's estimate, **single-call timings**: each call timed on its
  own with `Instant` (or the engine's `LiveClock`), the samples kept in a
  preallocated `Vec`, and p50 and p99 printed beside criterion's lines. A path
  near the timer's own cost is timed in batches of a stated size (an
  `Instant` pair costs tens of nanoseconds on some hosts).
- End-to-end latency and capacity benches write a **percentile file** of their
  own; the repo's benchmarks doc (`docs/BENCHMARKS.md` where it exists) holds
  the recorded numbers with the host and the commit.
- Recorded, not gated, unless the repo already gates: wall-clock numbers on
  shared machines drift; a gate belongs on instruction counts.

## Running benches on this machine

The machine-local section of the global AGENTS.md forbids `cargo bench` in a
main checkout; the bash guard denies it. Use the named-bench runner instead:

- engine-middleware: `~/.cache/claude-scratch/bin/run-named-benches.sh <criterion filter>`.
  Other repos: `REPO_DIR=$PWD ~/.cache/claude-scratch/bin/run-named-benches-wt.sh <filter>`,
  with `BIN_TAG` set only to keep two gates of one session apart.
- The runner builds every bench target in the workspace with `--no-run`,
  copies each executable to a stable name under `~/.cache/claude-scratch/bin/benches*/`
  and runs it there with `--bench <args>`; criterion flags pass through, so
  `--save-baseline <name>` and `--baseline <name>` work. Its stdout filter
  keeps only `time:` and `thrpt:` lines, so read comparisons from
  `target/criterion/<group>/<id>/change/estimates.json` or the HTML report,
  not from the runner's output.
- In a linked worktree plain `cargo bench` is allowed and uses the worktree's
  own `target/`; a refused binary there is unverified, not failing, and reruns
  through the worktree runner.
- Escape hatch for a repo with no runner wiring:
  `CARGO_TARGET_DIR=~/.cache/claude-scratch/target-<checkout> cargo bench --bench <name> -- <filter>`.
- One gate at a time: no other cargo build while a bench runs, and no profiler
  attached to a run whose numbers you report.

## Microbenchmark rules

- `black_box` on every input and every output; a result that looks too fast
  was optimised away. Check the assembly or the instruction count.
- Setup outside the timed region (`iter_batched`, `with_inputs`); declare
  `Throughput::Elements` or `Bytes` so the report shows a rate.
- Build as production builds: `--release` with the same LTO, codegen-units
  and `target-cpu`; `[profile.bench] debug = true` for symbols.
- Production-shaped inputs: book depth, symbol count, message mix and value
  distribution from a recorded trace. Cache-resident toy data overstates speed.
- Warm caches, TLB and branch predictors; discard warmup; run to steady
  state. For a database, steady state includes compaction debt.
- Measure the timer's own overhead and subtract or batch; `rdtsc` needs an
  invariant TSC and a calibrated conversion.
- Allocation inside the loop is part of the measurement; say whether it is
  meant to be.

## Latency methodology

- Open-loop load: send on a schedule and record latency from the **intended**
  send time. A closed-loop client that waits for each reply hides queueing
  during a stall (coordinated omission) and under-reports the tail by orders
  of magnitude. HdrHistogram's `record_correct` applies the correction.
- Percentiles from a histogram, never the mean alone: p50, p99, p99.9,
  p99.99 and max, with the sample count. p99.9 needs about 100 000 samples,
  p99.99 about a million, and both stay noisy.
- Never average percentiles across runs or threads: merge the histograms.
- Keep the time of each outlier so it can be matched to a page fault, an
  interrupt, a GC or a compaction.

## Environment

- Pin: `taskset -c N` or `isolcpus`, `nohz_full`, `rcu_nocbs`; `irqbalance`
  off with IRQs steered away from the benchmark cores.
- Fix frequency: performance governor, turbo and deep C-states off, SMT
  siblings idle or pinned.
- NUMA: threads, memory and the NIC on one node (`numactl`). Huge pages by
  `madvise` or hugetlbfs; transparent-huge-page compaction off when the tail
  matters.
- Dedicated hosts; no VMs and no laptops for tail latency (thermal
  throttling). Record kernel, CPU model, microcode, governor, compiler and
  commit with every result. A result without its environment is not a result.

## Variance and statistics

- One process run is one sample: layout, ASLR and allocator state vary per
  process. Run at least five to ten separate invocations and report the
  median with a spread (min/max or a confidence interval).
- Baseline from the same machine in the same session; interleave A and B
  runs. Never claim a gain smaller than the run-to-run noise.
- Heiser's benchmarking crimes: selective benchmarks, no variance, toy
  workloads, a weak baseline, ignored warmup, means without spread.

## Trading systems

- Tick-to-trade: last byte of the market-data packet in to first byte of the
  order out. Wire-to-wire is the same span measured at the switch or a tap.
- Timestamp at the NIC (`SO_TIMESTAMPING`, PTP) or a capture card for any
  wire claim; userspace timestamps include kernel and scheduler jitter. Never
  compare timestamps across hosts without synchronised clocks.
- Replay recorded market data at its original rate and at a burst; report
  book updates per second per core and the latency distribution at several
  load levels.
- Ping-pong round trips (half for a one-way estimate) and burst runs at a
  stated message size and rate, the Aeron and Disruptor way.
- The benchmarked path obeys the hot-path rules: no allocation, locks,
  syscalls or logging, or the number measures those instead.

## Reporting contract

A benchmark result names: the metric and level; the commit and the build
profile; the host and its environment; the runner and the exact command;
sample count and number of process runs; p50, p99, p99.9 and max (or the
rate with its spread); the baseline it is compared with and the noise floor;
and what the number does not cover. Raw samples or the percentile file are
kept next to the report. Profile in a separate run from the one you report.

## Gotchas

1. Coordinated omission.
2. Means hide tails; averaged percentiles are not percentiles.
3. The compiler removed the work.
4. Governor, turbo, SMT and migration add 10 to 50 % noise.
5. Warmup and compaction debt.
6. One process run is one sample.
7. Wall-clock on shared CI is noise; gate on instruction counts.
8. Wire timestamps for wire claims.
9. Toy data predicts nothing.
10. A profiler in the measured run perturbs it.
