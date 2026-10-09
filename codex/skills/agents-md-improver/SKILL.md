---
name: agents-md-improver
description: Audit or improve Codex AGENTS.md project guidance when the user asks to maintain agent instructions or project context.
---

Find AGENTS.md files with rg --files --hidden -g AGENTS.md -g '!**/.git/**'.
Read repository and parent guidance. Check that commands work, architecture
matches code, rules are scoped correctly, and instructions add useful knowledge
without duplicating skills or defaults. Use references/ quality criteria when useful.

Present specific proposed changes and obtain approval for a multi-file rewrite.
Preserve explicit constraints and repository topology. Update only Codex guidance.
CLAUDE.md and Claude settings are read-only unless independently requested.
Global guidance belongs in ~/dev/dotfiles/codex/AGENTS.md, rules in codex/rules/,
machine-only context in ignored codex/local/. Do not assume @file imports or # shortcuts.
