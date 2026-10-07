# -*- coding: utf-8 -*-
"""Sheets route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION

from _request_utils import json_safe, route_error


def register_sheets_routes(api):
    @api.route("/sheets/", methods=["GET"])
    def get_sheets(doc, request):
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No document open"},
                    status_code=400,
                )

            collector = (
                DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_Sheets)
                .WhereElementIsNotElementType()
            )

            sheets = []
            for sheet in collector:
                sheets.append({
                    "id": REVIT_APPLICATION.get_element_id_value(sheet.Id),
                    "sheet_number": sheet.SheetNumber,
                    "name": sheet.Name,
                })

            # json_safe(): sheet numbers/names routinely carry non-ASCII glyphs
            # (accents, en-dashes); without coercion pyRevit's ensure_ascii
            # json.dumps raises on the raw cp1252 bytes and the client sees a 500.
            return routes.make_response(data=json_safe({
                "count": len(sheets),
                "sheets": sheets,
            }))
        except Exception:
            return route_error()
