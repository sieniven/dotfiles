---
name: pr-create
description: Open a GitHub pull request and write its body in the user's house
  style — pre-flight checks, section flow, voice, and the stop-at-creation
  rule. Use when asked to open, create, or raise a PR, or to write a PR
  description.
---

# Pull Request Creation

## Hard rules

- **Stop at creation.** Create it, return the URL. Never `gh pr merge`, never
  `--auto`, never merge into a shared branch — even if a repo convention says
  "PR + auto-merge".
- **Push only the PR's own branch.** No force-push, no history rewrite.
- **Never claim a test or check that was not actually run.**
- **Never commit on the user's behalf** to make the PR look complete.

## Pre-flight

```sh
git status --short
git branch -vv                                   # real branch name + tracking
git log --oneline origin/<base>..HEAD
gh pr list --state all --limit 10
```

- Base is `main` unless told otherwise. 0 commits ahead means nothing to open.
- A PR already open for this head → `gh pr edit`, don't open a second.
- Branch ahead of upstream or untracked → `git push -u origin <branch>`.
  Already in sync → don't push, and say so.
- **Uncommitted work stays uncommitted.** Open from the committed state and
  name the excluded files in a trailing note.

Commit bodies are the best source for the summary:
`git log origin/<base>..HEAD --format='=== %s%n%b'`

## Body structure

`## Summary` is the only required heading. Most PRs are just this:

```markdown
## Summary

This PR <verb>s <what>, to <why>. <link to the driving issue/PR, if any>

1. <change, naming the real symbol in `backticks`> — <what it does now>
2. <change> — <behavioural consequence>

Note - <invariant, caveat, or backwards-compat detail the reviewer must know>
```

**Always keep PR summaries short and sweet, straight to the point.** Every
other section is optional — add one only when it earns its place, and in this
order:

- `## Architecture` — the shape of a new component: what it is, where it sits,
  and the design decisions and trade-offs behind it. Earns its place when the
  PR introduces a new feature or component, not when it changes one.
- `## Implementation` — how a complex new feature actually works: control
  flow, key data structures, performance optimizations and their trade-offs.
  Earns its place when the numbered list above cannot carry the detail a
  reviewer needs.
- `## Breaking changes` — what breaks, and what callers must do. Required
  whenever a public interface signature, config flag, wire format, or default
  changes.
- `## Interfaces introduced` — new public surface, one line per item, exact
  names. Skip when the numbered list above already covers it (it usually does).
- `## Test coverage` — the unit and functional tests covering the diff, when
  that coverage is worth spelling out. Only tests actually run.

## Voice

- Open with "This PR ..." — declarative, present tense: *enables / adds /
  optimizes / merges / splits*.
- Once there is more than one distinct change, use a numbered list, not prose.
- One clause of *why*. Link the issue instead of restating its context.
- `Note -` / "Note that ..." carries caveats and backwards-compat.
- `Nits:` numbered list for minor secondary changes worth mentioning.
- Dense and technical is fine. Marketing adjectives are not.

Two of the user's own, trimmed:

> This PR enables the sharing of the payload processor, so that other external
> customized components are able to leverage on the payload processor's
> optimized caches and payload processing logic.
>
> Note - the state consistency is guaranteed on the customizer's end, and the
> payload processor cache states require an engine validator controller for
> atomic payload validation operations.

> This PR merges the previous separate ledger + index maps into a single
> StorageDoubleMap per side, eliminating the need for maintaining 2 state
> tries and dual-write overhead.

## Execution

Quoted heredoc, so backticks and `$` survive the shell:

```sh
gh pr create --base main --head <branch> \
  --title "<type>(<scope>): <subject>" \
  --body "$(cat <<'EOF'
## Summary
...
EOF
)"
```

- Title: conventional commits, `<type>(<scope>): <subject>`, <=72 chars.
- `--draft` when the branch is knowingly incomplete.
- **No `🤖 Generated with` footer on PR bodies** — that convention is for
  commits (see [git-commit](../git-commit/SKILL.md)); the user's own PRs
  don't carry it.

## Reply to the user

The URL, then a few lines: title and scale (commits, files, head → base),
anything that differed from what they asked, and what was left out. Confirm
creation only — no merge.
