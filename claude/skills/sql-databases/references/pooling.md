# Service-side connection pools

Defaults recalled on 2026-10-20; confirm against the version pinned in the
repo before relying on one. The rule in every row: set the acquire timeout,
max lifetime, idle timeout, checkout health check and per-session settings
explicitly.

| Stack | Pool | Set explicitly | Default trap |
|---|---|---|---|
| Rust sqlx (Postgres, MySQL) | `PoolOptions` | `max_connections` (10), `min_connections`, `acquire_timeout` (30 s), `idle_timeout` (10 min), `max_lifetime` (30 min), `test_before_acquire` (keep true), `after_connect` for `SET` | `statement_cache_capacity` 100 breaks pgbouncer transaction mode unless `max_prepared_statements` is set; a dropped `Transaction` rolls back, so `commit().await` explicitly |
| Rust deadpool-postgres | `Pool` | `RecyclingMethod::Verified` or `Clean`, `Timeouts { wait, create, recycle }` | `Fast` recycling skips the health check |
| Rust bb8 | `Pool::builder()` | `max_lifetime`, `idle_timeout`, `connection_timeout`, `test_on_check_out` | none of the lifetimes are set by default |
| Rust tokio-postgres | none | bring a pool | a bare client reconnects nothing |
| Python asyncpg | `create_pool` | `min_size`, `max_size`, `max_queries` (50000), `max_inactive_connection_lifetime` (300), `command_timeout`, `server_settings={'statement_timeout': ...}` | `statement_cache_size` 100 must be 0 behind an older pgbouncer in transaction mode |
| Python psycopg 3 | `psycopg_pool.AsyncConnectionPool` | `min_size`, `max_size`, `max_lifetime` (3600), `max_idle` (600), `timeout` (30), `check=AsyncConnectionPool.check_connection` | open explicitly (`open=False`, `await pool.open()`) |
| Python SQLAlchemy (Postgres, MySQL) | `QueuePool` via `create_engine` / `create_async_engine` | `pool_size`, `max_overflow`, `pool_timeout`, `pool_pre_ping=True`, `pool_recycle` (below MySQL `wait_timeout`) | defaults are `pool_recycle=-1` and no pre-ping; asyncpg dialect needs `connect_args={"statement_cache_size": 0}` behind pgbouncer |
| Python PyMySQL | none | SQLAlchemy `QueuePool`, or asyncmy / aiomysql `create_pool(minsize, maxsize, pool_recycle=...)` | PyMySQL has no pool; autocommit is off by default so a forgotten commit holds locks; aiomysql `pool_recycle` defaults to -1 |
| Go pgx | `pgxpool.ParseConfig` | `MaxConns`, `MinConns`, `MaxConnLifetime` (1 h), `MaxConnLifetimeJitter`, `MaxConnIdleTime` (30 min), `HealthCheckPeriod` (1 min) | default statement cache mode needs `QueryExecModeCacheDescribe` or `Exec` behind pgbouncer transaction mode |

## Sizing

- HikariCP's starting point, measured not assumed: connections about
  `cores * 2 + effective spindles` on the database host, hyperthreads not
  counted. Past saturation more connections cost throughput.
- `sum(instances * pool_max) <= max_connections - reserve`, where the reserve
  covers admin, replication, migrations and monitoring. MySQL's default
  `max_connections` is 151 and each connection is a thread with its own
  buffers; Postgres connections cost about 1 to 3 MB each.
- Server-side pooling (pgbouncer, RDS Proxy, ProxySQL) adds to a bounded
  client pool; it does not replace it. Bursts queue in the application.

## Failover and dead connections

- Connect by cluster or proxy hostname; keep max lifetime in minutes with
  jitter; test by failing over a staging instance and watching the pool.
- Postgres stale-connection errors: `57P01`, `08006`, `25006` (read-only).
  MySQL: `2006` server has gone away, `2013` lost connection during query,
  `1927`/`1053`. Discard the connection, acquire a new one, retry once only
  for idempotent work.
- Per-session settings through `after_connect` or `init_command`:
  Postgres `statement_timeout`, `lock_timeout`,
  `idle_in_transaction_session_timeout`; MySQL `time_zone='+00:00'`,
  `sql_mode`, the isolation level.

## Pooler mode compatibility

pgbouncer transaction mode: no `SET`/`RESET` (use `SET LOCAL`), no `LISTEN`,
no `WITH HOLD` cursors, no SQL-level `PREPARE`, no session advisory locks
(use `pg_advisory_xact_lock`), no `PRESERVE`/`DELETE ROWS` temp tables;
protocol-level prepared statements only with `max_prepared_statements > 0`
(1.21+). ProxySQL multiplexing: `SET`, `GET_LOCK`, temp tables,
`LAST_INSERT_ID()` and open transactions pin or break the multiplexed
connection; test with multiplexing on.

## References

- https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing
- https://docs.rs/sqlx/latest/sqlx/pool/struct.PoolOptions.html
- https://magicstack.github.io/asyncpg/current/api/index.html#connection-pools
- https://www.psycopg.org/psycopg3/docs/advanced/pool.html
- https://docs.sqlalchemy.org/en/20/core/pooling.html and https://docs.sqlalchemy.org/en/20/dialects/mysql.html
- https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool
- https://github.com/long2ice/asyncmy ; https://aiomysql.readthedocs.io/
- https://www.pgbouncer.org/features.html ; https://proxysql.com/documentation/
