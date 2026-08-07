# -*- coding: utf-8 -*-
"""Status route handler for EnneadTab MCP."""
from pyrevit import routes, revit, HOST_APP


def register_status_routes(api):
    @api.route("/status/", methods=["GET"])
    def get_status(doc, request):
        result = {
            "app": "Revit",
            "version": str(HOST_APP.version),
            "document": None,
            "path": None,
            "is_workshared": False,
        }

        if doc:
            result["document"] = doc.Title
            result["path"] = doc.PathName
            result["is_workshared"] = doc.IsWorkshared

        return routes.make_response(data=result)
