# -*- coding: utf-8 -*-
"""Execute arbitrary code route handler for EnneadTab MCP."""
import json
import sys
import traceback

from pyrevit import routes, revit
from Autodesk.Revit import DB
from StringIO import StringIO


def register_execute_code_routes(api):
    @api.route("/execute-code/", methods=["POST"])
    def execute_code(doc, request):
        if not doc:
            return routes.make_response(
                data={"error": "No document open"},
                status_code=400,
            )

        data = json.loads(request.data) if isinstance(request.data, str) else request.data
        code = data.get("code")

        if not code:
            return routes.make_response(
                data={"error": "code is required"},
                status_code=400,
            )

        uidoc = revit.uidoc

        stdout_capture = StringIO()
        stderr_capture = StringIO()

        old_stdout = sys.stdout
        old_stderr = sys.stderr

        exec_globals = {
            "doc": doc,
            "uidoc": uidoc,
            "DB": DB,
            "__builtins__": __builtins__,
        }

        error_msg = None

        t = DB.Transaction(doc, "MCP: Execute Code")
        try:
            t.Start()

            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            try:
                exec(code, exec_globals)
            except Exception:
                error_msg = traceback.format_exc()

            sys.stdout = old_stdout
            sys.stderr = old_stderr

            if error_msg:
                t.RollBack()
            else:
                t.Commit()
        except Exception as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            if t.HasStarted():
                t.RollBack()
            return routes.make_response(
                data={"error": str(e)},
                status_code=500,
            )

        result = {
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "error": error_msg,
        }

        status = 200 if error_msg is None else 400
        return routes.make_response(data=result, status_code=status)
