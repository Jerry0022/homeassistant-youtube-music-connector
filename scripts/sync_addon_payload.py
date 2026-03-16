#!/usr/bin/env python3
"""Synchronize the add-on payload with the repository sources."""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_INTEGRATION = REPO_ROOT / "custom_components" / "youtube_music_connector"
SOURCE_WIDGET = REPO_ROOT / "www" / "community" / "youtube-music-connector"
PAYLOAD_ROOT = REPO_ROOT / "youtube_music_connector_companion" / "payload"
PAYLOAD_INTEGRATION = PAYLOAD_ROOT / "custom_components" / "youtube_music_connector"
PAYLOAD_WIDGET = PAYLOAD_ROOT / "www" / "community" / "youtube-music-connector"


def ignore_names(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name == "__pycache__"}
    ignored.update(name for name in names if name.endswith((".pyc", ".pyo", ".bak", ".tmp")))
    return ignored


def replace_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=ignore_names)


def compare_dirs(source: Path, target: Path) -> list[str]:
    differences: list[str] = []
    comparison = filecmp.dircmp(source, target, ignore=list(ignore_names("", comparison_names(source))))
    collect_differences(comparison, differences)
    return differences


def comparison_names(path: Path) -> list[str]:
    return [child.name for child in path.iterdir()] if path.exists() else []


def collect_differences(comparison: filecmp.dircmp, differences: list[str]) -> None:
    if comparison.left_only:
        differences.extend(f"Missing from payload: {comparison.left}/{name}" for name in comparison.left_only)
    if comparison.right_only:
        differences.extend(f"Unexpected in payload: {comparison.right}/{name}" for name in comparison.right_only)
    if comparison.diff_files:
        differences.extend(f"Changed file: {comparison.left}/{name}" for name in comparison.diff_files)
    if comparison.funny_files:
        differences.extend(f"Uncomparable file: {comparison.left}/{name}" for name in comparison.funny_files)
    for sub in comparison.subdirs.values():
        collect_differences(sub, differences)


def check_synced() -> int:
    problems: list[str] = []
    if not PAYLOAD_INTEGRATION.exists():
        problems.append(f"Missing payload directory: {PAYLOAD_INTEGRATION}")
    else:
        problems.extend(compare_dirs(SOURCE_INTEGRATION, PAYLOAD_INTEGRATION))
    if not PAYLOAD_WIDGET.exists():
        problems.append(f"Missing payload directory: {PAYLOAD_WIDGET}")
    else:
        problems.extend(compare_dirs(SOURCE_WIDGET, PAYLOAD_WIDGET))
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("Add-on payload is in sync")
    return 0


def sync() -> int:
    replace_tree(SOURCE_INTEGRATION, PAYLOAD_INTEGRATION)
    replace_tree(SOURCE_WIDGET, PAYLOAD_WIDGET)
    print("Add-on payload synchronized")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check_synced() if args.check else sync()


if __name__ == "__main__":
    raise SystemExit(main())
