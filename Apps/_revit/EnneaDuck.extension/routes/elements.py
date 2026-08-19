# -*- coding: utf-8 -*-
"""Elements route handler for EnneadTab MCP."""
import json

from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION

from _request_utils import get_param


MAX_RESULTS = 500


def _find_builtin_category(category_name):
    """Find a BuiltInCategory by matching against member names."""
    for member in dir(DB.BuiltInCategory):
        if member.startswith("OST_"):
            # Match against the name with or without OST_ prefix
            if member == category_name or member == "OST_{}".format(category_name):
                return getattr(DB.BuiltInCategory, member)
            # Also try case-insensitive match
            if member.lower() == category_name.lower():
                return getattr(DB.BuiltInCategory, member)
            if member.lower() == "ost_{}".format(category_name.lower()):
                return getattr(DB.BuiltInCategory, member)
    return None


def register_element_routes(api):
    # GET+POST: on this pyRevit build query strings are stripped before the
    # handler runs, so `category` must ride the JSON body (POST). GET is kept so
    # an older client fails with a clean 400 rather than a masked 408.
    @api.route("/elements/", methods=["GET", "POST"])
    def get_elements(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        category = get_param(request, "category")
        if not category:
            return routes.make_response(
                data={"error": "category is required (send it in the JSON POST body)"},
                status_code=400,
            )

        bic = _find_builtin_category(category)
        if bic is None:
            return routes.make_response(
                data={"error": "Unknown category: {}".format(category)},
                status_code=400,
            )

        collector = (
            DB.FilteredElementCollector(doc)
            .OfCategory(bic)
            .WhereElementIsNotElementType()
        )

        # Optional filters. Accept either a JSON string (legacy) or an already
        # decoded object (when sent as a nested value in the POST body).
        filters_raw = get_param(request, "filters")
        if isinstance(filters_raw, dict):
            filters = filters_raw
        elif filters_raw:
            try:
                filters = json.loads(filters_raw)
            except (ValueError, TypeError):
                filters = {}
        else:
            filters = {}

        elements = []
        count = 0
        for elem in collector:
            if count >= MAX_RESULTS:
                break

            elem_data = {
                "id": REVIT_APPLICATION.get_element_id_value(elem.Id),
                "name": elem.Name if elem.Name else None,
                "category": elem.Category.Name if elem.Category else None,
            }

            # Apply parameter filters if provided
            if filters:
                match = True
                for param_name, expected_value in filters.items():
                    param = elem.LookupParameter(param_name)
                    if param is None:
                        match = False
                        break
                    actual = param.AsString() or str(param.AsValueString() or "")
                    if actual != str(expected_value):
                        match = False
                        break
                if not match:
                    continue

            elements.append(elem_data)
            count += 1

        return routes.make_response(data={
            "category": category,
            "count": len(elements),
            "capped": count >= MAX_RESULTS,
            "elements": elements,
        })
