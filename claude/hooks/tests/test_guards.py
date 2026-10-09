"""Tests for bash_guard.py and edit_guard.py.

Run: python3 -m unittest discover -s claude/hooks/tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_hook(script, payload, env=None):
    e = dict(os.environ)
    e.pop("CLAUDE_HOOKS_DISABLE", None)
    e.pop("CLAUDE_HOOKS", None)
    e.update(env or {})
    r = subprocess.run(
        [sys.executable, os.path.join(HOOKS, script)],
        input=json.dumps(payload), capture_output=True, text=True, env=e, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "internal error" not in r.stderr, r.stderr
    if not r.stdout.strip():
        return None, ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    return out["permissionDecision"], out["permissionDecisionReason"]


class GitRepo:
    def __init__(self, branch="main"):
        self.dir = tempfile.mkdtemp()
        self.git("init", "-q", "-b", branch)
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("README.md", "hi\n")
        self.git("add", "README.md")
        self.git("commit", "-qm", "init")

    def git(self, *args):
        subprocess.run(["git", "-C", self.dir] + list(args), check=True, capture_output=True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path


class BashGuardTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = {"HOME": self.home, "CLAUDE_GUARD_DIRECT_TESTS": "1"}

    def decide(self, command, cwd=None, env=None):
        e = dict(self.env)
        e.update(env or {})
        return run_hook("bash_guard.py", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd or self.home}, e)[0]

    def test_plain_commands_pass(self):
        for cmd in ["ls -la", "git status", "git push -u origin feat/x", "cargo build --release",
                    "cargo nextest run -p foo", "just lint", "rm -rf target", "gh pr create --title t --body b"]:
            self.assertIsNone(self.decide(cmd), cmd)

    def test_git_push_allowed_including_main(self):
        self.assertIsNone(self.decide("git push origin main"))

    def test_gh_pr_merge_denied_everywhere(self):
        for cmd in ["gh pr merge 12 --squash", "cd x && gh pr merge --auto", "bash -c 'gh pr merge 3'",
                    "gh api -X PUT repos/o/r/pulls/7/merge", "timeout 30 gh pr merge 1"]:
            self.assertEqual(self.decide(cmd), "deny", cmd)

    def test_nohup_denied(self):
        self.assertEqual(self.decide("nohup ./run.sh > out.log 2>&1 &"), "deny")
        self.assertEqual(self.decide("FOO=1 nohup python3 x.py"), "deny")

    def test_no_verify_denied(self):
        for cmd in ["git commit --no-verify -m x", "git commit -nm x", "git push --no-verify",
                    "git -c core.hooksPath=/dev/null commit -m x"]:
            self.assertEqual(self.decide(cmd), "deny", cmd)
        self.assertIsNone(self.decide("git commit -m 'mention --no-verify in text'"))

    def test_heredoc_body_is_not_parsed(self):
        cmd = "git commit -F - <<'EOF'\nfix: avoid gh pr merge and nohup in docs\nEOF"
        self.assertIsNone(self.decide(cmd))

    def test_direct_tests(self):
        for cmd in ["cargo test -p foo", "cargo +nightly test", "just test", "timeout 600 just check",
                    "cd crates/x && cargo bench"]:
            self.assertEqual(self.decide(cmd), "deny", cmd)
        self.assertIsNone(self.decide("cargo test", env={"CLAUDE_GUARD_DIRECT_TESTS": "0"}))

    def test_direct_tests_follow_local_rules_file(self):
        env = {"CLAUDE_GUARD_DIRECT_TESTS": ""}
        e = dict(self.env)
        e.pop("CLAUDE_GUARD_DIRECT_TESTS")
        base = run_hook("bash_guard.py", {"tool_name": "Bash", "tool_input": {"command": "cargo test"}, "cwd": self.home}, e)[0]
        self.assertIsNone(base)
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", "CLAUDE.local.md"), "w") as fh:
            fh.write("Never run `cargo test` directly.\n")
        after = run_hook("bash_guard.py", {"tool_name": "Bash", "tool_input": {"command": "cargo test"}, "cwd": self.home}, e)[0]
        self.assertEqual(after, "deny")
        del env

    def test_force_push(self):
        repo = GitRepo("main")
        self.assertEqual(self.decide("git push --force origin main", cwd=repo.dir), "deny")
        self.assertEqual(self.decide("git push -f", cwd=repo.dir), "deny")
        self.assertEqual(self.decide("git push origin +HEAD", cwd=repo.dir), "deny")
        self.assertEqual(self.decide("git push origin :main", cwd=repo.dir), "deny")
        self.assertEqual(self.decide("git push --force-with-lease origin feat/x", cwd=repo.dir), "ask")

    def test_destructive(self):
        self.assertEqual(self.decide("rm -rf ~"), "deny")
        self.assertEqual(self.decide("rm -rf /"), "deny")
        self.assertEqual(self.decide("rm -fr $HOME/"), "deny")
        self.assertEqual(self.decide("rm -r .."), "ask")
        self.assertEqual(self.decide("git reset --hard HEAD~1"), "ask")
        self.assertEqual(self.decide("git clean -fdx"), "ask")
        self.assertEqual(self.decide("docker system prune -a"), "ask")
        self.assertIsNone(self.decide("rm -f notes.txt"))

    def test_secret_scan_on_commit(self):
        repo = GitRepo("feat")
        repo.write("key.txt", "token = 'x'\n-----BEGIN OPENSSH PRIVATE KEY-----\n")
        self.assertEqual(self.decide("git add key.txt && git commit -m add", cwd=repo.dir), "deny")
        self.assertEqual(self.decide("git add -A && git commit -m add", cwd=repo.dir), "deny")
        repo.write(".env", "A=1\n")
        repo.git("add", ".env")
        self.assertEqual(self.decide("git commit -m env", cwd=repo.dir), "deny")
        repo.git("reset", "-q")

    def test_secret_generic_assignment_asks(self):
        repo = GitRepo("feat")
        repo.write("cfg.py", 'api_key = "Zq8rT2mN4vB7xK1pL9sD"\n')
        repo.git("add", "cfg.py")
        self.assertEqual(self.decide("git commit -m cfg", cwd=repo.dir), "ask")
        repo2 = GitRepo("feat")
        repo2.write("cfg.py", 'api_key = "your-api-key-goes-here-123"\n')
        repo2.git("add", "cfg.py")
        self.assertIsNone(self.decide("git commit -m cfg", cwd=repo2.dir))

    def test_disable_switches(self):
        self.assertIsNone(self.decide("nohup x", env={"CLAUDE_HOOKS_DISABLE": "bash-guard:nohup"}))
        self.assertIsNone(self.decide("gh pr merge 1", env={"CLAUDE_HOOKS_DISABLE": "bash-guard"}))
        self.assertIsNone(self.decide("gh pr merge 1", env={"CLAUDE_HOOKS": "off"}))

    def test_unbalanced_quotes_fail_safe(self):
        self.assertEqual(self.decide("gh pr merge 1 'oops"), "deny")


class EditGuardTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()

    def touch(self, rel, text=""):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def decide(self, tool, tool_input, env=None):
        e = {"HOME": self.home}
        e.update(env or {})
        return run_hook("edit_guard.py", {"tool_name": tool, "tool_input": tool_input, "cwd": self.dir}, e)[0]

    def test_lint_config_asks(self):
        p = self.touch("clippy.toml", "x = 1\n")
        self.assertEqual(self.decide("Edit", {"file_path": p, "old_string": "x = 1", "new_string": "x = 2"}), "ask")

    def test_new_file_allowed(self):
        p = os.path.join(self.dir, "rustfmt.toml")
        self.assertIsNone(self.decide("Write", {"file_path": p, "content": "edition = '2021'\n"}))

    def test_pyproject_only_lint_tables(self):
        p = self.touch("pyproject.toml", "[project]\nname='x'\n[tool.ruff]\nline-length=100\n")
        self.assertEqual(self.decide("Edit", {"file_path": p, "old_string": "[tool.ruff]\nline-length=100", "new_string": "[tool.ruff]\nline-length=200"}), "ask")
        self.assertIsNone(self.decide("Edit", {"file_path": p, "old_string": "name='x'", "new_string": "name='y'"}))

    def test_crate_allow(self):
        p = self.touch("src/lib.rs", "pub fn a() {}\n")
        self.assertEqual(self.decide("Edit", {"file_path": p, "old_string": "pub fn a", "new_string": "#![allow(dead_code)]\npub fn a"}), "ask")
        self.assertIsNone(self.decide("Edit", {"file_path": p, "old_string": "pub fn a", "new_string": "pub fn b"}))

    def test_secrets_and_prod_config(self):
        self.assertEqual(self.decide("Edit", {"file_path": self.touch(".env", "A=1"), "old_string": "A=1", "new_string": "A=2"}), "ask")
        self.assertIsNone(self.decide("Edit", {"file_path": self.touch(".env.example", "A=1"), "old_string": "A=1", "new_string": "A=2"}))
        self.assertEqual(self.decide("Edit", {"file_path": self.touch("config/risk_limits.yaml", "max: 1"), "old_string": "max: 1", "new_string": "max: 2"}), "ask")
        self.assertEqual(self.decide("Edit", {"file_path": self.touch("config.prod.toml", "a=1"), "old_string": "a=1", "new_string": "a=2"}), "ask")
        self.assertIsNone(self.decide("Edit", {"file_path": self.touch("src/risk.py", "a=1"), "old_string": "a=1", "new_string": "a=2"}))
        p = self.touch("strategies/mm/params.json", "{}")
        self.assertEqual(self.decide("Edit", {"file_path": p, "old_string": "{}", "new_string": "{ }"}, {"CLAUDE_PROTECTED_PATHS": "*/strategies/*/params.json"}), "ask")

    def test_harness_check_follows_symlinked_hooks(self):
        # ~/.claude/hooks linked into a dotfiles checkout: an edit through either path is the same file.
        repo_hooks = os.path.join(self.dir, "dotfiles", "claude", "hooks")
        os.makedirs(repo_hooks)
        hook = os.path.join(repo_hooks, "bash_guard.py")
        with open(hook, "w") as fh:
            fh.write("# guard\n")
        claude = os.path.join(self.home, ".claude")
        os.makedirs(claude)
        os.symlink(repo_hooks, os.path.join(claude, "hooks"))
        edit = {"old_string": "# guard", "new_string": "# weakened"}
        self.assertEqual(self.decide("Edit", dict(edit, file_path=os.path.join(claude, "hooks", "bash_guard.py"))), "ask")
        self.assertEqual(self.decide("Edit", dict(edit, file_path=hook)), "ask")
        settings = os.path.join(claude, "settings.json")
        with open(settings, "w") as fh:
            fh.write("{}\n")
        self.assertEqual(self.decide("Edit", {"file_path": settings, "old_string": "{}", "new_string": "{ }"}), "ask")
        self.assertIsNone(self.decide("Edit", dict(edit, file_path=self.touch("dotfiles/claude/CLAUDE.md", "# guard\n"))))


if __name__ == "__main__":
    unittest.main()
