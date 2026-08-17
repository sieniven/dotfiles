---
description: Design and run a multi-agent workflow (find → verify → synthesize) for the given task
argument-hint: <task — e.g. "audit the hedger's risk gating" or "check StrategyBase drift across strategy/">
---

The user has explicitly opted into multi-agent orchestration via this command.
Task: $ARGUMENTS

Follow this process:

1. **Scope inline first.** Before building any graph, discover the work-list
   yourself (list the repos/files/configs/findings the task fans out over).
   Do not spawn agents for scoping you can do with a few greps.

2. **Design the graph from the task's shape:**
   - Unit of parallelism: the item discovered in step 1.
   - Lenses: prefer the repo's custom agents in `.claude/agents/` as nodes
     (via `agentType`) when one matches; author inline finder prompts only
     for lenses no custom agent covers.
   - Evidence standard: findings must survive adversarial verification
     (majority of independent skeptics) before being reported. Report
     confirmed findings only; note the discard count.
   - Output: structured schemas between stages; final synthesis as a table
     or ranked list with file:line citations.

3. **Show the plan before running.** Present phases, per-stage agent prompts
   (abridged), verification threshold, and rough agent count. Wait for
   approval — this composes with the global plan-before-coding rule.

4. **Constraints:**
   - Read-only by default. If the task requires writing code, say so
     explicitly in the plan and get separate approval for the write phase.
   - Never touch live trading state, exchange APIs, or production config.
   - Respect per-repo CLAUDE.md orchestration rules (e.g. worktree
     restrictions) — check the target repo's CLAUDE.md before designing
     write-mode stages.
   - After the run, name the script path and runId so a stage can be edited
     and resumed cheaply instead of re-running the whole graph.
