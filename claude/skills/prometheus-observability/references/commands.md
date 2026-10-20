# Commands, test schema, snippets and references

The Prometheus practice pages, the rule unit-testing page and the Python
client docs were read on 2026-10-20; Grafana provisioning keys and the Rust
crate APIs are to be confirmed against the pinned version.

## promtool and amtool

```
promtool check config prometheus.yml          # also validates the referenced rule files
promtool check rules rules/*.yml
promtool test rules tests/*.yml
promtool query instant http://localhost:9090 'up == 0'
amtool check-config alertmanager.yml
amtool config routes test --config.file=alertmanager.yml severity=page desk=mm
amtool silence add alertname=Foo --duration=2h --comment="..."
curl -X POST http://localhost:9090/-/reload   # needs --web.enable-lifecycle; or kill -HUP
```

On this machine promtool is `~/.cache/claude-scratch/bin/promtool`;
engine-middleware installs its own through `scripts/checks/install-promtool.sh`
and regenerates rules, scenarios and dashboards with `just metrics-codegen`.

## Rule unit test file

```yaml
rule_files:
  - ../rules/trading.yml
evaluation_interval: 1m
tests:
  - interval: 15s
    input_series:
      - series: 'md_last_update_timestamp_seconds{venue="bybit",symbol="BTCUSDT"}'
        values: '1700000000+0x40'      # a+bxc expands to a, a+b, ... a+c*b; _ is an empty sample
    alert_rule_test:
      - eval_time: 5m
        alertname: MarketDataStale
        exp_alerts:
          - exp_labels: {severity: page, venue: bybit, symbol: BTCUSDT}
            exp_annotations: {summary: "bybit BTCUSDT market data stale"}
      - eval_time: 1m
        alertname: MarketDataStale
        exp_alerts: []                 # the not-firing case
    promql_expr_test:
      - expr: 'sum by (venue) (rate(orders_total[5m]))'
        eval_time: 10m
        exp_samples:
          - labels: 'sum by (venue) (rate(orders_total[5m])){venue="bybit"}'
            value: 0.5
```

Pitfalls: staleness can make a test pass by accident; an expected empty
result needs `exp_samples: []`; functions such as `idelta` drop `__name__`.

## Alert rule shape

```yaml
groups:
  - name: trading
    interval: 30s
    rules:
      - record: venue:orders:rate5m
        expr: sum without (instance, pod) (rate(orders_total[5m]))
      - alert: MarketDataStale
        expr: time() - md_last_update_timestamp_seconds > 5
        for: 2m
        labels: {severity: page, desk: mm}
        annotations:
          summary: "{{ $labels.venue }} {{ $labels.symbol }} market data stale"
          description: "No update for {{ $value | humanizeDuration }}"
          runbook_url: https://.../runbooks/market-data-stale
      - alert: Watchdog
        expr: vector(1)
        labels: {severity: none}
```

## Client snippets

- Python single process: `from prometheus_client import start_http_server, Counter, Gauge, Histogram`;
  `start_http_server(port, addr="127.0.0.1", registry=registry)`; a custom
  collector subclasses `Collector`, yields `GaugeMetricFamily` from
  `collect()` and is registered once.
- Python multiprocess: `PROMETHEUS_MULTIPROC_DIR` set and wiped in the startup
  script; per scrape `registry = CollectorRegistry(); multiprocess.MultiProcessCollector(registry)`;
  gunicorn `child_exit` calls `multiprocess.mark_process_dead(worker.pid)`.
  Unsupported there: custom collectors, `Gauge` `set_function` and `pid`
  label, `Info`, `Enum`, exemplars, pushgateway, label removal.
- Rust: the `prometheus` crate (`register_int_counter_vec!`, `Registry`,
  `TextEncoder`) or the `metrics` facade with `metrics-exporter-prometheus`
  (`PrometheusBuilder::new().with_http_listener(addr).set_buckets_for_metric(...)`;
  histograms export as summaries unless buckets are set). Pre-register
  handles; never build label strings on the hot path.

## Grafana provisioning (confirm keys against the pinned Grafana)

`provisioning/dashboards/desk.yaml`: `apiVersion: 1`, `providers:` with
`name`, `orgId`, `folder`, `type: file`, `disableDeletion`,
`updateIntervalSeconds`, `allowUiUpdates: false`, `options.path`,
`options.foldersFromFilesStructure: true`. `provisioning/datasources/*.yaml`
with an explicit `uid`. Generators: grafanalib (Python), Grafonnet (Jsonnet),
Grizzly, the Terraform Grafana provider, or the middleware's own codegen.

## Dashboard review checklist

Units set; legends from labels; `rate` windows at least four scrape intervals
or `$__rate_interval`; no high-cardinality template variables; thresholds on
stat panels; sane default time range; `uid` unchanged; no hard-coded
datasource names; queries hit recording rules; generated JSON not hand-edited.

## Primary references

- Prometheus practices: naming https://prometheus.io/docs/practices/naming/ ; instrumentation https://prometheus.io/docs/practices/instrumentation/ ; histograms https://prometheus.io/docs/practices/histograms/ ; recording rules https://prometheus.io/docs/practices/rules/ ; alerting https://prometheus.io/docs/practices/alerting/
- Unit testing rules: https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/
- Alertmanager configuration (grouping, inhibition): https://prometheus.io/docs/alerting/latest/configuration/
- Rob Ewaschuk, "My Philosophy on Alerting" (search by title)
- client_python: https://github.com/prometheus/client_python and https://prometheus.github.io/client_python
- Rust: https://github.com/tikv/rust-prometheus ; https://github.com/metrics-rs/metrics
- Grafana provisioning: https://grafana.com/docs/grafana/latest/administration/provisioning/ ; grafanalib https://github.com/weaveworks/grafanalib ; Grafonnet https://github.com/grafana/grafonnet ; Grizzly https://github.com/grafana/grizzly
- Exporters on GitHub: prometheus/node_exporter, prometheus/mysqld_exporter, prometheus-community/postgres_exporter, oliver006/redis_exporter, danielqsj/kafka_exporter, prometheus/blackbox_exporter
