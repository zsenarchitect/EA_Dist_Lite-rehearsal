from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Dict, List, Optional

from aps_auth import get_access_token
from aps_dm import find_project_by_name, find_item_ids_by_names


def _merge_items(existing: List[dict], new_map: Dict[str, Optional[str]]) -> List[dict]:
    name_to_item = {i.get("name"): i for i in existing}
    for name, iid in new_map.items():
        if name in name_to_item:
            if iid:
                name_to_item[name]["id"] = iid
        else:
            name_to_item[name] = {"name": name, "id": iid, "enabled": False}
    return list(name_to_item.values())


def resolve_and_merge(config: dict, project_name_override: Optional[str], file_names: List[str], config_path: Path) -> Optional[dict]:
    """Resolve project_id and item ids for given names, merge into config.

    Returns updated config or None on failure.
    """
    # Prepare
    config_dir = config_path.parent
    project_name = project_name_override or config.get("project_name")
    if not project_name:
        return None

    token = get_access_token(config_dir)
    if not token:
        return None

    # Ensure project id
    b_project_id = config.get("project_id")
    hub_id = None
    if not b_project_id:
        proj = find_project_by_name(token, project_name)
        if not proj:
            return None
        b_project_id, hub_id = proj
        config["project_id"] = b_project_id
    else:
        # Need hub id for traversal; re-find by name as simplest approach
        proj = find_project_by_name(token, project_name)
        if not proj:
            return None
        _, hub_id = proj

    # Find items
    name_to_id = find_item_ids_by_names(token, b_project_id, hub_id, file_names)
    if not name_to_id:
        return None

    config["items"] = _merge_items(config.get("items", []), name_to_id)
    config["last_resolved_utc"] = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return config


