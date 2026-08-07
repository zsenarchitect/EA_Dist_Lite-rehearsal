# -*- coding: utf-8 -*-
"""Grids route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION


def register_grids_routes(api):
    @api.route("/grids/", methods=["GET"])
    def get_grids(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        collector = (
            DB.FilteredElementCollector(doc)
            .OfCategory(DB.BuiltInCategory.OST_Grids)
            .WhereElementIsNotElementType()
        )

        grids = []
        for grid in collector:
            grids.append({
                "id": REVIT_APPLICATION.get_element_id_value(grid.Id),
                "name": grid.Name,
            })

        return routes.make_response(data={
            "count": len(grids),
            "grids": grids,
        })
