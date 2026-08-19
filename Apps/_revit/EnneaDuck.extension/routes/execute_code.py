# -*- coding: utf-8 -*-
"""Execute arbitrary code route handler for EnneadTab MCP.

This is the assistant's general-purpose tool. It was returning a bogus HTTP 408
("Revit timed out") for EVERY call -- even `print "hello"` -- because:
  * `uidoc = revit.uidoc` (and any other exception in the handler) propagated out
    to pyRevit's route dispatcher, whose error formatter crashes on
    `clsx.TargetSite.ToString()` for a pure-Python exception and masks the real
    error as a 408. See routes/_request_utils.py for the full write-up.
Fixes: take the framework-injected `uidoc` instead of `revit.uidoc`, and wrap the
whole handler so the real error is returned honestly rather than masked.
"""
import json
import sys
import traceback

from pyrevit import routes
from Autodesk.Revit import DB
from StringIO import StringIO

from _request_utils import get_param, route_error, json_safe


def register_execute_code_routes(api):
    @api.route("/execute-code/", methods=["POST"])
    def execute_code(doc, uidoc, request):
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No document open"},
                    status_code=400,
                )

            code = get_param(request, "code")
            if not code:
                return routes.make_response(
                    data={"error": "code is required"},
                    status_code=400,
                )

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
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
                if error_msg:
                    t.RollBack()
                else:
                    t.Commit()
            finally:
                # Never leave a transaction dangling if something above threw
                # between Start() and Commit()/RollBack().
                if t.HasStarted() and t.GetStatus() == DB.TransactionStatus.Started:
                    t.RollBack()

            result = {
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue(),
                # Keep the key JSON-null-safe: json.dumps handles None, but "" is
                # cleaner for the client to branch on ("" == no error).
                "error": error_msg or "",
            }
            status = 200 if error_msg is None else 400
            # json_safe(): generated code routinely prints non-ASCII (sheet/family
            # names, accented text). Without coercion those cp1252 bytes make
            # pyRevit's ensure_ascii json.dumps raise 0xE9 AFTER this handler
            # returns -- outside our try/except -- surfacing as an opaque 500/408
            # with no traceback, so the assistant can't self-heal it. Coercing the
            # response here makes ANY generated-code output survive serialization.
            return routes.make_response(data=json_safe(result), status_code=status)
        except Exception:
            return route_error()
