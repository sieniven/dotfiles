"""Native Codex event behavior: patch guards, verification and isolated handoffs."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS))
import activity
import authorize
import patches
import session_handoff
import stop_gate


class NativeEventsTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.env_patch = patch.dict(os.environ, {"CODEX_HOOK_STATE_DIR": str(self.root / "state")}, clear=False)
        self.env_patch.start()
        self.payload = {"session_id": "thread-one", "turn_id": "turn-one", "cwd": str(self.root)}

    def tearDown(self):
        self.env_patch.stop()
        self.scratch.cleanup()

    def hook(self, name, payload):
        process = subprocess.run([sys.executable, str(HOOKS / (name + ".py"))], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("internal error", process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def test_patch_multiple_files_and_move(self):
        payload = dict(self.payload, tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: src/a.rs\n-old\n+new\n*** Move to: src/b.rs\n*** Add File: lib.py\n+print(1)\n*** End Patch"})
        edits = patches.edits(payload)
        self.assertEqual([e["tool_input"]["file_path"] for e in edits], ["src/a.rs", "src/b.rs", "lib.py"])
        self.assertEqual(edits[0]["tool_input"]["new_string"], "new\n")

    def test_patch_risk_config_is_denied(self):
        (self.root / "risk.toml").write_text("limit=1\n")
        result = self.hook("edit_guard", dict(self.payload, tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: risk.toml\n-limit=1\n+limit=2\n*** End Patch"}))
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("authorize.py", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_patch_content_lint_protection(self):
        (self.root / "lib.rs").write_text("pub fn x() {}\n")
        result = self.hook("edit_guard", dict(self.payload, tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: lib.rs\n+#![allow(dead_code)]\n*** End Patch"}))
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_one_use_approval_is_exact_and_turn_bound(self):
        payload = dict(self.payload, tool_name="apply_patch", tool_input={"command": "patch-a"})
        key = authorize.pending(payload, "test")
        approved = self.root / "state/approvals" / (key + ".approved.json")
        import time
        approved.write_text(json.dumps({"approved_at": time.time()}))
        self.assertFalse(authorize.consume(dict(payload, turn_id="different")))
        self.assertFalse(authorize.consume(dict(payload, tool_input={"command": "patch-b"})))
        self.assertTrue(authorize.consume(payload))
        self.assertFalse(authorize.consume(payload))

    def test_expired_approval_does_not_allow(self):
        payload = dict(self.payload, tool_name="Bash", tool_input={"command": "git push origin feature"})
        key = authorize.pending(payload, "test")
        approved = self.root / "state/approvals" / (key + ".approved.json")
        approved.write_text('{"approved_at": 0}')
        self.assertFalse(authorize.consume(payload))

    def test_verification_after_successful_patch(self):
        activity.record(dict(self.payload, hook_event_name="UserPromptSubmit", prompt="fix code"))
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Add File: logic.py\n+x=1\n*** End Patch"}, tool_response={"success": True}))
        events = activity.load(self.payload)["events"]
        self.assertEqual(stop_gate.unverified_edits(events), ["logic.py"])
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "python3 -m unittest"}, tool_response={"exit_code": 1}))
        self.assertEqual(stop_gate.unverified_edits(activity.load(self.payload)["events"]), ["logic.py"])
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "python3 -m unittest"}, tool_response={"exit_code": 0}))
        self.assertEqual(stop_gate.unverified_edits(activity.load(self.payload)["events"]), [])

    def test_unknown_outcome_does_not_count_as_pass(self):
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "cargo check"}, tool_response="Script running"))
        command = activity.load(self.payload)["commands"][0]
        self.assertIsNone(command["exit_code"])
        path = session_handoff.snapshot(self.payload)
        self.assertIn("exit ?: `cargo check`", path.read_text())

    def test_failed_patch_is_not_a_successful_edit(self):
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Add File: x.py\n+bad"}, tool_response={"isError": True}))
        self.assertEqual(activity.load(self.payload)["events"], [])

    def test_steering_same_turn_preserves_unverified_changes(self):
        activity.record(dict(self.payload, hook_event_name="UserPromptSubmit", prompt="first"))
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Add File: x.py\n+x=1"}, tool_response={"success": True}))
        activity.record(dict(self.payload, hook_event_name="UserPromptSubmit", prompt="also check"))
        self.assertTrue(activity.load(self.payload)["events"])
        activity.record(dict(self.payload, turn_id="turn-two", hook_event_name="UserPromptSubmit", prompt="new task"))
        self.assertEqual(activity.load(dict(self.payload, turn_id="turn-two"))["events"], [])

    def test_child_turn_check_does_not_verify_parent_changes(self):
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Add File: x.py\n+x=1"}, tool_response={"success": True}))
        activity.record(dict(self.payload, turn_id="child-turn", hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "cargo check"}, tool_response={"exit_code": 0}))
        self.assertEqual(stop_gate.unverified_edits(activity.load(self.payload)["events"]), ["x.py"])

    def test_stop_blocks_or_accepts_honest_unverified_reply(self):
        activity.record(dict(self.payload, hook_event_name="PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Add File: x.py\n+x=1"}, tool_response={"success": True}))
        result = self.hook("stop_gate", dict(self.payload, last_assistant_message="Done", hook_event_name="Stop"))
        self.assertEqual(result["decision"], "block")
        result = self.hook("stop_gate", dict(self.payload, last_assistant_message="Unverified: the target could not run.", hook_event_name="Stop"))
        self.assertEqual(result, {})
        result = self.hook("stop_gate", dict(self.payload, stop_hook_active=True, hook_event_name="Stop"))
        self.assertEqual(result, {})

    def test_handoff_narrative_survives_snapshot_and_clear_loads_none(self):
        path = session_handoff.snapshot(self.payload, "### Goal\nKeep the narrative")
        activity.record(dict(self.payload, hook_event_name="UserPromptSubmit", prompt="do work"))
        session_handoff.snapshot(self.payload)
        self.assertIn("Keep the narrative", path.read_text())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            session_handoff.main_hook(dict(self.payload, hook_event_name="SessionStart", source="clear"))
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(list((self.root / "state").glob("*claude*")), [])

    def test_missing_session_id_cannot_write_shared_handoff(self):
        with self.assertRaises(ValueError):
            session_handoff.snapshot({"cwd": str(self.root)})


if __name__ == "__main__":
    unittest.main()
