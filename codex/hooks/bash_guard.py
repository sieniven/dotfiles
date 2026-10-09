#!/usr/bin/env python3
"""PreToolUse(Bash) guard: enforce the global AGENTS.md hard rules in code.

Prose rules are requests; this hook makes the important ones binding. It
parses the command into simple commands (splitting on ; && || | & newlines,
command substitutions, `bash -c` / `eval` strings, and wrappers such as
`timeout`, `env`, `sudo`) and checks each one.

Checks (ids for CODEX_HOOKS_DISABLE, prefixed `bash-guard:`):
  merge        deny  `gh pr merge`, merge via `gh api`          (never merge a PR)
  nohup        deny  `nohup`                                     (never use nohup)
  no-verify    deny  `--no-verify`, `git commit -n`, core.hooksPath overrides
  force-push   deny  force-push or delete of a protected branch; ask for other force-pushes
  direct-tests deny  `cargo test|bench`, `just test|check` where the machine-local
                     AGENTS.local.md routes tests through its own runner; skipped
                     inside a linked git worktree, and when CARGO_TARGET_DIR or
                     --target-dir sends build output under $HOME outside the checkout
  destructive  deny  `rm -r` of /, ~ or an ancestor of ~; ask for `rm -r .`/`..`/`*`,
                     `git reset --hard`, `git clean -f`, `git checkout/restore .`,
                     docker volume/system prune
  secrets      deny  committing private keys, known token formats, .env/key files;
                     ask for generic `password = "..."`-style assignments
"""

import fnmatch
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import enabled, pre_tool_decision, run  # noqa: E402

HOOK = "bash-guard"
HOME = os.path.realpath(os.path.expanduser("~"))
PROTECTED_BRANCHES = {"main", "master"} | {
    b.strip() for b in os.environ.get("CODEX_PROTECTED_BRANCHES", "").split(",") if b.strip()
}
WRAPPERS = {"sudo", "command", "exec", "builtin", "time", "nice", "env", "stdbuf", "caffeinate", "noglob", "nohup"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
SYSTEM_DIRS = {
    "/usr", "/etc", "/var", "/bin", "/sbin", "/lib", "/opt", "/System", "/Library",
    "/Applications", "/private", "/Users", "/home", "/root",
}
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")

DENY, ASK = 2, 1


class Findings:
    def __init__(self):
        self.items = []

    def add(self, level, check, msg):
        if enabled("%s:%s" % (HOOK, check)):
            self.items.append((level, msg))

    def emit(self):
        if not self.items:
            return
        level = max(l for l, _ in self.items)
        msgs = []
        for _, m in self.items:
            if m not in msgs:
                msgs.append(m)
        reason = "[bash-guard] " + " | ".join(msgs)
        if level == DENY:
            reason += (
                " This is a hard rule from the global AGENTS.md, not an obstacle: do not route"
                " around it (bash -c, scripts, aliases). If the user wants it anyway, ask them"
                " to run it themselves."
            )
        pre_tool_decision("deny" if level == DENY else "ask", reason)


# --------------------------------------------------------------------------
# Parsing


def strip_heredocs(cmd):
    """Drop heredoc bodies so text inside them is never parsed as commands."""
    out, pending = [], []
    for line in cmd.split("\n"):
        if pending:
            delim, dash = pending[0]
            if (line.strip() if dash else line) == delim:
                pending.pop(0)
            continue
        out.append(line)
        for m in HEREDOC.finditer(line):
            if line[max(0, m.start() - 1):m.start()] == "<":  # <<< here-string
                continue
            pending.append((m.group(3), m.group(1) == "-"))
    return "\n".join(out)


def tokenize(cmd):
    cmd = strip_heredocs(cmd).replace("`", " ; ").replace("\n", " ; ")
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return re.sub(r"[;&|()]", " ; ", cmd).split()


def split_simple_commands(cmd):
    """Yield argv lists for each simple command, redirections removed."""
    segments, cur, skip_next = [], [], False
    for tok in tokenize(cmd):
        if skip_next:
            skip_next = False
            continue
        if tok and all(c in ";&|()" for c in tok):
            if cur:
                segments.append(cur)
            cur = []
            continue
        if tok and all(c in "<>&" for c in tok):
            skip_next = True  # redirection operator and its target
            continue
        if tok == "$":
            continue
        cur.append(tok)
    if cur:
        segments.append(cur)
    return segments


def unwrap(argv, findings):
    """Strip env assignments and wrappers; return the real argv and the assignments seen."""
    argv, assigns = list(argv), {}

    def take_assign(tok):
        name, _, value = tok.partition("=")
        assigns[name] = value

    while argv:
        if ENV_ASSIGN.match(argv[0]):
            take_assign(argv.pop(0))
            continue
        head = os.path.basename(argv[0])
        if head == "nohup":
            findings.add(DENY, "nohup", "`nohup` is banned: use tmux/screen, systemd, or `&` with proper process management.")
        if head in WRAPPERS:
            argv.pop(0)
            while argv and (argv[0].startswith("-") or ENV_ASSIGN.match(argv[0])):
                opt = argv.pop(0)
                if ENV_ASSIGN.match(opt):
                    take_assign(opt)
                elif head in ("sudo", "nice") and opt in ("-u", "-g", "-n") and argv:
                    argv.pop(0)
            continue
        if head == "timeout":
            argv.pop(0)
            while argv and argv[0].startswith("-"):
                opt = argv.pop(0)
                if opt in ("-s", "-k", "--signal", "--kill-after") and argv:
                    argv.pop(0)
            if argv:
                argv.pop(0)  # duration
            continue
        break
    return argv, assigns


def short_cluster(tok):
    return re.match(r"^-[A-Za-z]+$", tok) is not None


# --------------------------------------------------------------------------
# Context


class Ctx:
    def __init__(self, cwd):
        self.cwd = cwd or os.getcwd()
        self.added_paths = None  # None: no `git add` seen; [] : add-all
        self.add_all = False


def git_out(repo, *args):
    try:
        r = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, timeout=5, errors="replace",
        )
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve(base, path):
    path = os.path.expanduser(path.replace("${HOME}", "~").replace("$HOME", "~"))
    return os.path.realpath(os.path.join(base, path))


# --------------------------------------------------------------------------
# Checks


def check_git(argv, ctx, findings):
    i, repo, configs = 1, ctx.cwd, []
    while i < len(argv) and argv[i].startswith("-"):
        opt = argv[i]
        if opt in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(argv):
            if opt == "-C":
                repo = resolve(repo, argv[i + 1])
            if opt == "-c":
                configs.append(argv[i + 1])
            i += 2
            continue
        i += 1
    if any(c.lower().startswith("core.hookspath") for c in configs):
        findings.add(DENY, "no-verify", "Overriding `core.hooksPath` bypasses git hooks; fix what the hook flags instead.")
    if i >= len(argv):
        return
    sub, args = argv[i], argv[i + 1:]

    if "--no-verify" in args:
        findings.add(DENY, "no-verify", "`--no-verify` bypasses git hooks; fix what the hook flags instead.")
    if sub == "commit":
        for a in args:
            if short_cluster(a) and "n" in a:
                vals = [a.index(c) for c in "mFCct" if c in a]
                if not vals or a.index("n") < min(vals):
                    findings.add(DENY, "no-verify", "`git commit -n` bypasses git hooks; fix what the hook flags instead.")
        check_commit_secrets(args, repo, ctx, findings)
    elif sub == "add":
        paths = [a for a in args if not a.startswith("-")]
        if any(a in ("-A", "--all", "-u", "--update") for a in args) or "." in paths or ":/" in paths:
            ctx.add_all = True
        ctx.added_paths = (ctx.added_paths or []) + [resolve(repo, p) for p in paths if p not in (".", ":/")]
        ctx.add_repo = repo
    elif sub == "push":
        findings.add(ASK, "push", "Never push without the user's explicit request in this turn. This push requires an exact-operation approval.")
        check_push(args, repo, findings)
    elif sub == "reset" and "--hard" in args:
        findings.add(ASK, "destructive", "`git reset --hard` discards uncommitted work.")
    elif sub == "clean" and any(a == "--force" or (short_cluster(a) and "f" in a) for a in args):
        findings.add(ASK, "destructive", "`git clean -f` deletes untracked files.")
    elif sub in ("checkout", "restore") and any(a in (".", ":/", "./") for a in args):
        findings.add(ASK, "destructive", "`git %s .` discards working-tree changes." % sub)


def check_push(args, repo, findings):
    force, delete, positional, i = False, False, [], 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            i += 2
            continue
        if a in ("--force", "--force-with-lease", "--mirror") or a.startswith("--force-with-lease="):
            force = True
        elif a in ("--delete",):
            delete = True
        elif short_cluster(a):
            force = force or "f" in a
            delete = delete or "d" in a
        elif not a.startswith("-"):
            positional.append(a)
        i += 1
    refspecs = positional[1:]
    targets = []
    for ref in refspecs:
        plus = ref.startswith("+")
        ref = ref.lstrip("+")
        src, _, dst = ref.partition(":")
        dst = (dst or src).replace("refs/heads/", "")
        if dst == "HEAD":
            dst = git_out(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() or dst
        if ":" in ref and not src:
            targets.append((dst, False, True))
        else:
            targets.append((dst, plus, False))
    if not refspecs:
        branch = git_out(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if branch:
            targets.append((branch, False, False))
    for dst, plus, is_delete in targets:
        protected = dst in PROTECTED_BRANCHES
        if (force or plus) and protected:
            findings.add(DENY, "force-push", "Force-pushing protected branch `%s` rewrites shared history." % dst)
        elif (delete or is_delete) and protected:
            findings.add(DENY, "force-push", "Deleting protected branch `%s`." % dst)
        elif force or plus:
            findings.add(ASK, "force-push", "Force-push to `%s` rewrites its history." % dst)


def check_gh(argv, findings):
    args = argv[1:]
    words = [a for a in args if not a.startswith("-")]
    joined = " ".join(args)
    if len(words) >= 2 and words[0] == "pr" and words[1] == "merge":
        findings.add(DENY, "merge", "Never merge a PR: stop at creation and hand the user the link.")
    if words and words[0] == "api" and (
        re.search(r"/pulls/\d+/merge\b", joined) or "mergePullRequest" in joined or "enablePullRequestAutoMerge" in joined
    ):
        findings.add(DENY, "merge", "Never merge a PR (including via `gh api`).")


def direct_tests_active():
    flag = os.environ.get("CODEX_GUARD_DIRECT_TESTS")
    if flag is not None:
        return flag.lower() in ("1", "true", "on", "yes")
    local = os.path.join(HOME, ".codex", "local", "AGENTS.local.md")
    try:
        with open(local, encoding="utf-8", errors="replace") as fh:
            return "cargo test" in fh.read()
    except OSError:
        return False


DIRECT_TEST_MSG = (
    "Don't run `%s` directly in this checkout: use the named-test runner from the"
    " machine-local rules (~/.codex/local/AGENTS.local.md, plus the repo's own AGENTS.local.md"
    " where it has one). If it cannot run the target, report the target as unverified."
)


def in_linked_worktree(cwd):
    """True when the nearest enclosing checkout is a linked `git worktree` (its .git is a file)."""
    path = os.path.realpath(cwd)
    while True:
        dot_git = os.path.join(path, ".git")
        if os.path.exists(dot_git):
            return os.path.isfile(dot_git)
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def target_dir_redirected(target, cwd):
    """True when cargo's target dir is sent under $HOME but outside the current checkout."""
    if not target:
        return False
    full = resolve(cwd, target)
    if not full.startswith(HOME + os.sep):
        return False
    top = os.path.realpath(git_out(cwd, "rev-parse", "--show-toplevel").strip() or cwd)
    return full != top and not full.startswith(top + os.sep)


def direct_tests_exempt(ctx, target_dir):
    """The local rules lift the deny inside linked worktrees and for a redirected target dir."""
    return in_linked_worktree(ctx.cwd) or target_dir_redirected(target_dir, ctx.cwd)


def cargo_target_dir(rest, assigns):
    for i, a in enumerate(rest):
        if a == "--target-dir" and i + 1 < len(rest):
            return rest[i + 1]
        if a.startswith("--target-dir="):
            return a.split("=", 1)[1]
    return assigns.get("CARGO_TARGET_DIR")


def check_cargo(argv, assigns, ctx, findings):
    rest = [a for a in argv[1:] if not a.startswith("+")]
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in ("-Z", "--config", "-C") else 1
    if i < len(rest) and rest[i] in ("test", "t", "bench") and direct_tests_active():
        if not direct_tests_exempt(ctx, cargo_target_dir(rest, assigns)):
            findings.add(DENY, "direct-tests", DIRECT_TEST_MSG % ("cargo " + rest[i]))


def check_just(argv, assigns, ctx, findings):
    args, i = argv[1:], 0
    one_arg = {"-f", "--justfile", "-d", "--working-directory", "--dotenv-path", "--dotenv-filename", "--shell", "--color", "--shell-arg"}
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "--set":
            i += 3
        elif args[i] in one_arg:
            i += 2
        else:
            i += 1
    if i < len(args) and args[i] in ("test", "check") and direct_tests_active():
        if not direct_tests_exempt(ctx, assigns.get("CARGO_TARGET_DIR")):
            findings.add(DENY, "direct-tests", DIRECT_TEST_MSG % ("just " + args[i]))


def check_rm(argv, ctx, findings):
    args = argv[1:]
    recursive, targets, after_dd = False, [], False
    for a in args:
        if after_dd or not a.startswith("-") or a == "-":
            targets.append(a)
        elif a == "--":
            after_dd = True
        elif a == "--recursive" or (short_cluster(a) and ("r" in a or "R" in a)):
            recursive = True
    if not recursive:
        return
    for t in targets:
        bare = t.rstrip("/") or "/"
        if bare in ("/", "/*", "~", "~/*", "$HOME", "${HOME}", "$HOME/*", "${HOME}/*"):
            findings.add(DENY, "destructive", "`rm -r %s` would delete the root or home directory." % t)
            continue
        if t in (".", "./", "..", "../", "*", "./*", "../*"):
            findings.add(ASK, "destructive", "`rm -r %s` deletes the current or parent directory contents." % t)
            continue
        path = resolve(ctx.cwd, t)
        if path == "/" or path == HOME or HOME.startswith(path.rstrip("/") + "/") or path in SYSTEM_DIRS:
            findings.add(DENY, "destructive", "`rm -r %s` would delete a system, home, or ancestor-of-home directory." % t)
        elif ctx.cwd == path or ctx.cwd.startswith(path.rstrip("/") + "/"):
            findings.add(ASK, "destructive", "`rm -r %s` deletes an ancestor of the working directory." % t)


def check_docker(argv, findings):
    words = [a for a in argv[1:] if not a.startswith("-")]
    pair = tuple(words[:2])
    if pair in (("system", "prune"), ("volume", "prune"), ("volume", "rm")):
        findings.add(ASK, "destructive", "`docker %s` deletes volumes or images." % " ".join(pair))
    if words[:2] == ["compose", "down"] and any(a in ("-v", "--volumes") for a in argv):
        findings.add(ASK, "destructive", "`docker compose down -v` deletes volumes.")


# --------------------------------------------------------------------------
# Secret scan on commit

SECRET_DENY = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"), "GitHub fine-grained token"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "Slack token"),
    (re.compile(r"\bsk_live_[A-Za-z0-9]{20,}"), "Stripe live key"),
]
SECRET_ASK = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?secret|secret[_-]?key|secret|passphrase|private[_-]?key|access[_-]?token|auth[_-]?token|password)"
    r"\b[\"']?\s*[:=]\s*[\"']([A-Za-z0-9/+_\-=.]{16,})[\"']"
)
PLACEHOLDER = re.compile(r"(?i)(example|changeme|dummy|placeholder|your[_-]|xxxx|test|fake|sample|<|\$\{|\{\{)")
SECRET_FILES = ["*.pem", "*.p12", "*.pfx", "*.key", "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*", ".env", ".env.*"]
SECRET_FILE_OK = [".env.example", ".env.sample", ".env.template", "*.pub"]


def is_secret_file(path):
    name = os.path.basename(path)
    if any(fnmatch.fnmatch(name, p) for p in SECRET_FILE_OK):
        return False
    return any(fnmatch.fnmatch(name, p) for p in SECRET_FILES)


def scan_lines(lines, origin, findings):
    for line in lines:
        for rx, label in SECRET_DENY:
            if rx.search(line):
                findings.add(DENY, "secrets", "Commit would add a %s (%s). Remove it and use env vars or a secret manager." % (label, origin))
                return
        m = SECRET_ASK.search(line)
        if m and not PLACEHOLDER.search(m.group(2)):
            findings.add(ASK, "secrets", "Commit may add a hard-coded `%s` value (%s)." % (m.group(1), origin))
            return


def scan_diff(diff, findings):
    current = "?"
    added = {}
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("diff --git"):
            current = line.split(" b/", 1)[-1]
            if is_secret_file(current):
                findings.add(DENY, "secrets", "Commit would add `%s`, which looks like a secrets file." % current)
        elif line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    for path, lines in added.items():
        scan_lines(lines, path, findings)


def check_commit_secrets(args, repo, ctx, findings):
    if not enabled(HOOK + ":secrets"):
        return
    top = git_out(repo, "rev-parse", "--show-toplevel").strip()
    if not top:
        return
    diffs = [git_out(top, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff")]
    commit_all = any(a in ("-a", "--all") or (short_cluster(a) and "a" in a) for a in args)
    if commit_all or ctx.add_all:
        diffs.append(git_out(top, "diff", "-U0", "--no-color", "--no-ext-diff", "HEAD"))
    elif ctx.added_paths:
        diffs.append(git_out(top, "diff", "-U0", "--no-color", "--no-ext-diff", "HEAD", "--", *ctx.added_paths))
    for d in diffs:
        scan_diff(d[: 4 * 1024 * 1024], findings)
    if ctx.add_all or ctx.added_paths:
        untracked = git_out(top, "ls-files", "--others", "--exclude-standard").splitlines()
        wanted = set(ctx.added_paths or [])
        for rel in untracked:
            full = os.path.realpath(os.path.join(top, rel))
            if not ctx.add_all and not any(full == w or full.startswith(w.rstrip("/") + "/") for w in wanted):
                continue
            if is_secret_file(rel):
                findings.add(DENY, "secrets", "Commit would add `%s`, which looks like a secrets file." % rel)
                continue
            try:
                if os.path.getsize(full) > 512 * 1024:
                    continue
                with open(full, encoding="utf-8", errors="strict") as fh:
                    scan_lines(fh.read().splitlines(), rel, findings)
            except (OSError, UnicodeDecodeError):
                continue


# --------------------------------------------------------------------------


def analyze(command, ctx, findings, depth=0):
    if depth > 3:
        return
    for raw in split_simple_commands(command):
        argv, assigns = unwrap(raw, findings)
        if not argv:
            continue
        head = os.path.basename(argv[0])
        if head in SHELLS:
            for j, a in enumerate(argv[1:-1], start=1):
                if a == "-c" or (short_cluster(a) and "c" in a):
                    analyze(argv[j + 1], ctx, findings, depth + 1)
                    break
        elif head == "eval":
            analyze(" ".join(argv[1:]), ctx, findings, depth + 1)
        elif head == "cd" and len(argv) > 1:
            ctx.cwd = resolve(ctx.cwd, argv[1])
        elif head == "git":
            check_git(argv, ctx, findings)
        elif head == "gh":
            check_gh(argv, findings)
        elif head == "cargo":
            check_cargo(argv, assigns, ctx, findings)
        elif head == "just":
            check_just(argv, assigns, ctx, findings)
        elif head == "rm":
            check_rm(argv, ctx, findings)
        elif head == "docker":
            check_docker(argv, findings)


def main(payload):
    if payload.get("tool_name") not in (None, "Bash"):
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command.strip():
        return
    findings = Findings()
    inp = payload.get("tool_input") or {}
    analyze(command, Ctx(inp.get("workdir") or inp.get("cwd") or payload.get("cwd")), findings)
    findings.emit()


if __name__ == "__main__":
    sys.exit(run(HOOK, main))
