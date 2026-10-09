---
name: skill-comply
description: Measures whether a skill, rule, or agent definition is actually followed, instead of assuming it is. Extracts the definition's checkable obligations into a spec, runs the target on scenarios at three prompt strictness levels (or on a seeded fixture set), has an independent grader score each run against the spec, and reports compliance per obligation with evidence and a fix for each gap — reword, move to a path-scoped rule, or promote to a hook. Use after writing or changing a skill, rule or agent, when one seems to be ignored, or to regression-test trading-code-reviewer against its fixtures.
---

# skill-comply

Prose instructions are requests. This skill measures how often a request is
honoured, and turns low compliance into a concrete fix. It ports ECC's
`skill-comply` to this harness: in-session subagents and `claude -p` instead
of a Python pipeline.

## Inputs

- **Target**: a path — `~/.claude/skills/<name>/SKILL.md`, `~/.claude/rules/<name>.md`,
  `~/.claude/agents/<name>.md`, or a repo's `.claude/...` equivalent.
- **Mode**: `scenarios` (default) or `fixtures` when the target has a fixture set
  under `fixtures/<target-name>/` next to this file (today: `trading-code-reviewer`).
- **Runs per scenario**: default 1; use 3 when deciding whether to change a
  definition (report pass^3 — all three runs compliant).

Say the expected cost before starting: roughly (scenarios × runs) target runs
plus as many grader runs.

## 1. Spec

Read the target and list its **obligations** — behaviours an observer could
check from a transcript or output, not aspirations. For each:

```yaml
- id: kebab-case
  source: "<quoted line from the target>"
  check: "<what a grader looks for: a tool call, an ordering, an output field, an absence>"
  kind: action | ordering | output | prohibition
```

Skip lines nobody could check ("write clean code"). Show the spec to the user
and wait for a go before spending on runs.

## 2. Scenarios (mode `scenarios`)

Write three tasks that exercise the obligations, decreasing in support:

1. **supportive** — the prompt asks for exactly what the target prescribes.
2. **neutral** — the same task, with no mention of the target's practices.
3. **competing** — the same task, with time pressure or an instruction that
   tempts the agent to skip an obligation ("just patch it quickly").

Each task must be small, self-contained, and runnable in a scratch sandbox
under `~/.cache/claude-scratch/skill-comply/<target>/<scenario>/` — never a
real repo, never anything that touches exchanges, credentials or live config.

## 3. Run

- **Agent targets**: call the Agent tool with `subagent_type` = the agent name
  and the scenario prompt (plus the sandbox path). Keep its final report.
- **Skill and rule targets**: run headless in the sandbox so the target loads
  the way it does for real:

  ```sh
  cd ~/.cache/claude-scratch/skill-comply/<target>/<scenario> && \
    claude -p "<scenario prompt>" --output-format stream-json --verbose \
      > trace.jsonl 2> stderr.txt
  ```

  The trace's `tool_use` entries are the behaviour timeline.

Run scenarios in parallel where they are independent. Never let a run push,
open PRs, or leave the sandbox.

## 4. Grade

Spawn a separate grader (Agent tool, `model: "opus"`), never the run's own
context. Give it the spec, the scenario, and the run's output or trace; ask
for, per obligation: `complied | violated | not-applicable`, with the
evidence (tool call number, quoted output line). Check orderings
deterministically from the trace order, not by the grader's impression.

For `fixtures` mode, grade against each case's `expected.yaml` instead (see
`fixtures/README.md`): verdict match, every `must_find` reported at the right
place, no `must_not_flag` reported.

## 5. Report

```
COMPLIANCE: <target>   runs: <n>   overall: <complied>/<applicable> (<pct>)
obligation            supportive  neutral  competing   evidence
<id>                  ✓           ✓        ✗           run 3, tool #7: edited before reading callers
```

Then, for every obligation below ~80% (or failed in `competing`), recommend
one fix, strongest first:

1. **Promote to a hook** when the obligation is mechanically checkable
   (a command that must or must not run, a file that must not change).
   Name the event and the check — `~/.claude/hooks/` has the patterns.
2. **Move to a path-scoped rule** (`~/.claude/rules/*.md` with `paths:`)
   when it is skipped because the skill wasn't loaded.
3. **Reword** when the grader's evidence shows the instruction was
   misunderstood: make it concrete, put it first, say why it matters.
4. **Delete** it when it is aspirational and nobody can check it.

Apply nothing without the user's go-ahead. Save the report under
`~/.cache/claude-scratch/skill-comply/<target>/report-<date>.md`.
