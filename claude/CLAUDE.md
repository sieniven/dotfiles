# Global Context

Rules that apply in every workspace. Language and domain guidance lives in
skills; repo-specific detail belongs in that repo's own CLAUDE.md.

## Hard constraints

- **Never merge a PR** — no `gh pr merge`, no `--auto` flag, no
  merge/squash/rebase into a shared branch. "Create a PR" means push the
  branch, open the PR, stop, and hand me the link (see the `pr-create`
  skill). Repo-level CLAUDE.md conventions (e.g. "PR + auto-merge") do NOT
  override this: merging is mine.
- **Pushing is fine; rewriting shared history is not.** Push feature branches
  freely. Never force-push or delete `main`/`master`; ask before any other
  force-push.
- **Never use `nohup`.** Use `&` with proper process management, `tmux`/`screen`,
  `systemd` services, or `tokio` task spawning instead.
- **Plan before coding.** For new features, multi-file changes, new test suites,
  or refactors: present a structured plan and wait for approval. Single-line
  fixes and typo corrections can skip this.
- **Guards are rules, not obstacles.** Hooks in `~/.claude/hooks/` enforce
  the rules above (plus no `--no-verify`, no secrets in commits, and a prompt
  before loosening lint config or touching risk/production config). When one
  denies a call, do not route around it with `bash -c`, a script, or an
  alias — tell me what you wanted to run and why.

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

## Advisor

The `advisor` tool (a stronger reviewer that sees the full transcript) is
configured via `advisorModel` in `~/.claude/settings.json`. Consult it at these points,
not only when stuck:

- **Before a large plan** — before committing to an approach for a
  multi-file change, refactor, new feature, or audit.
- **When the same error appears twice** — a repeated failure means the
  current approach is not converging; get a second read before a third try.
- **Before marking a long task done** — make the deliverable durable first
  (file written, result saved), then consult the advisor before declaring
  done.

## Sessions and context

- Hooks keep a per-session handoff file (requests, files changed, commands
  and their outcome, open todos, last reply). It is restored after
  compaction, loaded in full after `/clear`, and offered as a pointer to the
  next session in the same project.
- Run `/handoff` before `/clear`, before a long break, or when the
  compaction suggestion fires: it records what worked (with evidence), what
  failed, what was not tried, and next steps — the part a transcript digest
  cannot reconstruct.
- Compact at phase boundaries (plan agreed, tests green, before switching
  subtask), not mid-change. Don't start a large multi-file change with the
  window nearly full — hand off and compact first.

## Skills

When working under `~/dev`, load `trading` (domain practice) plus
`crypto-struct` (current-stack specifics) for trading work, and `rust` when
the code is Rust. Add `quant-research` for alpha or signal research and
`strategy-validation` when implementing, backtesting, or promoting a strategy:

- `rust` — language and runtime conventions.
- `trading` — quant trading domain expertise: market making, engine design,
  execution, market data, risk.
- `crypto-struct` — the existing CryptoStruct-based stack: gateway, engine
  callbacks, money conventions, known gaps, research and backtester facts.
- `quant-research` — QR practice: hypothesis-first research loop, tick/L2
  data hygiene, microstructure signals, statistical validation,
  multiple-testing discipline, cost-first reporting.
- `strategy-validation` — QD practice: backtest fidelity and optimism audit,
  parity and determinism, walk-forward and parameter robustness, TCA and
  markouts, promotion gates and kill criteria.

## Model tiering

Subagents and workflow agents should not inherit the session model by
default — pick the cheapest tier that does the job:

- **haiku** — mechanical, low-judgment stages: file discovery, grep/list
  sweeps, formatting, collecting inputs, `effort: "low"`.
- **sonnet** (the default for Agent-tool subagents via
  `CLAUDE_CODE_SUBAGENT_MODEL`; the custom agents in `~/.claude/agents/` —
  `Explore`, `implementer`, `docs-lookup`, `code-reader`,
  `trading-code-reviewer` — pin opus at medium effort, and `verifier`,
  `quant-researcher`, and `quant-developer` pin opus at high) — reading and
  summarizing code, drafting findings, applying well-specified edits,
  single-item reviews.
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
