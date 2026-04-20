#!/usr/bin/env python3
"""Keep integration and add-on versions aligned."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "custom_components" / "youtube_music_connector" / "manifest.json"
ADDON_CONFIG_PATH = REPO_ROOT / "youtube_music_connector_companion" / "config.yaml"
CONST_PATH = REPO_ROOT / "custom_components" / "youtube_music_connector" / "const.py"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
ADDON_VERSION_RE = re.compile(r'^(version:\s*")(\d+\.\d+\.\d+)(")$', re.MULTILINE)
PANEL_VERSION_RE = re.compile(r'(FRONTEND_CACHE_VERSION\s*=\s*")([^"]+)(")')


def parse_version(raw: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(raw.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {raw!r}")
    return tuple(int(part) for part in match.groups())


def format_version(parts: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in parts)


def bump_version(version: str, part: str) -> str:
    major, minor, patch = parse_version(version)
    if part == "major":
        return format_version((major + 1, 0, 0))
    if part == "minor":
        return format_version((major, minor + 1, 0))
    if part == "patch":
        return format_version((major, minor, patch + 1))
    raise ValueError(f"Unknown bump part: {part}")


def read_manifest_version() -> str:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return manifest["version"]


def write_manifest_version(version: str) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["version"] = version
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def read_addon_version() -> str:
    for line in ADDON_CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.split('"')[1]
    raise ValueError("Add-on version not found")


def write_addon_version(version: str) -> None:
    content = ADDON_CONFIG_PATH.read_text(encoding="utf-8")
    updated = ADDON_VERSION_RE.sub(rf'\g<1>{version}\g<3>', content, count=1)
    if updated == content:
        raise ValueError("Failed to update add-on version")
    ADDON_CONFIG_PATH.write_text(updated, encoding="utf-8")


def write_panel_cache_version(version: str) -> None:
    content = CONST_PATH.read_text(encoding="utf-8")
    updated = PANEL_VERSION_RE.sub(rf"\g<1>{version}\g<3>", content, count=1)
    if updated == content:
        raise ValueError("Failed to update panel cache version")
    CONST_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=["patch", "minor", "major"], default="patch")
    parser.add_argument("--set", dest="set_version")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    manifest_version = read_manifest_version()
    addon_version = read_addon_version()
    const_content = CONST_PATH.read_text(encoding="utf-8")
    panel_match = PANEL_VERSION_RE.search(const_content)
    if panel_match is None:
        raise ValueError("Could not find panel cache version in const.py")
    panel_version = panel_match.group(2)

    if args.check:
        if manifest_version != addon_version or manifest_version != panel_version:
            raise SystemExit(
                f"Version mismatch: manifest={manifest_version}, add-on={addon_version}, panel={panel_version}"
            )
        parse_version(manifest_version)
        print(f"Versions aligned at {manifest_version}")
        return 0

    current_version = manifest_version
    parse_version(current_version)
    parse_version(addon_version)
    parse_version(panel_version)
    if addon_version != current_version or panel_version != current_version:
        raise SystemExit(
            f"Refusing to bump misaligned versions: manifest={current_version}, add-on={addon_version}, panel={panel_version}"
        )

    next_version = args.set_version or bump_version(current_version, args.part)
    parse_version(next_version)

    write_manifest_version(next_version)
    write_addon_version(next_version)
    write_panel_cache_version(next_version)
    print(f"Bumped versions: {current_version} -> {next_version}")

    sync_script = Path(__file__).resolve().parent / "sync_addon_payload.py"
    subprocess.check_call([sys.executable, str(sync_script)])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
