#!/usr/bin/env python3
"""Install dotfiles/codex with symlinks, archiving replaced customization.

Dry-run by default. --apply performs the reviewed changes. Auth, conversations,
databases, bundled system skills and installed connector plugins are untouched.
--home is useful for testing installation in an isolated fake home directory.
"""
import argparse
import datetime
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SKILLS = {"trading", "crypto-struct", "rust"}


def install(home, apply=False):
    codex = home / ".codex"
    skills = home / ".agents/skills"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = codex / "backups" / ("dotfiles-" + stamp)
    links = {codex / name: ROOT / name for name in ("config.toml", "AGENTS.md", "hooks.json", "hooks", "rules", "agents", "scripts", "local")}
    links.update({skills / p.name: p for p in sorted((ROOT / "skills").iterdir()) if (p / "SKILL.md").exists()})
    actions = []
    archived = []

    def archive(path):
        relative = path.relative_to(home)
        dest = backup / relative
        actions.append(f"ARCHIVE {path} -> {dest}")
        if apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
            archived.append({"original": str(path), "backup": str(dest)})

    # Retire the stale manually ported skills. Do not replace the skills
    # directory itself: Codex owns its .system subtree.
    for name in sorted(LEGACY_SKILLS):
        path = codex / "skills" / name
        if path.exists() or path.is_symlink():
            archive(path)
    # Any older same-name user skill can cause duplicate discovery.
    for dest in links:
        if dest.parent == skills:
            legacy = codex / "skills" / dest.name
            if legacy.name not in LEGACY_SKILLS and (legacy.exists() or legacy.is_symlink()):
                archive(legacy)
    # Remove links belonging to a previous installation when the maintained
    # skill no longer exists; never infer ownership from unrelated directory names.
    previous = ROOT / "local/installation.json"
    if previous.exists():
        old = json.loads(previous.read_text())
        for item in old.get("links", []):
            dest = Path(item["path"])
            if str(dest).startswith(str(home) + "/") and dest not in links and dest.is_symlink() and dest.resolve() == Path(item["target"]):
                archive(dest)
    for dest, target in links.items():
        if dest.is_symlink() and dest.resolve() == target.resolve():
            continue
        if dest.exists() or dest.is_symlink():
            archive(dest)
        actions.append(f"LINK {dest} -> {target}")
        if apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(target, target_is_directory=target.is_dir())
    for action in actions:
        print(action)
    if apply:
        record = {"installed_at": stamp, "home": str(home), "backup": str(backup), "archived": archived, "links": [{"path": str(p), "target": str(t)} for p, t in links.items()]}
        (ROOT / "local").mkdir(exist_ok=True)
        # Test installs do not replace the real machine's installation record.
        record_path = ROOT / "local" / ("installation.json" if home == Path.home() else "test-installation.json")
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        if archived:
            (backup / "restore-manifest.json").write_text(json.dumps(archived, indent=2) + "\n")
        print(f"Installed {len(links)} symlinks. Backup: {backup if archived else 'no replacements'}")
        print("Restart Codex, then review and trust the new definitions in /hooks. Hook trust is never bypassed by this installer.")
    else:
        print(f"Dry run: {len(actions)} actions. Run with --apply to install.")
    return links


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    install(args.home.expanduser().resolve(), args.apply)
