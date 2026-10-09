#!/usr/bin/env python3
"""Static checks for the Claude Code harness in this repo (claude/).

Catches the drift that otherwise only shows up as a silently ignored agent or
skill: frontmatter that does not parse, names that don't match files,
descriptions over the 1,024-character limit, SKILL.md files past 500 lines,
broken relative links, hard-coded home paths, agents preloading skills that
don't exist, and settings.json hooks pointing at missing scripts.

Usage: python3 claude/scripts/lint_harness.py [--root claude]
Exit status 1 when any error is found; warnings never fail.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs pyyaml
    yaml = None

MODELS = {"opus", "sonnet", "haiku", "fable", "inherit"}
ABS_HOME = re.compile(r"(?<![\w~])/(Users|home)/[A-Za-z0-9._-]+")
LINK = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")
MAX_DESC, MAX_SKILL_LINES, MAX_CLAUDE_MD_LINES = 1024, 500, 200


class Report:
    def __init__(self, root):
        self.root, self.errors, self.warnings = root, [], []

    def err(self, path, msg):
        self.errors.append("%s: %s" % (os.path.relpath(path, self.root), msg))

    def warn(self, path, msg):
        self.warnings.append("%s: %s" % (os.path.relpath(path, self.root), msg))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter(path, rep):
    text = read(path)
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        rep.err(path, "frontmatter is not closed with ---")
        return None
    raw = text[4:end]
    if yaml is None:
        rep.warn(path, "pyyaml not installed; frontmatter syntax not checked")
        return dict(re.findall(r"^([A-Za-z_-]+):\s*(.*)$", raw, re.M))
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        rep.err(path, "frontmatter is not valid YAML (%s)" % str(e).splitlines()[0])
        return None
    if not isinstance(data, dict):
        rep.err(path, "frontmatter is not a mapping")
        return None
    return data


def git_ignored(repo, path):
    try:
        return subprocess.run(["git", "-C", repo, "check-ignore", "-q", path], capture_output=True).returncode == 0
    except OSError:
        return False


def check_description(path, fm, rep):
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        rep.err(path, "missing description")
    elif len(str(desc)) > MAX_DESC:
        rep.err(path, "description is %d chars (limit %d)" % (len(str(desc)), MAX_DESC))


def check_text(path, rep):
    text = read(path)
    for n, line in enumerate(text.splitlines(), 1):
        if ABS_HOME.search(line):
            rep.err(path, "line %d: hard-coded home path; use ~ instead" % n)
    for target, _ in LINK.findall(text):
        if re.match(r"^[a-z]+:", target) or target.startswith(("/", "~", "$")):
            continue
        if not os.path.exists(os.path.join(os.path.dirname(path), target)):
            rep.err(path, "broken relative link: %s" % target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    args = ap.parse_args()
    root = os.path.realpath(args.root)
    repo = os.path.dirname(root)
    rep = Report(root)

    skills = {}
    for path in sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md"))):
        name = os.path.basename(os.path.dirname(path))
        skills[name] = path
        fm = frontmatter(path, rep)
        if fm is None:
            rep.err(path, "SKILL.md needs frontmatter with name and description")
            continue
        if fm.get("name") != name:
            rep.err(path, "name %r does not match directory %r" % (fm.get("name"), name))
        check_description(path, fm, rep)
        lines = read(path).count("\n") + 1
        if lines > MAX_SKILL_LINES:
            rep.err(path, "%d lines; keep SKILL.md under %d and move detail to reference files" % (lines, MAX_SKILL_LINES))
        for md in glob.glob(os.path.join(os.path.dirname(path), "**", "*.md"), recursive=True):
            check_text(md, rep)

    for path in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
        fm = frontmatter(path, rep)
        if fm is None:
            rep.err(path, "agent needs frontmatter with name and description")
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        if fm.get("name") != stem:
            rep.err(path, "name %r does not match file name %r" % (fm.get("name"), stem))
        check_description(path, fm, rep)
        model = fm.get("model")
        if model and model not in MODELS and not str(model).startswith("claude-"):
            rep.err(path, "unknown model %r" % model)
        for s in fm.get("skills") or []:
            if s not in skills and not git_ignored(repo, os.path.join(root, "skills", s) + "/"):
                rep.err(path, "preloads skill %r, which is neither in skills/ nor a local-only (gitignored) skill" % s)
        check_text(path, rep)

    for path in sorted(glob.glob(os.path.join(root, "commands", "*.md"))):
        fm = frontmatter(path, rep)
        if not fm or not fm.get("description"):
            rep.warn(path, "command has no description in frontmatter")
        check_text(path, rep)

    for path in sorted(glob.glob(os.path.join(root, "rules", "*.md"))):
        fm = frontmatter(path, rep)
        if not fm or not fm.get("paths"):
            rep.warn(path, "rule has no paths: and loads in every session")
        check_text(path, rep)

    claude_md = os.path.join(root, "CLAUDE.md")
    if os.path.exists(claude_md):
        check_text(claude_md, rep)
        text = read(claude_md)
        if text.count("\n") > MAX_CLAUDE_MD_LINES:
            rep.warn(claude_md, "%d lines; it loads every session, keep it lean" % text.count("\n"))
        for imp in re.findall(r"^@(\S+)", text, re.M):
            if imp.startswith("~/.claude/"):
                local = os.path.join(root, imp[len("~/.claude/"):])
                if not os.path.exists(local) and not git_ignored(repo, local):
                    rep.err(claude_md, "imports %s, which is neither in the repo nor gitignored as machine-local" % imp)

    settings = os.path.join(root, "settings.json")
    if os.path.exists(settings):
        try:
            data = json.loads(read(settings))
        except ValueError as e:
            rep.err(settings, "invalid JSON: %s" % e)
            data = {}
        for event, matchers in (data.get("hooks") or {}).items():
            for m in matchers:
                for h in m.get("hooks", []):
                    for script in re.findall(r"\$HOME/\.claude/hooks/([\w.-]+)", h.get("command", "")):
                        p = os.path.join(root, "hooks", script)
                        if not os.path.exists(p):
                            rep.err(settings, "%s hook runs missing script hooks/%s" % (event, script))
                        elif not os.access(p, os.X_OK):
                            rep.err(settings, "hooks/%s is not executable" % script)

    for w in rep.warnings:
        print("warning: " + w)
    for e in rep.errors:
        print("error: " + e)
    print("%d error(s), %d warning(s)" % (len(rep.errors), len(rep.warnings)))
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
