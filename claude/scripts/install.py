#!/usr/bin/env python3
"""Install this checkout's claude/ directory into ~/.claude.

Dry run by default: prints one line per planned action and changes nothing;
--apply performs them. Python 3.8+ standard library only.

  - Symlinks CLAUDE.md, agents, commands, hooks, rules and scripts, plus one
    link per skill directory holding a SKILL.md at <target>/skills/<name>. The
    skills directory itself is never linked and entries this repo does not
    provide are never touched.
  - settings.json is copied, never linked. An existing different one is kept
    (a diff summary is printed) unless --settings is given, which backs it up
    first.
  - CLAUDE.local.md is created from CLAUDE.local.md.example only if missing.
  - A path in the way (real file or directory, or a link pointing elsewhere)
    is moved to <target>/backups/install-<UTC timestamp>/, never deleted.
  - Correct links report "ok", so running it again changes nothing.
"""
import argparse
import datetime
import difflib
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
LINKED = ("CLAUDE.md", "agents", "commands", "hooks", "rules", "scripts")
REQUIRED = LINKED + ("skills", "settings.json", "CLAUDE.local.md.example")
DIFF_LINES = 40


class Run:
    def __init__(self, src, target, apply):
        self.src, self.target, self.apply = src, target, apply
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.backup_root = target / "backups" / ("install-" + stamp)

    def say(self, verb, text):
        print("%-14s %s" % (verb, text))

    def verb(self, done, planned):
        return done if self.apply else planned


def lexists(path):
    return path.is_symlink() or path.exists()


def same_link(dest, src):
    return dest.is_symlink() and dest.resolve() == src.resolve()


def back_up(run, path):
    dest = run.backup_root / path.relative_to(run.target)
    n = 1
    while lexists(dest):
        dest = dest.with_name("%s.%d" % (path.name, n))
        n += 1
    run.say(run.verb("back up", "would back up"), "%s -> %s" % (path, dest))
    if run.apply:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))


def make_link(run, dest, src):
    if same_link(dest, src):
        run.say("ok", "%s -> %s" % (dest, src))
        return
    if lexists(dest):
        back_up(run, dest)
    run.say(run.verb("link", "would link"), "%s -> %s" % (dest, src))
    if run.apply:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src, target_is_directory=src.is_dir())


def skill_dirs(src):
    return [p for p in sorted((src / "skills").iterdir()) if (p / "SKILL.md").is_file()]


def link_skills(run):
    skills = run.target / "skills"
    if skills.is_symlink() or (skills.exists() and not skills.is_dir()):
        back_up(run, skills)  # a linked skills dir would write into the checkout
    for path in skill_dirs(run.src):
        make_link(run, skills / path.name, path)


def read_lines(path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def settings_differs(dest, src):
    if dest.is_symlink() or not dest.is_file():
        return True
    return dest.read_bytes() != src.read_bytes()


def show_diff(dest, src):
    if dest.is_symlink() or not dest.is_file():
        print("  installed settings.json is %s, not a regular file" % ("a symlink" if dest.is_symlink() else "not a file"))
        return
    diff = list(difflib.unified_diff(read_lines(dest), read_lines(src), "installed", "repo"))
    changed = sum(1 for l in diff if l[0] in "+-" and not l.startswith(("+++", "---")))
    print("  %d changed line(s); first %d diff lines:" % (changed, DIFF_LINES))
    for line in diff[:DIFF_LINES]:
        print("  " + line.rstrip("\n"))


def copy_settings(run, replace):
    dest, src = run.target / "settings.json", run.src / "settings.json"
    if not lexists(dest):
        run.say(run.verb("copy", "would copy"), "settings.json -> %s" % dest)
    elif not settings_differs(dest, src):
        run.say("ok", "%s identical to the repo's settings.json" % dest)
        return
    elif not replace:
        run.say("kept", "%s differs from the repo's; use --settings to replace it" % dest)
        show_diff(dest, src)
        return
    else:
        back_up(run, dest)
        run.say(run.verb("replace", "would replace"), "settings.json -> %s" % dest)
    if run.apply:
        run.target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(src), str(dest))


def local_md(run):
    dest, src = run.target / "CLAUDE.local.md", run.src / "CLAUDE.local.md.example"
    if lexists(dest):
        run.say("ok", "%s exists, left alone" % dest)
        return
    run.say(run.verb("create", "would create"), "%s from CLAUDE.local.md.example" % dest)
    if run.apply:
        run.target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(src), str(dest))


def note_hosts(run):
    hosts = run.target / "local" / "ssh-dev-hosts"
    state = "exists" if hosts.exists() else "not created"
    run.say("note", "%s (%s): list this machine's dev hosts there, one ssh alias or address per line" % (hosts, state))


def check_layout(src, target):
    missing = [n for n in REQUIRED if not (src / n).exists()]
    if missing:
        return "source %s is missing: %s" % (src, ", ".join(missing))
    root = target.resolve()
    if root == src or src in root.parents:
        return "target %s is inside the source checkout %s" % (target, src)
    if root in src.parents:
        return "target %s contains the source checkout %s" % (target, src)
    return None


def install(run, replace_settings):
    for name in LINKED:
        make_link(run, run.target / name, run.src / name)
    link_skills(run)
    copy_settings(run, replace_settings)
    local_md(run)
    note_hosts(run)


def parse(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="perform the planned actions (default: dry run)")
    p.add_argument("--settings", action="store_true", help="replace a differing settings.json (old one is backed up first)")
    p.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude", metavar="PATH", help="target directory (default ~/.claude)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    target = args.claude_dir.expanduser().absolute()
    problem = check_layout(SRC, target)
    if problem:
        print("install.py: " + problem, file=sys.stderr)
        return 2
    run = Run(SRC, target, args.apply)
    try:
        install(run, args.settings)
    except OSError as exc:
        print("install.py: %s" % exc, file=sys.stderr)
        return 1
    if not args.apply:
        print("Dry run: nothing changed. Run with --apply to perform these actions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
