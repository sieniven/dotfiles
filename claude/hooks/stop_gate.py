#!/usr/bin/env python3
"""Stop: format once, then refuse to finish on unverified code or debug leftovers.

Runs when Claude is about to end its turn:

  format   rustfmt / ruff format / gofmt every file edited this session that was
           formatted (or new) before the first edit (see format_tracker.py).
  debug    blocks once if code edited this turn still contains debug
           leftovers: dbg!, todo!, unimplemented!, breakpoint(), pdb,
           console.log, debugger.
  verify   blocks once if code was edited this turn and no build/test/lint
           command (or verifying subagent) ran after the last edit, unless the
           final reply already says the change is unverified.

Blocking returns {"decision": "block"} so Claude continues and either runs
the check or states plainly that it did not. With `stop_hook_active` set
(Claude is already continuing because of this hook) it never blocks again.

Extra verification commands: CLAUDE_VERIFY_PATTERNS (a regex), e.g. the
machine's named-test runner.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import emit, enabled, run  # noqa: E402
from format_tracker import formatter, load, save  # noqa: E402
from session_handoff import is_prompt  # noqa: E402

HOOK = "stop-gate"
CODE_EXT = (
    ".rs", ".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".sol", ".java", ".kt", ".swift", ".zig", ".sh",
)
VERIFY = re.compile(
    r"\b(cargo\s+(\+\S+\s+)?(check|clippy|build|nextest|test|bench)|just\s+\S*(lint|check|test|build|boot)\S*"
    r"|pytest|python3?\b[^;&|\n]*?\s-m\s+(pytest|unittest|mypy)|ruff\s+check|mypy|pyright|go\s+(test|vet|build)"
    r"|npm\s+(test|run\s+\S*(test|lint|build|typecheck)\S*)|pnpm\s+\S*(test|lint|build)|tsc\b|make\s+\S*(test|check|lint|build)\S*"
    r"|forge\s+(test|build)|tox|nox|bazel\s+(test|build)|shellcheck|bash\s+-n)"
)
VERIFY_AGENTS = {"implementer", "verifier", "quant-trading-developer", "blockchain-unit-test", "quant-trading-code-reviewer"}
ACK = re.compile(
    r"(?i)\b(unverified|not\s+(yet\s+)?(run|tested|verified|built)|didn'?t\s+(run|test|build)|did\s+not\s+(run|test|build)"
    r"|haven'?t\s+(run|tested|built)|have\s+not\s+(run|tested|built)|could\s?n[o']t\s+(run|test|build)|no\s+tests?\s+(were\s+)?run)\b"
)
DEBUG = [
    (".rs", re.compile(r"\b(dbg!\(|todo!\(|unimplemented!\()")),
    (".py", re.compile(r"^\s*(breakpoint\(\)|import\s+i?pdb\b|(i?pdb\.)?set_trace\()")),
    ((".ts", ".tsx", ".js", ".jsx", ".mjs"), re.compile(r"(^\s*console\.log\(|^\s*debugger;)")),
]
TEST_PATH = re.compile(r"(^|/)(tests?|benches|examples)/|(_test|_tests|\.test|\.spec)\.\w+$|(^|/)test_[^/]*$")


def turn_activity(transcript_path):
    """Events since the last real user prompt, in order."""
    events, last_text = [], ""
    if not transcript_path or not os.path.exists(transcript_path):
        return events, last_text
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
                texts = [content] if isinstance(content, str) else [
                    b.get("text", "") for b in content or [] if b.get("type") == "text"]
                if not o.get("isMeta") and any(is_prompt(t) for t in texts):
                    events, last_text = [], ""
                continue
            for b in content or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    last_text = b["text"]
                elif b.get("type") == "tool_use":
                    events.append((b.get("name"), b.get("input") or {}))
    return events, last_text


def is_verify(cmd, extra_rx):
    if VERIFY.search(cmd) or (extra_rx and extra_rx.search(cmd)):
        return True
    # A test-runner script or binary as the command itself: run-tests.sh, nextest, ...
    for seg in re.split(r"[;&|\n]+", cmd):
        words = [w for w in seg.split() if "=" not in w]
        if words and re.search(r"(?i)(test|check|lint)", os.path.basename(words[0])):
            return True
    return False


def run_formatters(session_id, cwd):
    data = load(session_id)
    changed = []
    for path, state in sorted(data.items()):
        if state not in ("clean", "new") or not os.path.exists(path):
            continue
        fmt = formatter(path)
        if not fmt:
            continue
        try:
            with open(path, "rb") as fh:
                old = fh.read()
            subprocess.run(fmt[1], cwd=os.path.dirname(path), capture_output=True, timeout=30)
            with open(path, "rb") as fh:
                if fh.read() != old:
                    changed.append(path)
        except (OSError, subprocess.SubprocessError):
            continue
        data[path] = "clean"
    save(session_id, data)
    return changed


def debug_leftovers(events, cwd):
    found = []
    for name, inp in events:
        if name not in ("Edit", "Write", "MultiEdit"):
            continue
        path = os.path.realpath(os.path.join(cwd, inp.get("file_path") or ""))
        if TEST_PATH.search(path) or not os.path.exists(path):
            continue
        added = (inp.get("new_string") or "") + (inp.get("content") or "") + "".join(
            e.get("new_string") or "" for e in inp.get("edits") or [])
        for ext, rx in DEBUG:
            if not path.endswith(ext) or not any(rx.search(l) for l in added.splitlines()):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if line.lstrip().startswith(("#", "//", "*", "/*")):
                        continue
                    if rx.search(line) and line.strip() in added:
                        found.append("`%s:%d` %s" % (os.path.relpath(path, cwd), n, line.strip()[:80]))
    return sorted(set(found))


def unverified_edits(events):
    last_edit, edited = None, []
    for i, (name, inp) in enumerate(events):
        if name in ("Edit", "Write", "MultiEdit") and (inp.get("file_path") or "").endswith(CODE_EXT):
            last_edit = i
            edited.append(os.path.basename(inp["file_path"]))
    if last_edit is None:
        return []
    extra = os.environ.get("CLAUDE_VERIFY_PATTERNS")
    extra_rx = re.compile(extra) if extra else None
    for name, inp in events[last_edit + 1:]:
        if name == "Bash":
            if is_verify(inp.get("command") or "", extra_rx):
                return []
        if name in ("Agent", "Task") and (inp.get("subagent_type") or "") in VERIFY_AGENTS:
            return []
    return sorted(set(edited))


def main(payload):
    cwd = payload.get("cwd") or os.getcwd()
    sid = payload.get("session_id")
    messages, reasons = [], []

    if enabled(HOOK + ":format"):
        changed = run_formatters(sid, cwd)
        if changed:
            messages.append("[stop-gate] formatted %d edited file(s): %s" % (
                len(changed), ", ".join(os.path.basename(p) for p in changed)))

    if not payload.get("stop_hook_active"):
        events, last_text = turn_activity(payload.get("transcript_path"))
        if enabled(HOOK + ":debug"):
            leftovers = debug_leftovers(events, cwd)
            if leftovers:
                reasons.append("Debug leftovers in code edited this turn: %s. Remove them, or say in your reply why they stay." % "; ".join(leftovers[:8]))
        if enabled(HOOK + ":verify") and not ACK.search(last_text or ""):
            files = unverified_edits(events)
            if files:
                reasons.append(
                    "You changed code this turn (%s) and nothing built, tested or linted it after the last edit. "
                    "Run the narrowest check that covers the change (through the machine's test runner where one is "
                    "prescribed), or state plainly in your reply that it is unverified and why." % ", ".join(files[:6])
                )

    out = {}
    if messages:
        out["systemMessage"] = " ".join(messages)
    if reasons:
        out["decision"] = "block"
        out["reason"] = "[stop-gate] " + " ".join(reasons)
    if out:
        emit(out)


if __name__ == "__main__":
    sys.exit(run(HOOK, main))
