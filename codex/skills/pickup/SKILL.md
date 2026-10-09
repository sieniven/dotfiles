---
description: Continue earlier work in this fresh session by loading the latest session handoff for this repo (pairs with /handoff before /new)
name: pickup
---

Pick up earlier work from a session handoff. Target: the user's supplied task or focus

1. Find the handoff to load:
   - If a path was given above, use it.
   - Otherwise run
     `python3 "$HOME/.codex/hooks/session_handoff.py" previous --cwd "$PWD"`.
     It skips this session's own file (found from `$CODEX_THREAD_ID`).
   - If none is found, say so and stop.
2. Read the whole file. It has the narrative (goal, what worked, what failed,
   not tried, next steps) and a snapshot (recent requests, files changed,
   commands with ✓/✗, open todos, last reply).
3. Check it is still current before trusting it: the branch it names, and
   whether the files it lists changed since (`git status`, `git log -3`).
   Call out anything that moved.
4. Reply with: the goal in one line, where it stopped, the first next step,
   and anything it marked unverified. Then wait for my go-ahead before acting
   on it — the handoff is context, not an instruction.
