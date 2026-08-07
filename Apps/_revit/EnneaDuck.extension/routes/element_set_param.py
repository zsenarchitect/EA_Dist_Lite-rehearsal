# -*- coding: utf-8 -*-
"""Element set-parameter route handler for EnneadTab MCP."""
import json

from pyrevit import routes
from Autodesk.Revit import DB


def register_element_set_param_routes(api):
    @api.route(
        "/element/<element_id>/set-parameter/", methods=["POST"]
    )
    def set_element_param(doc, request, element_id):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        data = json.loads(request.data) if isinstance(request.data, str) else request.data
        param_name = data.get("param_name")
        value = data.get("value")

        if not param_name:
            return routes.make_response(
                data={"error": "param_name is required"},
                status_code=400,
            )

        try:
            eid = DB.ElementId(int(element_id))
        except (ValueError, TypeError):
            return routes.make_response(
                data={"error": "Invalid element_id: {}".format(element_id)},
                status_code=400,
            )

        elem = doc.GetElement(eid)
        if elem is None:
            return routes.make_response(
                data={"error": "Element not found: {}".format(element_id)},
                status_code=404,
            )

        param = elem.LookupParameter(param_name)
        if param is None:
            return routes.make_response(
                data={"error": "Parameter not found: {}".format(param_name)},
                status_code=404,
            )

        if param.IsReadOnly:
            return routes.make_response(
                data={"error": "Parameter is read-only: {}".format(param_name)},
                status_code=400,
            )

        t = DB.Transaction(doc, "MCP: Set Parameter")
        try:
            t.Start()

            storage = param.StorageType
            if storage == DB.StorageType.String:
                param.Set(str(value) if value is not None else "")
            elif storage == DB.StorageType.Integer:
                param.Set(int(value))
            elif storage == DB.StorageType.Double:
                param.Set(float(value))
            elif storage == DB.StorageType.ElementId:
                param.Set(DB.ElementId(int(value)))
            else:
                t.RollBack()
                return routes.make_response(
                    data={"error": "Unsupported StorageType: {}".format(storage)},
                    status_code=400,
                )

            t.Commit()
        except Exception as e:
            if t.HasStarted():
                t.RollBack()
            return routes.make_response(
                data={"error": str(e)},
                status_code=500,
            )

        return routes.make_response(data={
            "element_id": int(element_id),
            "param_name": param_name,
            "value": value,
            "success": True,
        })
