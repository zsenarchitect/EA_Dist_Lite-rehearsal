# -*- coding: utf-8 -*-
"""Rooms route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SPATIAL_ELEMENT


def register_rooms_routes(api):
    @api.route("/rooms/", methods=["GET"])
    def get_rooms(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        collector = (
            DB.FilteredElementCollector(doc)
            .OfCategory(DB.BuiltInCategory.OST_Rooms)
            .WhereElementIsNotElementType()
        )

        rooms = []
        for room in collector:
            # Level name (guarded -- an unplaced room may have no level).
            level_name = None
            try:
                level = room.Level
                if level is not None:
                    level_name = level.Name
            except Exception:
                level_name = None

            # Placement/enclosure status via the shared helper (checks Location
            # first, then Area). Guard so a single odd element can't 500 the list.
            try:
                status = REVIT_SPATIAL_ELEMENT.get_element_status(room)
            except Exception:
                status = None

            rooms.append({
                "id": REVIT_APPLICATION.get_element_id_value(room.Id),
                "name": room.Name,
                "number": room.Number,
                "area": room.Area,
                "level": level_name,
                "status": status,
            })

        return routes.make_response(data={
            "count": len(rooms),
            "rooms": rooms,
        })
