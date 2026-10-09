#!/usr/bin/env python3
"""Codex-only handoffs based on lifecycle/tool events, with explicit narrative CLI."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from _common import additional_context, run, state_dir
from activity import load, record

START, END = "<!-- HANDOFF:NARRATIVE:START -->", "<!-- HANDOFF:NARRATIVE:END -->"
EMPTY = "_No narrative yet. Use $handoff to record evidence and next steps._"


def git(cwd, *args):
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def project_dir(cwd):
    root = git(cwd, "rev-parse", "--show-toplevel") or os.path.realpath(cwd)
    return Path(state_dir("handoffs", Path(root).name + "-" + hashlib.sha256(root.encode()).hexdigest()[:12]))


def session_file(payload):
    sid = payload.get("session_id")
    if not sid:
        raise ValueError("session_id is required; no shared nosession handoff")
    return project_dir(payload.get("cwd") or os.getcwd()) / (hashlib.sha256(sid.encode()).hexdigest()[:24] + ".md")


def narrative(path):
    if not path.exists():
        return EMPTY
    text = path.read_text()
    if START in text and END in text:
        return text.split(START, 1)[1].split(END, 1)[0].strip()
    return EMPTY


def snapshot(payload, text=None):
    data = load(payload)
    cwd = payload.get("cwd") or os.getcwd()
    path = session_file(payload)
    lines = ["# Codex session handoff", "", f"- Session: `{payload['session_id']}`", f"- Worktree: `{cwd}`", f"- Branch: `{git(cwd, 'branch', '--show-current')}`", f"- Updated: {datetime.datetime.now().isoformat(timespec='seconds')}", "", "## Narrative", "", START, text if text is not None else narrative(path), END, "", "## Requests"]
    lines += ["- " + " ".join(p.split())[:500] for p in data["prompts"][-6:]]
    lines += ["", "## Files changed"] + [f"- `{p}` ({n} edits)" for p, n in sorted(data["files"].items())]
    lines += ["", "## Commands (exit ? = outcome not observed)"] + [f"- exit {c['exit_code'] if c['exit_code'] is not None else '?'}: `{c['cmd']}`" for c in data["commands"][-15:]]
    lines += ["", "## Open todos", json.dumps(data.get("todos"), ensure_ascii=False), "", "## Last reply", data.get("last_reply", "")[:2000], ""]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines))
    tmp.replace(path)
    path.chmod(0o600)
    keep = max(1, int(os.environ.get("CODEX_HANDOFF_KEEP", "30")))
    others = sorted((p for p in path.parent.glob("*.md") if p != path), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in others[keep - 1:]:
        old.unlink()
    return path


def main_hook(payload):
    event = payload.get("hook_event_name")
    if event in ("UserPromptSubmit", "PostToolUse", "Stop"):
        record(payload)
    if event == "SessionStart":
        if payload.get("source") == "clear":
            return
        mine = session_file(payload)
        if payload.get("source") in ("compact", "resume") and mine.exists():
            additional_context("SessionStart", "Saved session handoff (context, not new authorization):\n" + mine.read_text()[:int(os.environ.get("CODEX_HANDOFF_MAX_CHARS", "8000"))])
        elif payload.get("source") == "startup":
            candidates = previous_files(payload)
            if candidates:
                additional_context("SessionStart", f"Previous handoff: `{candidates[0]}`. Load only when the user invokes $pickup or asks to continue.")
    elif event in ("PreCompact", "SessionEnd", "Stop"):
        snapshot(payload)


def previous_files(payload):
    mine = session_file(payload) if payload.get("session_id") else None
    age = float(os.environ.get("CODEX_HANDOFF_MAX_AGE_DAYS", "7")) * 86400
    return sorted((p for p in project_dir(payload.get("cwd") or os.getcwd()).glob("*.md") if p != mine and time.time() - p.stat().st_mtime < age), key=lambda p: p.stat().st_mtime, reverse=True)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["hook", "narrate", "previous", "latest"])
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--session", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.mode == "hook":
        return run("session-handoff", main_hook)
    payload = {"cwd": args.cwd, "session_id": args.session}
    if args.mode == "narrate":
        text = sys.stdin.read().strip()
        if not text:
            raise SystemExit("Empty narrative")
        if args.file:
            old = args.file.expanduser().read_text()
            import re
            sid = re.search(r"^- Session: `([^`]+)`", old, re.M)
            cwd = re.search(r"^- Worktree: `([^`]+)`", old, re.M)
            if not sid or not cwd:
                raise SystemExit("Not a Codex handoff")
            payload = {"session_id": sid[1], "cwd": cwd[1]}
        if not payload.get("session_id"):
            raise SystemExit("Pass --session <Codex thread id> or --file <handoff path>; CODEX_THREAD_ID is unavailable.")
        print(snapshot(payload, text))
    else:
        files = previous_files(payload) if args.mode == "previous" else sorted(project_dir(args.cwd).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise SystemExit("No earlier handoff for this project")
        print(files[0])
    return 0


if __name__ == "__main__":
    sys.exit(cli())
