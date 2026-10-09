"""Tests for session_handoff.py and suggest_compact.py.

Run: python3 -m unittest discover -s claude/hooks/tests -v
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path) as fh:
        return fh.read()


def write_transcript(path, entries):
    with open(path, "w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def tool_use(id_, name, inp):
    return {"type": "tool_use", "id": id_, "name": name, "input": inp}


def tool_result(id_, error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": id_, "is_error": error, "content": "x"}]}}


TRANSCRIPT = [
    user("fix the hedger cancel path"),
    assistant({"type": "text", "text": "Looking."}, tool_use("t1", "Edit", {"file_path": "/r/src/hedger.rs"})),
    tool_result("t1"),
    assistant(tool_use("t2", "Bash", {"command": "cargo check -p hedger"})),
    tool_result("t2", error=True),
    assistant(tool_use("t3", "TodoWrite", {"todos": [
        {"content": "fix cancel", "status": "completed"},
        {"content": "add test for reject branch", "status": "pending"}]})),
    tool_result("t3"),
    {"type": "assistant", "isSidechain": True, "message": {"content": [tool_use("s1", "Edit", {"file_path": "/sub.rs"})]}},
    assistant({"type": "text", "text": "Cancel path fixed; check fails on an unrelated crate."}),
]


class Base(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.cwd = tempfile.mkdtemp()
        self.transcript = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        write_transcript(self.transcript, TRANSCRIPT)
        self.env = dict(os.environ, CLAUDE_HOOK_STATE_DIR=self.state)
        self.env.pop("CLAUDE_HOOKS_DISABLE", None)

    def hook(self, script, args, payload, stdin=None):
        r = subprocess.run(
            [sys.executable, os.path.join(HOOKS, script)] + args,
            input=stdin if stdin is not None else json.dumps(payload),
            capture_output=True, text=True, env=self.env, timeout=30,
        )
        self.assertNotIn("internal error", r.stderr)
        return r

    def payload(self, **kw):
        p = {"session_id": "abcdef1234", "cwd": self.cwd, "transcript_path": self.transcript}
        p.update(kw)
        return p

    def files(self):
        return sorted(glob.glob(os.path.join(self.state, "handoffs", "*", "*.md")))


class HandoffTest(Base):
    def test_precompact_snapshot(self):
        self.hook("session_handoff.py", ["precompact"], self.payload())
        [f] = self.files()
        text = read(f)
        self.assertIn("fix the hedger cancel path", text)
        self.assertIn("`/r/src/hedger.rs` (Edit×1)", text)
        self.assertIn("✗ `cargo check -p hedger`", text)
        self.assertIn("[pending] add test for reject branch", text)
        self.assertNotIn("fix cancel", text.split("## Open todos")[1])
        self.assertNotIn("/sub.rs", text)
        self.assertIn("Cancel path fixed", text)

    def test_start_after_compact_injects_state(self):
        self.hook("session_handoff.py", ["precompact"], self.payload())
        r = self.hook("session_handoff.py", ["start"], self.payload(source="compact"))
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("State saved before this compact", ctx)
        self.assertIn("cargo check -p hedger", ctx)

    def test_narrate_preserved_and_new_session_sees_it(self):
        self.hook("session_handoff.py", ["end"], self.payload())
        [f] = self.files()
        r = self.hook("session_handoff.py", ["narrate", "--file", f], None, stdin="### Goal\nShip the cancel fix\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.hook("session_handoff.py", ["precompact"], self.payload())
        self.assertIn("Ship the cancel fix", read(f))
        r = self.hook("session_handoff.py", ["start"], self.payload(session_id="zzzz9999", source="startup"))
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Previous session handoff", ctx)
        self.assertIn("Ship the cancel fix", ctx)
        r = self.hook("session_handoff.py", ["start"], self.payload(session_id="yyyy8888", source="clear"))
        self.assertIn("Handoff from the previous session", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_start_fresh_project_only_names_file(self):
        r = self.hook("session_handoff.py", ["start"], self.payload(source="startup", transcript_path=None))
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("Session handoff file:"))
        self.assertNotIn("Previous session", ctx)

    def test_latest_cli(self):
        self.hook("session_handoff.py", ["end"], self.payload())
        r = self.hook("session_handoff.py", ["latest", "--cwd", self.cwd], None, stdin="")
        self.assertEqual(r.stdout.strip(), self.files()[-1])


class SuggestCompactTest(Base):
    def test_threshold_and_reset(self):
        self.env.update(CLAUDE_COMPACT_SUGGEST_AT="3", CLAUDE_COMPACT_SUGGEST_EVERY="2")
        outs = [self.hook("suggest_compact.py", [], self.payload()).stdout for _ in range(5)]
        self.assertEqual([bool(o.strip()) for o in outs], [False, False, True, False, True])
        self.hook("suggest_compact.py", ["reset"], self.payload())
        self.assertFalse(self.hook("suggest_compact.py", [], self.payload()).stdout.strip())


if __name__ == "__main__":
    unittest.main()
