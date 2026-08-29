# Global Context

Rules that apply in every workspace. Language and domain guidance lives in
skills; repo-specific detail belongs in that repo's own CLAUDE.md.

## Hard constraints

- **Never `git push`** unless I ask for it in the current turn. Prior push
  approvals do not carry forward.
- **Never merge a PR** — no `gh pr merge`, no `--auto` flag, no
  merge/squash/rebase into a shared branch — unless I explicitly ask for the
  merge in the current turn. "Create a PR" means stop at creation and hand me
  the link. Repo-level CLAUDE.md conventions (e.g. "PR + auto-merge") do NOT
  override this: leave merging to me.
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

## Orchestration

- Difficulty alone doesn't justify multi-agent work; shape does. When a task
  decomposes into many independent items, or its findings need independent
  verification before acting on them, propose a workflow (stages + rough
  scale) instead of grinding it inline — I'll approve per run.
- When work is long-running or a backlog (backtests, CI, migration sweeps),
  suggest /loop or ralph-loop with an explicit stop condition rather than
  polling manually.
- "ultracode" in my prompt = standing opt-in: orchestrate by default,
  maximize thoroughness over token cost.
- Loops and workflows never touch live trading state. Repos, backtests, and
  CI only.

## Skills

When working under `~/dev`, load `trading` (domain practice) plus
`crypto-struct` (current-stack specifics) for trading work, and `rust` when
the code is Rust:

- `rust` — language and runtime conventions.
- `trading` — quant trading domain expertise: market making, engine design,
  execution, market data, risk.
- `crypto-struct` — the existing CryptoStruct-based stack: gateway, engine
  callbacks, money conventions, known gaps.

## Model tiering

Subagents and workflow agents should not inherit the session model by
default — pick the cheapest tier that does the job:

- **haiku** — mechanical, low-judgment stages: file discovery, grep/list
  sweeps, formatting, collecting inputs, `effort: "low"`.
- **sonnet** (the default for Agent-tool subagents via
  `CLAUDE_CODE_SUBAGENT_MODEL`; `Explore` is pinned to opus in
  `~/.claude/agents/Explore.md`) — reading and summarizing code, drafting
  findings, applying well-specified edits, single-item reviews.
- **opus** — verification and judgment: adversarial verify/refute votes,
  judge panels, synthesis across many findings, non-trivial Rust or
  trading-logic reasoning.
- **fable** — only when explicitly asked, or for the single final synthesis
  of a large audit where correctness dominates cost.

In every Workflow script, set `model` (and `effort`) explicitly on each
`agent()` call — never leave it to inherit. Match the tier to the stage,
not to the task's overall difficulty: a hard audit still runs its find stage
on sonnet and its verify stage on opus. When using the Agent tool directly,
pass `model` when the default `sonnet` is wrong in either direction.
