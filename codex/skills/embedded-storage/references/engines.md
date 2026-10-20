# Engine knobs, commands and references

Companion to `SKILL.md`. Facts marked [F] were read from the libmdbx README or
the RocksDB wiki on 2026-10-20; the rest is working knowledge to confirm against
the version pinned in the repo (`Cargo.lock`, vendored `mdbx-sys`).

## libmdbx

| Topic | Fact |
|---|---|
| Long readers [F] | A long-lived read transaction blocks recycling of freed pages; the file grows under parallel writes. Keep read txns short, or use the Handle-Slow-Readers callback or transaction parking. |
| Page size [F] | Power of two, 256 to 65536, default 4096. |
| Keys and dupsort values [F] | Limited to about half a page; `DUPFIXED` for fixed-size duplicates. |
| Sync modes [F] | `MDBX_DURABLE` default; `MDBX_NOMETASYNC`; `MDBX_SAFE_NOSYNC` (lazy, call `mdbx_env_sync` or set a sync period or bytes threshold); `MDBX_UTTERLY_NOSYNC` (corruption possible). `MDBX_WRITEMAP` usually with `NOMETASYNC`. macOS: `MDBX_OSX_SPEED_INSTEADOF_DURABILITY=1` trades safety for speed. |
| Environment caveats [F] | No fork after open; no NFS; containers share PID namespace and libc. |
| Geometry | Lower bound, upper bound, growth step, shrink threshold, page size. `MDBX_MAP_FULL`: upper bound hit or pages pinned. `MDBX_UNABLE_EXTEND_MAPSIZE` when the map cannot grow in place. Documented in `mdbx.h`. |
| Readahead | `MDBX_NORDAHEAD` for random access over a working set larger than RAM. |
| How reth uses it | `crates/storage/db` (tables, `Table` trait, key `Encode`/`Decode`, value `Compress`/`Decompress`, dupsort tables), `crates/storage/libmdbx-rs` (binding; `mdbx-sys/libmdbx` vendored). History and changesets are separate tables from plain state. |
| How erigon uses it | `erigon-lib/kv/mdbx`: geometry, `SafeNoSync` with periodic sync, page-size choice, notes on long read transactions. |

Commands: `mdbx_stat -ef <db>` (environment and freelist), `mdbx_stat -r <db>`
(reader table), `mdbx_chk -v <db>`, `mdbx_dump`, `mdbx_load`, `mdbx_copy -c`
(compacting copy), `mdbx_drop`.

## RocksDB

| Topic | Fact |
|---|---|
| Tuning stance [F] | Do not tune an SSD setup without a measured problem. |
| Memtables [F] | `write_buffer_size`, `max_write_buffer_number`, `min_write_buffer_number_to_merge`; writes stall when memtables exceed the max. |
| L0 triggers [F] | `level0_file_num_compaction_trigger`, `level0_slowdown_writes_trigger`, `level0_stop_writes_trigger`; wiki examples 20/40 for prefix DBs, 17/24 for total-order. |
| Leveled sizing [F] | `max_bytes_for_level_base` about the size of L0; multiplier 10; `target_file_size_base` = base / 10; `compaction_pri = kMinOverlappingRatio`. |
| Universal [F] | Write-heavy; can double temporary space; care above about 100 GB per column family; `max_size_amplification_percent` default 200. |
| Block cache [F] | LRU or `HyperClockCache`, about a third of memory to start, shared across CFs and instances; raise shard bits under mutex contention. Holds uncompressed blocks; the OS cache holds compressed ones. |
| Table options [F] | `block_size = 16KB`, `cache_index_and_filter_blocks = true`, `pin_l0_filter_and_index_blocks_in_cache = true`, latest `format_version`, `optimize_filters_for_memory = true`. |
| Filters [F] | Bloom 10 bits per key (about 1 % false positives) only if point `Get` dominates; no help for range scans; Ribbon trades CPU for about 30 % less memory; partitioned filters for large files. |
| Compression [F] | LZ4 on levels 0 to n-2, ZSTD bottommost; none on L0/L1. |
| Deletes [F] | `CompactOnDeletionCollectorFactory`, TTL, `periodic_compaction_seconds`. |
| Files [F] | `max_open_files = -1` keeps all table files open, within the descriptor limit. |
| Background | `max_background_jobs`, `max_subcompactions`; `NewGenericRateLimiter`; `bytes_per_sync`, `wal_bytes_per_sync`. |
| WAL | `WriteOptions.sync`; `disableWAL`; group commits through `WriteBatch`. |
| Direct I/O | `use_direct_reads`, `use_direct_io_for_flush_and_compaction`; then the block cache is the only cache. |
| Prefix seek | `prefix_extractor` plus prefix Bloom; `prefix_same_as_start` or `total_order_seek = false` on the iterator. |
| Stats | `GetProperty("rocksdb.stats")`, the `LOG` "Compaction Stats" dump, `STALL_MICROS`, PerfContext and IOStatsContext. |

Commands: `db_bench --benchmarks=fillrandom,readrandom,readwhilewriting,overwrite --num=50000000 --threads=16 --statistics --histogram --stats_interval_seconds=10`;
`ldb`, `sst_dump`, `rocksdb_dump`.

## LevelDB

Single compaction thread, no column families, basic Bloom only, one memtable
flush pipeline, no rate limiter. Implementation notes in `doc/impl.md`;
limitations in the README. Not a target for new work.

## System tools

`iostat -x 1`, `vmstat 1`, `perf stat -e major-faults,minor-faults`,
`perf record -g`, `pidstat -d`, `blktrace` or bcc `biolatency`,
`fio --rw=randread --bs=4k --iodepth=32 --ioengine=io_uring`,
`/proc/<pid>/smaps_rollup`, `strace -c -e trace=fsync,fdatasync,msync,pwrite64 -p <pid>`,
`diskchecker.pl` for power-loss tests; `cargo flamegraph`, `samply record`,
`heaptrack` or `dhat` for allocations.

## Amplification

Write amplification = bytes written to disk / bytes written by the
application (SMART counters or `iostat`). Leveled LSM write amplification runs
about 10 to 30 or more; a B-tree rewrites a whole page per small change; MDBX
copy-on-write amplifies by tree height. Report all three amplifications per
configuration.

## Primary references

- libmdbx README and API docs: https://github.com/erthink/libmdbx and `mdbx.h` in the same repo (errors and options).
- LMDB docs and caveats: http://www.lmdb.tech/doc/
- reth storage: https://github.com/paradigmxyz/reth/tree/main/crates/storage/db and `.../libmdbx-rs`.
- erigon mdbx usage: https://github.com/ledgerwatch/erigon (`erigon-lib/kv/mdbx`).
- RocksDB wiki (https://github.com/facebook/rocksdb/wiki/): RocksDB-Tuning-Guide, Setup-Options-and-Basic-Tuning, Memory-usage-in-RocksDB, Block-Cache, Write-Stalls, Compaction, RocksDB-Bloom-Filter, Prefix-Seek, Write-Ahead-Log-(WAL), Rate-Limiter, Direct-IO, RocksDB-FAQ, Benchmarking-tools, Performance-Benchmarks.
- LevelDB: https://github.com/google/leveldb/blob/main/doc/impl.md
- Pebble (Go LSM with design docs): https://github.com/cockroachdb/pebble
- redb benchmarks against LMDB, RocksDB and sled: https://github.com/cberner/redb#benchmarks
- "Are You Sure You Want to Use MMAP in Your DBMS?" (Crotty et al., CIDR 2022): https://db.cs.cmu.edu/papers/2022/cidr2022-p13-crotty.pdf
- The RUM conjecture: https://stratos.seas.harvard.edu/publications/rum-conjecture-read-update-memory-trade-offs
