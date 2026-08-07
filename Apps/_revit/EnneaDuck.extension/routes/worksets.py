# -*- coding: utf-8 -*-
"""Worksets route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB


def register_worksets_routes(api):
    @api.route("/worksets/", methods=["GET"])
    def get_worksets(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        # A non-workshared model has no user worksets -- report it plainly rather
        # than returning an empty list that looks like a bug.
        if not doc.IsWorkshared:
            return routes.make_response(data={
                "worksets": [],
                "note": "not workshared",
            })

        # Inline collector on the INJECTED doc (do not use REVIT_WORKSET.get_all_userworkset:
        # it binds a module-global doc and returns raw objects).
        collector = (
            DB.FilteredWorksetCollector(doc)
            .OfKind(DB.WorksetKind.UserWorkset)
            .ToWorksets()
        )

        worksets = []
        for ws in collector:
            worksets.append({
                "id": ws.Id.IntegerValue,
                "name": ws.Name,
                "is_open": ws.IsOpen,
            })

        return routes.make_response(data={
            "count": len(worksets),
            "worksets": worksets,
        })
