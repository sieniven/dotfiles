"""Shared helpers for the Codex hooks in this directory.

Every hook reads one JSON object on stdin and answers on stdout. A hook with
nothing to say prints nothing. Hooks fail open: an internal error is reported
on stderr and the tool call proceeds, because a crashing guard must never
wedge the session.

Runtime switches (environment):
  CODEX_HOOKS=off                  disable every hook here
  CODEX_HOOKS_DISABLE=a,b:c        disable hook ids or single check ids
"""

import json
import os
import sys
import traceback

MAX_STDIN = 1024 * 1024
CURRENT_PAYLOAD = {}


def read_input():
    raw = sys.stdin.read(MAX_STDIN)
    if not raw.strip():
        return {}
    return json.loads(raw)


def _disabled_set():
    return {x.strip() for x in os.environ.get("CODEX_HOOKS_DISABLE", "").split(",") if x.strip()}


def hooks_off():
    return os.environ.get("CODEX_HOOKS", "").lower() in ("0", "off", "false", "disabled")


def enabled(check_id):
    """True unless the hook or this check is switched off.

    `check_id` is `hook-id` or `hook-id:check`; disabling `hook-id` disables
    all of its checks.
    """
    if hooks_off():
        return False
    disabled = _disabled_set()
    hook_id = check_id.split(":", 1)[0]
    return check_id not in disabled and hook_id not in disabled


def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")


def pre_tool_decision(decision, reason):
    """PreToolUse answer: decision is "deny" or "ask"."""
    if decision == "ask":
        from authorize import consume, pending
        if consume(CURRENT_PAYLOAD):
            return
        key = pending(CURRENT_PAYLOAD, reason)
        decision = "deny"
        reason += (
            " Codex cannot prompt from PreToolUse yet. The user can approve this exact operation"
            " once in their terminal: python3 ~/.codex/hooks/authorize.py " + key +
            ". Never run that approval command on the user's behalf; never route around this guard."
        )
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }
    )


def additional_context(event, text):
    emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def run(hook_id, main):
    """Run `main(payload)` with fail-open error handling."""
    if not enabled(hook_id):
        return 0
    try:
        global CURRENT_PAYLOAD
        payload = read_input()
        CURRENT_PAYLOAD = payload
        main(payload)
    except Exception:  # noqa: BLE001 - fail open by design
        sys.stderr.write("[%s] internal error, allowing the call:\n" % hook_id)
        traceback.print_exc(file=sys.stderr)
    return 0


def state_dir(*parts):
    """Per-user state directory outside ~/.codex (kept out of the dotfiles repo)."""
    base = os.environ.get("CODEX_HOOK_STATE_DIR") or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state"),
        "codex-hooks",
    )
    path = os.path.join(base, *parts)
    os.makedirs(path, exist_ok=True)
    return path
