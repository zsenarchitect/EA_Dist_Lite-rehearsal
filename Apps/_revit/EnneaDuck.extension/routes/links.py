# -*- coding: utf-8 -*-
"""Revit links route handler for EnneadTab MCP."""
from pyrevit import routes
from Autodesk.Revit import DB

from EnneadTab.REVIT import REVIT_APPLICATION


def register_links_routes(api):
    @api.route("/links/", methods=["GET"])
    def get_links(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        link_types = REVIT_APPLICATION.get_revit_link_types(doc)

        links = []
        for link_type in link_types:
            # GetLinkedFileStatus() -> LinkedFileStatus enum (Loaded/Unloaded/NotFound/...).
            try:
                status = str(link_type.GetLinkedFileStatus())
            except Exception:
                status = None

            # RevitLinkType.IsLoaded is a STATIC method taking (doc, id).
            try:
                is_loaded = DB.RevitLinkType.IsLoaded(doc, link_type.Id)
            except Exception:
                is_loaded = None

            links.append({
                "id": REVIT_APPLICATION.get_element_id_value(link_type.Id),
                "name": link_type.Name,
                "status": status,
                "is_loaded": is_loaded,
            })

        return routes.make_response(data={
            "count": len(links),
            "links": links,
        })
