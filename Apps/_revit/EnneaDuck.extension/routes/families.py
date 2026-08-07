# -*- coding: utf-8 -*-
"""Families route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION


def register_family_routes(api):
    @api.route("/families/", methods=["GET"])
    def get_families(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        category_filter = request.get("category")

        collector = (
            DB.FilteredElementCollector(doc)
            .OfClass(DB.Family)
            .ToElements()
        )

        families = []
        for family in collector:
            # Apply optional category filter
            if category_filter:
                fam_cat = family.FamilyCategory
                if fam_cat is None:
                    continue
                if fam_cat.Name != category_filter:
                    continue

            # Count types WITHOUT fetching each symbol. The old code did
            # doc.GetElement(type_id) for every type of every family just to read
            # symbol.Name -- thousands of API calls on a large model, blowing the
            # 30s client timeout (HTTP 408). GetFamilySymbolIds() alone gives the
            # count; per-type names are dropped from this list route (ask for a
            # specific family's types via a targeted query if needed).
            type_count = len(family.GetFamilySymbolIds())

            families.append({
                "id": REVIT_APPLICATION.get_element_id_value(family.Id),
                "name": family.Name,
                "category": family.FamilyCategory.Name if family.FamilyCategory else None,
                "is_in_place": family.IsInPlace,
                "type_count": type_count,
            })

        return routes.make_response(data={
            "count": len(families),
            "families": families,
        })
