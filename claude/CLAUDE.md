# Global Context

Rules that apply in every workspace. Language conventions live in
path-scoped rules, domain guidance in skills; repo-specific detail belongs in
that repo's own CLAUDE.md.

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
  suggest /loop or ralph-loop with an explicit stop condition rather than
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
  and their outcome, open todos, last reply), saved before compaction and
  restored right after it — automatic, no command needed.
- `/clear` always starts fresh: no hook injects anything into a cleared
  session. To carry work into a new session, do it
  explicitly: `/handoff` → `/clear` (or quit) → `/pickup`. `/handoff`
  records what worked (with evidence), what failed, what was not tried, and
  next steps — the part a transcript digest cannot reconstruct — and
  `/pickup` loads it in the new session. A brand-new session only gets a
  one-line pointer to the previous handoff's goal.
- Compact at phase boundaries (plan agreed, tests green, before switching
  subtask), not mid-change. Don't start a large multi-file change with the
  window nearly full — hand off and compact first.

## Rules

One file per language in `~/.claude/rules/`, loaded automatically when a
matching file is read or edited; subagents working from a diff read them
explicitly: `rust.md` (`**/*.rs`).

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

- Run `/learn` at the end of a session that involved a correction or a
  hard-won fix: it routes each lesson to CLAUDE.md, a path-scoped rule, a
  skill, a hook, or memory, as diffs I approve.
- After adding or changing a skill, rule or agent, measure it with the
  `skill-comply` skill instead of assuming it is followed; obligations that
  keep failing become hooks. `quant-trading-code-reviewer` has a seeded
  fixture set there for regression runs.
- The dotfiles CI runs `claude/scripts/lint_harness.py` and the hook tests;
  run both locally before pushing harness changes.
- How `~/.claude` is wired to this repo (what is linked, what is copied, the
  `CLAUDE.local.md` requirement) is in `claude/hooks/README.md` under Install.

## Model tiering

Ad-hoc subagents and workflow agents should not inherit the session model by
default. Pick the cheapest tier that does the job:

| Tier | Use for |
|------|---------|
| **haiku** | Mechanical, low-judgment stages: grep/list sweeps, formatting, collecting inputs, `effort: "low"` |
| **sonnet** | The default for Agent-tool subagents (`CLAUDE_CODE_SUBAGENT_MODEL`). Reading and summarizing code, drafting findings, applying well-specified edits, single-item reviews |
| **opus** | Verification and judgment: adversarial verify/refute votes, judge panels, synthesis across many findings, non-trivial Rust or trading-logic reasoning |
| **fable** | Only when explicitly asked, or for the single final synthesis of a large audit where correctness dominates cost |

The custom agents in `~/.claude/agents/` pin their own tier, and the pin wins
over the default:

| Agent | Model | Effort |
|-------|-------|--------|
| `Explore`, `code-reader`, `docs-lookup`, `implementer`, `quant-trading-code-reviewer` | opus | medium |
| `verifier`, `quant-trading-researcher`, `quant-trading-developer` | opus | high |
| `blockchain-protocol` | opus | session default |
| `blockchain-unit-test`, `xlayer-devnet` | sonnet | session default |

In every Workflow script, set `model` (and `effort`) explicitly on each
`agent()` call — never leave it to inherit. Match the tier to the stage,
not to the task's overall difficulty: a hard audit still runs its find stage
on sonnet and its verify stage on opus. When using the Agent tool directly,
pass `model` when the default `sonnet` is wrong in either direction.

## Machine-local rules

Rules that only hold on one machine — test-runner arbitration, scratch
directories — live in the untracked `~/.claude/CLAUDE.local.md`. That path
is not loaded on its own, so it is imported here; agents that defer to "the
global CLAUDE.md" for these rules get them through this import.

@~/.claude/CLAUDE.local.md
