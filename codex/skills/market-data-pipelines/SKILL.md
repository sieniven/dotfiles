---
name: market-data-pipelines
description: Building the data platform that captures, stores and serves tick, order-book, trade, funding and reference data for research and backtesting. Kafka topic, key and producer or consumer discipline for feed capture, the parquet lake layout (nanosecond timestamps, integer prices with scales, row groups, Hive partitions, manifests, versions), order-book storage as snapshots plus deltas with deterministic rebuild, point-in-time reference data, data-quality checks and quarantine, idempotent resumable backfills from Tardis and Databento, and serving research through lazy scans with a pinned dataset version. Use when writing or reviewing ingestion, lake layout, backfill, quality or serving code in the data platform or a research repo's data layer.
---

# Market-data pipelines

Practice for the capture-to-research path. The researcher's rules for using
the data (two clocks, look-ahead, labels after latency) are in
`quant-trading-research` under Data hygiene and are not repeated; the
platform's current feeds and layout are in
`quant-trading-backtesting/references/platform-backtester.md`. Config keys,
library facts and URLs are in `references/kafka-and-lake.md`.

## Where the platform stands

- `system-pgd-data` holds the market-data pipeline (`marketdata/pipeline`:
  Tardis bulk fetch, ingest, quality, reindex, sync, S3 upload) on the
  `pgd-marketdata` package (pyarrow, boto3), plus reference data and the
  governed schemas. `infra-pgd-kafka` runs a single-node KRaft Kafka with the
  `pgd.trading.orders` topic (12 partitions, 30-day retention) fed by the
  trading adapters, and the read-only `kq` query tool on `confluent-kafka`.
  `engine-backtesting` documents the shared `data/` layout its drivers read.
- Read the repo's `AGENTS.md`, conventions and migration protocol first;
  `system-pgd-data` governs schema changes through paired migrations and a
  reviewer, and its design principles (mechanism over persuasion, rollback
  before automation, budget by blast radius) bind data work too.

## Three clocks, two of them kept

- Every record carries the exchange event time and the capture receive time
  as separate nanosecond UTC fields; the Kafka timestamp is a third clock and
  never replaces them. The receive timestamp is taken before the producer and
  never overwritten downstream.
- Capture hosts run chrony or PTP; the offset is recorded per host and
  alerted above a threshold, because a skewed receive clock turns into
  look-ahead in every backtest built on it.

## Kafka for capture

- One topic per feed type, keyed by venue and instrument so one instrument's
  updates stay on one partition and in order. Partition count and partitioner
  never change on a live topic; a new topic migrates. The partitioner is set
  explicitly and identically across Rust, Python and Java producers.
- Raw capture producers: `acks=all`, idempotence on, replication three with
  two in sync, unclean leader election off, compression set (the default is
  none), a deliberate delivery timeout with delivery reports checked, and
  message-size limits that agree across producer, topic and consumer or a
  large snapshot fails at the weakest one.
- Consumers: cooperative-sticky assignment, static membership, auto-commit
  off, offsets committed only after the sink write is durable (file closed
  and published, manifest written). Lake files are named from topic,
  partition and offset range so a replay overwrites instead of duplicating.
- Reference data on a compacted topic keyed by instrument id; raw feeds on
  time-based retention because the lake, not Kafka, is the system of record.
- Schemas in a registry with backward compatibility: optional fields only,
  field numbers and names never reused. A fixed envelope (receive timestamp,
  sequence, source, capture host, feed version) in the payload.
- Lag measured in time, not offsets, with stalled partitions alerted.

## Lake layout

- Timestamps as `INT64 TIMESTAMP(NANOS, UTC)`, never INT96; prices and sizes
  as integer mantissas with a per-instrument scale from reference data, or a
  decimal column; never floats. Venue-native semantics preserved, with units
  stated in reference data.
- Files of 128 MB to 1 GB, row groups near 128 MB uncompressed, sorted within
  a file by instrument, event time and sequence so statistics prune; zstd;
  dictionary encoding on low-cardinality columns; statistics written for the
  columns queries filter on.
- Hive partitions on low-cardinality columns (`venue=`, `date=`), never by
  symbol when that yields thousands of tiny files; compaction for small
  files. Schema evolution adds nullable columns and bumps a schema version;
  types never change in place.
- Object storage has no atomic rename: write to a temporary key, then publish
  through a manifest; lifecycle rules move raw data to cold tiers.
- A table format (Delta, Iceberg) is a request to be justified by a need for
  ACID commits or time travel; plain parquet with a manifest covers
  append-only immutable days.

## Order books

- Store raw L2 increments plus periodic full snapshots as replay checkpoints;
  replay starts from the nearest snapshot before the requested time and
  rebuilds deterministically by the venue's sequence rules. A gap marks the
  book invalid until the next snapshot; nothing patches through a gap.
- L3 order-by-order data is the only source of exact queue position; keep it
  beside the derived L2 where the venue offers it.
- Vendor clocks are not yours: Tardis `local_timestamp` is the vendor
  collector's receive time, Databento `ts_recv` is theirs; record which
  source a row came from.

## Point-in-time reference data

- Reference data (tick and lot size, multiplier, contract size, funding
  schedule, fee and margin tiers, status, expiry) is SCD2: `valid_from`,
  `valid_to`, `recorded_at`. A query at time t takes rows valid at t and
  recorded by t. Restatements are new versions, never edits.
- Delisted instruments stay in the universe; renames and rollovers map to a
  stable internal instrument id. Funding stores the realized rate with its
  effective time and predictions separately with their own timestamps.

## Quality gates in the pipeline

Every ingest and backfill runs, and records per chunk: sequence and time
gaps against the instrument's normal rate, duplicates on the dedup key,
out-of-order events, crossed or locked books and negative sizes, stale
feeds, clock skew distribution per host and venue, completeness per
instrument per day, volume and trade counts reconciled against exchange
daily totals. Failing rows go to a quarantine table with the reason, never
silently dropped. A closed day is reprocessed only as a new dataset version.

## Backfills and versions

- Idempotent, resumable chunks keyed by venue, instrument and day, with a
  manifest of completed chunks carrying checksum, row count and source
  version; a dry run and a cost or size estimate before any vendor pull.
- Every row carries `source` and `dataset_version`; live and backfilled data
  never mix silently, and overlaps at day and source boundaries are
  deduplicated by key.
- A new version writes to a new path and switches the catalog pointer
  atomically, with lineage (inputs, code commit, parameters).

## Serving research

- A catalog (name, version, schema, coverage, owner) behind a thin Python
  read API; lazy scans with predicate pushdown (polars `scan_parquet` with
  Hive partitioning, pyarrow datasets, duckdb over parquet); columns selected
  early and days streamed so memory stays bounded.
- Derived features cached by dataset version, code hash and parameters; every
  research record pins the dataset version it read.

## Gotchas

1. A receive timestamp overwritten by the Kafka timestamp.
2. One instrument spread over partitions, or two clients with two partitioners.
3. Offsets auto-committed before the file is durable.
4. Message-size limits that disagree across producer, topic and consumer.
5. Delivery timeouts dropping messages nobody checks for.
6. INT96 or microsecond-truncated timestamps; timezone-naive columns.
7. A book patched through a sequence gap.
8. Reference data without `recorded_at`; delisted symbols missing.
9. Duplicates at the live-to-backfill seam.
10. A reprocessed day overwriting the version a research record pinned.
