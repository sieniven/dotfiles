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
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)
        self.env["HOME"] = tempfile.mkdtemp()  # isolates ~/.claude/projects transcript lookup

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

    def ctx(self, **kw):
        r = self.hook("session_handoff.py", ["start"], self.payload(**kw))
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def narrate(self, text):
        self.hook("session_handoff.py", ["end"], self.payload())
        [f] = self.files()
        r = self.hook("session_handoff.py", ["narrate", "--file", f], None, stdin=text)
        self.assertEqual(r.returncode, 0, r.stderr)
        return f

    def test_narrate_preserved_across_refresh(self):
        f = self.narrate("### Goal\nShip the cancel fix\n")
        self.hook("session_handoff.py", ["precompact"], self.payload())
        self.assertIn("Ship the cancel fix", read(f))
        self.assertIn("cargo check -p hedger", read(f))

    def test_clear_runs_nothing(self):
        # /clear means a fresh start, even right after /handoff.
        self.narrate("### Goal\nShip the cancel fix\n")
        before = self.files()
        r = self.hook("session_handoff.py", ["start"], self.payload(session_id="yyyy8888", source="clear"))
        self.assertEqual(r.stdout.strip(), "")  # no context injected at all
        self.assertEqual(self.files(), before)  # no file created either

    def test_settings_do_not_register_session_start_on_clear(self):
        with open(os.path.join(os.path.dirname(HOOKS), "settings.json")) as fh:
            hooks = json.load(fh)["hooks"]["SessionStart"]
        for m in hooks:
            self.assertNotIn("clear", m["matcher"])
            self.assertNotEqual(m["matcher"], "*")

    def test_startup_gets_one_line_pointer_with_goal(self):
        self.narrate("### Goal\nShip the cancel fix\n")
        ctx = self.ctx(session_id="zzzz9999", source="startup")
        self.assertIn("Previous session in this project", ctx)
        self.assertIn("(Ship the cancel fix)", ctx)
        self.assertIn("/pickup", ctx)
        self.assertNotIn("cargo check -p hedger", ctx)

    def test_start_fresh_project_injects_nothing(self):
        r = self.hook("session_handoff.py", ["start"], self.payload(source="startup", transcript_path=None))
        self.assertEqual(r.stdout.strip(), "")

    def test_narrate_finds_own_session_from_env(self):
        sid = "abcdef1234"
        proj = os.path.join(self.env["HOME"], ".claude", "projects", "-x")
        os.makedirs(proj)
        write_transcript(os.path.join(proj, sid + ".jsonl"), TRANSCRIPT)
        self.env["CLAUDE_CODE_SESSION_ID"] = sid
        r = self.hook("session_handoff.py", ["narrate", "--cwd", self.cwd], None, stdin="### Goal\nShip it\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        [f] = self.files()
        self.assertEqual(r.stdout.strip(), f)
        self.assertTrue(f.endswith("-%s.md" % sid[:8]))
        self.assertIn("Ship it", read(f))
        self.assertIn("cargo check -p hedger", read(f))  # snapshot from the session's own transcript
        self.env.pop("CLAUDE_CODE_SESSION_ID")
        r = self.hook("session_handoff.py", ["narrate", "--cwd", self.cwd], None, stdin="x")
        self.assertEqual(r.returncode, 1)  # no session id and no --file

    def test_previous_cli_skips_current_session_file(self):
        prev = self.narrate("### Goal\nShip the cancel fix\n")  # session abcdef12
        self.env["CLAUDE_CODE_SESSION_ID"] = "yyyy8888"
        self.hook("session_handoff.py", ["end"], self.payload(session_id="yyyy8888"))  # new session, newer file
        r = self.hook("session_handoff.py", ["previous", "--cwd", self.cwd], None, stdin="")
        self.assertEqual(r.stdout.strip(), prev)
        r = self.hook("session_handoff.py", ["previous", "--cwd", self.cwd, "--exclude", prev], None, stdin="")
        self.assertEqual(r.returncode, 1)

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
