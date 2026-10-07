# -*- coding: utf-8 -*-
"""Sync with central route handler for EnneadTab MCP."""
import System
from pyrevit import routes
from Autodesk.Revit import DB

from _request_utils import route_error


def register_sync_routes(api):
    @api.route("/sync-with-central/", methods=["POST"])
    def sync_with_central(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        if not doc.IsWorkshared:
            return routes.make_response(
                data={"error": "Document is not workshared"},
                status_code=400,
            )

        try:
            # Configure transact options to relinquish all
            transact_opts = DB.TransactWithCentralOptions()

            # Configure sync options
            sync_opts = DB.SynchronizeWithCentralOptions()
            relinquish_opts = DB.RelinquishOptions(True)
            sync_opts.SetRelinquishOptions(relinquish_opts)
            sync_opts.SaveLocalBefore = True
            sync_opts.SaveLocalAfter = True
            sync_opts.Comment = "MCP: Sync with Central"

            doc.SynchronizeWithCentral(transact_opts, sync_opts)
        except (Exception, System.Exception):
            return route_error()

        return routes.make_response(data={
            "document": doc.Title,
            "success": True,
            "message": "Synchronized with central model",
        })
