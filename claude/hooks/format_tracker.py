#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit): remember whether a file was formatted
before Claude first touched it this session.

stop_gate.py formats edited files once at Stop instead of after every edit,
and only files that were already formatted (or new), so it never turns a
small edit into a whole-file formatting diff in a repo that isn't
rustfmt/ruff-clean. Rust uses `rustfmt --check`; Python uses
`ruff format --check` only when the project configures ruff.
"""

import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import enabled, run, state_dir  # noqa: E402

HOOK = "stop-gate"


def state_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id or "nosession")[:64]
    return os.path.join(state_dir("format"), sid + ".json")


def load(session_id):
    try:
        with open(state_path(session_id)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(session_id, data):
    tmp = state_path(session_id) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, state_path(session_id))


def find_up(start, names):
    d = os.path.dirname(start)
    while True:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def rust_edition(path):
    cargo = find_up(path, ["Cargo.toml"])
    if cargo:
        try:
            with open(cargo, encoding="utf-8", errors="replace") as fh:
                m = re.search(r'^\s*edition\s*=\s*"(\d{4})"', fh.read(), re.M)
            if m:
                return m.group(1)
        except OSError:
            pass
    return "2021"


def ruff_configured(path):
    cfg = find_up(path, ["ruff.toml", ".ruff.toml", "pyproject.toml"])
    if not cfg:
        return False
    if not cfg.endswith("pyproject.toml"):
        return True
    try:
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            return "[tool.ruff" in fh.read()
    except OSError:
        return False


def formatter(path):
    """Return (check_argv, format_argv) for this file, or None."""
    if path.endswith(".rs") and shutil.which("rustfmt"):
        ed = rust_edition(path)
        return (["rustfmt", "--check", "--edition", ed, path], ["rustfmt", "--edition", ed, path])
    if path.endswith(".py") and shutil.which("ruff") and ruff_configured(path):
        return (["ruff", "format", "--check", "--quiet", path], ["ruff", "format", "--quiet", path])
    return None


def is_clean(check_argv, cwd):
    try:
        r = subprocess.run(check_argv, cwd=cwd, capture_output=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main(payload):
    if not enabled(HOOK + ":format"):
        return
    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return
    cwd = payload.get("cwd") or os.getcwd()
    full = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
    fmt = formatter(full)
    if fmt is None:
        return
    sid = payload.get("session_id")
    data = load(sid)
    if full in data:
        return
    data[full] = "new" if not os.path.exists(full) else ("clean" if is_clean(fmt[0], os.path.dirname(full)) else "dirty")
    save(sid, data)


if __name__ == "__main__":
    sys.exit(run(HOOK, main))
