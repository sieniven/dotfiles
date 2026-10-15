---
name: cleanup
description: Remove the git worktrees, merged branches and build output this session used, keeping anything dirty, unpushed, in use or with an open PR. Use at the end of a session, or when asked to clean up its worktrees.
---

Clean up after this session. Extra worktrees named by the user: the user's
supplied worktree names or paths, if any.

1. If the shell's working directory is inside a linked worktree, run the
   command below from that repo's main checkout instead (its `workdir`): the
   script keeps any worktree the shell is inside.
2. Run it as one command, outside the sandbox (request escalated permissions:
   it calls `gh` over the network and removes worktrees in other repos), with
   a timeout of ten minutes (deleting a large `target/` takes minutes):

   ```sh
   python3 "$HOME/.codex/scripts/session_cleanup.py" apply <names>
   ```

   It reads this session's activity record (`$CODEX_THREAD_ID`) to find the
   linked worktrees it worked in or created, adds any named, and removes each
   one that is clean, fully pushed, unlocked and not in use, together with its
   build output. A branch goes only once its PR merged with the same tip (or
   the default branch holds it); an open PR keeps its branch. It never forces
   anything, and lists the repos' other worktrees as left alone. Use `plan`
   instead of `apply` to preview without changing anything.
3. Reply in a few lines from its output: what was removed and the space freed,
   the branches deleted and why, everything kept with its reason, and what was
   left alone. Pass on any `Note:` lines. If worktrees the user expected show
   up as left alone (typical after `/new`, or for a session recorded before
   the activity trail existed), tell them to rerun with the names:
   `$cleanup latency cs-latency`.
4. For each kept item, name the step that would free it (commit and push, merge
   the PR, wait for the other session, or `$cleanup <name>` to skip the
   other-session check) and stop. Never remove a kept worktree or branch
   yourself with `--force`, `rm -r` or `git branch -D` unless the user asks for
   that one by name.
