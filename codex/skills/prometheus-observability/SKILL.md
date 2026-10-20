---
name: prometheus-observability
description: Prometheus and Grafana practice for the desk's monitors and services. Metric design (base units, counter versus gauge, explicit histogram buckets, bounded labels, last-event timestamps), recording-rule naming and rate windows, symptom-based alert rules with for durations, runbooks and promtool unit tests, scrape and relabel configuration, exporters that never block a scrape, Grafana dashboards as generated code with stable uids and recording-rule queries, the trading metrics worth standardising (round-trip latency, fill ratio, quote uptime, staleness, risk utilisation, connectivity state), and the house rule that engine-middleware generates its dashboards, rules and promtool scenarios from the metrics registry. Use when adding metrics to a service, writing or reviewing rules, dashboards, exporters or scrape config, or debugging a monitor.
---

# Prometheus observability

Practice for metrics, rules, dashboards and exporters. Commands, the rule
test-file schema, client snippets and the primary references are in
`references/commands.md`.

## House facts

- The `monitor/` repos are Python `prometheus_client` exporters per desk with
  a dependency-free `metric_spec` module as the single source of truth and
  codegen from it; a metric is added in the spec, never ad hoc in the
  exporter. They deploy as systemd units.
- `engine-middleware` keeps metrics in its `pgd-metrics` crate and
  **generates** the committed Grafana dashboards, alert rules and promtool
  scenarios from the registry (`just metrics-codegen`), then diffs them in
  tests. Never hand-edit a generated dashboard or rule there; change the
  registry or the codegen and regenerate. Its `just lint` needs promtool,
  which on this machine lives in `~/.cache/claude-scratch/bin`.
- Rules and dashboards are code: in git, linted, unit-tested, reviewed.

## Metrics

- Names are `namespace_what_unit` in plural base units (`_seconds`, `_bytes`);
  counters end in `_total` after the unit; ratios run 0 to 1 and end in
  `_ratio`; no label name inside the metric name; build metadata on an
  `_info` metric whose value is 1.
- A value that can go down is a gauge; `rate()` is for counters only.
  Counters with a bounded label set are initialised to zero at startup so
  `rate()` sees the first increment.
- Elapsed time is the last-event Unix timestamp (`*_last_update_timestamp_seconds`)
  with `time() - x` in the query; a ticking age gauge goes stale exactly when
  its updater hangs.
- Labels are bounded: venue, strategy, side, order type, status, error class,
  and symbol only from a whitelist. Never order ids, client ids, prices,
  quantities or trace ids. Most metrics need no labels; past about ten label
  combinations a metric needs a reason, past a hundred a different design.
- Latency is a histogram with explicit buckets that cover the range and are
  identical across series (order round trip from 0.5 ms to 5 s in 1-2-5
  steps, extra buckets around the budget); quantiles come from
  `histogram_quantile` over `sum by (le) (rate(_bucket[5m]))` and are never
  averaged. Summaries only where nothing aggregates. Native histograms only
  once the server flag and the client support are confirmed.
- Hot paths record through pre-registered handles: no label strings built per
  event, no blocking in the recording call.
- Python multiprocess mode (forked workers) has its own rules: the
  multiprocess directory wiped at start, a fresh registry with the
  multiprocess collector per scrape, dead workers marked on exit, and no
  custom collectors, `Info`, `Enum` or exemplars.

## Recording rules

- Named `level:metric:operations`, with `without (...)` naming the labels
  aggregated away. A ratio sums numerator and denominator separately and
  divides once; ratios and averages are never averaged.
- `rate()` windows span at least four scrape intervals; `irate()` never feeds
  an alert; `increase()` extrapolates and is not an exact count. The group
  interval is at or above the scrape interval.
- Precompute what dashboards fan out or alerts consume, with the `rate()` and
  the aggregation inside the rule so panels query one series.

## Alerting

- Symptom first: what the desk feels (quotes stale, fills stopped, venue
  down, risk utilisation, data age), capacity nearing a limit, and the
  monitoring stack itself through a Watchdog alert (`vector(1)`) routed to an
  external heartbeat whose absence pages.
- Every alert has a `for` duration in minutes, a `severity` label that
  Alertmanager routes, a `desk` or `team` label, a `summary`, a templated
  `description` and a `runbook_url`. Inhibition mutes consequences of a
  cause (venue down mutes quote stale for that venue).
- Missing data is `up == 0` or a staleness expression on the last-update
  timestamp; `absent()` only with literal matchers and a test.
- PnL and position alerts carry hysteresis (a longer `for`, or a rule over
  `max_over_time`), never fire on a raw tick-level gauge, and never trigger an
  automatic action on positions.
- Every rule ships with promtool test scenarios for the firing case and the
  not-firing case, with staleness modelled where it matters; the rule file
  passes `promtool check rules` and the config `promtool check config` before
  any reload.

## Scrape, retention and operations

- `scrape_timeout` below `scrape_interval` (5 to 15 s for trading exporters);
  `relabel_configs` for target labels, `metric_relabel_configs` as the
  cardinality brake; `honor_labels` only for pushgateway and federation;
  file-based service discovery for a small desk.
- `up`, `scrape_duration_seconds` and `scrape_samples_post_metric_relabeling`
  are alerted on; the pushgateway serves batch jobs only.
- Reload only after `promtool check config`, through `SIGHUP` or `/-/reload`;
  image tags pinned; state on persisted volumes; the Grafana database backed
  up even though dashboards come from git.
- Long retention and HA through remote write (Thanos, Mimir, VictoriaMetrics)
  with replica labels deduplicated downstream; federation only for
  aggregated series.

## Grafana

- Dashboards as JSON in git with stable `uid`, `title` and datasource uid,
  provisioned from `provisioning/dashboards` and `provisioning/datasources`,
  produced by one generator (the middleware's codegen, grafanalib or
  Grafonnet) and never hand-edited afterwards.
- Panels query recording rules, use `$__rate_interval`, carry a unit, a
  legend from labels, thresholds on stat panels, a state timeline for
  connectivity, a folder per desk, a default range of one to six hours and a
  refresh at or above the scrape interval. Template variables come from
  bounded labels only.
- Service-health alerts live in Prometheus rules; Grafana alerting is for
  non-Prometheus sources. Never both on one condition.

## Exporters

- A collector never blocks on a network call inside the scrape: slow sources
  (exchange REST, a database) are polled by a background thread into a cache
  the scrape reads, with `*_last_success_timestamp_seconds`,
  `*_scrape_errors_total{source}` and `*_up` exposed and `/healthz` apart
  from `/metrics`. Secrets from the environment, never in labels or logs.
- Standard exporters cover hosts (node_exporter, cadvisor), databases
  (mysqld_exporter, postgres_exporter), Redis, Kafka lag (kafka_exporter) and
  probes (blackbox_exporter); a desk exporter adds only what the venue or
  strategy exposes.

## Trading metrics worth standardising

`order_roundtrip_seconds{venue,op}` histogram; `orders_total{venue,status}`
and fills, with the fill ratio as a rule over sums; `quote_live{venue,symbol}`
as a 0/1 gauge with uptime as `avg_over_time`; `position_base` and
`inventory_notional_usd` gauges; `pnl_usd{strategy,kind}` with hysteresis;
`venue_connection_state{venue,feed}` 0/1; `md_sequence_gaps_total{venue}`;
`risk_limit_utilisation_ratio{limit}` (warn 0.8, page 0.95);
`md_last_update_timestamp_seconds{venue,symbol}` for staleness; exporter
self-health on every exporter.

## Gotchas

1. `rate()` on a gauge, or a counter that can decrease.
2. A rate window shorter than four scrapes, or `irate()` in an alert.
3. Averaged quantiles or averaged ratios.
4. An unbounded label with no `metric_relabel_configs` brake.
5. An alert without `for`, `runbook_url` or a not-firing test.
6. A counter never initialised, so its first increment is invisible.
7. A dead exporter still serving old values inside the staleness window.
8. A collector blocking on REST until the scrape times out.
9. A generated dashboard or rule hand-edited in engine-middleware.
10. A PnL alert without hysteresis, or an alert that acts on positions.
