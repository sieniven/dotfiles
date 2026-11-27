# dotfiles

Repo-specific rules for the Claude Code harness in `claude/`; the global rules it
links into `~/.claude` are in `claude/CLAUDE.md`.

- The dotfiles CI runs `scripts/check` (lint, Claude hook tests, Codex validate and
  Codex hook tests); run it locally before pushing harness or Codex changes.
- How `~/.claude` is wired to this repo (what is linked, what is copied, the
  `CLAUDE.local.md` requirement) is in `claude/hooks/README.md` under Install.
