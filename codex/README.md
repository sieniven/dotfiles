# Personal Codex harness

`dotfiles/codex` is the maintained source of truth. It is an independent port
of the active Claude configuration, including merged
[PR #28](https://github.com/sieniven/dotfiles/pull/28). Updating this tree never
updates Claude configuration, and no installed link points to `dotfiles/claude`.

## Installation

```sh
cd ~/dev/dotfiles
python3 codex/scripts/validate.py
python3 -m unittest discover -s codex/hooks/tests -v
python3 codex/scripts/install.py          # preview
python3 codex/scripts/install.py --apply  # install symlinks, back up replacements
```

The installer archives replaced customization under
`~/.codex/backups/dotfiles-<timestamp>/` before installing these links:

| Local path | Repository target |
|------------|-------------------|
| `~/.codex/config.toml` | `codex/config.toml` |
| `~/.codex/AGENTS.md` | `codex/AGENTS.md` |
| `~/.codex/hooks.json` | `codex/hooks.json` |
| `~/.codex/{hooks,rules,agents,scripts}` | Matching Codex directories |
| `~/.codex/local` | Ignored `codex/local/` |
| `~/.agents/skills/<name>` | `codex/skills/<name>` |

User skills use the current supported `.agents/skills` location. Old custom
`~/.codex/skills/{trading,crypto-struct,rust}` and duplicate same-name user copies
are retired into the backup. Codex-owned `.system` skills, credentials,
conversations, databases and installed connector plugins stay in place.
`local/installation.json` records links and the restore manifest. Installation
is idempotent; later runs only replace changed destinations.

**Restart Codex and open `/hooks` to review and trust the new hook definitions.**
Codex skips non-managed hooks until their current hashes are trusted. The
installer does not bypass trust or silently modify its trust database. Changes
to definitions can require another review. Native command rules apply after
restart independently of hook trust.

## Maintaining the source

Edit `codex/` files directly, or their local symlink paths. Both reach the same
repository files. Codex may also update linked `config.toml` for UI preferences
and `rules/default.rules` when the user accepts command approvals; inspect these
diffs before committing. Do not place credentials or tokens in tracked files.

`local/AGENTS.local.md` and `local/engine-middleware.md` are independent,
untracked copies of machine-only test routing. Existing named test runners under
`~/.cache/claude-scratch/` are real machine dependencies; the port does not rename
or edit them. A new machine supplies its own local context. `AGENTS.md` explicitly
routes to it, and SessionStart/SubagentStart inject it when trusted.

For a later Claude resync, create a separate review directory:

```sh
python3 codex/scripts/import_claude.py --output <empty-review-directory>
```

The importer reads Claude only and refuses a nonempty output. Compare the
snapshot with maintained Codex files and merge useful changes; never replace
native Codex adapters blindly. Runtime hooks and installation need only Python's
standard library. Import/validation additionally need PyYAML.

## What was ported

- Global preferences, machine context, repo-document fallback, Rust/Python/Go rules.
- 14 active custom skills, 23 AWS skills with all references/scripts/assets,
  4 portable document skills, 6 commands, 3 plugin workflows, 3 language skills
  and 4 adapted synced/loop workflows: **57 skills** total.
- 11 custom agents and 7 review/simplifier plugin agents: **18 native roles**.
  Explicit skill preloads become instructions to read the skill. Read-only
  roles use a read-only sandbox; only available tools may be used.
- AWS MCP uses the same command/arguments as the active Claude configuration.
  `uvx` is currently missing on this machine, so the server cannot start until
  that dependency is installed. Its credentials and live connectivity were not tested.
- Command guards, protected edits, format tracking, verification/debug stop
  checks, handoffs and compaction suggestions use native Codex hooks.

The main model is `gpt-6.1-sol` at xhigh effort. Default subagents use that model
at medium effort. Opus roles map to `gpt-6-astra`, Sonnet roles to `gpt-6.1-sol`,
with explicit medium/high effort; these are workflow mappings, not identical
model capabilities. Both slugs were verified in the local account model catalog.

## Compatibility and limits

| Claude feature | Codex port |
|----------------|------------|
| `CLAUDE.md` | Independent global `AGENTS.md`; existing repo Claude guidance is read-only fallback when native guidance is absent |
| `@CLAUDE.local.md` | Explicit local-context instructions and lifecycle loader |
| Language `paths:` rules | Language skills plus a tool-event context loader; read matching rules explicitly for diffs or unrecognized read tools |
| Commands | `$handoff`, `$pickup`, `$learn`, `$deep`, `$blockchain-unit-test`, `$xlayer-devnet` |
| Advisor / Workflow | Explicitly approved native delegation and verifier review; no pretend advisor or Workflow API |
| Agent memory | Proposed durable notes via `$learn`, or Codex handoffs; existing Claude session memories are not imported |
| Ralph plugin | `$ralph-loop` with immutable check, iteration cap and progress stop condition |
| Review plugins | Native roles and `$code-review` / `$review-pr`; no automatic external comments or code edits |
| LSP plugin registration | Language rules and installed toolchains; Claude LSP plugins are not registered in Codex |
| Telegram / Greptile | Not activated: their transports/auth require a separate setup |
| Claude desktop/browser/docs tools | Use actual available Codex tools and installed Google Drive plugin; those Claude runtime skills are not copied as working capabilities |
| Synced morning/research/memory | Portable workflows with explicit unavailable-source/tool behavior |
| Broad Bash permission globs | Workspace sandbox with on-request approvals, narrow native prefixes and guards; arbitrary interpreters are not broadly pre-approved |

**Approval-required hooks:** Codex currently parses but does not support
`PreToolUse permissionDecision: ask`. This port returns `deny` and a pending
request id. The user can review and approve that exact operation once:

```sh
python3 ~/.codex/hooks/authorize.py <request-id>
```

Only the user runs that interactive command; agents must never run it. The
grant is bound to session, turn, cwd and exact tool input, expires in ten minutes,
and is consumed on retry. Hard denials such as merging, nohup, known secrets or
protected history cannot be granted. This is deliberately stricter than a
Claude inline permission prompt. It also guards pushes; no push is authorized
by this migration.

Hook state lives under `~/.local/state/codex-hooks/` (or `CODEX_HOOK_STATE_DIR`),
never Claude state. Handoffs digest stable tool events, not Claude JSONL. Command
outcomes are unknown unless an exit code is observed; only a successful check
after the last edit counts as verification. `Stop` formatting changes require
another check or an explicit unverified report. `$handoff` accepts `--session`
or `--file` if `CODEX_THREAD_ID` is unavailable. New sessions get a pointer only;
a `clear` event never injects old task state. Native tool hooks do not cover every
hosted/specialized tool path or shell-written file; written rules still apply.

Guard implementation errors retain the original fail-open behavior and print
diagnostics. Hooks supplement the sandbox and do not replace it. Behavioral
model compliance has not been measured by structural validation or unit tests;
`$skill-comply` requires a separately approved scenario run.

## Validation and provenance

`migration-manifest.json` records imported inputs, source hashes, role mappings,
final skill names and PR #28 provenance. Local source snapshots remain ignored.
PR #28 updated the Claude checkout externally during migration; that one update
is recorded in `local/concurrent-source-update.json`, and later comparisons use
the merged baseline. The migration itself made no Claude edits.

The installed Codex 0.162.0 strict parser loaded this config. Unit tests cover
wrapped command guards, secrets, linked-worktree test exemptions, symlinked
harness protection, native patches, exact one-use grants, verification order,
failed/unknown results and isolated handoffs. The installer has a fake-home
smoke test covering backups, links, idempotence and preservation of auth/system
skills. These are offline checks; no model calls or live trading actions are used.

Official references:
[skills](https://learn.chatgpt.com/docs/build-skills),
[configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
[hooks and trust](https://learn.chatgpt.com/docs/hooks),
[command rules](https://learn.chatgpt.com/docs/agent-configuration/rules).
