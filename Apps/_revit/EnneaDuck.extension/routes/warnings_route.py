# -*- coding: utf-8 -*-
"""Warnings route handler for EnneadTab MCP."""
from pyrevit import routes

from EnneadTab.REVIT import REVIT_APPLICATION


def register_warnings_routes(api):
    @api.route("/warnings/", methods=["GET"])
    def get_warnings(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        warnings = []
        for failure in doc.GetWarnings():
            failing_ids = [
                REVIT_APPLICATION.get_element_id_value(eid)
                for eid in failure.GetFailingElements()
            ]
            warnings.append({
                "description": failure.GetDescriptionText(),
                "severity": str(failure.GetSeverity()),
                "failing_elements": failing_ids,
            })

        return routes.make_response(data={
            "count": len(warnings),
            "warnings": warnings,
        })
