# -*- coding: utf-8 -*-
"""Rooms route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SPATIAL_ELEMENT
from _request_utils import json_safe, route_error


def register_rooms_routes(api):
    @api.route("/rooms/", methods=["GET"])
    def get_rooms(doc, request):
        try:
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

                # Room name: In IronPython, room.Name raises AttributeError because of
                # property dispatch on SpatialElement. Access BuiltInParameter.ROOM_NAME
                # directly, falling back to Element.Name.GetValue(room).
                room_name = ""
                try:
                    param = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
                    if param and param.HasValue:
                        room_name = param.AsString() or ""
                    elif hasattr(room, "Name"):
                        room_name = room.Name or ""
                    else:
                        room_name = DB.Element.Name.GetValue(room) or ""
                except Exception:
                    try:
                        room_name = DB.Element.Name.GetValue(room) or ""
                    except Exception:
                        room_name = ""

                # Room number: parameter access first, fallback to attribute
                room_number = ""
                try:
                    param = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
                    if param and param.HasValue:
                        room_number = param.AsString() or ""
                    else:
                        room_number = getattr(room, "Number", "") or ""
                except Exception:
                    room_number = getattr(room, "Number", "") or ""

                # Room area
                area = 0.0
                try:
                    area = room.Area
                except Exception:
                    area = 0.0

                rooms.append({
                    "id": REVIT_APPLICATION.get_element_id_value(room.Id),
                    "name": room_name,
                    "number": room_number,
                    "area": area,
                    "level": level_name,
                    "status": status,
                })

            return routes.make_response(data=json_safe({
                "count": len(rooms),
                "rooms": rooms,
            }))
        except Exception:
            return route_error()
