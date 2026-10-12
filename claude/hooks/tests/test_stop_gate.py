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
sys.path.insert(0, HOOKS)
from format_tracker import rust_edition  # noqa: E402

# rustfmt-clean under edition 2024 only: 2021 sorts the `use` list
# `{hash_map::Entry, BTreeMap, HashMap}` and cannot parse a let chain.
USES_2024 = (
    "use std::collections::{BTreeMap, HashMap, hash_map::Entry};\n\n"
    "pub type T<'a> = (BTreeMap<u8, u8>, HashMap<u8, u8>, Entry<'a, u8, u8>);\n"
)
LET_CHAIN = (
    "pub fn f(a: Option<u8>) -> bool {\n    if let Some(x) = a\n        && x > 1\n    {\n"
    "        return true;\n    }\n    false\n}\n"
)


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

    def workspace_member(self, rel, text):
        """`text` at `rel` in a crate that takes its edition (2024) from the workspace."""
        self.write("Cargo.toml", '[workspace]\nmembers = ["crates/x"]\n\n[workspace.package]\nedition = "2024"\n')
        self.write("crates/x/Cargo.toml", '[package]\nname = "x"\nversion = "0.1.0"\nedition.workspace = true\n')
        return self.write(os.path.join("crates/x", rel), text)

    @unittest.skipUnless(shutil.which("rustfmt"), "rustfmt not installed")
    def test_new_file_formats_under_workspace_edition(self):
        p = os.path.join(self.repo, "crates/x/src/new.rs")
        self.hook("format_tracker.py", {"session_id": "s1", "cwd": self.repo, "tool_name": "Write", "tool_input": {"file_path": p}})
        self.workspace_member("src/new.rs", USES_2024 + "\npub fn   a( ) {}\n")
        self.stop([user("x"), tool("Write", {"file_path": p, "content": ""}), tool("Bash", {"command": "cargo check"}), say("Done.")])
        self.assertEqual(self.read(p), USES_2024 + "\npub fn a() {}\n")

    @unittest.skipUnless(shutil.which("rustfmt"), "rustfmt not installed")
    def test_let_chain_file_is_tracked_clean_and_formatted(self):
        p = self.workspace_member("src/lib.rs", LET_CHAIN)
        self.hook("format_tracker.py", {"session_id": "s1", "cwd": self.repo, "tool_name": "Edit", "tool_input": {"file_path": p}})
        with open(p, "w") as fh:
            fh.write(LET_CHAIN.replace("return true;", "return   true;"))
        self.stop([user("x"), tool("Edit", {"file_path": p, "new_string": "return   true;"}), tool("Bash", {"command": "cargo check"}), say("Done.")])
        self.assertEqual(self.read(p), LET_CHAIN)

    @unittest.skipUnless(shutil.which("gofmt"), "gofmt not installed")
    def test_gofmt_formats_only_previously_clean_files(self):
        clean = self.write("pkg/clean.go", "package pkg\n\nfunc A() {}\n")
        dirty = self.write("pkg/dirty.go", "package pkg\nfunc   A( ) {}\n")
        for p in (clean, dirty):
            self.hook("format_tracker.py", {"session_id": "s1", "cwd": self.repo, "tool_name": "Edit", "tool_input": {"file_path": p}})
        with open(clean, "w") as fh:
            fh.write("package pkg\n\nfunc   A( ) {}\n")
        out = self.stop([user("x"), tool("Edit", {"file_path": clean, "new_string": "A( )"}), tool("Bash", {"command": "go vet ./..."}), say("Done.")])
        self.assertEqual(self.read(clean), "package pkg\n\nfunc A() {}\n")
        self.assertEqual(self.read(dirty), "package pkg\nfunc   A( ) {}\n")
        self.assertIn("formatted 1", out.get("systemMessage", ""))


class RustEditionTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def manifest(self, rel, text):
        os.makedirs(os.path.join(self.root, rel), exist_ok=True)
        with open(os.path.join(self.root, rel, "Cargo.toml"), "w") as fh:
            fh.write(text)

    def edition(self, rel="crates/x"):
        return rust_edition(os.path.join(self.root, rel, "src", "lib.rs"))

    def test_own_edition(self):
        self.manifest("crates/x", '[package]\nname = "x"\n# edition = "2015"\nedition = "2018"  # pinned\n')
        self.assertEqual(self.edition(), "2018")

    def test_inherited_edition_comes_from_the_workspace_root(self):
        self.manifest("", '[workspace]\nmembers = ["crates/x"]\n\n[workspace.package]\nedition = "2024"\n')
        for form in ("edition.workspace = true", "edition = { workspace = true }"):
            self.manifest("crates/x", '[package]\nname = "x"\n%s\n\n[[bin]]\nname = "x"\n' % form)
            self.assertEqual(self.edition(), "2024", form)
        self.assertEqual(self.edition(""), "2024")

    def test_root_package_is_its_own_workspace(self):
        self.manifest("", '[package]\nname = "r"\nedition.workspace = true\n\n[workspace.package]\nedition = "2024"\n')
        self.assertEqual(self.edition(""), "2024")

    def test_unresolved_edition_falls_back_to_2021(self):
        self.assertEqual(self.edition(), "2021")
        self.manifest("crates/x", '[package]\nname = "x"\nedition.workspace = true\n')
        self.assertEqual(self.edition(), "2021")


if __name__ == "__main__":
    unittest.main()
