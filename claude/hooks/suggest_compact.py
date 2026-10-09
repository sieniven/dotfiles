#!/usr/bin/env python3
"""PostToolUse: suggest a handoff + /compact at a phase boundary.

Auto-compaction fires when the window is full, which is usually mid-change.
This counts tool calls per session and, at CLAUDE_COMPACT_SUGGEST_AT calls
(default 60) and every CLAUDE_COMPACT_SUGGEST_EVERY after (default 40), adds
a one-line note to Claude's context: at the next natural boundary, suggest
/handoff then /compact. SessionStart(compact) resets the count via
`suggest_compact.py reset`.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import additional_context, run, state_dir  # noqa: E402

HOOK = "suggest-compact"
FIRST = int(os.environ.get("CLAUDE_COMPACT_SUGGEST_AT", "60"))
EVERY = int(os.environ.get("CLAUDE_COMPACT_SUGGEST_EVERY", "40"))


def counter_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id or "nosession")[:64]
    return os.path.join(state_dir("tool-counts"), sid + ".json")


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"count": 0}


def save(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh)


def on_tool(payload):
    path = counter_path(payload.get("session_id"))
    data = load(path)
    data["count"] = data.get("count", 0) + 1
    save(path, data)
    n = data["count"]
    if n == FIRST or (n > FIRST and EVERY > 0 and (n - FIRST) % EVERY == 0):
        additional_context(
            "PostToolUse",
            "[suggest-compact] %d tool calls since the last compaction. At the next natural phase boundary "
            "(plan agreed, tests green, before switching subtask), suggest the user run /handoff then /compact. "
            "Do not suggest it in the middle of a change." % n,
        )


def on_reset(payload):
    save(counter_path(payload.get("session_id")), {"count": 0})


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "tool"
    sys.exit(run(HOOK, on_reset if mode == "reset" else on_tool))
