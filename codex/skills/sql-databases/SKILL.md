---
name: sql-databases
description: "MySQL/InnoDB and Postgres practice for the desk's backend services \u2014 the ledger, data platform, control plane and monitors. Schema design for money and time, idempotent fill ingestion, append-only ledger journals, indexes derived from real queries, time partitioning, zero-downtime migrations and online DDL, service-side connection pools (SQLAlchemy, asyncpg, asyncmy, sqlx, pgx) that survive failover, transaction isolation and retry classes, and operations (durability settings, replication lag, backups and restore drills, monitoring). Use when writing or reviewing a schema, migration, query, pool configuration or database deployment, in either dialect."
---

# SQL databases

Practice for relational storage behind the desk's services. Where a repo has
its own migration protocol or reviewer (system-pgd-data has both), that repo
wins; this skill fills the gaps and covers repos without one. Dialect detail,
driver defaults and commands live in `references/postgres.md`,
`references/mysql.md` and `references/pooling.md`. Money and async rules for
the service code itself are in `~/.codex/rules/python.md` and
`~/.codex/rules/rust.md`.

## Know the dialect and the version first

- The ledger (`system-pgd-ledger`, `ledger_system`) and the Prometheus
  monitors run on MySQL 8 or MariaDB: InnoDB, utf8mb4, `DATETIME(6)` in UTC,
  `DECIMAL` money, PyMySQL and asyncmy, hand-applied paired `up`/`down` SQL
  files. The strategy-manager control plane (SQLAlchemy async, asyncpg,
  Alembic) and the ai-pgd-agents skill registry (asyncpg, `psql`-applied
  `NNNN_*.sql`) run on Postgres. system-pgd-data governs the ledger and
  market-data schemas with its migration protocol, guard hook and
  `schema-migration-reviewer`.
- Read `SELECT version()` or `@@version` and the repo's manifests before
  writing a line: online-DDL rules, `EXPLAIN ANALYZE`, `SKIP LOCKED` and
  instant column changes all depend on the exact version, and MariaDB
  diverges from MySQL.

## Schema

- Money, price and quantity are exact decimals: Postgres `numeric(p,s)`,
  MySQL `DECIMAL(M,D)` with scale matching the venue's tick and lot. Never
  float, double or the Postgres `money` type. The driver must map to
  `Decimal`, `rust_decimal` or `bigdecimal`; a float anywhere on the path
  undoes the column type. Asset or currency in an adjacent column; `CHECK`
  constraints for sign and bounds.
- Time: Postgres `timestamptz`; MySQL `DATETIME(6)` stored in UTC with
  `time_zone='+00:00'` set on every connection (MySQL `TIMESTAMP` converts by
  session zone and ends in 2038). Keep venue event time, receive time and
  insert time as separate columns. Ranges are `>= start AND < end`.
- Surrogate keys: Postgres `bigint GENERATED ALWAYS AS IDENTITY`; MySQL
  `BIGINT UNSIGNED AUTO_INCREMENT`, declared in `CREATE TABLE` because InnoDB
  clusters rows by the primary key and copies it into every secondary index.
  No random UUIDv4 keys; a time-ordered UUIDv7 as `uuid` or `BINARY(16)` when
  the application must mint ids.
- The idempotency key is a real `UNIQUE` constraint, such as
  `(venue, account_id, order_id, fill_id)`, with narrow columns (MySQL caps an
  index key at 3072 bytes; utf8mb4 `VARCHAR(255)` is 1020 of them).
- `NOT NULL` by default; justify each nullable column. Foreign keys on
  ledger tables (not on MySQL partitioned tables, which forbid them). Text
  as `text` with a `CHECK` on Postgres; explicit utf8mb4 collation on MySQL,
  never the 3-byte `utf8`; a lookup table over a native enum.
- Journals are append-only: revoke `UPDATE`, `DELETE` and `TRUNCATE` from the
  application role and add a `BEFORE UPDATE OR DELETE` trigger that raises.
  Corrections are compensating rows. Every row carries its source, insert
  time and a request or batch id.
- MySQL `sql_mode` strict (`STRICT_TRANS_TABLES`, `NO_ZERO_DATE`,
  `ERROR_FOR_DIVISION_BY_ZERO`) on the server and per session; without it an
  overflowing `DECIMAL` clamps and a long string truncates silently.

## Ledger design

- Double entry: accounts, a transaction header, and entries with signed
  amounts per asset whose sum is zero per transaction. Enforce it with a
  deferred constraint trigger or by posting through one function.
- The journal is the truth; balances and positions are snapshots stamped with
  the sequence they were taken at, rebuilt by replaying past it, and checked
  by a reconciliation job.
- A database sequence or auto-increment has gaps and commits out of order;
  a reader that tails by id can miss rows. Allocate the ledger sequence
  explicitly (single writer, or a counter row locked `FOR UPDATE`) and never
  treat the surrogate id as a sequence number.
- Exactly-once fills: Postgres `INSERT ... ON CONFLICT (...) DO NOTHING
  RETURNING id` (empty means duplicate); MySQL `INSERT ... ON DUPLICATE KEY
  UPDATE id=id` and read the row count. Not `INSERT IGNORE`, which downgrades
  every error to a warning, and not `REPLACE INTO`, which deletes and
  re-inserts. Both dialects burn auto-increment values on duplicates: use
  unsigned 64-bit ids.
- Amends and cancels are event rows; the current order state is a projection.

## Indexes

- Derive the index set from the actual queries; equality columns first, then
  the range or sort column; the index serves its leading prefix only.
- A function on an indexed column, or a leading wildcard, defeats the index:
  expression index, trigram index or a rewritten predicate.
- Covering indexes (`INCLUDE` on Postgres, the composite itself on InnoDB)
  for the hot reads; partial indexes for hot subsets; BRIN for large
  append-only time series whose physical order follows time.
- Index every foreign key's referencing side. Cap composites at about three
  columns, drop unused indexes, and remember every index is write
  amplification on the fills firehose.
- Prove the plan with `EXPLAIN (ANALYZE, BUFFERS)` or MySQL `EXPLAIN ANALYZE`
  on production-sized data; a tiny table always seq-scans.

## Partitioning and time series

- Range-partition fills, ticks and audit tables by time. Every primary and
  unique key must include the partition column, so the idempotency key
  includes it from day one.
- Retention is detach-and-drop (Postgres `DETACH PARTITION ... CONCURRENTLY`,
  MySQL `DROP PARTITION`), never a mass `DELETE`. Pre-create partitions
  (pg_partman) and keep the count in the hundreds.
- TimescaleDB when market-data volume is high and queries are time-bucketed
  rollups (not on RDS); ClickHouse as the analytics sibling for tick history,
  backtest analytics and TCA, fed by export or CDC, never the system of record
  for balances.

## Migrations

- One concern per migration file, paired `up` and `down`, never edited once
  applied. The `down` restores structure; data comes back from a backup, and
  a lossy `down` says so in its header. Follow the repo's numbering, guard
  comments and blast-radius labels where it has them.
- Expand, backfill, contract: add the nullable column or the new table, dual
  write, backfill in batches outside the DDL transaction, then constrain or
  drop. Deploy code that ignores a column before dropping it.
- Postgres: `SET lock_timeout` and `statement_timeout` at the top; `CREATE
  INDEX CONCURRENTLY` outside a transaction block (clean up `INVALID`
  leftovers); `NOT VALID` then `VALIDATE` for constraints; `SET NOT NULL` via
  a validated check; no volatile defaults or type changes that rewrite the
  table. Lint with squawk.
- MySQL: state `ALGORITHM` and `LOCK` on every `ALTER` so a blocking path
  fails instead of being chosen silently; add column and drop column are
  instant on 8.0.29+, a secondary index is `INPLACE` but waits on open
  transactions (metadata lock), a type or primary-key change rebuilds the
  table and goes through gh-ost or pt-online-schema-change with a dry run
  first. `SET SESSION lock_wait_timeout` short. DDL is not transactional, so
  a half-applied file does not roll back.
- Apply to a scratch database (docker, matching major version) at a
  production-like row count and read the lock behaviour before handing a
  migration to a human. Agents never run DDL or DML against production.

## Connection pools

- Small pools: start near `cores * 2` on the database host and measure; more
  connections past saturation add contention. The sum over all service
  instances stays under `max_connections` minus a reserve for admin,
  replication and migrations.
- Every pool sets all five: acquire timeout, max lifetime (with jitter, so
  failover and DNS changes are survived), idle timeout, a health check on
  checkout, and per-session settings (`statement_timeout`, `lock_timeout`,
  `idle_in_transaction_session_timeout`; MySQL `time_zone`, `sql_mode`,
  isolation level). Defaults are wrong in every driver for at least one of
  these; the table is in `references/pooling.md`.
- PyMySQL has no pool: SQLAlchemy `QueuePool` with `pool_pre_ping` and
  `pool_recycle` below the server's `wait_timeout`, or asyncmy's pool. Treat
  MySQL 2006 and 2013 as a dead connection: discard, reconnect, retry once
  only when the work is idempotent.
- Transaction-mode poolers (pgbouncer, ProxySQL multiplexing) break session
  state: `SET`, session advisory locks, `LISTEN`, `GET_LOCK`, SQL-level
  `PREPARE`, temp tables, driver statement caches. Use `SET LOCAL`,
  transaction-scoped locks, and match the driver cache setting to the pooler.
- A dropped transaction rolls back; commit explicitly. Never hold a database
  transaction across a venue or network call.

## Transactions and retries

- Default isolation (Postgres `READ COMMITTED`, MySQL `REPEATABLE READ`) and
  know what it buys. MySQL range locks under `REPEATABLE READ` (`FOR UPDATE`
  or `UPDATE` on a range) take gap locks that block inserts and deadlock:
  lock by unique key, or use `READ COMMITTED` with `binlog_format=ROW`.
- Lock rows in one order; keep transactions short; set
  `innodb_lock_wait_timeout` to seconds, not the 50-second default.
- Retry only the whole transaction, only when idempotent, with bounded
  backoff and jitter: Postgres `40001`, `40P01`, `57P01`, `08xxx`; MySQL
  `1213`, `1205` (roll back explicitly first), `2006`, `2013`. After an
  unknown commit outcome, re-read by idempotency key instead of retrying.
- Work queues: `SELECT ... FOR UPDATE SKIP LOCKED` (Postgres; MySQL 8.0+,
  MariaDB 10.6+) with an attempt counter and a dead-letter state.

## Operations

- Durability for a ledger: Postgres `fsync` and `synchronous_commit` on;
  MySQL `innodb_flush_log_at_trx_commit=1` with `sync_binlog=1`. Lower
  settings lose committed rows or diverge replicas; say so when proposed.
- Memory: Postgres `shared_buffers` about a quarter of RAM and
  `effective_cache_size` half to three quarters; MySQL
  `innodb_buffer_pool_size` half to three quarters on a dedicated host.
- Postgres needs vacuum to keep up (bloat, visibility map, wraparound age);
  long transactions, idle-in-transaction sessions and stale replication slots
  hold it back. MySQL needs its slow log and `sys` schema views read.
- Replication lag is measured in bytes and seconds, and read-your-writes
  goes to the primary or waits for the replay position (`WAIT_FOR_EXECUTED_GTID_SET`
  on MySQL). `Seconds_Behind_Source` lies on idle replicas.
- A backup that has never been restored is not a backup: continuous WAL or
  binlog archiving plus base backups, a restore drill with its measured RTO
  and RPO, and binlog retention at least as long as the backup interval.
- Monitoring through `postgres_exporter` or `mysqld_exporter`: connection
  saturation, lock waits, long transactions, replication lag, wraparound
  age, invalid indexes, slow queries.

## Gotchas

1. A float on the money path, including the driver mapping.
2. An idempotency key that is not a `UNIQUE`, or omits the partition column.
3. DDL without a lock timeout behind one long transaction becomes an outage.
4. `CREATE INDEX CONCURRENTLY` inside a transaction; `INVALID` leftovers.
5. MySQL `INSERT IGNORE` hiding truncation and `NOT NULL` errors.
6. Gap locks under `REPEATABLE READ` on a fills table.
7. `timestamp` without zone; MySQL `TIMESTAMP`; `DATETIME` without `(6)`.
8. Treating a surrogate id as a gap-free, commit-ordered sequence.
9. A pool with no acquire timeout, lifetime or health check after failover.
10. A transaction-mode pooler and session state or driver statement caches.
11. Retrying a non-idempotent transaction after an ambiguous commit.
12. Plans proven on tiny dev tables; replicas read right after a write.
