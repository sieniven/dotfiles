# dotfiles

Repo-specific rules for the Claude Code harness in `claude/`; the global rules it
links into `~/.claude` are in `claude/CLAUDE.md`.

- The dotfiles CI runs `claude/scripts/lint_harness.py` and the hook tests; run both
  locally before pushing harness changes.
- How `~/.claude` is wired to this repo (what is linked, what is copied, the
  `CLAUDE.local.md` requirement) is in `claude/hooks/README.md` under Install.
