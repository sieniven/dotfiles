# MySQL 8 and MariaDB (InnoDB) reference

Facts marked [V] were read from the MySQL 8.0 online-DDL operations table on
2026-10-20; the rest is working knowledge to confirm against the exact server
version (`SELECT @@version`).

## Online DDL [V]

| Operation | Algorithm | Notes |
|---|---|---|
| Add column | INSTANT | any position from 8.0.29 (last position only before) |
| Drop column | INSTANT | from 8.0.29 |
| Rename column | INSTANT | from 8.0.28; a column referenced by a foreign key needs INPLACE |
| Set or drop default | INSTANT | |
| Reorder columns | INPLACE | rebuilds |
| Add secondary index | INPLACE, concurrent DML | waits for open transactions on the table (metadata lock); the pending lock then blocks new queries |
| Change column type | COPY | blocks DML; use gh-ost or pt-online-schema-change |
| Add primary key | INPLACE | rebuilds |

Instant changes are not allowed on `ROW_FORMAT=COMPRESSED`, FULLTEXT or
temporary tables; adding an `AUTO_INCREMENT` column blocks DML; a table
carries at most 64 instant row versions until a rebuild
(`ALTER TABLE t ENGINE=InnoDB`) resets the count. Check
`SELECT TOTAL_ROW_VERSIONS FROM information_schema.INNODB_TABLES WHERE NAME='db/t';`.

Always write `ALTER TABLE t ..., ALGORITHM=INSTANT;` or
`ALGORITHM=INPLACE, LOCK=NONE` so an unsupported path fails loudly. Set
`SET SESSION lock_wait_timeout = 10;` in migration sessions (the default is a
year). DDL auto-commits per statement: one DDL per file and a
`schema_migrations` table written after each file.

gh-ost reads the binlog (`binlog_format=ROW`, no triggers; run without
`--execute` for a dry run); pt-online-schema-change uses triggers (extra
write load on the primary; `--dry-run` first). Both need a primary or unique
key and struggle with foreign keys. skeema (`skeema lint`, `skeema diff`,
`skeema push --alter-algorithm=inplace --alter-lock=none`) and Atlas lint
MySQL schemas; squawk and strong_migrations are Postgres-only.

## Types and limits

- `DECIMAL(M,D)`, M up to 65 and D up to 30. `DECIMAL(65,30)` works but
  leaves 35 integer digits and costs storage and CPU; `DECIMAL(38,18)` or a
  per-field scale is usually enough. PyMySQL round-trips `Decimal` exactly
  when passed as a parameter.
- `DATETIME(6)` in UTC with `time_zone='+00:00'` per connection; `DATETIME`
  without `(6)` truncates microseconds; `TIMESTAMP` converts by session zone
  and ends in 2038.
- Index key limit 3072 bytes with `DYNAMIC` rows; utf8mb4 `VARCHAR(255)` is
  1020 bytes. Short `VARCHAR(n)`, an `ascii` charset for venue and symbol
  codes, or a prefix index. Mixed collations across joined tables raise
  error 1267 and prevent index use.
- `sql_mode`: `STRICT_TRANS_TABLES`, `NO_ZERO_DATE`, `NO_ZERO_IN_DATE`,
  `ERROR_FOR_DIVISION_BY_ZERO`, `NO_ENGINE_SUBSTITUTION`; verify
  `@@sql_mode` per connection because a pooled connection may come from a
  server with a different default.
- Partitioning: `PARTITION BY RANGE COLUMNS(ts)`; every unique key includes
  the partition column; no foreign keys on partitioned InnoDB tables.

## Locking and retries

- `REPEATABLE READ` takes next-key (gap) locks on range predicates: range
  `SELECT ... FOR UPDATE`, `UPDATE` or `DELETE` block inserts and deadlock.
  Lock by unique key, narrow the range, or run `READ COMMITTED` with
  `binlog_format=ROW`.
- `INSERT ... ON DUPLICATE KEY UPDATE` locks the conflicting index entry;
  with several unique keys, concurrent statements deadlock and the update can
  hit an unexpected row. One unique key on the idempotency path.
- Error classes: `1213` deadlock (retry the transaction), `1205` lock wait
  timeout (`innodb_lock_wait_timeout` default 50 s, set 5 to 10 s; only the
  statement rolls back by default, so roll back explicitly), `2006` server
  has gone away and `2013` lost connection (reconnect; retry only if
  idempotent), `1927`/`1053` shutdown or kill.
- Deadlock forensics: `SHOW ENGINE INNODB STATUS\G` (latest only) or
  `innodb_print_all_deadlocks=ON`; waits in `sys.innodb_lock_waits` and
  `performance_schema.data_locks` / `data_lock_waits` (8.0).
- `GET_LOCK` is session-level and unsafe behind ProxySQL multiplexing.
  `SKIP LOCKED` and `NOWAIT` exist from MySQL 8.0 and MariaDB 10.6.

## Idempotent ingestion

- `INSERT ... ON DUPLICATE KEY UPDATE id=id`: row count 1 inserted, 2
  updated, 0 unchanged. `INSERT IGNORE` returns 0 on a duplicate but also
  turns truncation, out-of-range and `NOT NULL` errors into warnings.
- `innodb_autoinc_lock_mode` 1 or 2 (default 2 in 8.0) consumes an
  auto-increment value on a duplicate: `BIGINT UNSIGNED`, and never a
  gap-free assumption. `INSERT ... SELECT ... WHERE NOT EXISTS` avoids the
  burn but is not atomic without the unique key. `REPLACE INTO` deletes and
  re-inserts (new id, delete triggers, broken foreign keys): never on a ledger.
- `binlog_format=ROW`, which gh-ost, Debezium and `READ COMMITTED` also need.

## Operations

- `innodb_buffer_pool_size` 50 to 75 % of RAM on a dedicated host (online
  resize in chunks); `innodb_buffer_pool_instances` 8 or more for large
  pools; hit rate from `SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%'`.
- Durability pair for a ledger: `innodb_flush_log_at_trx_commit=1` and
  `sync_binlog=1`, `innodb_doublewrite=ON`. Anything lower can lose committed
  rows or diverge replicas after a crash.
- `max_connections` default 151 (confirm on the server with `SELECT @@max_connections`); one thread per connection with per-thread
  buffers (`sort_buffer_size`, `join_buffer_size`, `read_buffer_size`);
  ProxySQL in front of many clients. Guards: driver `connect_timeout`,
  `read_timeout`, `write_timeout`; server `max_execution_time` (MySQL, SELECT
  only, ms) or MariaDB `max_statement_time` (s).
- Slow queries: `slow_query_log=ON`, `long_query_time=0.2`;
  `sys.statements_with_runtimes_in_95th_percentile`, `sys.statement_analysis`,
  `sys.schema_unused_indexes`, `sys.schema_redundant_indexes`;
  `pt-query-digest slow.log`.
- `EXPLAIN ANALYZE` executes (8.0.18+, tree format); `EXPLAIN FORMAT=TREE`
  does not; `EXPLAIN FORMAT=JSON` shows `used_key_parts`. Read `type` (`ALL`
  is a full scan), `key`, `rows`, `Extra` (`Using filesort`, `Using
  temporary`, `Using index` means covering). MariaDB uses `ANALYZE <stmt>`.
- Replication: `gtid_mode=ON`, `enforce_gtid_consistency=ON`,
  `binlog_format=ROW`, semi-sync to bound loss. `SHOW REPLICA STATUS\G`
  (`SHOW SLAVE STATUS` before 8.0.22): `Replica_IO_Running`,
  `Replica_SQL_Running`, `Last_SQL_Error`; `Seconds_Behind_Source` is
  unreliable on idle or multi-threaded replicas (pt-heartbeat for a real
  number). Read-your-writes: `SELECT WAIT_FOR_EXECUTED_GTID_SET('<gtid>', t)`.
  MariaDB GTIDs (`domain-server-seq`) are not MySQL GTIDs.
- Backups: `mysqldump --single-transaction --routines --triggers --events`
  (consistent InnoDB snapshot, no locks, but logical, slow to restore, and
  not protected against concurrent DDL); Percona XtraBackup
  (`xtrabackup --backup --target-dir=...`, `--prepare`, `--copy-back`),
  `mysqlbackup`, `mariabackup` for large sets. PITR: restore the full backup,
  then `mysqlbinlog --start-position=... --stop-datetime='...' binlog.0000NN | mysql`.
  `binlog_expire_logs_seconds` at least the backup interval; drill restores.
- Monitoring: `prometheus/mysqld_exporter` (PROCESS, REPLICATION CLIENT,
  SELECT on performance_schema); alert on `Threads_connected` against
  `max_connections`, `Aborted_connects`, `Innodb_row_lock_waits`, lag,
  `Slow_queries`.

## MariaDB divergences

`ANALYZE` / `ANALYZE FORMAT=JSON` instead of `EXPLAIN ANALYZE`; instant DDL
rules differ by version (check the MariaDB InnoDB online-DDL page);
`ADD COLUMN IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` exist; JSON is a
`LONGTEXT` alias (no `->`, no multi-valued index; generated column plus index
to query inside); collation names differ (no `utf8mb4_0900_*`);
`max_statement_time`; system-versioned tables (`WITH SYSTEM VERSIONING`) for
audit history; built-in thread pool; Galera; older lock views
(`information_schema.INNODB_LOCKS`, `INNODB_LOCK_WAITS`).

## Commands

```
mysql --defaults-extra-file=~/.my.cnf -e "SELECT @@version, @@sql_mode, @@transaction_isolation, @@time_zone, @@innodb_flush_log_at_trx_commit, @@sync_binlog"
mysql db < migrations/0007_add_fill_idx.up.sql        # inside a set -e wrapper, one DDL per file
SHOW CREATE TABLE fills\G
SHOW INDEX FROM fills;
SHOW FULL PROCESSLIST;                                 # "Waiting for table metadata lock"
SHOW ENGINE INNODB STATUS\G
SELECT * FROM sys.innodb_lock_waits\G
EXPLAIN ANALYZE SELECT ...;                            # MySQL 8.0.18+
SHOW REPLICA STATUS\G
gh-ost --host=... --database=db --table=fills --alter="ADD COLUMN x BIGINT NULL" --assume-rbr --execute   # omit --execute for a dry run
pt-online-schema-change --alter "ADD COLUMN x BIGINT NULL" D=db,t=fills --dry-run                         # then --execute
mysqldump --single-transaction --routines --triggers --events db > db.sql
```
Confirm gh-ost and pt-osc flag names with `--help` for the installed version.

## References

MySQL 8.0 reference manual (https://dev.mysql.com/doc/refman/8.0/en/):
innodb-online-ddl-operations [V], innodb-online-ddl, innodb-index-types,
innodb-limits, fixed-point-types, precision-math-decimal-characteristics,
datetime, innodb-locking, innodb-deadlocks, insert-on-duplicate,
innodb-auto-increment-handling, sql-mode, using-explain, explain, sys-schema,
replication-gtids, point-in-time-recovery, gone-away.
https://github.com/github/gh-ost ; https://docs.percona.com/percona-toolkit/pt-online-schema-change.html ;
https://github.com/skeema/skeema ; https://docs.percona.com/percona-xtrabackup/ ;
https://proxysql.com/documentation/ ; https://github.com/prometheus/mysqld_exporter ;
https://mariadb.com/kb/en/instant-add-column-for-innodb/ ; https://mariadb.com/kb/en/analyze-statement/
