#!/usr/bin/env python3
"""Load independent local context and language rules on native Codex events."""
import json
import os
from pathlib import Path
import re
import sys

from _common import additional_context, run, state_dir
from patches import edits

ROOT = Path(__file__).resolve().parents[1]


def body(path):
    text = path.read_text()
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)


def main(payload):
    event = payload.get("hook_event_name")
    pieces = []
    if event in ("SessionStart", "SubagentStart"):
        local = ROOT / "local/AGENTS.local.md"
        if local.exists():
            pieces.append("Machine-local Codex context:\n" + body(local))
        cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
        # Read legacy repo guidance without modifying Claude files. Prefer
        # native AGENTS.md where present. Stop at the checkout root.
        for directory in [cwd, *cwd.parents]:
            if not str(directory).startswith(str(Path.home() / "dev")):
                break
            for legacy, native in (("CLAUDE.md", "AGENTS.md"), ("CLAUDE.local.md", "AGENTS.local.md")):
                path = directory / legacy
                if path.is_file() and not (directory / native).is_file():
                    pieces.append(f"Read-only compatibility context from {path}:\n" + body(path)[:14000])
            if (directory / ".git").exists():
                if directory.name == "engine-middleware":
                    repo_local = ROOT / "local/engine-middleware.md"
                    if repo_local.exists():
                        pieces.append(body(repo_local))
                break
        # Clear only clears previous work; machine and project rules still apply.
        sid = re.sub(r"[^A-Za-z0-9_-]", "", (payload.get("session_id") or "nosession") + "-" + (payload.get("agent_id") or "root"))[:140]
        cache = Path(state_dir("rule-loads")) / (sid + ".json")
        cache.write_text("[]")
    elif event == "PreToolUse":
        inp = payload.get("tool_input") or {}
        text = json.dumps(inp)
        languages = set()
        if re.search(r"\.rs\b|\bcargo\b|\brustfmt\b", text):
            languages.add("rust")
        if re.search(r"\.pyi?\b|\bpython[23]?\b|\bpytest\b|\bruff\b", text):
            languages.add("python")
        if re.search(r"\.go\b|go\.mod\b|\bgo (test|build|vet)\b|\bgofmt\b", text):
            languages.add("go")
        for edit in edits(payload):
            extension = Path(edit["tool_input"]["file_path"]).suffix
            language = {".rs": "rust", ".py": "python", ".pyi": "python", ".go": "go"}.get(extension)
            if language:
                languages.add(language)
        # Include agent identity so a parent load doesn't suppress a child load.
        sid = re.sub(r"[^A-Za-z0-9_-]", "", (payload.get("session_id") or "nosession") + "-" + (payload.get("agent_id") or "root"))[:140]
        cache = Path(state_dir("rule-loads")) / (sid + ".json")
        try:
            loaded = set(json.loads(cache.read_text()))
        except (OSError, ValueError):
            loaded = set()
        for language in sorted(languages - loaded):
            pieces.append(body(ROOT / "rules" / (language + ".md")))
        cache.write_text(json.dumps(sorted(loaded | languages)))
    if pieces:
        additional_context(event, "\n\n".join(pieces))


if __name__ == "__main__":
    sys.exit(run("context-loader", main))
