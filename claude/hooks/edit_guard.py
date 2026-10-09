#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit) guard: config protection.

Agents often "fix" a failing check by weakening the check. This hook turns
edits to lint/format configuration, crate-wide lint allows, credentials and
production/risk configuration into a permission prompt, so the user decides.
Creating a new file is always allowed; only changes to existing files ask.

Checks (ids for CLAUDE_HOOKS_DISABLE, prefixed `edit-guard:`):
  lint-config  linter/formatter config files, lint tables in pyproject/Cargo.toml,
               new crate-level `#![allow(...)]`
  secrets      .env files, keys and certificates
  prod-config  production / live / risk-limit config files, plus any globs in
               CLAUDE_PROTECTED_PATHS (comma-separated fnmatch patterns)
  harness      ~/.claude/settings.json and the hooks themselves, resolved through
               symlinks so a hooks/ directory linked into a dotfiles checkout
               is guarded under either path
"""

import fnmatch
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import enabled, pre_tool_decision, run  # noqa: E402

HOOK = "edit-guard"
CLAUDE_DIR = os.path.realpath(os.path.expanduser("~/.claude"))
# Resolved like the edited path is, so ~/.claude/hooks -> <dotfiles>/claude/hooks still matches.
HARNESS_SETTINGS = os.path.realpath(os.path.join(CLAUDE_DIR, "settings.json"))
HARNESS_HOOKS = os.path.realpath(os.path.join(CLAUDE_DIR, "hooks"))

LINT_CONFIGS = [
    "rustfmt.toml", ".rustfmt.toml", "clippy.toml", ".clippy.toml", "deny.toml",
    "ruff.toml", ".ruff.toml", ".flake8", "mypy.ini", ".mypy.ini", ".pylintrc", "pylintrc",
    ".pre-commit-config.yaml", ".editorconfig", ".golangci.yml", ".golangci.yaml",
    ".eslintrc", ".eslintrc.*", "eslint.config.*", ".prettierrc", ".prettierrc.*",
    "prettier.config.*", "biome.json", "biome.jsonc", ".shellcheckrc", ".markdownlint.json",
]
LINT_TABLE = re.compile(
    r"\[(tool\.(ruff|mypy|black|pylint|isort|flake8)[^\]]*|(workspace\.)?lints[^\]]*)\]"
    r"|^\s*(extend-)?(select|ignore|per-file-ignores|disable_error_code)\s*=",
    re.M,
)
CRATE_ALLOW = re.compile(r"#!\[allow\(")
SECRET_FILES = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_ed25519", "credentials*.json", "secrets.*"]
SECRET_OK = [".env.example", ".env.sample", ".env.template"]
CONFIG_EXT = (".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".env")
PROD_NAME = re.compile(r"(?i)(^|[._\-/])(prod|production|live|mainnet|risk|limits?)([._\-/]|$)")


def changed_text(tool_input):
    """Old and new text of the edit, for content-sensitive checks."""
    old, new = [], []
    if "old_string" in tool_input or "new_string" in tool_input:
        old.append(tool_input.get("old_string") or "")
        new.append(tool_input.get("new_string") or "")
    for e in tool_input.get("edits") or []:
        old.append(e.get("old_string") or "")
        new.append(e.get("new_string") or "")
    if "content" in tool_input:
        new.append(tool_input.get("content") or "")
    return "\n".join(old), "\n".join(new)


def file_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(2 * 1024 * 1024)
    except OSError:
        return ""


def main(payload):
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return
    cwd = payload.get("cwd") or os.getcwd()
    full = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
    if not os.path.exists(full):
        return  # first-time creation is fine
    name = os.path.basename(full)
    old, new = changed_text(tool_input)
    if payload.get("tool_name") == "Write":
        old = file_text(full)
    reasons = []

    def flag(check, msg):
        if enabled("%s:%s" % (HOOK, check)):
            reasons.append(msg)

    if any(fnmatch.fnmatch(name, p) for p in LINT_CONFIGS):
        flag("lint-config", "`%s` is linter/formatter config. Fix the code rather than loosening the check, unless the user asked for a config change." % name)
    elif name in ("pyproject.toml", "Cargo.toml", "setup.cfg", "tox.ini") and (
        LINT_TABLE.search(old) or LINT_TABLE.search(new)
    ):
        flag("lint-config", "This edit touches lint settings in `%s`. Fix the code rather than loosening the check, unless the user asked for it." % name)
    if name.endswith(".rs") and len(CRATE_ALLOW.findall(new)) > len(CRATE_ALLOW.findall(old)):
        flag("lint-config", "Adds a crate-level `#![allow(...)]` in `%s`. Prefer fixing the lint or a narrowly scoped `#[allow]` with a reason." % name)

    if not any(fnmatch.fnmatch(name, p) for p in SECRET_OK) and any(fnmatch.fnmatch(name, p) for p in SECRET_FILES):
        flag("secrets", "`%s` holds environment or credential material." % name)

    extra = [g.strip() for g in os.environ.get("CLAUDE_PROTECTED_PATHS", "").split(",") if g.strip()]
    if (full.endswith(CONFIG_EXT) and PROD_NAME.search(os.path.relpath(full, cwd) if full.startswith(cwd) else name)) or any(
        fnmatch.fnmatch(full, os.path.expanduser(g)) for g in extra
    ):
        flag("prod-config", "`%s` looks like production, live, or risk-limit config. Never change risk parameters or production config without the user's explicit go-ahead." % name)

    if full == HARNESS_SETTINGS or full.startswith(HARNESS_HOOKS + os.sep):
        flag("harness", "This edits the Claude Code harness (settings or guard hooks).")

    if reasons:
        pre_tool_decision("ask", "[edit-guard] " + " ".join(reasons))


if __name__ == "__main__":
    sys.exit(run(HOOK, main))
