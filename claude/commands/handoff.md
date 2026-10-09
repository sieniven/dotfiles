---
description: Write the session handoff narrative (worked / failed / not tried / next) so the next session or post-compaction context can pick up cleanly
argument-hint: "[optional focus, e.g. \"the hedger latency investigation\"]"
---

Record a handoff for this session. Focus: $ARGUMENTS

1. Find this session's handoff file. It was named in context at session start
   ("Session handoff file: ..."). If you can't find it, run
   `python3 "$HOME/.claude/hooks/session_handoff.py" latest --cwd "$PWD"`.
2. Write the narrative from what actually happened in this session — evidence
   over impressions. Use exactly these sections, each a short bullet list:

   ### Goal
   One or two lines: what the user is trying to achieve.

   ### What worked
   Approaches that were verified, each with its evidence: the command, test,
   metric or `path:line` that shows it.

   ### What failed
   Approaches tried and abandoned, and why — the error, the counterexample, or
   the number that ruled each out — so nobody retries them blind.

   ### Not tried yet
   Options considered but not attempted, with why they might matter.

   ### Next steps
   The concrete next actions in order, and anything unverified that must be
   checked first. Name open questions for the user.

3. Save it by piping the narrative into the handoff script (this also refreshes
   the mechanical snapshot of files, commands and todos):

   ```sh
   python3 "$HOME/.claude/hooks/session_handoff.py" narrate --file "<path>" <<'EOF'
   ### Goal
   ...
   EOF
   ```

4. Reply with the file path and a two-line summary. Tell the user they can now
   `/clear` (or quit) and run `/pickup` in the fresh session to continue from
   this handoff, or `/compact` to keep going here.
