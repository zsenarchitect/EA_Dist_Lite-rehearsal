# -*- coding: utf-8 -*-
"""Views route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION


def register_view_routes(api):
    @api.route("/views/", methods=["GET"])
    def get_views(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        collector = (
            DB.FilteredElementCollector(doc)
            .OfClass(DB.View)
            .ToElements()
        )

        # OfClass(DB.View) returns every View-derived element, including sheets and
        # schedules. Those are their own top-level nodes in the Project Browser -- an
        # architect asking "how many views" does not mean sheets or schedules -- so they
        # are excluded from the count. Legends are borderline; excluded here to match the
        # Project Browser's separate "Legends" node. The full breakdown is still returned
        # under views_by_type so nothing is hidden.
        NON_VIEW_TYPES = ("DrawingSheet", "Schedule", "Legend")

        grouped = {}
        total = 0
        for view in collector:
            # Skip view templates
            if view.IsTemplate:
                continue

            view_type = str(view.ViewType)
            if view_type in NON_VIEW_TYPES:
                continue
            if view_type not in grouped:
                grouped[view_type] = []

            # OfClass(DB.View) also returns ViewSheet and ViewSchedule (both subclass
            # View). View.Scale's GETTER throws InvalidOperationException on sheets,
            # schedules, legends, and perspective 3D views -- a hasattr() guard does NOT
            # help because the property IS declared, only its getter throws when invoked.
            # An unguarded throw here bubbles to a pyRevit 500 (any model with a sheet or
            # schedule -> always 500). Guard the getter, mirroring model_info.py.
            try:
                scale = view.Scale
            except Exception:
                scale = None

            grouped[view_type].append({
                "id": REVIT_APPLICATION.get_element_id_value(view.Id),
                "name": view.Name,
                "view_type": view_type,
                "scale": scale,
            })
            total += 1

        return routes.make_response(data={
            "count": total,
            "view_types": list(grouped.keys()),
            "views_by_type": grouped,
        })
