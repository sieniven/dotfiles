"""Tests for format_tracker.py and stop_gate.py.

Run: python3 -m unittest discover -s claude/hooks/tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool(name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "x", "name": name, "input": inp}]}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


class StopGateTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.env = dict(os.environ, CLAUDE_HOOK_STATE_DIR=tempfile.mkdtemp())
        self.env.pop("CLAUDE_HOOKS_DISABLE", None)
        self.env.pop("CLAUDE_VERIFY_PATTERNS", None)
        self.transcript = os.path.join(tempfile.mkdtemp(), "t.jsonl")

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def read(self, path):
        with open(path) as fh:
            return fh.read()

    def hook(self, script, payload):
        r = subprocess.run([sys.executable, os.path.join(HOOKS, script)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertNotIn("internal error", r.stderr, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def stop(self, entries, **kw):
        with open(self.transcript, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        p = {"session_id": "s1", "cwd": self.repo, "transcript_path": self.transcript, "stop_hook_active": False}
        p.update(kw)
        return self.hook("stop_gate.py", p)

    def test_unverified_code_edit_blocks(self):
        p = self.write("src/lib.rs", "pub fn a() {}\n")
        out = self.stop([user("change a"), tool("Edit", {"file_path": p, "old_string": "a", "new_string": "b"}), say("Done.")])
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("lib.rs", out["reason"])

    def test_verified_after_last_edit_passes(self):
        p = self.write("src/lib.rs", "pub fn a() {}\n")
        for cmd in ["cargo check -p x", "cd crates && ./scripts/run-tests.sh core", "python3 -m pytest -q",
                    "python3 -W error::ResourceWarning -m unittest discover -s t"]:
            out = self.stop([user("change a"), tool("Edit", {"file_path": p, "new_string": "b"}), tool("Bash", {"command": cmd}), say("Done.")])
            self.assertNotIn("decision", out, cmd)

    def test_check_before_edit_does_not_count(self):
        p = self.write("src/lib.rs", "pub fn a() {}\n")
        out = self.stop([user("x"), tool("Bash", {"command": "cargo check"}), tool("Edit", {"file_path": p, "new_string": "b"}), say("Done.")])
        self.assertEqual(out.get("decision"), "block")

    def test_custom_runner_pattern_and_agents(self):
        p = self.write("src/lib.rs", "pub fn a() {}\n")
        self.env["CLAUDE_VERIFY_PATTERNS"] = r"\bntr\b"
        out = self.stop([user("x"), tool("Edit", {"file_path": p, "new_string": "b"}), tool("Bash", {"command": "ntr -p x"}), say("ok")])
        self.assertNotIn("decision", out)
        out = self.stop([user("x"), tool("Edit", {"file_path": p, "new_string": "b"}), tool("Agent", {"subagent_type": "verifier"}), say("ok")])
        self.assertNotIn("decision", out)

    def test_acknowledged_unverified_passes(self):
        p = self.write("src/lib.rs", "pub fn a() {}\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": p, "new_string": "b"}), say("Changed it; this is unverified because the runner is down.")])
        self.assertNotIn("decision", out)

    def test_docs_only_and_previous_turn_pass(self):
        md = self.write("README.md", "x")
        self.assertNotIn("decision", self.stop([user("x"), tool("Edit", {"file_path": md, "new_string": "y"}), say("Done.")]))
        rs = self.write("src/lib.rs", "pub fn a() {}\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": rs, "new_string": "y"}), say("unverified"), user("thanks"), say("np")])
        self.assertNotIn("decision", out)

    def test_stop_hook_active_never_blocks(self):
        p = self.write("src/lib.rs", "pub fn a() {}\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": p, "new_string": "b"}), say("Done.")], stop_hook_active=True)
        self.assertNotIn("decision", out)

    def test_debug_leftovers(self):
        p = self.write("src/lib.rs", "pub fn a() {\n    dbg!(1);\n}\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": p, "new_string": "    dbg!(1);"}), tool("Bash", {"command": "cargo check"}), say("Done.")])
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("src/lib.rs:2", out["reason"])
        doc = self.write("src/gate.py", '"""Flags breakpoint() and dbg!( leftovers."""\nx = 1\n')
        out = self.stop([user("x"), tool("Write", {"file_path": doc, "content": self.read(doc)}), tool("Bash", {"command": "ruff check"}), say("Done.")])
        self.assertNotIn("decision", out)
        py = self.write("src/app.py", "def f():\n    breakpoint()\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": py, "new_string": "    breakpoint()"}), tool("Bash", {"command": "ruff check"}), say("Done.")])
        self.assertEqual(out.get("decision"), "block")
        t = self.write("tests/it.rs", "fn t() { dbg!(1); }\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": t, "new_string": "dbg!(1);"}), tool("Bash", {"command": "cargo check"}), say("Done.")])
        self.assertNotIn("decision", out)

    @unittest.skipUnless(shutil.which("rustfmt"), "rustfmt not installed")
    def test_formats_only_previously_clean_files(self):
        clean = self.write("src/clean.rs", "pub fn a() {}\n")
        dirty = self.write("src/dirty.rs", "pub fn   a( ) {}\n")
        for p in (clean, dirty):
            self.hook("format_tracker.py", {"session_id": "s1", "cwd": self.repo, "tool_name": "Edit", "tool_input": {"file_path": p}})
        with open(clean, "w") as fh:
            fh.write("pub fn a( ) {}\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": clean, "new_string": "a( )"}), tool("Bash", {"command": "cargo check"}), say("Done.")])
        self.assertEqual(self.read(clean), "pub fn a() {}\n")
        self.assertEqual(self.read(dirty), "pub fn   a( ) {}\n")
        self.assertIn("formatted 1", out.get("systemMessage", ""))


if __name__ == "__main__":
    unittest.main()
