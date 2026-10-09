# Global Context

Rules that apply in every workspace. Language conventions live in
path-scoped rules, domain guidance in skills; repo-specific detail belongs in
that repo's own AGENTS.md.

## Hard constraints

- **Never merge a PR** — no `gh pr merge`, no `--auto` flag, no
  merge/squash/rebase into a shared branch. "Create a PR" means open the PR from an already pushed branch, stop, and hand me the link; push only if explicitly requested (see the `pr-create`
  skill). Repo-level AGENTS.md conventions (e.g. "PR + auto-merge") do NOT
  override this: merging is mine.
- **Never `git push` unless I explicitly ask in the current turn.** Prior approvals do not carry forward. Never force-push or delete `main`/`master`; ask before any other force-push.
- **Never use `nohup`.** Use `&` with proper process management, `tmux`/`screen`,
  `systemd` services, or `tokio` task spawning instead.
- **Plan before coding.** For new features, multi-file changes, new test suites,
  or refactors: present a structured plan and wait for approval. Single-line
  fixes and typo corrections can skip this.
- **Guards are rules, not obstacles.** Hooks in `~/.codex/hooks/` enforce
  the rules above (plus no `--no-verify`, no secrets in commits, and exact-operation approval
  before loosening lint config or touching risk/production config). When one
  denies a call, do not route around it with `bash -c`, a script, or an
  alias — tell me what you wanted to run and why.
- **Never end a turn on unverified code without saying so.** After the last
  code edit, run the narrowest build/test/lint that covers it, or state
  plainly that the change is unverified and why. A Stop hook holds the turn
  open once when neither happened, and when debug leftovers remain.

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
  suggest $ralph-loop with an explicit stop condition rather than
  polling manually.
- "ultracode" in my prompt = standing opt-in: orchestrate by default,
  maximize thoroughness over token cost.
- Loops and workflows never touch live trading state. Repos, backtests, and
  CI only.
- **Brief subagents with the purpose, not just the query.** Say what the
  result is for, what done looks like, and what is already known. Read each
  return critically; if it misses what you need, send a follow-up to the same
  agent (up to ~3 rounds) before accepting it or re-spawning.
- **Delegation completion contract.** A subagent's final message is its
  deliverable: never end a turn on "waiting for background agents". If you
  delegate, you collect — wait for every child, integrate the results, then
  report. Delegate only work that does not fit one context; don't re-split a
  task already sized for one agent.
- **Loops need a machine-decidable goal.** Before starting one, name the
  check that ends it (a test, a metric threshold, an empty work-list), make
  sure the loop cannot edit that check, and set a max iteration count. Stop
  and report when two consecutive checkpoints show no progress or the same
  failure repeats.

## Second opinions

Codex has no Claude `advisor` tool. Before a large plan, after the same failure
twice, or before finishing a long task, consider an independent `verifier`
review. Propose it and obtain per-run delegation approval unless the user's
request already authorizes it (for example `$deep` or `ultracode`). Supply the
purpose, evidence and artifacts; a reviewer does not automatically see the
full transcript. Do not claim a review happened when no reviewer ran.

## Sessions and context

- Hooks keep a per-session handoff file (requests, files changed, commands
  and their outcome, open todos, last reply), saved before compaction and
  restored right after it — automatic, no command needed.
- `/new` always starts fresh: no hook injects anything into a cleared
  session. To carry work into a new session, do it
  explicitly: `$handoff` → `/new` (or quit) → `$pickup`. `$handoff`
  records what worked (with evidence), what failed, what was not tried, and
  next steps — the part a transcript digest cannot reconstruct — and
  `$pickup` loads it in the new session. A brand-new session only gets a
  one-line pointer to the previous handoff's goal.
- Compact at phase boundaries (plan agreed, tests green, before switching
  subtask), not mid-change. Don't start a large multi-file change with the
  window nearly full — hand off and compact first.

## Rules

Rules live in `~/.codex/rules/{rust,python,go}.md`. Read the matching rule
when reading, writing, reviewing or debugging that language, including diffs.
The PreToolUse context loader recognizes file extensions and language commands;
language skills provide an explicit fallback. Codex does not natively implement
Claude's `paths:` frontmatter. Repo conventions win where a rule says so.

## Skills

When working under `~/dev`, load `quant-trading` (domain practice) for
trading work, plus `quant-trading-research` for alpha or signal research,
`quant-trading-backtesting` and `quant-trading-validation` when
implementing, backtesting or promoting a strategy. Add the venue skill when
the work names that venue: `quant-trading-crypto-struct` for the CryptoStruct
adapters and the engine, strategy and monitor repos that trade on them today,
`quant-trading-apex` or `quant-trading-tt` for those venues:

- `quant-trading` — quant trading domain expertise: market making, engine
  design, execution, market data, risk.
- `quant-trading-research` — QR practice: hypothesis-first research loop,
  tick/L2 data hygiene, microstructure signals, statistical validation,
  multiple-testing discipline, cost-first reporting.
- `quant-trading-backtesting` — simulator practice: replay design and
  determinism, L2/L3 data and queue position, matching semantics, latency
  and jitter with the cancel-fill race, calibrating against live fills,
  benchmarking and reading a backtest; the platform's backtester facts.
- `quant-trading-validation` — QD practice: fidelity ladder and optimism
  audit, parity against live, walk-forward and parameter robustness, TCA
  and markouts, promotion gates and kill criteria.
- `quant-trading-crypto-struct` — the CryptoStruct adapters and
  engine-middleware's venue module for them, and the legacy Python stack
  and Rust bot that trade on them today.
- `quant-trading-apex` — the APEX venue: the vendor SDK and documents, the
  engine-middleware `apex` module, UAT tiers and live-safety rules, open
  questions.
- `quant-trading-tt` — the TradingTechnologies venue: TT FIX and REST facts,
  the engine-middleware `tt` module, proven offline only, and what its live
  path still needs.

## Harness maintenance

- Run `$learn` at the end of a session that involved a correction or a
  hard-won fix: it routes each lesson to AGENTS.md, a path-scoped rule, a
  skill, a hook, or memory, as diffs I approve.
- After adding or changing a skill, rule or agent, measure it with the
  `skill-comply` skill instead of assuming it is followed; obligations that
  keep failing become hooks. `quant-trading-code-reviewer` has a seeded
  fixture set there for regression runs.
- Run `python3 codex/scripts/validate.py` and
  `python3 -m unittest discover -s codex/hooks/tests -v` for Codex harness changes.
- Installation, symlinks, hook trust, backups and compatibility notes live in
  `~/dev/dotfiles/codex/README.md`. Codex configuration is maintained there,
  independently of Claude. Never edit Claude settings as part of a Codex update.
- Behavioral `skill-comply` runs spend model calls and require their own
  approved scenario plan; structural validation is not behavioral compliance.

## Model tiering

Use explicit models when delegation is authorized. The current account's model
catalog supports these configured tiers; they are approximate workflow mappings,
not claims of equivalence to Claude models:

| Work | Model | Effort |
|------|-------|--------|
| Mechanical collection | `gpt-6-luna` | low |
| Default subagent / well-specified work | `gpt-6.1-sol` | medium |
| Independent verification, synthesis, complex trading/Rust reasoning | `gpt-6-astra` | medium or high |

Custom roles in `~/.codex/agents/*.toml` pin their model and effort. Honor those
pins; do not substitute an inherited model. The main session uses
`gpt-6.1-sol` with xhigh effort. Claude's Fable/advisor setting is not a Codex
model and is not copied verbatim.

## Machine-local and repository context

Read `~/.codex/local/AGENTS.local.md` when present. The SessionStart and
SubagentStart hooks load this independent, untracked copy; AGENTS.md has no
Claude `@file` import syntax. For engine-middleware, also read
`~/.codex/local/engine-middleware.md` before running tests.

Read native repository `AGENTS.md` first. Where none exists, `CLAUDE.md` is a
read-only project-document fallback. Existing repository `CLAUDE.local.md` can
supply test routing without being edited. This migration never modifies project
Claude contexts. `~/.cache/claude-scratch/` paths in local test guidance name the
existing machine runners; do not rename or edit them as part of this port.

Protected-operation hooks fail closed on approval-required operations. When one
provides an `authorize.py` command, only the user runs it in their terminal;
never run it yourself, turn off the hook, or rewrite the operation to avoid it.
The one-use grant is bound to the exact operation, session and turn.
