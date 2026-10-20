# Kafka, lake and vendor facts

Facts marked [V] were read from librdkafka's `CONFIGURATION.md`, the
tardis-node README and the dbn README on 2026-10-20; the rest is working
knowledge to confirm against the pinned library version.

## librdkafka defaults [V]

| Key | Default | Note |
|---|---|---|
| `enable.idempotence` | false | turning it on sets `acks=all` and bounds `max.in.flight` to 5 |
| `acks` | -1 (all) | |
| `linger.ms` | 5 | alias `queue.buffering.max.ms`; 5 to 20 ms for throughput |
| `batch.size` / `batch.num.messages` | 1000000 / 10000 | |
| `compression.codec` | none | gzip, snappy, lz4, zstd |
| `message.max.bytes` | 1000000 | producer side; topic `max.message.bytes` and consumer `fetch.message.max.bytes` (1048576) must agree |
| `message.timeout.ms` | 300000 | alias `delivery.timeout.ms`; expired messages are dropped with a delivery-report error |
| `partitioner` | `consistent_random` | not the Java client's murmur2; use `murmur2_random` when clients are mixed |
| `partition.assignment.strategy` | `range,roundrobin` | `cooperative-sticky` available (not with `group.protocol=consumer`) |
| `enable.auto.commit` / `enable.auto.offset.store` | true / true | set both false for commit-after-durable-write |
| `isolation.level` | read_committed | |
| `statistics.interval.ms` | 0 (off) | client-side metrics |
| `max.in.flight` | 1000000 | alias `max.in.flight.requests.per.connection` |
| `transactional.id` | unset | transactional producer, Kafka-to-Kafka only |

Broker and topic keys: `min.insync.replicas`, `retention.ms`, `retention.bytes`,
`cleanup.policy=compact`, `message.timestamp.type` (CreateTime or
LogAppendTime), `max.message.bytes`, `unclean.leader.election.enable`.

## Clients

- Rust `rdkafka`: `ClientConfig::set(key, value)` with the librdkafka keys;
  `FutureProducer` and `StreamConsumer` need a tokio runtime; `BaseProducer`
  needs `poll()`; features `cmake-build`, `zstd`, `libz-static`.
- Python `confluent-kafka` (what `infra-pgd-kafka` uses): same keys in a
  dict; `Producer.poll()` or `flush()` to receive delivery callbacks;
  `Consumer.commit(asynchronous=False)` for explicit commits;
  `SerializingProducer` for the schema registry.
- `aiokafka`: asyncio, different option names (`max_batch_size`, `linger_ms`,
  `enable_idempotence`), lower throughput; not for hot ingestion.
- Lag: `kafka_exporter` (Prometheus) or Burrow.

## Parquet and query engines

- pyarrow: `pyarrow.parquet.write_table(table, path, compression="zstd", row_group_size=..., use_dictionary=..., write_statistics=True)`;
  `pyarrow.dataset.dataset(path, format="parquet", partitioning="hive")` with a filter expression.
- polars: `write_parquet(compression="zstd", row_group_size=..., statistics=True)`;
  `pl.scan_parquet(path, hive_partitioning=True)`; `join_asof(strategy="backward", by=...)`.
- duckdb: `COPY ... TO ... (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE ..., PARTITION_BY (venue, date))`;
  `read_parquet(..., hive_partitioning=true, union_by_name=true)`; set `memory_limit` and `temp_directory`.
- Quality tooling: pandera (polars and pyarrow), Great Expectations, dbt tests, or plain polars assertions in the pipeline.

## Vendors

- Tardis: channels `incremental_book_L2`, `book_snapshot_25`, `book_snapshot_5`,
  `trades`, `quotes`, `derivative_ticker`, `liquidations`; CSV `timestamp`
  (exchange) and `local_timestamp` (Tardis collector receive). tardis-node
  replays from `https://api.tardis.dev/v1` with `from`/`to` and a local
  per-slice cache [V]; tardis-machine is the local replay server. The
  platform's feeds over these files are listed in
  `quant-trading-backtesting/references/platform-backtester.md`.
- Databento: schemas `mbo`, `mbp-1`, `mbp-10`, `tbbo`, `trades`, `ohlcv-*`,
  `definition`, `statistics`; `ts_event` (matching engine) and `ts_recv`
  (Databento capture); prices int64 at a 1e-9 scale with `UNDEF_PRICE` as the
  sentinel. DBN is a self-describing, zstd-compressible binary format with
  Rust crates `dbn` and `dbn-cli` and Python `databento-dbn` [V].

## Primary references

- Kafka: https://kafka.apache.org/documentation/ ; https://docs.confluent.io/kafka/design/ ; schema compatibility https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html
- librdkafka configuration [V]: https://github.com/confluentinc/librdkafka/blob/master/CONFIGURATION.md ; https://docs.rs/rdkafka/latest/rdkafka/ ; https://docs.confluent.io/kafka-clients/python/current/overview.html ; https://aiokafka.readthedocs.io/
- Lag: https://github.com/danielqsj/kafka_exporter ; https://github.com/linkedin/Burrow
- Parquet: https://parquet.apache.org/docs/ ; https://arrow.apache.org/docs/python/parquet.html ; https://arrow.apache.org/docs/python/dataset.html ; https://docs.pola.rs/user-guide/io/parquet/ ; https://duckdb.org/docs/data/parquet/overview ; https://duckdb.org/docs/data/partitioning/hive_partitioning
- Table formats: https://delta.io/ ; https://iceberg.apache.org/docs/latest/
- Vendors: https://docs.tardis.dev/ ; https://github.com/tardis-dev/tardis-node [V] ; https://databento.com/docs/ ; https://github.com/databento/dbn [V]
- Quality: https://pandera.readthedocs.io/ ; https://docs.greatexpectations.io/
