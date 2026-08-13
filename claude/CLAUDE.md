# Global Context

Rules that apply in every workspace. Language and domain guidance lives in
skills; repo-specific detail belongs in that repo's own CLAUDE.md.

## Hard constraints

- **Never `git push`** unless I ask for it in the current turn. Prior push
  approvals do not carry forward.
- **Never use `nohup`.** Use `&` with proper process management, `tmux`/`screen`,
  `systemd` services, or `tokio` task spawning instead.
- **Plan before coding.** For new features, multi-file changes, new test suites,
  or refactors: present a structured plan and wait for approval. Single-line
  fixes and typo corrections can skip this.

## Environment

`~/dev/` — trading team core services: market making and hedging across CEX
and perp-DEX order books. Each subdirectory groups independent git repos,
named `<group>-<name>`:

- `engine/` — trading engine platform (Python). `engine-trading-cs` is the
  core engine — its `tradingenginecs` package is the shared dependency most
  other repos build on. `engine-backtesting` runs the same strategies
  unchanged on recorded data. `engine-strategy-manager` is a control plane
  only, deliberately outside the execution path.
- `strategy/` — trading strategies. `strategy-exchange-mm-hedger-bot` is the
  self-contained Rust market-maker/hedger; the rest are Python on
  `tradingenginecs`.
- `monitor/` — Prometheus/Grafana monitors, one repo per desk (market making,
  arb, portfolio NAV).
- `system/` — supporting services: ledger, data platform, backtesting web UI.
- `research/` — quant research.
- `infra/` — infrastructure (Kafka, etc.).
- `ai-pgd-agents/` — internal AI agent platform.

## Skills

When working under `~/dev`, load `trading` (domain practice) plus
`crypto-struct` (current-stack specifics) for trading work, and `rust` when
the code is Rust:

- `rust` — language and runtime conventions.
- `trading` — quant trading domain expertise: market making, engine design,
  execution, market data, risk.
- `crypto-struct` — the existing CryptoStruct-based stack: gateway, engine
  callbacks, money conventions, known gaps.
