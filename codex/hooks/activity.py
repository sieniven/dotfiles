"""Track stable Codex hook events instead of parsing a private transcript format."""
import json
import fcntl
from pathlib import Path
import re

from _common import state_dir
from patches import edits, full_path


def state_path(payload):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", payload.get("session_id") or "nosession")[:100]
    return Path(state_dir("activity")) / (sid + ".json")


def load(payload):
    try:
        data = json.loads(state_path(payload).read_text())
        data["events"] = data.get("turns", {}).get(payload.get("turn_id") or "root", [])
        return data
    except (OSError, ValueError):
        return {"events": [], "prompts": [], "files": {}, "commands": [], "todos": None, "last_reply": ""}


def save(payload, data):
    path = state_path(payload)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _record(payload):
    data = load(payload)
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        turn = payload.get("turn_id")
        # Turn-scoped events keep child verification from passing a parent's
        # pending edits. Steering within the same turn keeps its events.
        data["turn_id"] = turn
        data["prompts"] = (data["prompts"] + [payload.get("prompt", "")[:1000]])[-12:]
    elif event == "PostToolUse":
        name = payload.get("tool_name")
        inp = payload.get("tool_input") or {}
        response = payload.get("tool_response") or {}
        response_text = json.dumps(response)
        failed = (isinstance(response, dict) and (response.get("isError") or response.get("is_error") or response.get("success") is False)) or bool(re.search(r"apply_patch verification failed|Failed to apply patch|invalid patch", response_text, re.I))
        if name == "apply_patch":
            if not failed:
                for edit in edits(payload):
                    path = full_path(edit)
                    normalized = dict(edit["tool_input"], file_path=path)
                    data["events"].append([edit["tool_name"], normalized])
                    data["files"][path] = data["files"].get(path, 0) + 1
        elif name in ("Bash", "exec_command"):
            command = inp.get("command") or inp.get("cmd") or ""
            exit_code = response.get("exit_code") if isinstance(response, dict) else None
            if exit_code is None:
                m = re.search(r'(?:Process exited with code|exit_code["\s:]+)\s*(-?\d+)', response_text)
                exit_code = int(m[1]) if m else None
            data["events"].append(["Bash", {"command": command, "exit_code": exit_code}])
            data["commands"] = (data["commands"] + [{"cmd": command[:500], "exit_code": exit_code}])[-30:]
        elif name == "update_plan":
            data["todos"] = inp.get("plan")
        data["events"] = data["events"][-1000:]
    elif event in ("Stop", "SubagentStop"):
        data["last_reply"] = payload.get("last_assistant_message") or ""
    turns = data.setdefault("turns", {})
    turns[payload.get("turn_id") or "root"] = data["events"]
    while len(turns) > 30:
        del turns[next(iter(turns))]
    save(payload, data)
    return data


def record(payload):
    with state_path(payload).with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _record(payload)
