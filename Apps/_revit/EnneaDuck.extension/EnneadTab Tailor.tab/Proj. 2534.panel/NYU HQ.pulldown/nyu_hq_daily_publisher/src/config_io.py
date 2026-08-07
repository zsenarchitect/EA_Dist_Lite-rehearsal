from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "project_name": "2534_NYUL Long Island HQ",
    "project_id": None,
    "publish_with_links": False,
    "items": [
        {"name": "2534_A_EA_NYU HQ_Shell.rvt", "id": None, "enabled": True},
        {"name": "2534_A_EA_NYU HQ_Site.rvt", "id": None, "enabled": False},
    ],
    "last_resolved_utc": None,
}


def load_config(config_path: Path) -> Dict[str, Any]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        save_config(config_path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(config_path: Path, data: Dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


