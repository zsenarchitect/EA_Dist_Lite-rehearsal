#! python 2
# -*- coding: utf-8 -*-
"""L3 runtime check: does the GetEarth progress meter work in the SHIPPING runtime?

PR #214 added `RhinoProgressMeter` and byte-progress plumbing. The L1 suite
(`test_download_progress.py`) proves the lifecycle and the maths, but it drives
a `FakeStatusBar` under CPython -- so it says nothing about whether the real
RhinoCommon call resolves. Two things make that gap matter more than usual:

1. **The failure is SILENT.** `RhinoProgressMeter` guards every Rhino call and
   `_disable()`s on a surprise, so a non-resolving overload degrades to "no
   progress bar plus one printed line", never an exception. `FakeStatusBar`
   mirrors the 5-arg shape and stays green no matter what real RhinoCommon
   accepts. Nothing outside a live Rhino can see this.

2. **Arity is the whole question, and arity is runtime-specific.**
   `get_earth_utility.py` calls the 5-arg `ShowProgressMeter(0, 100, label,
   True, True)` on purpose, because RhinoCommon also carries doc-serial-number
   overloads and IronPython picks between them BY ARITY. A probe run under
   CPython 3.9 -- which is what `rhinocode script` defaults to -- is therefore
   asking a different runtime's question. The `#! python 2` shebang on line 1
   is load-bearing: it selects IronPython 2.7, which is what ships inside
   Rhino (the `Apps/_rhino/` rule in CLAUDE.md).

An earlier pass on 2026-08-23 returned all-PASS while calling the SIX-arg
doc-serial overload under CPython. Every check was green and none of it
described production. That is the mistake this file exists to not repeat.

Run:  RhinoCode.exe script DarkSide/tests/get_earth/rhino_l3_progress_meter.py

READING THE RESULT -- the CLI is ASYNCHRONOUS. `rhinocode script` returns as
soon as Rhino has ACCEPTED the script, not when the script has finished, and it
exits 0 either way while printing nothing. So a result file checked in the same
breath as the dispatch is checked BEFORE the script has written it, and the
absence looks exactly like "Rhino never ran it".

This probe takes tens of seconds (an 8 MB download plus ~1000 meter updates).
Poll for the JSON instead of reading it once:

    rhinocode script DarkSide/tests/get_earth/rhino_l3_progress_meter.py
    until [ -f DarkSide/tests/get_earth/l3_progress_meter_result.json ]; do
      sleep 2
    done

Getting this wrong costs more than a retry: on 2026-08-23 the immediate-read
produced four "the script server is dead" conclusions, a wrong root-cause
theory about re-entrant RhinoApp.Wait(), and an unnecessary Rhino restart --
while every script had in fact run and passed. Check the file's mtime before
concluding anything from its absence OR its contents; a stale file from a
previous run is the other half of this trap, so delete it before dispatching.
"""

import os
import sys
import json
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BUTTON_DIR = os.path.join(REPO, "Apps", "_rhino", "Render.tab", "get_earth.button")

# Rhino's EnneadTab startup puts Apps/lib on sys.path; a rhinocode-driven
# script does NOT inherit that. Insert at 0 so an EA_Dist install already on
# the path cannot shadow THIS checkout.
LIB_DIR = os.path.join(REPO, "Apps", "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

JSON_PATH = os.path.join(HERE, "l3_progress_meter_result.json")

# A real GetEarth output, so the chunk loop runs ~1000 times rather than the
# single read a small file would produce. A one-chunk download makes
# "monotonic" vacuously true and never exercises the progress path at all.
GLB_URL = ("https://hl7kkex6nmxztgxo.public.blob.vercel-storage.com/"
           "models/87376420f3b77522ad2e6088b72ced52.glb")

result = {"ok": True, "checks": []}


def check(name, fn):
    try:
        result["checks"].append({"name": name, "ok": True, "value": fn()})
    except Exception as e:
        result["checks"].append({"name": name, "ok": False,
                                 "error": str(e),
                                 "traceback": traceback.format_exc()})
        result["ok"] = False


def main():
    check("runtime", lambda: sys.version.replace("\n", " "))
    check("is_ironpython2", lambda: sys.version_info[0] == 2)

    sys.path.insert(0, BUTTON_DIR)
    import get_earth_utility as U
    check("module_imported", lambda: U.__name__)

    # Which download branch actually ships here. The .NET branch is the one
    # that runs inside Rhino; a CPython probe would exercise urllib instead.
    def _branch():
        from EnneadTab.AI import _common
        return {"use_dotnet": bool(_common._USE_DOTNET)}
    check("download_branch", _branch)

    # --- the real question -------------------------------------------------
    # Drive the REAL meter against REAL RhinoCommon. `_disabled` is the
    # discriminator, not the absence of an exception: the class is built to
    # swallow exactly this failure.
    def _meter():
        total = 8208816
        chunk = 8192
        with U.RhinoProgressMeter() as meter:
            done = 0
            while done < total:
                done = min(total, done + chunk)
                meter.report(done, total)
            shown, disabled = meter._shown, meter._disabled
        return {
            "five_arg_overload_resolved": not disabled,
            "_disabled": disabled,
            "meter_was_shown": shown,
            "down_after_exit": not meter._shown and not meter._prompt_set,
        }
    check("real_meter_five_arg", _meter)

    # An indeterminate phase must produce words, never a bar sliding on a
    # number nobody measured.
    def _status():
        m = U.RhinoProgressMeter()
        m.set_status("Requesting model from the service...")
        out = {"no_bar": not m._shown, "not_disabled": not m._disabled}
        m.hide()
        return out
    check("set_status_shows_no_bar", _status)

    # --- NEGATIVE CONTROL --------------------------------------------------
    # Without this, "not disabled" could be green simply because the flag
    # never moves. Force the failure and prove the check can go red.
    def _control():
        class Boom(object):
            class UI(object):
                class StatusBar(object):
                    @staticmethod
                    def ShowProgressMeter(*a):
                        raise TypeError("no overload matches")

                    @staticmethod
                    def UpdateProgressMeter(*a):
                        pass

                    @staticmethod
                    def HideProgressMeter():
                        pass

            class RhinoApp(object):
                @staticmethod
                def SetCommandPromptMessage(t):
                    pass

                @staticmethod
                def Wait():
                    pass

        m = U.RhinoProgressMeter(rhino_module=Boom)
        m.report(4096, 8192)
        if not m._disabled:
            raise AssertionError(
                "negative control did not trip: _disabled stayed False, so a "
                "green 'real_meter_five_arg' proves nothing")
        return {"disabled_as_expected": True}
    check("negative_control_can_go_red", _control)

    # --- the shipping download path, in the shipping runtime ---------------
    def _download():
        from EnneadTab.AI._common import download_url_to_file
        dest = os.path.join(HERE, "l3_progress_download.tmp")
        seen = []

        def on_progress(done_bytes, total_bytes):
            seen.append((done_bytes, total_bytes))

        try:
            download_url_to_file(GLB_URL, dest, timeout_ms=60000,
                                 on_progress=on_progress)
            size = os.path.getsize(dest)
        finally:
            try:
                os.remove(dest)
            except Exception:
                pass

        dones = [d for d, _ in seen]
        totals = set(t for _, t in seen)
        return {
            "bytes": size,
            "callbacks": len(seen),
            "multi_chunk": len(seen) > 1,
            "monotonic": dones == sorted(dones),
            "last_call_carries_full_size": bool(dones) and dones[-1] == size,
            "content_length_seen": sorted(
                [t for t in totals if t is not None])[:1],
        }
    check("real_download_with_on_progress", _download)


try:
    main()
except Exception as e:
    result["ok"] = False
    result["fatal"] = {"error": str(e), "traceback": traceback.format_exc()}

with open(JSON_PATH, "w") as f:
    json.dump(result, f, indent=2, sort_keys=True)

try:
    print(json.dumps(result, indent=2, sort_keys=True))
except Exception:
    pass
