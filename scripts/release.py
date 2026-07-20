#!/usr/bin/env python3
"""Validate and version the Cinematic Video Analysis marketplace."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "cinematic-video-analysis"
MARKETPLACE_NAME = "cinematic-tools"
PLUGIN_ROOT = ROOT / "plugins" / PLUGIN_NAME
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = ROOT / ".agents" / "plugins" / "marketplace.json"
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ReleaseError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ReleaseError(f"Missing required file: {path.relative_to(ROOT)}") from error
    except json.JSONDecodeError as error:
        raise ReleaseError(f"Invalid JSON in {path.relative_to(ROOT)}: {error}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def relative_asset(manifest: dict[str, Any], key: str) -> None:
    value = manifest.get("interface", {}).get(key)
    if value:
        require(isinstance(value, str) and value.startswith("./"), f"{key} must be a ./ relative path")
        require((PLUGIN_ROOT / value[2:]).is_file(), f"Referenced {key} does not exist: {value}")


def validate() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    marketplace = load_json(MARKETPLACE_PATH)
    todo_marker = "[" + "TODO:"

    require(manifest.get("name") == PLUGIN_NAME, "Plugin folder and manifest name must match")
    require(bool(SEMVER.fullmatch(str(manifest.get("version", "")))), "Plugin version is not valid semver")
    require(bool(manifest.get("description")), "Plugin description is required")
    require(bool(manifest.get("author", {}).get("name")), "Plugin author.name is required")
    interface = manifest.get("interface", {})
    for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
        require(bool(interface.get(field)), f"Plugin interface.{field} is required")
    prompts = interface.get("defaultPrompt", [])
    require(isinstance(prompts, list) and 1 <= len(prompts) <= 3, "defaultPrompt must contain 1 to 3 prompts")
    require(all(isinstance(item, str) and len(item) <= 128 for item in prompts), "Each default prompt must be <= 128 characters")
    for key in ("composerIcon", "logo", "logoDark"):
        relative_asset(manifest, key)

    skills_root = PLUGIN_ROOT / "skills"
    skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir())
    require(len(skill_dirs) == 3, "Exactly three skill directories are expected")
    skill_names: list[str] = []
    for skill_dir in skill_dirs:
        skill_file = skill_dir / "SKILL.md"
        require(skill_file.is_file(), f"Missing {skill_dir.name}/SKILL.md")
        text = skill_file.read_text(encoding="utf-8")
        match = re.search(r"(?m)^name:\s*([a-z0-9-]+)\s*$", text)
        require(bool(match), f"Missing valid name frontmatter in {skill_file.relative_to(ROOT)}")
        require(match.group(1) == skill_dir.name, f"Skill folder/name mismatch: {skill_dir.name}")
        require(todo_marker not in text, f"Unresolved TODO in {skill_file.relative_to(ROOT)}")
        require((skill_dir / "agents" / "openai.yaml").is_file(), f"Missing UI metadata for {skill_dir.name}")
        skill_names.append(skill_dir.name)

    require(marketplace.get("name") == MARKETPLACE_NAME, "Marketplace name mismatch")
    entries = marketplace.get("plugins", [])
    entry = next((item for item in entries if item.get("name") == PLUGIN_NAME), None)
    require(entry is not None, "Plugin is missing from marketplace.json")
    require(entry.get("source") == {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"}, "Marketplace source path is invalid")
    require(entry.get("policy", {}).get("installation") == "AVAILABLE", "Plugin must be AVAILABLE")
    require(entry.get("policy", {}).get("authentication") in {"ON_INSTALL", "ON_USE"}, "Invalid authentication policy")
    require(bool(entry.get("category")), "Marketplace category is required")

    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.suffix in {".md", ".json", ".yaml", ".py"}:
            require(todo_marker not in path.read_text(encoding="utf-8"), f"Unresolved TODO in {path.relative_to(ROOT)}")

    return {
        "marketplace": MARKETPLACE_NAME,
        "plugin": PLUGIN_NAME,
        "version": manifest["version"],
        "skills": skill_names,
    }


def write_version(version: str | None) -> str:
    manifest = load_json(MANIFEST_PATH)
    current = str(manifest.get("version", "0.1.0"))
    base = current.split("+", 1)[0]
    target = version or f"{base}+codex.local-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    require(bool(SEMVER.fullmatch(target)), f"Invalid target version: {target}")
    manifest["version"] = target
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def git(command: list[str]) -> None:
    result = subprocess.run(["git", "-C", str(ROOT), *command], text=True, check=False)
    if result.returncode:
        raise ReleaseError(f"Git command failed: git {' '.join(command)}")


def release(args: argparse.Namespace) -> dict[str, Any]:
    version = write_version(args.version)
    result = validate()
    if args.commit or args.push:
        git(["add", "--", ".agents", ".github", "plugins", "scripts", "README.md"])
        git(["commit", "-m", f"Release {PLUGIN_NAME} {version}"])
    if args.push:
        git(["push", "origin", "HEAD"])
    result.update({"committed": bool(args.commit or args.push), "pushed": bool(args.push)})
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Validate the marketplace without changing files.")
    check.set_defaults(handler=lambda _: validate())
    bump = commands.add_parser("bump", help="Add a cachebuster or set an explicit version.")
    bump.add_argument("--version", help="Explicit semver; otherwise append a UTC Codex cachebuster.")
    bump.add_argument("--commit", action="store_true", help="Commit the validated release locally.")
    bump.add_argument("--push", action="store_true", help="Commit and push the validated release.")
    bump.set_defaults(handler=release)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = args.handler(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
