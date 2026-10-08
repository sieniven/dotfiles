# Claude Code hooks

Deterministic enforcement for the rules in `../CLAUDE.md`. Prose rules are
requests; these hooks make the important ones binding. Registered in
`../settings.json`; installed as `~/.claude/hooks/` (link this directory
alongside `CLAUDE.md`, `agents/`, `skills/`).

Python 3.8+ stdlib only, so macOS's system `python3` runs them. Every hook
fails open: an internal error prints to stderr and the tool call proceeds.

| Hook | Event | What it does |
|------|-------|--------------|
| `bash_guard.py` | PreToolUse `Bash` | Denies `gh pr merge`, `nohup`, `--no-verify`, force-push/delete of `main`/`master`, direct `cargo test`/`just test` where `CLAUDE.local.md` routes tests elsewhere, `rm -r` of `/`/`~`, and commits that add private keys, known token formats or `.env`/key files. Asks before other force-pushes, `git reset --hard`, `git clean -f`, `rm -r .`/`..`, docker volume prunes, and generic `password = "..."` assignments in a commit |
| `edit_guard.py` | PreToolUse `Edit\|Write\|MultiEdit` | Asks before changing lint/format config (incl. lint tables in `pyproject.toml`/`Cargo.toml` and new crate-level `#![allow]`), `.env`/key files, production/live/risk-limit config, and the harness itself. New files are always allowed |

`bash_guard.py` parses the command, so `cd x && gh pr merge`, `bash -c '...'`,
`timeout 60 cargo test` and `$(...)` are all seen, while text inside quoted
arguments and heredoc bodies (commit messages) is not.

## Switches

| Variable | Effect |
|----------|--------|
| `CLAUDE_HOOKS=off` | Disable every hook here |
| `CLAUDE_HOOKS_DISABLE=a,b` | Disable hook ids (`bash-guard`) or single checks (`bash-guard:secrets`) |
| `CLAUDE_GUARD_DIRECT_TESTS=1\|0` | Force the direct-test check on/off (default: on iff `~/.claude/CLAUDE.local.md` mentions `cargo test`) |
| `CLAUDE_PROTECTED_BRANCHES=a,b` | Extra protected branches besides `main`, `master` |
| `CLAUDE_PROTECTED_PATHS=glob,...` | Extra files `edit_guard` asks about (fnmatch on the absolute path) |
| `CLAUDE_HOOK_STATE_DIR` | Where stateful hooks keep per-session state (default `~/.local/state/claude-hooks`) |

Check ids: `bash-guard:{merge,nohup,no-verify,force-push,direct-tests,destructive,secrets}`,
`edit-guard:{lint-config,secrets,prod-config,harness}`.

## Tests

```sh
python3 -m unittest discover -s claude/hooks/tests -v
```

## Writing a hook

Read one JSON object from stdin, print nothing unless there is a decision or
context to return, and use the helpers in `_common.py` (`run`, `enabled`,
`pre_tool_decision`, `additional_context`). Keep PreToolUse hooks fast
(tens of milliseconds); anything slow belongs in an `async` hook or at `Stop`.
