# Postgres reference

Facts marked [V] were read from the source on 2026-10-20 (Postgres wiki "Don't
Do This", strong_migrations, squawk, HikariCP pool sizing, pgbouncer features);
the rest is working knowledge to confirm against the pinned server version.

## Anti-patterns [V]

`money`, `timestamp` without time zone, `timetz`, `CURRENT_TIME`, `serial`
(use identity), `char(n)` and `varchar(n)` (use `text` with a `CHECK`),
`NOT IN` (use `NOT EXISTS`), `BETWEEN` on timestamps, table inheritance,
rules, `trust` authentication (use `scram-sha-256`), upper-case identifiers.

## Safe migration moves [V strong_migrations and squawk]

| Change | Safe form |
|---|---|
| Add column | nullable, no default or a non-volatile default (no rewrite since PG11; a stable function such as `now()` also qualifies); a volatile default rewrites |
| `NOT NULL` on existing column | `ADD CONSTRAINT ... CHECK (c IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT`, `SET NOT NULL` (skips the scan when a validated check proves no NULLs, PG12 onward), drop the check |
| Foreign key or check | `ADD CONSTRAINT ... NOT VALID` then `VALIDATE CONSTRAINT` (SHARE UPDATE EXCLUSIVE only) |
| Index | `CREATE INDEX CONCURRENTLY` outside a transaction block; unique = concurrent unique index + `ADD CONSTRAINT ... USING INDEX` |
| Type change, rename, drop | expand and contract: new column, dual write, backfill, switch reads, drop later |
| Any DDL | `SET lock_timeout = '5s'; SET statement_timeout = '...'` first; retry on timeout |

squawk rules worth knowing: `prefer-bigint-over-int`, `prefer-identity`,
`prefer-text-field`, `require-concurrent-index-creation`,
`require-concurrent-index-deletion`, `constraint-missing-not-valid`,
`disallowed-unique-constraint`, `ban-drop-column`, `ban-drop-database`,
`renaming-column`, `adding-field-with-default`.

## Pooler compatibility [V pgbouncer]

Transaction mode does not support `SET`/`RESET`, `LISTEN`, `WITH HOLD`
cursors, SQL-level `PREPARE`/`DEALLOCATE`, session advisory locks, and
`PRESERVE`/`DELETE ROWS` temp tables; protocol-level prepared statements need
`max_prepared_statements > 0` (1.21+). `NOTIFY` works; `LISTEN` needs a
direct or session-mode connection. Use `pg_advisory_xact_lock`.

## Queries

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) <query>;
-- long and idle-in-transaction sessions
SELECT pid, state, now()-xact_start AS xact_age, wait_event_type, wait_event, left(query,120)
FROM pg_stat_activity WHERE state <> 'idle' ORDER BY xact_start;
-- who blocks whom
SELECT pid, pg_blocking_pids(pid) AS blocked_by, left(query,100)
FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;
-- top statements
SELECT calls, round(total_exec_time) AS ms, round(mean_exec_time::numeric,2) AS mean, left(query,100)
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;
-- wraparound
SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY 2 DESC;
-- replication lag, on the primary
SELECT application_name, state, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes, replay_lag
FROM pg_stat_replication;
-- invalid and unused indexes
SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
SELECT relname, indexrelname, idx_scan FROM pg_stat_user_indexes WHERE idx_scan = 0;
-- slots retaining WAL
SELECT slot_name, active, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;
```

## Commands

- Apply a file: `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f file.sql`
  (drop `--single-transaction` for a `CREATE INDEX CONCURRENTLY` file).
- sqlx: `sqlx migrate add -r <name>`, `sqlx migrate run`, `sqlx migrate info`,
  `cargo sqlx prepare` (commit `.sqlx/`, `--check` in CI); `-- no-transaction`
  as the first line of a concurrent-index migration.
- Alembic: `alembic revision -m "..."` (`--autogenerate` output is reviewed,
  not trusted), `alembic upgrade head`, `alembic downgrade -1`,
  `alembic upgrade head --sql`; `with op.get_context().autocommit_block():`
  for `CONCURRENTLY`.
- Others: refinery (`V1__name.sql`), diesel (`metadata.toml` with
  `run_in_transaction = false`), golang-migrate, Flyway, Atlas
  (`atlas migrate lint --dev-url "docker://postgres/16/dev"`), dbmate.
- Lint: `squawk migrations/*.sql` (`--exclude`, `--config .squawk.toml`,
  inline `-- squawk-ignore <rule>`).
- Partitions: `CREATE EXTENSION pg_partman; SELECT partman.create_parent('public.fills','ts','1 day');`
  and a scheduled `CALL partman.run_maintenance_proc();` (syntax varies by major version).
- Local: `docker run --rm -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16`
  matching the production major version.
- Ops: `pg_dump --schema-only`, `pg_basebackup`, `pg_repack -d db -t table`
  (not `VACUUM FULL`), `REINDEX CONCURRENTLY`, `pgbench -c 20 -j 4 -T 60`,
  `pg_isready`; pgbouncer admin `SHOW POOLS; SHOW STATS;`.
- Monitoring: `prometheus-community/postgres_exporter` with a `pg_monitor` role.

## Tuning starting points

`shared_buffers` about 25 % of RAM; `effective_cache_size` 50 to 75 %;
`work_mem` small (it is per sort or hash node per connection);
`maintenance_work_mem` large for index builds; `random_page_cost` about 1.1
on SSD; per-table `autovacuum_vacuum_scale_factor` 0.01 to 0.05 on hot
tables; `idle_in_transaction_session_timeout` about 30 s; `wal_level=logical`
only when logical replication is needed, with `max_slot_wal_keep_size` set.

## References

- https://wiki.postgresql.org/wiki/Don't_Do_This [V]
- https://use-the-index-luke.com/
- Postgres docs: using-explain, indexes-partial, indexes-expressional, brin, ddl-partitioning, datatype-numeric, sql-insert (ON CONFLICT), explicit-locking, sql-select (FOR UPDATE / SKIP LOCKED), ddl-rowsecurity, routine-vacuuming, pgstatstatements, logical-replication, transaction-iso, errcodes-appendix (all under https://www.postgresql.org/docs/current/)
- https://github.com/pgpartman/pg_partman
- https://github.com/ankane/strong_migrations [V] ; https://github.com/sbdchd/squawk and https://squawkhq.com/docs/rules [V]
- https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing [V]
- https://www.pgbouncer.org/features.html and https://www.pgbouncer.org/config.html [V]
- https://github.com/prometheus-community/postgres_exporter
- Ledger design: TigerBeetle docs (https://github.com/tigerbeetle/tigerbeetle/tree/main/docs), Modern Treasury journal on immutable double-entry ledgers, Square's "Books" post.
