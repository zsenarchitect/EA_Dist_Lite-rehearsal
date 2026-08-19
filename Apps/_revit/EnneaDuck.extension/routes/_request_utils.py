# -*- coding: utf-8 -*-
"""Shared request helpers for EnneadTab MCP routes.

Two hard facts about the pyRevit Routes build these routes run on
(pyRevit-Master, Revit 2026.1) -- both learned by probing the live server:

1. QUERY-STRING PARAMS ARE STRIPPED. pyRevit's HTTP server parses the URL with
   urlparse().path (server.py `_parse_api_path`) BEFORE the handler runs, so a
   query like "?category=Sheets" never reaches the Request object, and
   `request.params` only ever carries route-pattern {placeholders}. There is
   also no `request.get(...)` on this build. Therefore a parameter MUST ride the
   JSON body (`request.data`) -- register param routes for POST and read them
   with `get_param()`.

2. THE FRAMEWORK MASKS HANDLER EXCEPTIONS. When a route handler raises, pyRevit
   (handler.py `run_handler`) builds an error report that calls
   `clsx.TargetSite.ToString()`; for a pure-Python exception `TargetSite` is
   None, so the report itself throws "'NoneType' object has no attribute
   'ToString'" and the REAL error is replaced by a bogus HTTP 408. The desktop
   client then renders "Revit timed out" for what was actually a plain code bug.
   So every handler must catch its own exceptions and return an honest response
   -- never let one propagate. `route_error()` builds that response.
"""
import traceback

from pyrevit import routes


def get_param(request, key, default=None):
    """Read one request parameter without ever raising.

    Lookup order: JSON body (`request.data`, for POST) -> route {placeholder}
    params -> `default`. Query-string params are unavailable on this build
    (see module docstring), so a GET route with no {placeholder} cannot receive
    a parameter -- send it as a POST body instead.
    """
    data = getattr(request, "data", None)
    if isinstance(data, dict) and key in data:
        return data.get(key)
    for p in (getattr(request, "params", None) or []):
        if getattr(p, "key", None) == key:
            return p.value
    return default


def route_error(exc=None, status_code=500):
    """Build an honest JSON error response from the current exception.

    Use in a handler's `except` so the real traceback surfaces instead of
    tripping pyRevit's TargetSite.ToString() masking bug (which the client shows
    as a fake 408 'timed out'). Call with no args from inside an `except` block.
    """
    return routes.make_response(
        data={"error": traceback.format_exc() if exc is None else str(exc)},
        status_code=status_code,
    )


def json_safe(value):
    """Coerce a value tree so pyRevit's json.dumps can always encode it.

    THIRD hard fact about this build: pyRevit writes the response with
    json.dumps(ensure_ascii=True) (handler.py parse_response). Revit .NET strings
    surface in IronPython 2.7 as code-page (cp1252) BYTE strings, so a sheet name
    or number with a non-ASCII glyph -- an e-acute is a lone 0xE9 -- makes
    py_encode_basestring_ascii raise "'unknown' codec can't decode byte 0xe9",
    which the client sees as a 500 (or, via the TargetSite masking bug above, a
    bogus 408). Decoding every byte string to unicode here makes the whole payload
    JSON-safe. Recurses dicts/lists; scalars pass through.

    Apply to the data dict before make_response in any route that returns
    user-authored strings (sheet/view/family/room names, parameter values, code
    snippets, captured stdout, ...).
    """
    if isinstance(value, unicode):
        return value
    if isinstance(value, str):
        for codec in ("utf-8", "cp1252", "latin-1"):
            try:
                return value.decode(codec)
            except Exception:
                continue
        return value.decode("ascii", "replace")
    if isinstance(value, dict):
        return dict(
            (json_safe(k), json_safe(v)) for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
