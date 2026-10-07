#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Read clean target program data from the NYU HQ webapp API.

OWNERSHIP (per the NYU HQ zero-data architecture):
  - Postgres is the system of truth for program targets; the webapp's
    /api/targets endpoint is the only gateway.
  - The clean targets are written by the webapp's MCP server (AI agents
    ingesting dirty hand-crafted Excel drops) or the targets.html editor
    (humans fine-tuning).
  - Revit READS them here via GET /api/targets. Revit never parses the dirty
    Excel directly, never clones the website repo, and never reads JSON files.

Returns the same (data_dict, color_hierarchy) shape as the legacy
excel_data.get_excel_data(), so the AreaMatcher and exporter work unchanged:
  data_dict:       composite key "DEPT | DIV | ROOM" -> TargetRow
  color_hierarchy: {"department": {...}, "division": {...}, "room_name": {...}}

Python 2 / IronPython compatible (Revit).
"""

import config
import nyu_hq_api


class TargetRow(object):
    """Minimal RowData-compatible container.

    The AreaMatcher reads attributes named exactly like the Excel headers
    ("DEPARTMENT", "DIVISION", "ROOM NAME", "KEY UNIT", "DGSF+").
    """

    def __init__(self, department, division, room_name,
                 target_count, target_dgsf, color, row_number):
        setattr(self, config.DEPARTMENT_KEY[config.APP_EXCEL], department)
        setattr(self, config.PROGRAM_TYPE_KEY[config.APP_EXCEL], division)
        setattr(self, config.PROGRAM_TYPE_DETAIL_KEY[config.APP_EXCEL], room_name)
        setattr(self, config.COUNT_KEY[config.APP_EXCEL], target_count)
        setattr(self, config.SCALED_DGSF_KEY[config.APP_EXCEL], target_dgsf)
        setattr(self, "COLOR", color)
        self._row_number = row_number


def get_target_data():
    """Load clean targets from the NYU HQ webapp API.

    Returns:
        tuple: (data_dict, color_hierarchy) matching get_excel_data()'s shape.

    Raises:
        nyu_hq_api.NyuHqApiError: if the API cannot be reached, auth fails,
            or the database has not been seeded yet.
    """
    payload = nyu_hq_api.get_targets()
    if not isinstance(payload, dict):
        raise nyu_hq_api.NyuHqApiError(
            "Unexpected response from GET /api/targets.")

    rooms = payload.get("rooms", [])
    color_hierarchy = payload.get("color_hierarchy",
                                  {"department": {}, "division": {},
                                   "room_name": {}})

    sep = config.COMPOSITE_KEY_SEPARATOR
    data_dict = {}
    for i, room in enumerate(rooms):
        department = room.get("department", "")
        division = room.get("division", "")
        room_name = room.get("room_name", "")
        if not room_name:
            continue
        key = sep.join([department, division, room_name])
        # JSON null -> None (no requirement), preserved as-is for the matcher
        data_dict[key] = TargetRow(
            department=department,
            division=division,
            room_name=room_name,
            target_count=room.get("target_count"),
            target_dgsf=room.get("target_dgsf"),
            color=room.get("color"),
            row_number=i + 1,
        )

    print("Target data loaded: {} rooms from {}/api/targets".format(
        len(data_dict), config.NYU_HQ_API_URL))
    meta = payload.get("meta", {})
    if meta.get("updated_at"):
        print("  updated_at: {} by {}".format(
            meta.get("updated_at"), meta.get("updated_by", "?")))
    version = meta.get("version")
    if version is not None:
        print("  targets version: {}".format(version))
    return data_dict, color_hierarchy
