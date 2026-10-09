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
| `session_handoff.py` | SessionStart, PreCompact, SessionEnd | Keeps one handoff file per session under `~/.local/state/claude-hooks/handoffs/<project>/`: a snapshot digested from the transcript (requests, files changed, commands with ✓/✗, open todos, last reply) plus the narrative `/handoff` writes. Saves it before compaction and restores it right after. `/clear` starts fresh; a new session gets a one-line pointer to the previous goal; `/pickup` loads a handoff on request (`session_handoff.py previous`) |
| `suggest_compact.py` | PostToolUse `*`, SessionStart `compact` | Counts tool calls per session; at 60 and every 40 after, tells Claude to suggest `/handoff` + `/compact` at the next phase boundary. Resets on compaction |
| `format_tracker.py` | PreToolUse `Edit\|Write\|MultiEdit` | On the first touch of a `.rs`/`.py` file per session, records whether it was already `rustfmt`/`ruff format` clean (ruff only where the project configures it) |
| `stop_gate.py` | Stop | Formats edited files that were clean or new, once, instead of after every edit. Then blocks once (never when `stop_hook_active`) if code edited this turn still has debug leftovers (`dbg!`, `todo!`, `breakpoint()`, `pdb`, `console.log`, `debugger`) outside tests, or if no build/test/lint command or verifying subagent ran after the last code edit — unless the reply already says the change is unverified |
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
| `CLAUDE_HANDOFF_MAX_CHARS` | Cap on handoff text injected at SessionStart (default 8000) |
| `CLAUDE_HANDOFF_KEEP` / `CLAUDE_HANDOFF_MAX_AGE_DAYS` | Handoff files kept per project (30) / max age of the startup pointer (7 days) |
| `CLAUDE_COMPACT_SUGGEST_AT` / `_EVERY` | Compaction suggestion thresholds (60 / 40 tool calls) |
| `CLAUDE_VERIFY_PATTERNS` | Regex for extra commands that count as verification at Stop — set it to the machine's named-test runner |
| `CLAUDE_HOOK_STATE_DIR` | Where stateful hooks keep per-session state (default `~/.local/state/claude-hooks`) |

Check ids: `bash-guard:{merge,nohup,no-verify,force-push,direct-tests,destructive,secrets}`,
`edit-guard:{lint-config,secrets,prod-config,harness}`. Hook ids: `bash-guard`,
`edit-guard`, `session-handoff`, `suggest-compact`, `stop-gate`
(`stop-gate:{format,debug,verify}`).

Limits: the stop gate sees edits made with Edit/Write/MultiEdit, not files
rewritten by shell commands, and it checks that verification *ran*, not
that it passed — reporting failures honestly stays Claude's job.

## Tests

```sh
python3 -m unittest discover -s claude/hooks/tests -v
```

## Writing a hook

Read one JSON object from stdin, print nothing unless there is a decision or
context to return, and use the helpers in `_common.py` (`run`, `enabled`,
`pre_tool_decision`, `additional_context`). Keep PreToolUse hooks fast
(tens of milliseconds); anything slow belongs in an `async` hook or at `Stop`.
