"""Tests for scripts/install.py, which installs claude/ into ~/.claude.

Every test builds a fake claude/ source tree and a target under a temp
directory; nothing touches the real home or the real checkout.

Run: python3 -m unittest discover -s claude/hooks/tests -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REAL_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts", "install.py")
LINKED = ("CLAUDE.md", "agents", "commands", "hooks", "rules", "scripts")
HAS_SYMLINKS = hasattr(os, "symlink")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def read(path):
    with open(path) as fh:
        return fh.read()


@unittest.skipUnless(HAS_SYMLINKS, "no symlink support")
class InstallTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = os.path.join(self.root, "src", "claude")
        self.target = os.path.join(self.root, "home", ".claude")
        for name in LINKED:
            if name == "CLAUDE.md":
                write(os.path.join(self.src, name), "global\n")
            else:
                write(os.path.join(self.src, name, "keep.txt"), name)
        write(os.path.join(self.src, "skills", "alpha", "SKILL.md"), "a")
        write(os.path.join(self.src, "skills", "beta", "SKILL.md"), "b")
        write(os.path.join(self.src, "skills", "not-a-skill", "notes.txt"), "x")
        write(os.path.join(self.src, "settings.json"), '{"a": 1}\n')
        write(os.path.join(self.src, "CLAUDE.local.md.example"), "# example\n")
        shutil.copyfile(REAL_SCRIPT, os.path.join(self.src, "scripts", "install.py"))
        self.script = os.path.join(self.src, "scripts", "install.py")

    def run_install(self, *args, script=None):
        cmd = [sys.executable, script or self.script, "--claude-dir", self.target] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def tree(self):
        out = []
        for base, dirs, files in os.walk(self.root):
            for name in dirs + files:
                out.append(os.path.relpath(os.path.join(base, name), self.root))
        return sorted(out)

    def link_ok(self, rel, src_rel):
        path = os.path.join(self.target, rel)
        self.assertTrue(os.path.islink(path), rel)
        self.assertEqual(os.path.realpath(path), os.path.realpath(os.path.join(self.src, src_rel)))

    def backups(self):
        base = os.path.join(self.target, "backups")
        found = []
        for d, _, files in os.walk(base):
            found += [os.path.relpath(os.path.join(d, f), base) for f in files]
        return found

    def test_dry_run_changes_nothing(self):
        before = self.tree()
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tree(), before)
        self.assertFalse(os.path.exists(self.target))
        self.assertIn("would link", r.stdout)
        self.assertIn("Dry run", r.stdout)

    def test_dry_run_reports_backup_without_moving(self):
        write(os.path.join(self.target, "hooks", "mine.txt"), "mine")
        r = self.run_install()
        self.assertIn("would back up", r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(self.target, "hooks", "mine.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.target, "backups")))

    def test_apply_on_empty_target(self):
        r = self.run_install("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in LINKED:
            self.link_ok(name, name)
        self.link_ok("skills/alpha", "skills/alpha")
        self.link_ok("skills/beta", "skills/beta")
        self.assertFalse(os.path.lexists(os.path.join(self.target, "skills", "not-a-skill")))
        self.assertFalse(os.path.islink(os.path.join(self.target, "skills")))
        self.assertFalse(os.path.islink(os.path.join(self.target, "settings.json")))
        self.assertEqual(read(os.path.join(self.target, "settings.json")), '{"a": 1}\n')
        self.assertFalse(os.path.islink(os.path.join(self.target, "CLAUDE.local.md")))
        self.assertEqual(read(os.path.join(self.target, "CLAUDE.local.md")), "# example\n")
        self.assertFalse(os.path.exists(os.path.join(self.target, "local")))
        self.assertIn("ssh-dev-hosts", r.stdout)

    def test_second_apply_is_noop(self):
        self.run_install("--apply")
        before = self.tree()
        r = self.run_install("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tree(), before)
        for line in r.stdout.splitlines():
            if line.startswith("note") or line.startswith("Dry run"):
                continue
            self.assertTrue(line.startswith("ok"), line)

    def test_real_directory_in_the_way_is_backed_up(self):
        write(os.path.join(self.target, "hooks", "mine.txt"), "mine")
        r = self.run_install("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.link_ok("hooks", "hooks")
        moved = [b for b in self.backups() if b.endswith(os.path.join("hooks", "mine.txt"))]
        self.assertEqual(len(moved), 1, self.backups())
        self.assertTrue(moved[0].startswith("install-"))
        self.assertEqual(read(os.path.join(self.target, "backups", moved[0])), "mine")

    def test_link_pointing_elsewhere_is_backed_up(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere)
        os.makedirs(self.target)
        os.symlink(elsewhere, os.path.join(self.target, "rules"))
        self.run_install("--apply")
        self.link_ok("rules", "rules")
        self.assertTrue(os.path.isdir(elsewhere))
        backed = [d for d in os.listdir(os.path.join(self.target, "backups"))]
        self.assertEqual(len(backed), 1)
        self.assertTrue(os.path.islink(os.path.join(self.target, "backups", backed[0], "rules")))

    def test_foreign_skill_survives(self):
        write(os.path.join(self.target, "skills", "local-only", "SKILL.md"), "mine")
        self.run_install("--apply")
        self.run_install("--apply")
        self.assertEqual(read(os.path.join(self.target, "skills", "local-only", "SKILL.md")), "mine")
        self.assertFalse(os.path.islink(os.path.join(self.target, "skills", "local-only")))
        self.link_ok("skills/alpha", "skills/alpha")
        self.assertEqual(self.backups(), [])

    def test_differing_settings_kept_without_flag(self):
        write(os.path.join(self.target, "settings.json"), '{"a": 2}\n')
        r = self.run_install("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(os.path.join(self.target, "settings.json")), '{"a": 2}\n')
        self.assertIn("--settings", r.stdout)
        self.assertIn("changed line", r.stdout)
        self.assertIn('-{"a": 2}', r.stdout)
        self.assertIn('+{"a": 1}', r.stdout)
        self.assertEqual(self.backups(), [])

    def test_differing_settings_replaced_with_backup(self):
        write(os.path.join(self.target, "settings.json"), '{"a": 2}\n')
        r = self.run_install("--apply", "--settings")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(os.path.join(self.target, "settings.json")), '{"a": 1}\n')
        saved = [b for b in self.backups() if b.endswith("settings.json")]
        self.assertEqual(len(saved), 1)
        self.assertEqual(read(os.path.join(self.target, "backups", saved[0])), '{"a": 2}\n')

    def test_settings_flag_alone_is_still_a_dry_run(self):
        write(os.path.join(self.target, "settings.json"), '{"a": 2}\n')
        r = self.run_install("--settings")
        self.assertIn("would replace", r.stdout)
        self.assertEqual(read(os.path.join(self.target, "settings.json")), '{"a": 2}\n')
        self.assertFalse(os.path.exists(os.path.join(self.target, "backups")))

    def test_identical_settings_reported(self):
        write(os.path.join(self.target, "settings.json"), '{"a": 1}\n')
        r = self.run_install("--apply", "--settings")
        self.assertIn("identical", r.stdout)
        self.assertNotIn("settings.json", " ".join(self.backups()))

    def test_existing_local_md_untouched(self):
        write(os.path.join(self.target, "CLAUDE.local.md"), "mine: cargo test\n")
        self.run_install("--apply", "--settings")
        self.assertEqual(read(os.path.join(self.target, "CLAUDE.local.md")), "mine: cargo test\n")
        self.assertEqual(self.backups(), [])

    def test_missing_source_layout_fails(self):
        shutil.rmtree(os.path.join(self.src, "rules"))
        r = self.run_install("--apply")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rules", r.stderr)
        self.assertFalse(os.path.exists(self.target))

    def test_target_inside_source_refused(self):
        cmd = [sys.executable, self.script, "--apply", "--claude-dir", os.path.join(self.src, "sub")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("inside the source", r.stderr)

    def test_source_resolved_through_symlinked_script(self):
        alias = os.path.join(self.root, "alias.py")
        os.symlink(self.script, alias)
        r = self.run_install("--apply", script=alias)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.link_ok("hooks", "hooks")


class RealCheckoutTest(unittest.TestCase):
    def test_dry_run_against_real_source_changes_nothing(self):
        target = os.path.join(tempfile.mkdtemp(), "claude")
        self.addCleanup(shutil.rmtree, os.path.dirname(target), True)
        r = subprocess.run([sys.executable, REAL_SCRIPT, "--claude-dir", target], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(target))

    def test_help_mentions_dry_run(self):
        r = subprocess.run([sys.executable, REAL_SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Dry run", r.stdout)


if __name__ == "__main__":
    unittest.main()
