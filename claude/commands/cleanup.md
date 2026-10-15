---
description: Remove the worktrees, merged branches and build output this session used, keeping anything dirty, unpushed, in use or with an open PR
argument-hint: "[extra worktree names or paths; default: the ones this session worked in]"
allowed-tools: Bash(python3 ~/.claude/scripts/session_cleanup.py:*)
---

Clean up after this session. Extra worktrees named by the user: $ARGUMENTS

1. If your shell's working directory is inside a linked worktree, `cd` to that
   repo's main checkout in a call of its own first: the script keeps any
   worktree the shell is inside.
2. Run this as one call, with no `cd` in it and a 600000 ms timeout (deleting
   a large `target/` takes minutes):

   ```sh
   python3 ~/.claude/scripts/session_cleanup.py apply $ARGUMENTS
   ```

   It reads this session's transcript to find the linked worktrees it worked in
   or created, adds any named above, and removes each one that is clean, fully
   pushed, unlocked and not in use, together with its build output. A branch
   goes only once its PR merged with the same tip (or the default branch holds
   it); an open PR keeps its branch. It also deletes this session's test-runner
   copies, never forces anything, and lists the repos' other worktrees as left
   alone. Use `plan` instead of `apply` to preview without changing anything.
3. Reply in a few lines from its output: what was removed and the space freed,
   the branches deleted and why, everything kept with its reason, and what was
   left alone. Pass on any `Note:` lines. If worktrees the user expected show
   up as left alone (typical after `/clear`, whose transcript starts empty),
   tell them to rerun with the names: `/cleanup latency cs-latency`.
4. For each kept item, name the step that would free it (commit and push, merge
   the PR, wait for the other session, or `/cleanup <name>` to skip the
   other-session check) and stop. Never remove a kept worktree or branch
   yourself with `--force`, `rm -r` or `git branch -D` unless the user asks for
   that one by name.
