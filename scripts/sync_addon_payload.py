#!/usr/bin/env python3
"""Synchronize the add-on payload with the repository sources."""

from __future__ import annotations

import argparse
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


def iter_files(base: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for file_path in sorted(path for path in base.rglob("*") if path.is_file()):
        if file_path.name == "__pycache__":
            continue
        if file_path.suffix in {".pyc", ".pyo", ".bak", ".tmp"}:
            continue
        relative = file_path.relative_to(base).as_posix()
        result[relative] = file_path.read_bytes()
    return result


def compare_dirs(source: Path, target: Path) -> list[str]:
    source_files = iter_files(source)
    target_files = iter_files(target)
    differences: list[str] = []

    for relative in sorted(source_files.keys() - target_files.keys()):
        differences.append(f"Missing from payload: {source / relative}")
    for relative in sorted(target_files.keys() - source_files.keys()):
        differences.append(f"Unexpected in payload: {target / relative}")
    for relative in sorted(source_files.keys() & target_files.keys()):
        if source_files[relative] != target_files[relative]:
            differences.append(f"Changed file: {source / relative}")

    return differences


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
