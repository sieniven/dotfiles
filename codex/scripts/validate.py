#!/usr/bin/env python3
"""Validate Codex configuration, hook wiring, skill resources and Claude isolation."""
import hashlib
import json
from pathlib import Path
import re
import tomllib

import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate():
    errors = []
    config = tomllib.loads((ROOT / "config.toml").read_text())
    for name, role in config["agents"].items():
        if not isinstance(role, dict):
            continue
        path = ROOT / role["config_file"]
        if not path.is_file():
            errors.append(f"Missing role {name}: {path}")
        else:
            d = tomllib.loads(path.read_text())
            if not d.get("developer_instructions") or not d.get("model"):
                errors.append(f"Incomplete agent {name}")
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        match = re.match(r"\A---\n(.*?)\n---\n", path.read_text(), re.S)
        if not match:
            errors.append(f"Missing frontmatter: {path}")
            continue
        meta = yaml.safe_load(match[1])
        if meta.get("name") != path.parent.name or not meta.get("description"):
            errors.append(f"Invalid metadata: {path}")
        # Check concrete local Markdown references throughout each bundle.
        for doc in path.parent.rglob("*.md"):
            for link in re.findall(r"\]\(([^\s)]+)\)", doc.read_text(errors="replace")):
                link = link.split("#", 1)[0]
                if not link or ":" in link or link.startswith(("/", "~", "$", "<")) or any(c in link for c in ("*", "{", ">")):
                    continue
                if not (doc.parent / link).exists():
                    errors.append(f"Broken resource: {doc.relative_to(ROOT)} -> {link}")
    hooks = json.loads((ROOT / "hooks.json").read_text())
    for groups in hooks["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                match = re.search(r"/hooks/([^\"]+)\.py", hook["command"])
                if not match or not (ROOT / "hooks" / (match[1] + ".py")).exists():
                    errors.append(f"Missing hook script: {hook['command']}")
    # PR #28: exact added requirements must survive the port.
    backtesting = (ROOT / "skills/quant-trading-backtesting/SKILL.md").read_text()
    for requirement in ("running the same seed twice", "comparing the artifacts byte for byte", 'write "no baseline run"', "The first table of any backtest report", "horizons, the fill ratio", "spread capture, adverse selection and fees", "the replay has no market impact"):
        if requirement not in backtesting:
            errors.append("Missing PR #28 requirement: " + requirement)
    baseline = ROOT / "local/claude-source-snapshot.json"
    if baseline.exists():
        changed = []
        for name, before in json.loads(baseline.read_text()).items():
            path = Path(name)
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != before["sha256"]:
                changed.append(name)
            elif before.get("link") is not None and (not path.is_symlink() or str(path.readlink()) != before["link"]):
                changed.append(name)
        if changed:
            errors.append(f"Claude baseline changed ({len(changed)} files): " + ", ".join(changed[:8]))
        else:
            print(f"Claude source unchanged: {len(json.loads(baseline.read_text()))} files verified.")
    if errors:
        for error in errors:
            print("ERROR:", error)
        raise SystemExit(1)
    print(f"PASS: config, {len(list((ROOT / 'agents').glob('*.toml')))} agents, {len(list((ROOT / 'skills').glob('*/SKILL.md')))} skills, hooks, resource links, and PR #28.")


if __name__ == "__main__":
    validate()
