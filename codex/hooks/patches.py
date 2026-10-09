"""Normalize Codex apply_patch calls for file guards and change tracking."""
import os


def edits(payload):
    inp = payload.get("tool_input") or {}
    if isinstance(inp, str):
        inp = {"command": inp}
    if payload.get("tool_name") != "apply_patch":
        return [payload] if inp.get("file_path") else []
    patch = inp.get("command") or inp.get("patch") or inp.get("input") or ""
    result, current = [], None
    for line in patch.splitlines():
        for marker, operation in (("*** Add File: ", "Write"), ("*** Update File: ", "Edit"), ("*** Delete File: ", "Edit")):
            if line.startswith(marker):
                current = dict(payload, tool_name=operation, tool_input={"file_path": line[len(marker):], "old_string": "", "new_string": ""})
                result.append(current)
                break
        else:
            if current is None:
                continue
            if line.startswith("*** Move to: "):
                # Protect source and destination of a rename.
                moved = dict(payload, tool_name="Edit", tool_input={"file_path": line[len("*** Move to: "):], "old_string": "", "new_string": ""})
                result.append(moved)
            elif line.startswith("+"):
                current["tool_input"]["new_string"] += line[1:] + "\n"
            elif line.startswith("-"):
                current["tool_input"]["old_string"] += line[1:] + "\n"
    return result


def full_path(payload):
    return os.path.realpath(os.path.join(payload.get("cwd") or os.getcwd(), os.path.expanduser(payload["tool_input"]["file_path"])))
