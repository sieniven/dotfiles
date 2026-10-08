---
description: Extract the durable lessons from this session and route each to where it will be loaded next time — CLAUDE.md, a rule, a skill, or memory — as proposed diffs
argument-hint: "[optional focus, e.g. \"the funding-rate backtest bug\"]"
---

Review this session for lessons worth keeping. Focus: $ARGUMENTS

A lesson qualifies only if it is **non-obvious and will recur**: a user
correction of how I work, a debugging technique that cracked something, a
repo-specific gotcha, a workaround for a tool or API quirk, or a check that
would have caught a mistake earlier. Skip what any competent engineer would do
anyway, one-off task details, and anything already written down (grep the
destination before proposing).

For each lesson, give the evidence (the moment in this session: the error,
the correction, the fix) and route it to exactly one place:

| Lesson is about | Goes to |
|---|---|
| How the user wants me to work, everywhere | `~/.claude/CLAUDE.md` — only if short and broadly true |
| One repo's build, layout, conventions, gotchas | that repo's `CLAUDE.md` (or `.claude/rules/*.md` with `paths:` if it only matters for some files) |
| A language or file type | `~/.claude/rules/<lang>.md` (path-scoped) |
| Domain technique (trading, research, validation, reth) | the matching skill — extend the existing section; don't start a new skill for one lesson |
| A mechanical must/must-not (a command, a file, an ordering) | propose a hook check in `~/.claude/hooks/` instead of more prose |
| Personal, machine-specific, or temporary | auto memory, or `~/.claude/CLAUDE.local.md` for machine rules |

Then:

1. Show the lessons as a numbered list: lesson → destination → the exact diff
   (a few lines each). Keep wording imperative and concrete, with the why in
   one clause.
2. Wait for me to pick which to apply. Apply only those.
3. Keep destinations lean: if an edit pushes a SKILL.md past ~500 lines or
   CLAUDE.md past ~200, propose moving detail into a reference file instead.

The `claude-md-management` plugin's revise command covers CLAUDE.md alone;
this command routes across every destination above.
