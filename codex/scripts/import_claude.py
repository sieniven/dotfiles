#!/usr/bin/env python3
"""Import a read-only Claude snapshot into an EMPTY review directory.

Never run against the maintained codex tree. Review and merge later imports;
Codex-specific hooks, policies and adaptations are maintained independently.
Requires PyYAML (only the importer and validator, not runtime hooks).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

import yaml


HOME = Path.home()
SOURCE = HOME / "dev/dotfiles/claude"


def adapt(text):
    replacements = [
        ("$HOME/.claude/skills", "$HOME/.agents/skills"),
        ("~/.claude/skills", "~/.agents/skills"),
        ("~/.claude/CLAUDE.local.md", "~/.codex/local/AGENTS.local.md"),
        (".claude/CLAUDE.local.md", ".codex/local/AGENTS.local.md"),
        ("~/.claude/local/", "~/.codex/local/"),
        ("$HOME/.claude/hooks", "$HOME/.codex/hooks"),
        ("~/.claude/hooks", "~/.codex/hooks"),
        ("~/.claude/rules", "~/.codex/rules"),
        ("~/.claude/agents", "~/.codex/agents"),
        (".claude/agents/", ".codex/agents/"),
        ("CLAUDE.local.md", "AGENTS.local.md"),
        ("CLAUDE.md", "AGENTS.md"),
        ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"),
        ("Claude Code", "Codex"),
        ("before Claude", "before Codex"),
        ("Claude is", "Codex is"),
        ("/handoff", "$handoff"),
        ("/pickup", "$pickup"),
        ("/learn", "$learn"),
        ("/deep", "$deep"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def split_frontmatter(text):
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match[1]) or {}
    except yaml.YAMLError:
        # Some installed Claude plugin descriptions are unquoted YAML with
        # literal example blocks. Extract their single-line metadata safely.
        meta = {}
        for line in match[1].splitlines():
            key, sep, value = line.partition(":")
            if sep and key in ("name", "description", "model", "effort"):
                meta[key] = value.strip().strip('"\'')
    return meta, match[2]


def write_skill(out, name, meta, body):
    dest = out / "skills" / name / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    supported = {k: v for k, v in meta.items() if k in ("name", "description", "license", "metadata", "compatibility")}
    supported["name"] = name
    supported.setdefault("description", f"Run the {name} workflow when requested.")
    dest.write_text("---\n" + yaml.safe_dump(supported, sort_keys=False, width=1000) + "---\n" + adapt(body))


def copy_tree(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".git"))
    for p in dst.rglob("*.md"):
        p.write_text(adapt(p.read_text()))


def import_snapshot(out):
    if out.exists() and any(out.iterdir()):
        raise SystemExit("Output must be empty; this importer never overwrites maintained configuration.")
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"skills": [], "agents": [], "commands": [], "plugins": [], "omissions": []}
    sources = []
    # Active top-level skills win over obsolete synced copies.
    for src in sorted((HOME / ".claude/skills").iterdir()):
        if (src / "SKILL.md").is_file():
            copy_tree(src, out / "skills" / src.name)
            meta, body = split_frontmatter((out / "skills" / src.name / "SKILL.md").read_text())
            write_skill(out, src.name, meta, body)
            manifest["skills"].append({"name": src.name, "source": str(src)})
            sources.append(src)
    # Portable file-format skills; select the newest snapshot for each name.
    for name in ("docx", "pdf", "pptx", "xlsx"):
        candidates = list((HOME / ".claude/skills/synced").rglob(name + "/SKILL.md"))
        if candidates:
            src = max(candidates, key=lambda p: (p.stat().st_mtime_ns, str(p))).parent
            copy_tree(src, out / "skills" / name)
            meta, body = split_frontmatter((out / "skills" / name / "SKILL.md").read_text())
            write_skill(out, name, meta, body)
            manifest["skills"].append({"name": name, "source": str(src)})
            sources.append(src)
    for src in sorted((SOURCE / "rules").glob("*.md")):
        dst = out / "rules" / src.name
        dst.parent.mkdir(exist_ok=True)
        dst.write_text(adapt(src.read_text()))
    for src in sorted((SOURCE / "commands").glob("*.md")):
        meta, body = split_frontmatter(src.read_text())
        write_skill(out, src.stem, meta, body.replace("$ARGUMENTS", "the user's supplied task or focus"))
        manifest["commands"].append(src.stem)
    settings = json.loads((HOME / ".claude/settings.json").read_text())
    installed = json.loads((HOME / ".claude/plugins/installed_plugins.json").read_text())["plugins"]
    agent_sources = [(p, p.stem) for p in sorted((SOURCE / "agents").glob("*.md"))]
    for plugin, entries in installed.items():
        if not settings.get("enabledPlugins", {}).get(plugin):
            continue
        root = Path(entries[0]["installPath"])
        manifest["plugins"].append(plugin)
        prefix = plugin.split("@")[0]
        if prefix in ("pr-review-toolkit", "code-simplifier"):
            for p in sorted((root / "agents").glob("*.md")):
                # Preserve both simplifier definitions with unambiguous names.
                name = p.stem if prefix == "pr-review-toolkit" else "code-simplifier-focused"
                agent_sources.append((p, name))
        if prefix == "code-review":
            p = root / "commands/code-review.md"
            meta, body = split_frontmatter(p.read_text())
            write_skill(out, "code-review", meta, body)
        if prefix == "pr-review-toolkit":
            p = root / "commands/review-pr.md"
            meta, body = split_frontmatter(p.read_text())
            write_skill(out, "review-pr", meta, body)
        if prefix == "claude-md-management":
            src = root / "skills/claude-md-improver"
            copy_tree(src, out / "skills/agents-md-improver")
            meta, body = split_frontmatter((src / "SKILL.md").read_text())
            write_skill(out, "agents-md-improver", meta, body)
    agent_table = []
    for src, name in agent_sources:
        meta, body = split_frontmatter(src.read_text())
        dest = out / "agents" / (name + ".toml")
        dest.parent.mkdir(exist_ok=True)
        preload = meta.get("skills", [])
        instructions = adapt(body)
        if preload:
            instructions = "Before starting, read these skills explicitly:\n" + "\n".join(f"- ~/.agents/skills/{s}/SKILL.md" for s in preload) + "\n\n" + instructions
            instructions = instructions.replace("preloaded into your context", "listed above").replace("is preloaded", "must be read explicitly").replace("is already in your context", "is listed above")
        instructions = "Read ~/.codex/local/AGENTS.local.md if it exists; its machine-local testing rules apply. Read the repository's AGENTS.md and, if absent, its CLAUDE.md read-only for project guidance.\n\n" + instructions
        model = "gpt-6.1-sol" if meta.get("model") in ("sonnet", "haiku") else "gpt-6-astra"
        effort = meta.get("effort", "high")
        readonly = name in ("Explore", "code-reader", "docs-lookup", "verifier", "quant-trading-code-reviewer", "code-reviewer", "comment-analyzer", "pr-test-analyzer", "silent-failure-hunter", "type-design-analyzer")
        text = f'model = {json.dumps(model)}\nmodel_reasoning_effort = {json.dumps(effort)}\n'
        if readonly:
            text += 'sandbox_mode = "read-only"\n'
        text += "developer_instructions = " + json.dumps(instructions, ensure_ascii=False) + "\n"
        dest.write_text(text)
        agent_table.append(f'[agents.{json.dumps(name)}]\ndescription = {json.dumps(meta.get("description", name), ensure_ascii=False)}\nconfig_file = "agents/{name}.toml"\n')
        manifest["agents"].append({"name": name, "source": str(src), "model": model, "effort": effort, "read_only": readonly})
    (out / "agent-tables.toml").write_text("\n".join(agent_table))
    (out / "AGENTS.md").write_text(adapt((SOURCE / "CLAUDE.md").read_text()))
    # Independent copies: no destination symlink points back to Claude.
    for name in ("_common.py", "bash_guard.py", "edit_guard.py", "format_tracker.py", "stop_gate.py", "suggest_compact.py"):
        dst = out / "hooks" / name
        dst.parent.mkdir(exist_ok=True)
        text = (SOURCE / "hooks" / name).read_text().replace("CLAUDE_", "CODEX_").replace("claude-hooks", "codex-hooks")
        text = adapt(text).replace('".claude"', '".codex"').replace('"settings.json"', '"config.toml"').replace('"AGENTS.local.md"', '"local", "AGENTS.local.md"') if name == "bash_guard.py" else adapt(text).replace('".claude"', '".codex"').replace('"settings.json"', '"config.toml"')
        dst.write_text(text)
    manifest["omissions"] = [
        "Claude synced duplicate rust/trading/git-commit/pr-create: current rules and active custom skills win",
        "Claude skill-creator: Codex's bundled skill-creator remains authoritative",
        "Claude browser/computer-use/docs/google-workspace/import-memory/morning/deep-research: Claude-hosted tools; replace with Codex tools and explicit adapted skills",
        "LSP plugins: no direct Claude LSP plugin registration in Codex; use installed language tools",
        "Telegram channel and Greptile plugin: require separate transport/auth; not silently activated",
        "Ralph-loop: replace Claude plugin state with a bounded Codex workflow",
        "Commit commands: git-commit/pr-create cover creation; clean_gone deletes worktrees and is not auto-installed",
        "Claude advisor and Workflow tools: no direct native equivalent; use explicitly authorized Codex review/delegation",
        "Runtime histories, credentials, session memories and .trash are not configuration imports",
    ]
    hashes = {}
    for root in sources:
        for p in root.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                hashes[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest["source_hashes"] = hashes
    (out / "migration-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Imported {len(manifest['skills'])} skills, {len(manifest['commands'])} commands, {len(manifest['agents'])} agents into {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    import_snapshot(parser.parse_args().output.resolve())
