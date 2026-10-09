#!/usr/bin/env python3
"""Session handoff: persist session state across compaction and new sessions.

One markdown file per session under
  ~/.local/state/claude-hooks/handoffs/<project>/<YYYYmmdd-HHMM>-<session>.md
holding a mechanical snapshot (requests, files changed, commands and their
outcome, open todos, last reply) plus a narrative block (what worked with
evidence, what failed, what was not tried, next steps) written by /handoff.

Hook modes (argv[1]):
  start       SessionStart (registered for startup|resume|compact only, never
              /clear): after `compact`/`resume`, inject this session's
              snapshot; on `startup`, a one-line pointer to the previous
              handoff's goal. A cleared session gets nothing.
  precompact  PreCompact: refresh the snapshot before context is compacted
  end         SessionEnd: refresh the snapshot when the session closes

CLI modes (the session comes from $CLAUDE_CODE_SESSION_ID, which Claude Code
sets for the commands Claude runs, so no hook has to announce a file path):
  narrate [--cwd DIR] [--file PATH]
                        write stdin as this session's narrative and refresh
                        its snapshot (creates the session's file if needed)
  latest [--cwd DIR]    print the newest handoff path for a project
  previous [--cwd DIR] [--exclude PATH]
                        print the newest handoff with content, skipping this
                        session's own file (and PATH); used by /pickup

Env: CLAUDE_HANDOFF_MAX_CHARS (default 8000), CLAUDE_HANDOFF_KEEP (30),
CLAUDE_HANDOFF_MAX_AGE_DAYS for the startup pointer (7).
"""

import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import additional_context, run, state_dir  # noqa: E402

HOOK = "session-handoff"
START, END = "<!-- HANDOFF:NARRATIVE:START -->", "<!-- HANDOFF:NARRATIVE:END -->"
EMPTY_NARRATIVE = "_Not written yet. Run /handoff to record what worked, what failed, what was not tried, and next steps._"
MAX_CHARS = int(os.environ.get("CLAUDE_HANDOFF_MAX_CHARS", "8000"))
KEEP = int(os.environ.get("CLAUDE_HANDOFF_KEEP", "30"))
MAX_AGE_DAYS = float(os.environ.get("CLAUDE_HANDOFF_MAX_AGE_DAYS", "7"))


# --------------------------------------------------------------------------
# Locations


def git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def project_root(cwd):
    return git(cwd, "rev-parse", "--show-toplevel") or os.path.realpath(cwd)


def project_dir(cwd):
    root = project_root(cwd)
    key = re.sub(r"[^A-Za-z0-9._-]+", "-", root.strip("/")) or "root"
    return state_dir("handoffs", key)


def session_file(cwd, session_id, create=True):
    d = project_dir(cwd)
    sid = (session_id or "nosession")[:8]
    found = sorted(glob.glob(os.path.join(d, "*-%s.md" % sid)))
    if found:
        return found[-1]
    if not create:
        return None
    return os.path.join(d, "%s-%s.md" % (datetime.datetime.now().strftime("%Y%m%d-%H%M"), sid))


def current_session():
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def find_transcript(session_id):
    if not session_id:
        return None
    hits = glob.glob(os.path.join(os.path.expanduser("~/.claude/projects"), "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def newest_first(cwd):
    files = glob.glob(os.path.join(project_dir(cwd), "*.md"))
    return sorted(files, key=lambda f: (os.path.getmtime(f), f), reverse=True)


def prune(cwd):
    files = sorted(glob.glob(os.path.join(project_dir(cwd), "*.md")))
    for old in files[:-KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Transcript digest


def clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


NOT_PROMPTS = ("<", "[Request interrupted", "Base directory for this skill:", "Another Claude session sent a message", "Caveat:")


def is_prompt(text):
    return bool(text.strip()) and not text.lstrip().startswith(NOT_PROMPTS)


def digest(transcript_path):
    d = {"prompts": [], "files": {}, "commands": [], "todos": None, "last_reply": ""}
    if not transcript_path or not os.path.exists(transcript_path):
        return d
    pending = {}
    with open(transcript_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("isSidechain") or o.get("type") not in ("user", "assistant"):
                continue
            content = (o.get("message") or {}).get("content")
            if o["type"] == "user":
                if isinstance(content, str):
                    if not o.get("isMeta") and is_prompt(content):
                        d["prompts"].append(clip(content, 300))
                    continue
                for b in content or []:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                        pending.pop(b["tool_use_id"])["error"] = bool(b.get("is_error"))
                    elif b.get("type") == "text":
                        t = b.get("text", "")
                        if not o.get("isMeta") and is_prompt(t):
                            d["prompts"].append(clip(t, 300))
                continue
            for b in content or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    d["last_reply"] = b["text"]
                if b.get("type") != "tool_use":
                    continue
                name, inp = b.get("name"), b.get("input") or {}
                if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                    path = inp.get("file_path") or inp.get("notebook_path") or "?"
                    counts = d["files"].setdefault(path, {})
                    counts[name] = counts.get(name, 0) + 1
                elif name == "Bash":
                    entry = {"cmd": clip(inp.get("command", ""), 160), "error": None}
                    d["commands"].append(entry)
                    pending[b.get("id")] = entry
                elif name == "TodoWrite":
                    d["todos"] = inp.get("todos")
    return d


def render(meta, dg, narrative):
    out = [
        "# Session handoff — %s" % meta["project"],
        "",
        "- Session: `%s` · Branch: `%s` · Worktree: `%s`" % (meta["session"], meta["branch"] or "-", meta["cwd"]),
        "- Updated: %s (%s)" % (meta["updated"], meta["trigger"]),
        "- Transcript: `%s`" % (meta["transcript"] or "-"),
        "",
        "## Narrative",
        "",
        START,
        narrative.strip() or EMPTY_NARRATIVE,
        END,
        "",
        "## Requests (latest last)",
        "",
    ]
    out += ["- " + p for p in dg["prompts"][-6:]] or ["- (none recorded)"]
    out += ["", "## Files changed", ""]
    if dg["files"]:
        for path, counts in sorted(dg["files"].items()):
            out.append("- `%s` (%s)" % (path, ", ".join("%s×%d" % kv for kv in sorted(counts.items()))))
    else:
        out.append("- (none)")
    out += ["", "## Commands (last 15; ✗ = failed)", ""]
    cmds = dg["commands"][-15:]
    out += ["- %s `%s`" % ("✗" if c["error"] else "✓" if c["error"] is False else "·", c["cmd"]) for c in cmds] or ["- (none)"]
    if dg["todos"]:
        open_todos = [t for t in dg["todos"] if t.get("status") != "completed"]
        out += ["", "## Open todos", ""]
        out += ["- [%s] %s" % (t.get("status", "?"), clip(t.get("content", ""), 200)) for t in open_todos] or ["- (all completed)"]
    out += ["", "## Last reply", "", clip(dg["last_reply"], 1500) or "(none)", ""]
    return "\n".join(out)


def read_header(path):
    meta, narrative = {}, ""
    try:
        text = read_text(path)
    except OSError:
        return meta, narrative
    m = re.search(re.escape(START) + r"\n(.*?)\n" + re.escape(END), text, re.S)
    if m and m.group(1).strip() != EMPTY_NARRATIVE:
        narrative = m.group(1)
    t = re.search(r"^- Transcript: `([^`]*)`", text, re.M)
    if t and t.group(1) != "-":
        meta["transcript"] = t.group(1)
    return meta, narrative


def write_snapshot(path, cwd, session_id, transcript, trigger, narrative=None):
    old_meta, old_narrative = read_header(path)
    transcript = transcript or old_meta.get("transcript")
    meta = {
        "project": os.path.basename(project_root(cwd)),
        "session": session_id or "?",
        "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD"),
        "cwd": cwd,
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "trigger": trigger,
        "transcript": transcript,
    }
    text = render(meta, digest(transcript), old_narrative if narrative is None else narrative)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return path


def has_content(path):
    try:
        text = read_text(path)
    except OSError:
        return False
    narrative = EMPTY_NARRATIVE not in text
    files = "## Files changed\n\n- `" in text
    commands = "## Commands (last 15; ✗ = failed)\n\n- (none)" not in text
    return narrative or files or commands


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def goal_line(narrative):
    """First line of the narrative's Goal section, for a one-line pointer."""
    m = re.search(r"###\s*Goal\s*\n+(.+)", narrative)
    line = m.group(1) if m else (narrative.strip().splitlines() or [""])[0]
    return clip(line.lstrip("-* "), 200)


def capped(text, limit):
    return text if len(text) <= limit else text[:limit] + "\n…(truncated; read the file for the rest)"


# --------------------------------------------------------------------------
# Hook modes


def on_snapshot(payload, trigger):
    cwd = payload.get("cwd") or os.getcwd()
    path = session_file(cwd, payload.get("session_id"))
    write_snapshot(path, cwd, payload.get("session_id"), payload.get("transcript_path"), trigger)
    prune(cwd)


def on_start(payload):
    source = payload.get("source") or "startup"
    if source == "clear":
        return  # a cleared session starts fresh; settings.json doesn't register this for clear either
    cwd = payload.get("cwd") or os.getcwd()
    mine = session_file(cwd, payload.get("session_id"), create=False)
    parts = []
    if source in ("compact", "resume") and mine and has_content(mine):
        parts.append("State saved before this %s:\n\n%s" % (source, capped(read_text(mine), MAX_CHARS)))
    elif source == "startup":
        others = [
            f for f in newest_first(cwd)
            if f != mine and has_content(f) and time.time() - os.path.getmtime(f) < MAX_AGE_DAYS * 86400
        ]
        if others:
            _, narrative = read_header(others[0])
            goal = goal_line(narrative) if narrative.strip() else "no narrative, snapshot only"
            parts.append(
                "Previous session in this project: `%s` (%s). Ignore it unless the user runs /pickup "
                "or asks to continue that work." % (others[0], goal)
            )
    if parts:
        additional_context("SessionStart", "\n\n".join(parts))
    prune(cwd)


# --------------------------------------------------------------------------
# CLI modes


def cli(argv):
    if argv[1] == "previous":
        cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
        skip = set()
        if "--exclude" in argv:
            skip.add(os.path.realpath(os.path.expanduser(argv[argv.index("--exclude") + 1])))
        own = session_file(cwd, current_session(), create=False) if current_session() else None
        if own:
            skip.add(os.path.realpath(own))
        for f in newest_first(cwd):
            if os.path.realpath(f) not in skip and has_content(f):
                print(f)
                return 0
        sys.stderr.write("no earlier handoff with content for this project\n")
        return 1
    if argv[1] == "latest":
        cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
        files = sorted(glob.glob(os.path.join(project_dir(cwd), "*.md")))
        if not files:
            return 1
        print(files[-1])
        return 0
    if argv[1] == "narrate":
        narrative = sys.stdin.read().strip()
        if not narrative:
            sys.stderr.write("empty narrative on stdin\n")
            return 1
        if "--file" in argv:
            path = os.path.expanduser(argv[argv.index("--file") + 1])
            if not os.path.exists(path):
                sys.stderr.write("no such handoff file: %s\n" % path)
                return 1
            text = read_text(path)
            sid = re.search(r"Session: `([^`]*)`", text)
            wt = re.search(r"Worktree: `([^`]*)`", text)
            cwd, sid = (wt.group(1) if wt else os.getcwd()), (sid.group(1) if sid else None)
        else:
            sid = current_session()
            if not sid:
                sys.stderr.write("CLAUDE_CODE_SESSION_ID is not set; pass --file PATH\n")
                return 1
            cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
            path = session_file(cwd, sid)
        write_snapshot(path, cwd, sid, find_transcript(sid), "handoff", narrative)
        print(path)
        return 0
    sys.stderr.write(__doc__)
    return 2


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode in ("narrate", "latest", "previous"):
        return cli(sys.argv)
    handlers = {
        "start": on_start,
        "precompact": lambda p: on_snapshot(p, "precompact"),
        "end": lambda p: on_snapshot(p, "end"),
    }
    if mode not in handlers:
        sys.stderr.write(__doc__)
        return 2
    return run(HOOK, handlers[mode])


if __name__ == "__main__":
    sys.exit(main())
