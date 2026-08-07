# -*- coding: utf-8 -*-
"""Sheets route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION


def register_sheets_routes(api):
    @api.route("/sheets/", methods=["GET"])
    def get_sheets(doc, request):
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

        return routes.make_response(data={
            "count": len(sheets),
            "sheets": sheets,
        })
