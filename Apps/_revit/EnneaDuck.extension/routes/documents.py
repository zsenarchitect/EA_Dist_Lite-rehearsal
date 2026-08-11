# -*- coding: utf-8 -*-
"""Documents route handler for EnneadTab MCP.

Lists every open Revit document in the host process (Revit is multi-document per
process). Linked documents are skipped. The active document is flagged so the
desktop assistant's picker can mark it; v1 is list-only (no server-side switch).
"""
from pyrevit import routes, HOST_APP


def register_documents_routes(api):
    @api.route("/documents/", methods=["GET"])
    def get_documents(doc, request):
        # `doc` is the pyRevit-injected active document; its Title identifies which
        # of the open documents is currently active.
        active_title = doc.Title if doc else None

        documents = []
        for d in HOST_APP.app.Documents:
            # Skip linked models - they are not independently drivable documents.
            if d.IsLinked:
                continue
            is_active = active_title is not None and d.Title == active_title
            documents.append({
                "title": d.Title,
                "path": d.PathName,
                "is_active": is_active,
                "is_workshared": d.IsWorkshared,
            })

        return routes.make_response(data={
            "documents": documents,
            "active": active_title,
        })
