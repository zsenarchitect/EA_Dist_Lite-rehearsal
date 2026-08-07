#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry script to publish configured Revit cloud models via Autodesk APS commands.

Behavior:
- Reads configs/config.json for project_id and items (name/id/enabled)
- If a target item is missing id, resolve via APS and merge into config
- Publishes enabled items by default, or names provided via --files
- Prints and logs an end-of-run summary and exits non-zero on failure
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Local imports
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
CONFIG_DIR = BASE_DIR / "configs"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config_io import load_config, save_config
from resolver import resolve_and_merge
from publisher import publish_resources
from logging_utils import get_logger, summarize_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NYU HQ Daily APS Publisher")
    parser.add_argument("--files", nargs="*", default=None,
                        help="Explicit file names to publish (overrides enabled flags)")
    parser.add_argument("--batch", action="store_true",
                        help="Batch mode for scheduler (less verbose)")
    return parser.parse_args()


def main() -> int:
    logger = get_logger()

    config_path = CONFIG_DIR / "config.json"
    config = load_config(config_path)

    project_name = config.get("project_name")
    project_id = config.get("project_id")
    items = config.get("items", [])

    args = parse_args()

    # Determine target names
    if args.files:
        target_names = set(args.files)
    else:
        target_names = {item.get("name") for item in items if item.get("enabled")}

    # Map name -> item record
    name_to_item = {item.get("name"): item for item in items}

    # Identify names missing ids and resolve them
    missing_names = [n for n in target_names if not name_to_item.get(n) or not name_to_item[n].get("id")]
    if missing_names:
        logger.info("Resolving missing IDs for: %s", ", ".join(missing_names))
        updated_config = resolve_and_merge(
            config,
            project_name_override=project_name,
            file_names=missing_names,
            config_path=config_path
        )
        if updated_config is not None:
            config = updated_config
            save_config(config_path, config)
            items = config.get("items", [])
            name_to_item = {item.get("name"): item for item in items}
            project_id = config.get("project_id")
        else:
            logger.error("Failed to resolve required IDs; aborting")
            return 2

    # Collect item ids to publish
    item_ids = []
    publish_records = []
    for name in target_names:
        item = name_to_item.get(name)
        if not item or not item.get("id"):
            publish_records.append({
                "name": name,
                "attempted": False,
                "status": "missing_id",
                "http_status": None,
                "message": "Missing config or id"
            })
            continue
        item_ids.append(item["id"])
        publish_records.append({
            "name": name,
            "attempted": True,
            "status": "pending",
            "http_status": None,
            "message": ""
        })

    if not item_ids:
        logger.warning("No items to publish (check enabled flags or --files)")
        print("No items to publish.")
        return 0

    # Publish items individually (API requires exactly one resource per command)
    publish_with_links = bool(config.get("publish_with_links"))
    attempted_records = [r for r in publish_records if r["attempted"]]
    
    if attempted_records:
        logger.info(f"Publishing {len(attempted_records)} item(s) individually...")
        
        # Publish each item one at a time
        for i, rec in enumerate(attempted_records):
            item_id = item_ids[i]
            logger.info(f"Publishing {i+1}/{len(attempted_records)}: {rec['name']}")
            
            success, http_status, cmd_id, error_text = publish_resources(project_id, [item_id], publish_with_links=publish_with_links)
            
            rec["http_status"] = http_status
            if success:
                rec["status"] = "success"
                rec["message"] = f"CommandId={cmd_id}" if cmd_id else "Success"
                logger.info(f"  ✅ Success: {rec['name']}")
            else:
                rec["status"] = "failed"
                rec["message"] = error_text or ""
                logger.warning(f"  ❌ Failed: {rec['name']} - {error_text}")

    # Summary
    summary_text, any_failed = summarize_results(publish_records)
    print(summary_text)
    logger.info("\n" + summary_text)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())


