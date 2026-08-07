# -*- coding: utf-8 -*-
"""Selection route handler for EnneadTab MCP."""
from pyrevit import routes

from EnneadTab.REVIT import REVIT_APPLICATION


def register_selection_routes(api):
    @api.route("/selection/", methods=["GET"])
    def get_selection(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        # Resolve the UIDocument LIVE -- do NOT reuse REVIT_SELECTION.get_selection()'s
        # import-time UIDOC default (it binds stale/None at import).
        uidoc = REVIT_APPLICATION.get_uidoc()
        if uidoc is None:
            return routes.make_response(data={
                "selection": [],
                "note": "no active UI document",
            })

        element_ids = uidoc.Selection.GetElementIds()

        selection = []
        for eid in element_ids:
            elem = doc.GetElement(eid)
            if elem is None:
                continue

            # elem.Name can throw on some element types -- guard it.
            try:
                name = elem.Name if elem.Name else None
            except Exception:
                name = None

            selection.append({
                "id": REVIT_APPLICATION.get_element_id_value(eid),
                "name": name,
                "category": elem.Category.Name if elem.Category else None,
            })

        return routes.make_response(data={
            "count": len(selection),
            "selection": selection,
        })
