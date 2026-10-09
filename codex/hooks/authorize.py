#!/usr/bin/env python3
"""Human-only approval of an exact protected operation.

Run this command yourself after reviewing the printed request. Agents must
never invoke it. Grants expire after 10 minutes and are consumed on retry.
Hard denials (merge, nohup, secrets, protected history) cannot be approved.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from _common import state_dir


def request_key(payload):
    identity = {k: payload.get(k) for k in ("session_id", "turn_id", "cwd", "tool_name", "tool_input")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def consume(payload):
    path = Path(state_dir("approvals")) / (request_key(payload) + ".approved.json")
    try:
        data = json.loads(path.read_text())
        path.unlink()
        return time.time() - data["approved_at"] < 600
    except (OSError, ValueError, KeyError):
        return False


def pending(payload, reason):
    key = request_key(payload)
    path = Path(state_dir("approvals")) / (key + ".request.json")
    path.write_text(json.dumps({"reason": reason, "payload": payload, "created_at": time.time()}, indent=2))
    path.chmod(0o600)
    return key


def main():
    if len(sys.argv) != 2 or not all(c in "0123456789abcdef" for c in sys.argv[1]) or len(sys.argv[1]) != 24:
        raise SystemExit("Usage (human only): python3 ~/.codex/hooks/authorize.py <request-id>")
    base = Path(state_dir("approvals"))
    src = base / (sys.argv[1] + ".request.json")
    data = json.loads(src.read_text())
    if time.time() - data["created_at"] >= 600:
        raise SystemExit("Request expired; retry the tool to create a new request.")
    print(data["reason"])
    print(json.dumps(data["payload"].get("tool_input"), indent=2))
    if input("Approve this exact operation once? [y/N] ").strip().lower() != "y":
        raise SystemExit("Not approved")
    dest = base / (sys.argv[1] + ".approved.json")
    dest.write_text(json.dumps({"approved_at": time.time()}))
    dest.chmod(0o600)
    src.unlink()
    print("Approved once for this session and turn. Retry the same tool call.")


if __name__ == "__main__":
    main()
