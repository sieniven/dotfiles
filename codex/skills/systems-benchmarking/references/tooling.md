# Benchmark tooling and references

Companion to `SKILL.md`. Flags are the commonly used ones; confirm against the
installed version's `--help`.

## criterion (the desk's default, 0.8 with `cargo_bench_support` only)

- `cargo bench --bench <name> -- <regex filter>`; through the runner the
  filter is the positional argument.
- Baselines: `-- --save-baseline main` then `-- --baseline main`. Comparison
  lines are dropped by the runner's stdout filter; read
  `target/criterion/<group>/<id>/change/estimates.json`.
- `--warm-up-time 3 --measurement-time 10 --sample-size 100` on the command
  line, or `Criterion::default().warm_up_time(..).measurement_time(..).sample_size(..)` in `config()`.
- `iter_batched(|| setup(), |x| work(x), BatchSize::SmallInput)` keeps setup
  out of the timing; `Throughput::Elements(n)` or `Bytes(n)` on the group.
- Reports under `target/criterion`; `harness = false` on the `[[bench]]`.

## divan

`#[divan::bench]` functions and `divan::main()`; `Bencher::with_inputs` for
per-iteration state; `counter` for throughput; `#[divan::bench(args = [...])]`
for parameter sweeps; `--sample-count` on the CLI.

## Gungraun (formerly iai-callgrind)

Instruction counts, L1/LL hits, RAM accesses and estimated cycles under
Valgrind: stable on shared CI where wall-clock is noise. Needs the matching
`gungraun-runner` (the crate was renamed from iai-callgrind in 2025 and the
old runner is stale); not available on every macOS or arm64 host. Run
through `cargo bench` in a worktree or with the scratch target dir.

## hyperfine (CLI and process-level)

`hyperfine --warmup 3 --runs 30 --export-json out.json 'cmd a' 'cmd b'`;
`--prepare 'sync; echo 3 | sudo tee /proc/sys/vm/drop_caches'` for cold-cache
runs; `-N` for very short commands.

## HdrHistogram (`hdrhistogram` crate)

`Histogram::<u64>::new_with_bounds(1, 60_000_000_000, 3)`; `record(v)`;
`record_correct(v, expected_interval)` for coordinated-omission correction;
`value_at_quantile(0.999)`; `add(&other)` to merge; the `serialize` module and
interval logs for later analysis.

## Profilers and counters

`cargo flamegraph --bench <name> -- --bench`; `samply record <cmd>` (works on
macOS); `perf record -F 999 -g --call-graph dwarf -- <cmd>` then `perf report`;
`perf stat -e cycles,instructions,cache-misses,branch-misses,context-switches,cpu-migrations`;
`perf c2c` for false sharing; `perf sched` and bcc `runqlat` for scheduling
delay. Profile in a separate run from the one reported.

## System control

`taskset -c 2,3 <cmd>`, `chrt -f 80 <cmd>`, `numactl --cpunodebind=0 --membind=0`,
`cpupower frequency-set -g performance`, `turbostat`, `lscpu`, `mlc` (memory
latency), `cyclictest` and `hwlat` for the host's jitter floor. Kernel
parameters `isolcpus`, `nohz_full`, `rcu_nocbs`.

## Other harnesses and generators

Google Benchmark (`--benchmark_repetitions=10 --benchmark_report_aggregates_only=true`,
`benchmark::DoNotOptimize`, `compare.py` with a U-test); JMH (forks, warmup
iterations, `Blackhole`; its samples show every pitfall); `wrk2` and `vegeta`
for constant-rate, coordinated-omission-aware load.


## Primary references

- criterion (0.8, repository moved to the criterion-rs organisation): https://github.com/criterion-rs/criterion.rs with the user guide linked from its README
- divan: https://github.com/nvzqz/divan ; Gungraun (formerly iai-callgrind): https://github.com/gungraun/gungraun ; hyperfine: https://github.com/sharkdp/hyperfine
- HdrHistogram: https://github.com/HdrHistogram/HdrHistogram_rust and https://github.com/HdrHistogram/HdrHistogram ; wrk2: https://github.com/giltene/wrk2
- Gil Tene, "How NOT to Measure Latency": https://www.youtube.com/watch?v=lJ8ydIuPFeU
- Brendan Gregg, USE method and perf examples: https://www.brendangregg.com/usemethod.html , https://www.brendangregg.com/perf.html
- Gernot Heiser, "Systems Benchmarking Crimes": https://gernot-heiser.org/benchmarking-crimes.html
- Aeron performance testing: https://github.com/real-logic/aeron/wiki/Performance-Testing ; LMAX Disruptor perftests: https://github.com/LMAX-Exchange/disruptor
- Martin Thompson, Mechanical Sympathy: https://mechanical-sympathy.blogspot.com/
- Google Benchmark user guide: https://github.com/google/benchmark/blob/main/docs/user_guide.md ; JMH samples: https://github.com/openjdk/jmh
- Kernel docs: `admin-guide/kernel-parameters` (isolcpus, nohz_full, rcu_nocbs), `networking/timestamping` (SO_TIMESTAMPING).
