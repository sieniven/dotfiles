---
name: embedded-storage
description: Embedded key-value storage engines for services and nodes — libmdbx and LMDB (B+tree, copy-on-write, single writer), RocksDB and LevelDB (LSM), redb — and the tradeoffs between them. Workload-first engine choice, key encoding and table layout, transaction and batching discipline, durability and sync modes, page cache versus block cache and the memory budget, compaction, flush and write-stall tuning, long-reader file growth, mmap pitfalls, crash-safety testing and steady-state measurement. Use when designing, implementing, tuning or debugging a persistent store such as a recorder, market-data archive, ledger journal, state database or node storage layer.
---

# Embedded storage engines

Engine-level practice that holds regardless of the service on top. Measurement
method lives in `systems-benchmarking`; Rust conventions in
`~/.claude/rules/rust.md`; reth's trie and state layout in `reth-trie` and the
`blockchain-protocol` agent. The reference file `references/engines.md` holds
the knob tables, the commands and the primary URLs; this file holds the rules.

## Start from the workload, in numbers

Before choosing or tuning anything, write down: read/write ratio; key and
value sizes and their distribution; working set against RAM; point reads
against range scans and their prefixes; writers and readers at once; what may
be lost on a crash (nothing, the last commit, the last second); retention and
deletes. A design without these numbers is a guess, and every later decision
cites them.

## Choosing an engine

| Workload | Engine | Why |
|---|---|---|
| Read-heavy, working set fits RAM, one writer, range scans | libmdbx / LMDB | Zero-copy reads straight from the page cache, no compaction, MVCC readers never block the writer |
| Write-heavy, dataset exceeds RAM, many writers, tolerate compaction | RocksDB | Sequential writes, tunable amplification, column families, filters |
| Pure-Rust, read-mostly, simple, no C dependency | redb | B+tree with MDBX-like semantics; fewer knobs, smaller ecosystem |
| Anything new | not LevelDB | Single compaction thread, no column families, no rate limiter: the reasons RocksDB forked it |

Name the tradeoff you take (the RUM conjecture: you cannot minimise read,
update and memory overhead at once) and report write, read and space
amplification for the configuration you ship.

## Key encoding and layout

- Fixed-width big-endian integers in keys, so byte order equals numeric order
  and range scans and prefix iteration work. Never little-endian, never
  variable-width, never text numbers.
- The access path's prefix comes first: `(instrument, ts)` for per-instrument
  scans, `(ts, instrument)` for time slices. One table per access path when
  both are hot; the write cost of a second table is cheaper than a scan that
  reads everything.
- Keep keys small. Every B-tree level and every LSM filter carries them; MDBX
  caps keys at about half a page.
- Monotonic keys in a B-tree append; random (hash) keys split pages and spoil
  the cache. If the natural key is a hash, index it by a sequence and keep a
  hash-to-sequence table.
- Hot and cold data in different tables or column families, so history and
  changesets do not evict current state. Values larger than about a page go
  to overflow pages (MDBX) or hurt compaction (RocksDB): store blobs out of
  line or chunk them.
- Version the layout: a schema version key, and a migration path, from day one.

## Transactions and batching

- Group writes into one transaction or `WriteBatch`; one put per transaction
  pays a sync each time and is almost always wrong on a hot path.
- Keep write transactions short. MDBX has one writer, so a slow writer blocks
  everyone; RocksDB stalls on memtable and L0 pressure.
- Read-only transactions for reads, and short: a long-lived MDBX read
  transaction pins old pages and the file grows until it closes; a long
  RocksDB snapshot or iterator keeps obsolete files alive.
- A zero-copy read is valid only until its transaction ends. Never hold the
  slice across transactions or threads.
- Bound every iteration and every batch; a caller-controlled range must not
  turn into an unbounded scan.

## Durability

State which loss you accept, then configure for exactly that:

| Setting | Survives process crash | Survives power loss | Cost |
|---|---|---|---|
| MDBX_DURABLE, RocksDB WAL `sync=true` | yes | yes | one fsync per commit |
| MDBX_NOMETASYNC / MDBX_SAFE_NOSYNC, RocksDB `sync=false` | yes | last commits lost, integrity kept | periodic sync |
| MDBX_UTTERLY_NOSYNC, RocksDB `disableWAL` | no guarantee | corruption or loss | none |

- Lazy modes need a periodic `mdbx_env_sync` or a sync period, and a stated
  recovery source for what is lost. Never the unsafe modes for data you
  cannot rebuild.
- `fsync` flushes data and metadata, `fdatasync` skips non-essential
  metadata, and a new file needs an fsync of its directory. Consumer SSDs,
  VMs and macOS without `F_FULLFSYNC` lie about flushes: crash-test with a
  real power loss or an equivalent, not only `kill -9`.
- Durability is a decision to surface to the user when the data is money,
  positions or a ledger.

## Memory and the page cache

- Set an explicit budget: block cache, memtables, index and filter blocks,
  OS page cache, and application caches. RocksDB's block cache (uncompressed)
  plus the OS cache (compressed) double-caches by default; MDBX relies on the
  page cache alone. Without a budget the process is OOM-killed under load.
- Thrashing shows as `vmstat` swap-in, major page faults, a falling cache hit
  rate and p99 reads that jump to disk latency. When the working set exceeds
  RAM, random B-tree access becomes disk-bound and readahead makes it worse:
  disable readahead (MDBX_NORDAHEAD) and prefault or `madvise(WILLNEED)` a
  known hot set at startup.
- A cgroup memory limit counts page cache; an mmap-based engine inside one
  faults heavily. Size the limit for the map's resident set, not the heap.
- mmap is acceptable for a read-mostly copy-on-write engine (MDBX, LMDB) and
  wrong for a general buffer pool: unpredictable eviction, no write ordering,
  I/O stalls as page faults, errors as SIGBUS (Crotty et al., CIDR 2022).
  For explicit I/O use pread/pwrite or O_DIRECT, and io_uring only when I/O
  concurrency is the measured bottleneck.

## libmdbx specifics

- Geometry explicitly: lower and upper bound, growth step, shrink threshold.
  `MDBX_MAP_FULL` means the upper bound was hit, or old pages are pinned by a
  long reader or an oversized write transaction. Check `mdbx_stat -r` for
  readers before raising the bound.
- Page size is a power of two from 256 to 65536 (default 4096): larger pages
  mean bigger keys and fewer levels but more write amplification per update.
- Dupsort tables: values capped at about half a page; `DUPFIXED` for
  fixed-size values; never for large or unbounded duplicate sets.
- Fork after open, NFS and containers that do not share the PID namespace and
  libc are documented hazards.
- On macOS the default `F_FULLFSYNC` is slow; the speed-over-durability
  switch is a durability downgrade and must be stated as one.

## RocksDB specifics

- Diagnose before tuning: compaction stats in `LOG`, `STALL_MICROS`,
  `rocksdb.stats`, PerfContext. Stalls come from the L0 file count, the
  memtable count or pending compaction bytes; read the counters first.
- Write path: `write_buffer_size`, `max_write_buffer_number`,
  `min_write_buffer_number_to_merge`; L0 triggers for compaction, slowdown
  and stop. Leveled: `max_bytes_for_level_base` about the size of L0, level
  multiplier 10, `target_file_size_base` a tenth of the base. Universal for
  write-heavy loads at the cost of temporary space; FIFO for data you drop
  whole by age.
- Background work: `max_background_jobs` and `max_subcompactions`; a rate
  limiter when compaction I/O steals foreground read latency; `bytes_per_sync`
  so the OS does not stall on a dirty-page burst.
- Block cache shared across column families and instances; shard bits up when
  its mutex is contended; `cache_index_and_filter_blocks` with the L0 pins.
- Bloom (10 bits per key) or Ribbon filters only when point `Get` dominates;
  they do not help range scans. A prefix extractor that does not match the
  access pattern, or is changed on an existing database, silently returns
  wrong or missing results.
- Column families share one WAL, so a flush of one can be forced by another's
  log; separate them for different tuning or lifetimes, not for namespacing.
- Compression: LZ4 on the middle levels, ZSTD on the bottom, none on L0/L1.
  Tombstones and `DeleteRange` slow iterators until they compact away; use
  TTL, periodic compaction or the deletion-triggered collector on
  delete-heavy tables.
- `WriteBatch` for atomic multi-key updates; `disableWAL` only with a
  separately recoverable source. Direct I/O means the block cache is the only
  cache: size it.

## Verification

- Unit tests pin the key encoding (round trip, ordering across the full
  range, boundary values) and the schema version.
- Crash tests: kill the process mid-batch and reopen; the store comes back to
  the last committed state and the test asserts which commits survived
  under the chosen sync mode.
- Steady state before numbers: a fresh database hides compaction debt and an
  empty page cache. Fill to the production shape, run to steady state, then
  measure, per `systems-benchmarking`. Report write, read and space
  amplification beside latency.
- Watch the system while measuring: `iostat -x 1`, `vmstat 1`,
  `perf stat -e major-faults`, fsync counts via `strace -c`.

## Gotchas

1. A long-lived MDBX read transaction pins old pages; the file grows until it
   closes. Look for reader leaks before raising geometry.
2. Lazy sync modes buy speed with recent commits; the unsafe modes can corrupt.
3. Random keys in a B-tree destroy locality; hashed keys go behind a sequence.
4. RocksDB write stalls have three causes and three counters; options come
   after reading them.
5. Filters and prefix extractors that do not match the pattern give nothing,
   or give wrong results.
6. Double caching without a budget ends in the OOM killer.
7. A fresh-database benchmark is not a result.
8. fsync lies on consumer hardware, VMs and macOS defaults.
9. Tombstones make scans slow until compaction; deletes are not free.
10. One MDBX writer: batch, and keep the commit path short.
