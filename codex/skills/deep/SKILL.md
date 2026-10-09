---
name: deep
description: Design and run an explicitly requested multi-agent find, verify and synthesize workflow for an audit or large independent work-list.
---

Explicit invocation authorizes proposing delegation. Scope the work-list inline,
then show stages, unit of parallelism, agent prompts, write/read-only scope,
rough agent count, evidence threshold, output and stop condition. Wait for per-run
approval before execution, including the write scope when applicable.

Use native Codex spawn_agent, messaging/follow-up and wait tools when available.
Choose matching configured roles; brief each with purpose, done criteria, known
evidence and permission boundaries. Claude Workflow scripts, agentType APIs,
runId and resume semantics are unavailable. Save approved work-list, completed
items and artifact paths in a Codex handoff for resumption.

Finders may return zero findings. Independently verify exact lines, concrete
failures and surrounding guards. Only report claims meeting the approved
threshold; include discard count. Prefer follow-ups over respawning. Collect
all children and integrate every result before ending. Live trading state,
exchange writes and production config are excluded.
