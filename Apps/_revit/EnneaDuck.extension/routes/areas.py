# -*- coding: utf-8 -*-
"""Area schemes route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION


def register_areas_routes(api):
    @api.route("/areas/", methods=["GET"])
    def get_areas(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        # Imported inside the handler on purpose: REVIT_AREA_SCHEME runs
        # get_uidoc()/get_doc() and pulls in REVIT_SELECTION/forms/NOTIFICATION at
        # IMPORT time (unlike the lightweight REVIT_APPLICATION every other route
        # uses). A top-level import here would let one bad import kill startup.py's
        # registration of ALL routes; scoping it isolates any failure to /areas/.
        from EnneadTab.REVIT import REVIT_AREA_SCHEME
        schemes = REVIT_AREA_SCHEME.get_all_area_schemes(doc)

        # Collect all Area elements once, then count per scheme (avoids a
        # per-scheme collector). Guard AreaScheme access -- a stray area can lack
        # a scheme reference.
        all_areas = (
            DB.FilteredElementCollector(doc)
            .OfCategory(DB.BuiltInCategory.OST_Areas)
            .WhereElementIsNotElementType()
            .ToElements()
        )

        result = []
        for scheme in schemes:
            count = 0
            for area in all_areas:
                try:
                    if area.AreaScheme is not None and area.AreaScheme.Id == scheme.Id:
                        count += 1
                except Exception:
                    pass
            result.append({
                "id": REVIT_APPLICATION.get_element_id_value(scheme.Id),
                "name": scheme.Name,
                "area_count": count,
            })

        return routes.make_response(data={
            "count": len(result),
            "area_schemes": result,
        })
