#!/usr/bin/env python3
"""
One-time or reusable resolver to discover APS project and item IDs by names
and merge them into configs/config.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
CONFIG_DIR = BASE_DIR / "configs"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config_io import load_config, save_config
from resolver import resolve_and_merge


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve APS IDs and merge into config.json")
    parser.add_argument("--project", required=False, help="Project name override")
    parser.add_argument("--files", nargs="*", required=True, help="File names to resolve")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = CONFIG_DIR / "config.json"

    config = load_config(config_path)
    project_name = args.project or config.get("project_name")
    if not project_name:
        print("Project name required (either in config or via --project)")
        return 2

    updated_config = resolve_and_merge(
        config,
        project_name_override=project_name,
        file_names=args.files,
        config_path=config_path
    )

    if updated_config is None:
        print("Failed to resolve any IDs.")
        return 1

    save_config(config_path, updated_config)

    # Print a brief summary
    items = updated_config.get("items", [])
    print("Resolved/merged items:")
    for it in items:
        name = it.get("name")
        iid = it.get("id")
        print(f" - {name}: {'OK' if iid else 'MISSING'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


