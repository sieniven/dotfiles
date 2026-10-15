#!/usr/bin/env python3
"""Session cleanup: remove the git worktrees, merged branches and build output a
Claude session used, once its work is safe on a remote. Backs /cleanup.

Scope comes from the session's transcript ($CLAUDE_CODE_SESSION_ID, plus its
subagents' transcripts): every linked worktree the session ran a command in or
created with `git worktree add`, plus any worktree named on the command line (a
path, or a directory name such as `latency` for <repo>/.claude/worktrees/latency).
The repos those belong to, and the current one, are in scope; their other
worktrees are reported as left alone. With no transcript and no names, nothing
is removed.

A worktree is removed with `git worktree remove` (never --force; its ignored
build output such as target/ goes with it) only when all of these hold, and is
kept with every failing reason listed otherwise:
  - no uncommitted or untracked files
  - every commit is on a remote: reachable from a remote-tracking ref, or the
    tip is the head of a GitHub PR for its branch
  - not locked
  - no process has its working directory inside it (this shell included)
  - unless it was named: no other Claude session's transcript shows it working
    there within the last CLAUDE_CLEANUP_ACTIVE_MINUTES

A local branch is considered when it belonged to a removed worktree or the
session created it (`worktree add -b`, `checkout -b`, `switch -c`). It is
deleted only when it is not checked out, not main/master or the remote default,
has no open PR, and a merged PR's head or the remote default branch contains its
tip. `git branch -d` first, `-D` only on that proof (a squash merge whose remote
branch is gone). A closed, unmerged or missing PR keeps the branch.

Last, the session's own build output goes: each CLAUDE_CLEANUP_SESSION_DIRS
entry with {session} replaced by the session id.

Usage:
  session_cleanup.py plan  [WORKTREE ...] [--repo DIR] [--json]   report only
  session_cleanup.py apply [WORKTREE ...] [--repo DIR] [--json]   do it
  --session ID and --transcript PATH override the session lookup.

Env: CLAUDE_CODE_SESSION_ID, CLAUDE_PROJECTS_DIR (default ~/.claude/projects),
CLAUDE_CLEANUP_GH (default gh), CLAUDE_CLEANUP_ACTIVE_MINUTES (default 30),
CLAUDE_CLEANUP_SESSION_DIRS (':'-separated; default the per-session test copies
of the worktree test runner, ~/.cache/claude-scratch/bin/tests-{session} and
~/.cache/claude-scratch/bin/benches-{session}).
Exit status 1 when a removal or deletion failed.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

HOME = os.path.realpath(os.path.expanduser("~"))
PROJECTS = os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.join(HOME, ".claude", "projects")
GH = os.environ.get("CLAUDE_CLEANUP_GH") or "gh"
ACTIVE_SECONDS = 60 * float(os.environ.get("CLAUDE_CLEANUP_ACTIVE_MINUTES") or "30")
SESSION_DIRS = os.environ.get("CLAUDE_CLEANUP_SESSION_DIRS") or ":".join(
    os.path.join(HOME, ".cache", "claude-scratch", "bin", kind + "-{session}") for kind in ("tests", "benches")
)
TAIL_BYTES = 1 << 20
SHELL_OPS = {"&&", "||", ";", "|", "|&", "&", "(", ")", ";;"}
WRAPPERS = {"builtin", "command", "env", "exec", "nice", "time"}


# --------------------------------------------------------------------------
# Helpers


def run(argv: list[str], cwd: str | None = None, timeout: float | None = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return r.returncode, r.stdout, r.stderr


def git(cwd: str, *args: str, timeout: float | None = 60) -> tuple[int, str]:
    rc, out, err = run(["git", "-C", cwd] + list(args), timeout=timeout)
    return rc, (out if rc == 0 else err).strip()


def git_ok(cwd: str, *args: str) -> str | None:
    rc, out = git(cwd, *args)
    return out if rc == 0 else None


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def show(path: str, repo: str | None = None) -> str:
    if repo and path != repo and inside(path, repo):
        return os.path.relpath(path, repo)
    return "~" + path[len(HOME) :] if inside(path, HOME) else path


def size_kb(path: str) -> int | None:
    _, out, _ = run(["du", "-sk", path], timeout=None)
    try:
        return int(out.split()[0])
    except (IndexError, ValueError):
        return None


def human(kb: int | None) -> str:
    if kb is None:
        return "size unknown"
    n = float(kb)
    for unit in ("KB", "MB", "GB"):
        if n < 1024:
            return "%.0f %s" % (n, unit) if unit == "KB" else "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f TB" % n


def first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else "no output"


def stamp(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------
# What the session did, from its transcript


def find_transcript(session: str) -> str | None:
    hits = glob.glob(os.path.join(PROJECTS, "*", session + ".jsonl"))
    return hits[0] if hits else None


def with_subagents(transcript: str) -> list[str]:
    base = transcript[: -len(".jsonl")] if transcript.endswith(".jsonl") else transcript
    return [transcript] + sorted(glob.glob(os.path.join(base, "subagents", "*.jsonl")))


def simple_commands(command: str) -> list[list[str]]:
    """The words of each simple command in a shell command, redirections dropped. Best effort."""
    found = []
    for line in command.splitlines():
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        try:
            tokens = list(lex)
        except ValueError:
            continue
        words, skip = [], False
        for tok in tokens:
            if skip:
                skip = False
            elif tok and all(ch in "();<>|&" for ch in tok):
                if "<" in tok or ">" in tok:
                    skip = True  # the redirection target
                    if words and words[-1].isdigit():
                        words.pop()  # the 2 of 2>&1
                else:
                    found.append(words)
                    words = []
            else:
                words.append(tok)
        found.append(words)
    return [w for w in found if w]


def resolve(base: str, path: str) -> str:
    return os.path.normpath(os.path.join(base, os.path.expandvars(os.path.expanduser(path))))


def parse_worktree_add(args: list[str]) -> tuple[str | None, str | None]:
    path = branch = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-b", "-B") and i + 1 < len(args):
            branch = args[i + 1]
            i += 2
            continue
        if a == "--reason":
            i += 2
            continue
        if not a.startswith("-") and path is None:
            path = a
        i += 1
    return path, branch


def git_effects(command: str, cwd: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Worktree paths a Bash command adds, and the (directory, branch) pairs it creates."""
    dirs, branches = set(), set()
    base = cwd
    for words in simple_commands(command):
        while words and (words[0] in WRAPPERS or ("=" in words[0] and not words[0].startswith("-"))):
            words = words[1:]
        if len(words) >= 2 and words[0] == "cd":
            base = resolve(base, words[1])
            continue
        if not words or os.path.basename(words[0]) != "git":
            continue
        repo, i = base, 1
        while i < len(words) and words[i].startswith("-"):
            if words[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(words):
                if words[i] == "-C":
                    repo = resolve(repo, words[i + 1])
                i += 2
            else:
                i += 1
        sub, args = words[i : i + 1], words[i + 1 :]
        if sub == ["worktree"] and args[:1] == ["add"]:
            path, branch = parse_worktree_add(args[1:])
            if path:
                dirs.add(resolve(repo, path))
            if branch:
                branches.add((repo, branch))
        elif sub in (["checkout"], ["switch"]):
            flags = ("-b", "-B") if sub == ["checkout"] else ("-c", "-C", "--create", "--force-create")
            branches.update((repo, args[j + 1]) for j in range(len(args) - 1) if args[j] in flags)
    return dirs, branches


def tool_uses(entry: dict) -> list[dict]:
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]


def read_trail(paths: list[str]) -> tuple[set[str], set[tuple[str, str]]]:
    """Directories the session worked in (cwds and added worktrees) and the branches it created."""
    dirs, branches = set(), set()
    for path in paths:
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                cwd = entry.get("cwd") if isinstance(entry, dict) else None
                if not isinstance(cwd, str) or not cwd:
                    continue
                dirs.add(cwd)
                for use in tool_uses(entry):
                    inp = use.get("input")
                    cmd = inp.get("command") if use.get("name") == "Bash" and isinstance(inp, dict) else None
                    if isinstance(cmd, str) and "git" in cmd:
                        d, b = git_effects(cmd, cwd)
                        dirs |= d
                        branches |= b
    return dirs, branches


def recent_activity(own: set[str]) -> list[tuple[str, set[str]]]:
    """(session id, cwds) of every other transcript with entries inside the activity window."""
    cutoff = time.time() - ACTIVE_SECONDS
    paths = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    paths += glob.glob(os.path.join(PROJECTS, "*", "*", "subagents", "*.jsonl"))
    found = []
    for path in paths:
        if real(path) in own:
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            with open(path, "rb") as fh:
                fh.seek(max(0, os.path.getsize(path) - TAIL_BYTES))
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        cwds = set()
        for line in tail.splitlines():
            if '"cwd"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("cwd"), str) and stamp(entry.get("timestamp")) >= cutoff:
                cwds.add(entry["cwd"])
        if cwds:
            sub = os.path.basename(os.path.dirname(path)) == "subagents"
            sid = os.path.basename(os.path.dirname(os.path.dirname(path))) if sub else os.path.basename(path)[:-6]
            found.append((sid, {real(c) for c in cwds}))
    return found


def process_cwds() -> list[tuple[int, str, str]] | None:
    """(pid, command, cwd) of every process lsof can see; None when lsof is missing."""
    rc, out, _ = run(["lsof", "-nP", "-w", "-d", "cwd", "-Fpcn"], timeout=60)
    if rc == 127:
        return None
    procs, pid, cmd = [], None, ""
    for line in out.splitlines():
        tag, val = line[:1], line[1:]
        if tag == "p":
            pid, cmd = int(val), ""
        elif tag == "c":
            cmd = val
        elif tag == "n" and pid is not None:
            procs.append((pid, cmd, real(val)))
    return procs


# --------------------------------------------------------------------------
# Git state


def checkout_of(path: str) -> tuple[str, str] | None:
    """(checkout top, main checkout) for the nearest existing directory at or above path."""
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    out = git_ok(path, "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir")
    lines = (out or "").splitlines()
    if len(lines) < 2:
        return None
    top, common = real(lines[0]), real(lines[1])
    return top, os.path.dirname(common) if os.path.basename(common) == ".git" else common


def list_worktrees(repo: str) -> list[dict]:
    """`git worktree list --porcelain` as dicts, main checkout first, with path and branch_name added."""
    out = git_ok(repo, "worktree", "list", "--porcelain") or ""
    items, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if cur:
                items.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val
    for it in items:
        it["path"] = real(it.get("worktree", ""))
        ref = it.get("branch", "")
        it["branch_name"] = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else None
    return items


def default_remote_branch(repo: str) -> str | None:
    ref = git_ok(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref
    for name in ("origin/main", "origin/master"):
        if git_ok(repo, "rev-parse", "--verify", "-q", "refs/remotes/" + name):
            return name
    return None


def contains(repo: str, outer: str | None, tip: str) -> bool:
    """True when commit `outer` exists and has `tip` in its history."""
    if not outer:
        return False
    if outer == tip:
        return True
    if git(repo, "cat-file", "-e", outer + "^{commit}")[0] != 0:
        return False
    return git(repo, "merge-base", "--is-ancestor", tip, outer)[0] == 0


class Context:
    """Lookups shared across worktrees, each run at most once."""

    def __init__(self, own: set[str]):
        self.own = own
        self.cwd = real(os.getcwd())
        self._procs: list[tuple[int, str, str]] | None = None
        self._procs_read = False
        self._others: list[tuple[str, set[str]]] | None = None
        self._prs: dict[tuple[str, str], list[dict] | None] = {}

    def procs(self) -> list[tuple[int, str, str]] | None:
        if not self._procs_read:
            self._procs, self._procs_read = process_cwds(), True
        return self._procs

    def others(self) -> list[tuple[str, set[str]]]:
        if self._others is None:
            self._others = recent_activity(self.own)
        return self._others

    def prs(self, repo: str, branch: str | None) -> list[dict] | None:
        """The branch's PRs from gh (state, number, headRefOid); None when gh is unavailable."""
        if not branch:
            return None
        key = (repo, branch)
        if key not in self._prs:
            argv = [GH, "pr", "list", "--head", branch, "--state", "all", "--json", "number,state,headRefOid", "--limit", "20"]
            rc, out, _ = run(argv, cwd=repo, timeout=60)
            try:
                data = json.loads(out) if rc == 0 else None
            except ValueError:
                data = None
            self._prs[key] = data if isinstance(data, list) else None
        return self._prs[key]


# --------------------------------------------------------------------------
# Verdicts


def assess(ctx: Context, repo: str, wt: dict, named: bool) -> list[str]:
    """Reasons to keep a worktree; empty when it is safe to remove."""
    path, head, branch = wt["path"], wt.get("HEAD"), wt["branch_name"]
    reasons = []
    if "locked" in wt:
        reasons.append("locked" + (" (%s)" % wt["locked"] if wt["locked"] else ""))
    rc, out = git(path, "status", "--porcelain")
    if rc != 0:
        reasons.append("git status failed: %s" % first_line(out))
    elif out:
        reasons.append("%d uncommitted or untracked files" % len(out.splitlines()))
    count = git_ok(path, "rev-list", "--count", head, "--not", "--remotes") if head else None
    if count is None or not count.isdigit():
        reasons.append("could not tell whether its commits are pushed")
    elif int(count) and not any(p.get("headRefOid") == head for p in ctx.prs(repo, branch) or []):
        reasons.append("%s commit%s on no remote" % (count, "" if count == "1" else "s"))
    if inside(ctx.cwd, path):
        reasons.append("this shell is inside it; cd to %s first" % show(repo))
    procs = ctx.procs() or []
    users = [(pid, cmd) for pid, cmd, cwd in procs if inside(cwd, path) and pid not in (os.getpid(), os.getppid())]
    if users:
        reasons.append("in use by " + ", ".join("%s (pid %d)" % (cmd, pid) for pid, cmd in users[:3]))
    if not named:
        sessions = sorted({sid[:8] for sid, cwds in ctx.others() if any(inside(c, path) for c in cwds)})
        if sessions:
            reasons.append(
                "another Claude session worked here in the last %d min (%s); name it to remove anyway"
                % (ACTIVE_SECONDS // 60, ", ".join(sessions))
            )
    return reasons


def branch_verdict(
    ctx: Context, repo: str, name: str, tip: str, checked_out: dict[str, str], default: str | None
) -> tuple[bool, str]:
    """(delete?, why) for a local branch."""
    protected = {"main", "master"} | ({default.split("/", 1)[1]} if default else set())
    if name in protected:
        return False, "default branch"
    if name in checked_out:
        where = checked_out[name]
        return False, "checked out in %s" % ("the main checkout" if where == repo else show(where, repo))
    prs = ctx.prs(repo, name)
    for p in prs or []:
        if p.get("state") == "OPEN":
            return False, "PR #%s is open" % p.get("number")
    merged = [p for p in prs or [] if p.get("state") == "MERGED"]
    for p in merged:
        if contains(repo, p.get("headRefOid"), tip):
            return True, "PR #%s merged" % p.get("number")
    if default and git(repo, "merge-base", "--is-ancestor", tip, "refs/remotes/" + default)[0] == 0:
        return True, "already in %s" % default
    if merged:
        return False, "PR #%s merged, but the branch has commits the PR does not" % merged[0].get("number")
    if prs is None:
        return False, "PR state unknown (gh failed or is not installed)"
    closed = [p for p in prs if p.get("state") == "CLOSED"]
    if closed:
        return False, "PR #%s closed without merging" % closed[0].get("number")
    return False, "no PR"


def delete_branch(repo: str, name: str) -> tuple[bool, str]:
    """Called only once branch_verdict proved nothing is lost, which is what makes the -D fallback safe."""
    rc, out = git(repo, "branch", "-d", name)
    if rc == 0:
        return True, "-d"
    rc, out = git(repo, "branch", "-D", name)
    return rc == 0, "-D" if rc == 0 else first_line(out)


# --------------------------------------------------------------------------
# Main


def cleanup(args: argparse.Namespace) -> tuple[dict, bool]:
    apply = args.mode == "apply"
    notes = []
    failed = False

    transcript = args.transcript or (find_transcript(args.session) if args.session else None)
    own = [real(p) for p in with_subagents(transcript)] if transcript else []
    if transcript:
        dirs, created = read_trail(own)
    else:
        dirs, created = set(), set()
        notes.append(
            "no transcript for session %s: only named worktrees are in scope" % args.session[:8]
            if args.session
            else "CLAUDE_CODE_SESSION_ID is not set: only named worktrees are in scope"
        )

    repos: dict[str, None] = {}  # main checkouts, in discovery order
    session_wts, named = set(), set()
    here = checkout_of(real(args.repo))
    if here:
        repos[here[1]] = None
    for d in sorted(dirs):
        co = checkout_of(real(d))
        if co:
            repos.setdefault(co[1])
            if co[0] != co[1]:
                session_wts.add(co[0])
    created_branches = set()
    for d, b in created:
        co = checkout_of(real(d))
        if co:
            repos.setdefault(co[1])
            created_branches.add((co[1], b))
    bare_names = []
    for name in args.worktrees:
        co = checkout_of(real(name)) if os.path.isdir(real(name)) else None
        if co and co[0] != co[1]:
            repos.setdefault(co[1])
            named.add(co[0])
        elif co:
            notes.append("%s is not a linked worktree" % name)
        else:
            bare_names.append(name)

    linked = {repo: [w for w in list_worktrees(repo)[1:] if "prunable" not in w] for repo in repos}
    for name in bare_names:
        hits = [w["path"] for ws in linked.values() for w in ws if os.path.basename(w["path"]) == name]
        if len(hits) == 1:
            named.add(hits[0])
        else:
            notes.append("%s worktree named %s in scope" % ("no" if not hits else "more than one", name))

    ctx = Context(set(own))
    report = {"mode": args.mode, "session": args.session, "notes": notes, "repos": [], "session_dirs": [], "freed_kb": 0}
    for repo in repos:
        entry = {"repo": repo, "worktrees": [], "branches": [], "left_alone": []}
        for wt in linked[repo]:
            if wt["path"] not in session_wts and wt["path"] not in named:
                entry["left_alone"].append({"path": wt["path"], "branch": wt["branch_name"]})
                continue
            item = {"path": wt["path"], "branch": wt["branch_name"], "kept": assess(ctx, repo, wt, wt["path"] in named)}
            item["size_kb"] = None if item["kept"] else size_kb(wt["path"])
            if apply and not item["kept"]:
                rc, out = git(repo, "worktree", "remove", wt["path"], timeout=None)
                if rc != 0:
                    item["kept"] = ["git worktree remove failed: %s" % first_line(out)]
                    failed = True
            if not item["kept"]:
                report["freed_kb"] += item["size_kb"] or 0
            entry["worktrees"].append(item)
        if apply and entry["worktrees"]:
            git(repo, "worktree", "prune")

        gone = {i["path"] for i in entry["worktrees"] if not i["kept"]}
        checked_out = {w["branch_name"]: w["path"] for w in list_worktrees(repo) if w["branch_name"] and w["path"] not in gone}
        names = [i["branch"] for i in entry["worktrees"] if not i["kept"] and i["branch"]]
        names += sorted(b for r, b in created_branches if r == repo)
        default = default_remote_branch(repo)
        for name in dict.fromkeys(names):
            tip = git_ok(repo, "rev-parse", "--verify", "-q", "refs/heads/" + name)
            if not tip:
                continue  # already gone
            delete, why = branch_verdict(ctx, repo, name, tip, checked_out, default)
            branch = {"name": name, "delete": delete, "why": why, "deleted": False}
            if apply and delete:
                ok, how = delete_branch(repo, name)
                branch["deleted"] = ok
                if not ok:
                    branch["why"] += "; delete failed: %s" % how
                    failed = True
                elif how == "-D":
                    branch["why"] += " (squash merge: deleted with -D)"
            entry["branches"].append(branch)
        if entry["worktrees"] or entry["branches"] or entry["left_alone"]:
            report["repos"].append(entry)

    if args.session and re.fullmatch(r"[A-Za-z0-9_-]+", args.session):
        for pattern in SESSION_DIRS.split(":"):
            path = real(pattern.replace("{session}", args.session)) if "{session}" in pattern else None
            if not path or not os.path.isdir(path):
                continue
            item = {"path": path, "size_kb": size_kb(path), "removed": False}
            if apply:
                try:
                    shutil.rmtree(path)
                    item["removed"] = True
                except OSError as e:
                    item["error"] = str(e)
                    failed = True
            if apply == item["removed"]:
                report["freed_kb"] += item["size_kb"] or 0
            report["session_dirs"].append(item)

    if any(e["worktrees"] for e in report["repos"]) and ctx.procs() is None:
        notes.append("lsof not found: did not check for processes working inside the worktrees")
    return report, failed


def render(report: dict) -> str:
    plan = report["mode"] == "plan"
    sid = report["session"]
    lines = ["Session %s%s" % (sid[:8] if sid else "unknown", ": plan only, nothing changed" if plan else "")]
    acted = False
    for entry in report["repos"]:
        repo = entry["repo"]
        lines += ["", show(repo)]
        for w in entry["worktrees"]:
            label = "%s [%s]" % (show(w["path"], repo), w["branch"] or "detached")
            if w["kept"]:
                lines.append("  kept          %s: %s" % (label, "; ".join(w["kept"])))
            else:
                acted = True
                lines.append("  %s %s, %s" % ("would remove " if plan else "removed      ", label, human(w["size_kb"])))
        for b in entry["branches"]:
            if b["delete"] and (plan or b["deleted"]):
                acted = True
                lines.append("  %s branch %s: %s" % ("would delete" if plan else "deleted", b["name"], b["why"]))
            else:
                lines.append("  kept branch %s: %s" % (b["name"], b["why"]))
        if entry["left_alone"]:
            alone = ", ".join("%s [%s]" % (show(w["path"], repo), w["branch"] or "detached") for w in entry["left_alone"])
            lines.append("  left alone, not this session's: " + alone)
    if report["session_dirs"]:
        lines += ["", "Session build output"]
        for d in report["session_dirs"]:
            if d.get("error"):
                lines.append("  kept          %s: %s" % (show(d["path"]), d["error"]))
            else:
                acted = True
                lines.append("  %s %s, %s" % ("would remove " if plan else "removed      ", show(d["path"]), human(d["size_kb"])))
    lines.append("")
    if not acted:
        lines.append("Nothing to remove.")
    elif report["freed_kb"]:
        lines.append("%s %s." % ("Would free" if plan else "Freed", human(report["freed_kb"])))
    lines += ["Note: " + n for n in report["notes"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("plan", "apply"))
    ap.add_argument("worktrees", nargs="*", help="extra worktrees: a path, or a directory name such as latency")
    ap.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID") or None)
    ap.add_argument("--transcript", help="transcript to read instead of the session's own")
    ap.add_argument("--repo", default=os.getcwd(), help="repo to report on when the session names none (default: cwd)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_intermixed_args(argv)
    report, failed = cleanup(args)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
