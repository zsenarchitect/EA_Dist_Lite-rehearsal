# -*- coding: utf-8 -*-
"""Families route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION

from _request_utils import get_param

# Unbounded enumerate on a big model was returning HTTP 408 from pyRevit Routes
# (RevitAssistant "list all family"). Cap the page; callers pass limit/offset.
MAX_FAMILIES = 200


def _int_arg(request, name, default, lo, hi):
    raw = request.get(name)
    if raw is None:
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def register_family_routes(api):
    # GET+POST: the optional `category` filter must ride the JSON body on this
    # pyRevit build (query strings are stripped). GET still works (unfiltered).
    @api.route("/families/", methods=["GET", "POST"])
    def get_families(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        category_filter = get_param(request, "category")
        limit = _int_arg(request, "limit", MAX_FAMILIES, 1, MAX_FAMILIES)
        offset = _int_arg(request, "offset", 0, 0, 1000000)

        collector = (
            DB.FilteredElementCollector(doc)
            .OfClass(DB.Family)
            .ToElements()
        )

        families = []
        skipped = 0
        truncated = False
        for family in collector:
            if category_filter:
                fam_cat = family.FamilyCategory
                if fam_cat is None:
                    continue
                if fam_cat.Name != category_filter:
                    continue

            if skipped < offset:
                skipped += 1
                continue

            if len(families) >= limit:
                truncated = True
                break

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
            "offset": offset,
            "limit": limit,
            "truncated": truncated,
            "families": families,
        })
