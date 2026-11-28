"""Tests for scripts/devbox.py, with the launcher and ssh faked.

Run: python3 -m unittest discover -s claude/hooks/tests -v
"""

import os
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
sys.path.insert(0, SCRIPTS)
import devbox  # noqa: E402

ENV = {"LAUNCHER_URL": "https://launcher.invalid", "DEVBOX_ID": "i-mine", "DEVBOX_NAME": "pgd-dev-apne1-box",
       "DEVBOX_KEY": "me-dev", "DEVBOX_SSH": "ssh-box"}


class FakeLauncher:
    def __init__(self, state="stopped", name="pgd-dev-apne1-box", key="me-dev", api=True):
        self.state, self.name, self.key, self.api, self.calls = state, name, key, api, []

    def __call__(self, method, path):
        self.calls.append((method, path))
        if not self.api:
            return 404, None
        parts = path.split("/")
        if parts[3] != "i-mine":
            return 404, {"error": "not a researcher workstation: " + parts[3]}
        if method == "GET":
            return 200, {"id": "i-mine", "name": self.name, "key": self.key, "state": self.state, "ip": "",
                         "since": None}
        action = parts[4]
        if (action, self.state) in (("start", "stopping"), ("stop", "pending")):
            return 409, {"error": "%s is %s" % (self.name, self.state)}
        changed = self.state == ("stopped" if action == "start" else "running")
        if changed:
            self.state = "pending" if action == "start" else "stopping"
        return (202 if changed else 200), {"state": self.state, "changed": changed}


class DevBoxTest(unittest.TestCase):
    def box(self, launcher, tmux=None, ssh_code=0):
        self.ssh_calls, self.lines = [], []

        def ssh(alias, command):
            self.ssh_calls.append((alias, command))
            return ssh_code, tmux or ""
        return devbox.DevBox(ENV, launcher, ssh=ssh, sleep=lambda s: None, out=self.lines.append)

    def test_cli_takes_no_instance_argument(self):
        with self.assertRaises(SystemExit):
            devbox.main(["stop", "i-someone-else"])

    def test_start_addresses_only_the_configured_box(self):
        launcher = FakeLauncher()
        self.box(launcher).act("start")
        self.assertEqual(launcher.calls, [("GET", "/api/workstations/i-mine"),
                                          ("POST", "/api/workstations/i-mine/start")])
        self.assertEqual(self.lines, ["start pgd-dev-apne1-box: pending"])

    def test_refuses_when_the_id_is_somebody_elses_box(self):
        for launcher in (FakeLauncher(name="pgd-dev-apne1-other"), FakeLauncher(key="other-dev")):
            with self.assertRaises(devbox.Refused):
                self.box(launcher).act("stop", force=True)
            self.assertEqual([c for c in launcher.calls if c[0] == "POST"], [])

    def test_stop_refuses_while_tmux_sessions_run(self):
        launcher = FakeLauncher(state="running")
        with self.assertRaises(devbox.Refused) as ctx:
            self.box(launcher, tmux="bench: 1 windows\n").act("stop")
        self.assertIn("bench: 1 windows", str(ctx.exception))
        self.assertEqual(self.ssh_calls, [("ssh-box", "tmux ls 2>/dev/null || true")])
        self.assertEqual(launcher.state, "running")

    def test_stop_refuses_when_jobs_cannot_be_checked(self):
        launcher = FakeLauncher(state="running")
        with self.assertRaises(devbox.Refused):
            self.box(launcher, ssh_code=255).act("stop")
        self.assertEqual(launcher.state, "running")

    def test_stop_with_no_jobs_or_with_force(self):
        launcher = FakeLauncher(state="running")
        self.box(launcher).act("stop")
        self.assertEqual(launcher.state, "stopping")
        launcher = FakeLauncher(state="running")
        self.box(launcher, tmux="bench: 1 windows").act("stop", force=True)
        self.assertEqual((launcher.state, self.ssh_calls), ("stopping", []))

    def test_already_there_is_reported_as_no_change(self):
        self.box(FakeLauncher(state="running")).act("start")
        self.assertEqual(self.lines, ["start pgd-dev-apne1-box: running (no change)"])

    def test_mid_transition_is_refused(self):
        with self.assertRaises(devbox.Refused):
            self.box(FakeLauncher(state="stopping")).act("start")

    def test_launcher_without_the_api(self):
        with self.assertRaises(devbox.LauncherError) as ctx:
            self.box(FakeLauncher(api=False)).status()
        self.assertIn("no JSON API", str(ctx.exception))

    def test_wait_polls_until_the_state(self):
        launcher = FakeLauncher()
        states = iter(["pending", "pending", "running"])
        box = self.box(launcher)
        original = launcher.__call__

        def advancing(method, path):
            if method == "GET":
                launcher.state = next(states)
            return original(method, path)
        box.api = advancing
        self.assertEqual(box.wait_for("running", 300)["state"], "running")

    def test_load_env_requires_the_box(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write("# comment\nLAUNCHER_URL=https://x\nDEVBOX_ID=i-1  # trailing\n")
        try:
            with self.assertRaises(devbox.LauncherError) as ctx:
                devbox.load_env(fh.name)
            self.assertIn("DEVBOX_NAME, DEVBOX_KEY", str(ctx.exception))
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
