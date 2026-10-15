"""Tests for scripts/session_cleanup.py, which backs $cleanup, and the activity
trail it reads from hooks/activity.py.

Run: python3 -m unittest discover -s codex/hooks/tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(os.path.dirname(HOOKS), "scripts")
SCRIPT = os.path.join(SCRIPTS, "session_cleanup.py")
SID = "11111111-2222-3333-4444-555555555555"

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HOOKS)
import activity  # noqa: E402
from session_cleanup import git_effects  # noqa: E402

FAKE_GH = """import json, os, sys
if os.environ.get("FAKE_GH_FAIL"):
    sys.exit(1)
head = sys.argv[sys.argv.index("--head") + 1]
print(json.dumps(json.loads(os.environ.get("FAKE_GH_PRS", "{}")).get(head, [])))
"""


def write(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class Fixture:
    """A repo pushed to a bare origin, Codex activity records and a fake gh, under one temp dir."""

    def __init__(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.origin = os.path.join(self.root, "origin.git")
        self.repo = os.path.join(self.root, "repo")
        self.state = os.path.join(self.root, "state")
        self.scratch = os.path.join(self.root, "scratch")
        self.prs = {}
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        write(self.repo, ".gitignore", "target/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "init")
        self.git("remote", "add", "origin", self.origin)
        self.git("push", "-qu", "origin", "main")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.gh = os.path.join(self.root, "gh")
        write(self.root, "gh", "#!%s\n%s" % (sys.executable, FAKE_GH))
        os.chmod(self.gh, 0o755)

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", "-C", cwd or self.repo] + list(args), check=True, capture_output=True, text=True)
        return r.stdout.strip()

    def worktree(self, name, pushed=True):
        """A linked worktree on feat/<name> with one commit of its own."""
        path = os.path.join(self.repo, ".claude", "worktrees", name)
        self.git("worktree", "add", "-q", "-b", "feat/" + name, path, "main")
        self.commit(path, name)
        if pushed:
            self.git("push", "-qu", "origin", "feat/" + name, cwd=path)
        return path

    def commit(self, path, name):
        write(path, name + ".txt", name)
        self.git("add", name + ".txt", cwd=path)
        self.git("commit", "-qm", name, cwd=path)
        return self.git("rev-parse", "HEAD", cwd=path)

    def record(self, payload, session=SID):
        """Feed one hook event through the real activity.py, as Codex would."""
        payload = dict(payload, session_id=session, turn_id="turn-one")
        with mock.patch.dict(os.environ, {"CODEX_HOOK_STATE_DIR": self.state}):
            activity.record(payload)
        return os.path.join(self.state, "activity", session + ".json")

    def worked_in(self, *dirs, session=SID):
        for d in dirs:
            self.record({"hook_event_name": "UserPromptSubmit", "prompt": "go", "cwd": d}, session)

    def ran(self, command, cwd):
        tool = {"tool_name": "exec_command", "tool_input": {"cmd": command, "workdir": cwd}, "tool_response": {"exit_code": 0}}
        self.record(dict(tool, hook_event_name="PostToolUse", cwd=self.repo))

    def run(self, mode="apply", *names, session=SID, cwd=None, env=None):
        e = dict(os.environ)
        e.pop("CODEX_THREAD_ID", None)
        e.update({
            "CODEX_HOOK_STATE_DIR": self.state,
            "CODEX_CLEANUP_GH": self.gh,
            "CODEX_CLEANUP_SESSION_DIRS": os.path.join(self.scratch, "tests-{session}"),
            "FAKE_GH_PRS": json.dumps(self.prs),
        })
        if session:
            e["CODEX_THREAD_ID"] = session
        e.update(env or {})
        r = subprocess.run(
            [sys.executable, SCRIPT, mode, "--json"] + list(names),
            cwd=cwd or self.repo, env=e, capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)


def wt(report, name):
    return next(w for e in report["repos"] for w in e["worktrees"] if os.path.basename(w["path"]) == name)


def br(report, name):
    return next(b for e in report["repos"] for b in e["branches"] if b["name"] == name)


def left_alone(report):
    return {os.path.basename(w["path"]) for e in report["repos"] for w in e["left_alone"]}


class WorktreeTest(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(shutil.rmtree, self.f.root, True)

    def test_removes_clean_pushed_worktree_with_its_build_output(self):
        path = self.f.worktree("a")
        write(path, "target/debug/big", "x" * 4096)
        self.f.worked_in(os.path.join(path, "target"))
        r = self.f.run()
        self.assertEqual(wt(r, "a")["kept"], [])
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(path, self.f.git("worktree", "list"))
        self.assertEqual(br(r, "feat/a")["why"], "no PR")
        self.assertTrue(self.f.git("branch", "--list", "feat/a"))

    def test_keeps_dirty_unpushed_and_locked(self):
        dirty, unpushed, locked = self.f.worktree("dirty"), self.f.worktree("unpushed", pushed=False), self.f.worktree("locked")
        write(dirty, "new.txt", "x")
        self.f.git("worktree", "lock", locked)
        self.f.worked_in(dirty, unpushed, locked)
        r = self.f.run()
        self.assertEqual(wt(r, "dirty")["kept"], ["1 uncommitted or untracked files"])
        self.assertEqual(wt(r, "unpushed")["kept"], ["1 commit on no remote"])
        self.assertEqual(wt(r, "locked")["kept"], ["locked"])
        for path in (dirty, unpushed, locked):
            self.assertTrue(os.path.isdir(path))
        self.assertEqual([b for e in r["repos"] for b in e["branches"]], [])

    def test_leaves_worktrees_outside_the_session_alone(self):
        mine, other = self.f.worktree("mine"), self.f.worktree("other")
        self.f.worked_in(mine)
        r = self.f.run()
        self.assertFalse(os.path.exists(mine))
        self.assertTrue(os.path.isdir(other))
        self.assertEqual(left_alone(r), {"other"})

    def test_plan_changes_nothing(self):
        path = self.f.worktree("p")
        self.f.worked_in(path)
        r = self.f.run("plan")
        self.assertEqual(wt(r, "p")["kept"], [])
        self.assertTrue(os.path.isdir(path))

    def test_without_an_activity_record_nothing_is_removed(self):
        path = self.f.worktree("n")
        self.f.worked_in(path)
        r = self.f.run(session=None)
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(left_alone(r), {"n"})
        self.assertTrue(r["notes"])

    def test_named_worktree_is_removed_without_an_activity_record(self):
        path = self.f.worktree("named")
        self.f.run("apply", "named", session=None)
        self.assertFalse(os.path.exists(path))

    def test_recent_other_session_keeps_it_unless_named(self):
        path = self.f.worktree("shared")
        self.f.worked_in(path)
        self.f.worked_in(path, session="99999999-other")
        r = self.f.run()
        self.assertIn("another Codex session", wt(r, "shared")["kept"][0])
        self.assertTrue(os.path.isdir(path))
        self.f.run("apply", "shared")
        self.assertFalse(os.path.exists(path))

    def test_old_activity_in_another_session_does_not_block(self):
        path = self.f.worktree("old")
        self.f.worked_in(path)
        other = self.f.record({"hook_event_name": "UserPromptSubmit", "prompt": "go", "cwd": path}, "99999999-other")
        os.utime(other, (time.time() - 3 * 3600, time.time() - 3 * 3600))
        self.f.run()
        self.assertFalse(os.path.exists(path))

    def test_shell_inside_keeps_it(self):
        path = self.f.worktree("here")
        self.f.worked_in(path)
        r = self.f.run(cwd=path)
        self.assertIn("this shell is inside it", wt(r, "here")["kept"][0])
        self.assertTrue(os.path.isdir(path))

    @unittest.skipUnless(shutil.which("lsof"), "lsof not installed")
    def test_process_inside_keeps_it(self):
        path = self.f.worktree("busy")
        self.f.worked_in(path)
        proc = subprocess.Popen(["sleep", "60"], cwd=path)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        r = self.f.run()
        self.assertTrue(wt(r, "busy")["kept"][0].startswith("in use by sleep"), wt(r, "busy")["kept"])

    def test_session_build_output_is_removed(self):
        mine, other = os.path.join(self.f.scratch, "tests-" + SID), os.path.join(self.f.scratch, "tests-other")
        write(mine, "bin", "x")
        write(other, "bin", "x")
        r = self.f.run()
        self.assertFalse(os.path.exists(mine))
        self.assertTrue(os.path.isdir(other))
        self.assertTrue(r["session_dirs"][0]["removed"])


class BranchTest(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(shutil.rmtree, self.f.root, True)

    def test_merged_pr_deletes_branch_after_squash_and_prune(self):
        path = self.f.worktree("sq")
        tip = self.f.git("rev-parse", "HEAD", cwd=path)
        self.f.git("update-ref", "-d", "refs/remotes/origin/feat/sq")  # remote branch deleted after the squash merge
        self.f.prs = {"feat/sq": [{"number": 5, "state": "MERGED", "headRefOid": tip}]}
        self.f.worked_in(path)
        r = self.f.run()
        self.assertEqual(wt(r, "sq")["kept"], [])
        self.assertTrue(br(r, "feat/sq")["deleted"])
        self.assertIn("PR #5 merged", br(r, "feat/sq")["why"])
        self.assertFalse(self.f.git("branch", "--list", "feat/sq"))

    def test_merged_pr_with_later_local_commits_keeps_branch(self):
        path = self.f.worktree("more")
        merged = self.f.git("rev-parse", "HEAD", cwd=path)
        self.f.commit(path, "followup")
        self.f.git("push", "-q", "origin", "feat/more", cwd=path)
        self.f.prs = {"feat/more": [{"number": 6, "state": "MERGED", "headRefOid": merged}]}
        self.f.worked_in(path)
        r = self.f.run()
        self.assertFalse(os.path.exists(path))
        self.assertFalse(br(r, "feat/more")["deleted"])
        self.assertIn("commits the PR does not", br(r, "feat/more")["why"])

    def test_open_pr_keeps_branch(self):
        path = self.f.worktree("open")
        self.f.prs = {"feat/open": [{"number": 7, "state": "OPEN", "headRefOid": "0" * 40}]}
        self.f.worked_in(path)
        r = self.f.run()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(br(r, "feat/open")["why"], "PR #7 is open")
        self.assertTrue(self.f.git("branch", "--list", "feat/open"))

    def test_gh_failure_keeps_branch(self):
        path = self.f.worktree("nogh")
        self.f.worked_in(path)
        r = self.f.run(env={"FAKE_GH_FAIL": "1"})
        self.assertFalse(os.path.exists(path))
        self.assertIn("PR state unknown", br(r, "feat/nogh")["why"])

    def test_branches_the_session_created_are_found_from_its_commands(self):
        path = os.path.join(self.f.repo, ".claude", "worktrees", "made")
        self.f.ran("git worktree add .claude/worktrees/made -b feat/made main 2>&1 | tail -2", cwd=self.f.repo)
        self.f.git("worktree", "add", "-q", "-b", "feat/made", path, "main")
        self.f.ran("cd %s && git switch -c feat/tmp && git switch main" % self.f.repo, cwd=self.f.root)
        self.f.git("branch", "feat/tmp")
        r = self.f.run()
        self.assertFalse(os.path.exists(path))
        self.assertTrue(br(r, "feat/made")["deleted"])
        self.assertEqual(br(r, "feat/tmp")["why"], "already in origin/main")
        self.assertFalse(self.f.git("branch", "--list", "feat/tmp"))

    def test_checked_out_and_default_branches_are_kept(self):
        self.f.ran("git checkout -b feat/live && git checkout -b main", cwd=self.f.repo)
        self.f.git("checkout", "-q", "-b", "feat/live")
        r = self.f.run()
        self.assertEqual(br(r, "feat/live")["why"], "checked out in the main checkout")
        self.assertEqual(br(r, "main")["why"], "default branch")


class ActivityTrailTest(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(shutil.rmtree, self.f.root, True)

    def trail(self):
        with open(os.path.join(self.f.state, "activity", SID + ".json")) as fh:
            return json.load(fh)

    def test_trail_outlives_the_thirty_turn_event_cap(self):
        self.f.ran("git switch -c feat/early", cwd=self.f.repo)
        with mock.patch.dict(os.environ, {"CODEX_HOOK_STATE_DIR": self.f.state}):
            for n in range(40):
                activity.record({"session_id": SID, "turn_id": "t%d" % n, "hook_event_name": "UserPromptSubmit", "prompt": "p", "cwd": self.f.root})
        self.assertEqual(self.trail()["git_commands"], [[self.f.repo, "git switch -c feat/early"]])
        self.assertEqual(self.trail()["cwds"], [self.f.repo, self.f.root])

    def test_relative_workdir_resolves_against_the_session_cwd(self):
        tool = {"tool_name": "exec_command", "tool_input": {"cmd": "ls", "workdir": "sub"}, "tool_response": {"exit_code": 0}}
        self.f.record(dict(tool, hook_event_name="PostToolUse", cwd=self.f.repo))
        self.assertEqual(self.trail()["cwds"], [self.f.repo, os.path.join(self.f.repo, "sub")])
        self.assertNotIn("git_commands", self.trail())

    def test_record_from_before_the_trail_asks_for_names(self):
        write(os.path.join(self.f.state, "activity"), SID + ".json", json.dumps({"commands": [{"cmd": "git status"}]}))
        r = self.f.run("plan")
        self.assertTrue(any("predates" in n for n in r["notes"]), r["notes"])


class ParseTest(unittest.TestCase):
    def test_worktree_add_with_options_after_the_path(self):
        cmd = "git worktree add .claude/worktrees/latency -b feat/latency-series origin/main 2>&1 | tail -3"
        self.assertEqual(git_effects(cmd, "/r"), ({"/r/.claude/worktrees/latency"}, {("/r", "feat/latency-series")}))

    def test_cd_and_dash_c_move_the_repo(self):
        dirs, branches = git_effects("cd /a && git -C sub checkout -b x; git switch -c y", "/r")
        self.assertEqual(branches, {("/a/sub", "x"), ("/a", "y")})

    def test_text_that_mentions_git_is_not_a_command(self):
        self.assertEqual(git_effects("echo 'git worktree add /x' && grep -c 'git switch -c y' f", "/r"), (set(), set()))


if __name__ == "__main__":
    unittest.main()
