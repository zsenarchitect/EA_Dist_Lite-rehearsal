#! python 2
# -*- coding: utf-8 -*-
"""L3 runtime check: does get_earth_utility actually load under IronPython 2.7?

This closes the harness's largest blind spot. The L1 pytest suite proves the AOI
math is CORRECT, but it runs under CPython 3.9 -- and `rhinocode script` also
defaults to CPython 3.9. Neither proves the module survives the runtime it
actually SHIPS in, which is IronPython 2.7 inside Rhino (Apps/_rhino/ rule in
CLAUDE.md). Py3-only syntax would pass every L1 test and then fail live in the
toolbar, in front of a user.

The `#! python 2` shebang on line 1 selects IronPython 2.7 in Rhino 8.

Run:  RhinoCode.exe script DarkSide/tests/get_earth/rhino_l3_aoi_ironpython.py
POLL for the JSON it writes -- do not read it once. The CLI is asynchronous: it
returns when Rhino has ACCEPTED the script, not when the script has finished,
and exits 0 either way while printing nothing. A result file read in the same
breath as the dispatch is read before it exists, and that absence is
indistinguishable from "Rhino never ran it" (cost an hour and a needless Rhino
restart on 2026-08-23). Delete any previous result first, then poll on mtime.
"""

import os
import sys
import json
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BUTTON_DIR = os.path.join(REPO, "Apps", "_rhino", "Render.tab", "get_earth.button")

# Rhino's EnneadTab startup puts Apps/lib on sys.path; a rhinocode-driven script
# does NOT inherit that, so `from EnneadTab import X` fails with a bare
# "No module named EnneadTab" that reads like a broken module rather than a
# broken harness. Insert at position 0 deliberately: an EA_Dist install may
# already be on the path, and the test must exercise THIS checkout, not the
# deployed copy. (Cost one wrong diagnosis, 2026-08-05.)
LIB_DIR = os.path.join(REPO, "Apps", "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

JSON_PATH = os.path.join(HERE, "l3_ironpython_result.json")

result = {"ok": True, "checks": []}


def check(name, fn):
    try:
        result["checks"].append({"name": name, "ok": True, "value": fn()})
    except Exception as e:
        result["checks"].append({"name": name, "ok": False, "error": str(e)})
        result["ok"] = False


def main():
    check("runtime", lambda: sys.version.replace("\n", " "))
    check("is_ironpython2", lambda: sys.version_info[0] == 2)

    sys.path.insert(0, BUTTON_DIR)
    import get_earth_utility as U
    check("module_imported", lambda: U.__name__)

    # Same assertions as the L1 suite, re-run in the shipping runtime. If Py2
    # integer division or any 2/3 divergence bites, these are where it shows.
    check("unit_mm", lambda: U.meters_to_model(500.0, "millimeter"))

    def _square():
        bbox = U.square_bbox(40.7484, -73.9857, 500.0)
        w, h = U.bbox_size_m(bbox)
        return {"w": round(w, 3), "h": round(h, 3),
                "within_1m": abs(w - 500.0) < 1.0 and abs(h - 500.0) < 1.0}

    check("square_bbox_round_trip", _square)

    def _half_size_division():
        # Py2 integer division trap: size/2 with an int size must not floor.
        bbox = U.square_bbox(0.0, 0.0, 501)
        w, _h = U.bbox_size_m(bbox)
        return {"w": round(w, 3), "within_1m": abs(w - 501.0) < 1.0}

    check("integer_size_no_floor_division", _half_size_division)

    def _high_lat():
        bbox = U.square_bbox(60.1699, 24.9384, 1000.0)
        w, h = U.bbox_size_m(bbox)
        return {"w": round(w, 3), "h": round(h, 3),
                "within_1m": abs(w - 1000.0) < 1.0 and abs(h - 1000.0) < 1.0}

    check("high_latitude", _high_lat)

    def _antimeridian():
        bbox = U.square_bbox(-16.8, 179.9995, 500.0)
        return {"crosses": U.crosses_antimeridian(bbox)}

    check("antimeridian", _antimeridian)

    def _errors_still_raise():
        raised = 0
        for bad in ((90.0, 0.0, 500.0), (40.0, -73.0, 0), (40.0, -73.0, -5)):
            try:
                U.square_bbox(*bad)
            except ValueError:
                raised += 1
        return {"raised": raised, "expected": 3}

    check("validation_raises", _errors_still_raise)

    # EARTH_MODEL ships in Apps/lib and is loaded by Rhino, so it must survive
    # IronPython 2.7 too. Its CPython test suite proves the CONTRACT; this
    # proves the module even loads in the runtime it ships in. Both are needed:
    # the pytest suite would pass happily on Py3-only syntax.
    def _earth_model_loads():
        from EnneadTab import EARTH_MODEL as EMOD
        return {
            "endpoint": EMOD.model_endpoint(),
            "cache_key": EMOD.cache_key(40.7484, -73.9857, 500.0),
            "format": EMOD.FORMAT_GLB,
        }

    check("earth_model_imports_in_ironpython", _earth_model_loads)

    def _earth_model_key_matches_cpython():
        # The cache key is a sha256 over a formatted string. If Py2/Py3 differ
        # in float formatting or str/bytes handling, the two runtimes would
        # compute DIFFERENT keys for the same AOI -- the button and its tests
        # would silently disagree about what is cached.
        from EnneadTab import EARTH_MODEL as EMOD
        return {"key": EMOD.cache_key(40.7484, -73.9857, 500.0),
                "expected_from_cpython": "f1873085255f7559"}

    check("cache_key_agrees_across_runtimes", _earth_model_key_matches_cpython)


try:
    main()
except Exception:
    result["ok"] = False
    result["fatal"] = traceback.format_exc()
finally:
    # default=str: Rhino/.NET types are not JSON-serializable and a failure here
    # truncates the file mid-write.
    with open(JSON_PATH, "w") as f:
        json.dump(result, f, indent=2, default=str)
