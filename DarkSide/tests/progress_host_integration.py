"""End-to-end: a real NotificationHost must raise, hold and retire strips.

Run:  .venv/Scripts/python.exe DarkSide/tests/progress_host_integration.py

REQUIRES AN INTERACTIVE DESKTOP SESSION (builds a real QApplication, tray icon
and top-level windows). Not a CI test.

The Dump folder is redirected to a temp sandbox for the progress/capability
modules, so the real inbox and the user's real job files are untouched.

Note on assertion style: the "does not advertise chart" check asserts the
surface list is NON-EMPTY first. Without that it passes vacuously whenever the
capability file is missing -- which is exactly what happened on the first run of
this test, and the vacuous green was more dangerous than the two honest
failures beside it.
"""

import json
import os
import shutil
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOST = os.path.join(_HERE, os.pardir, "exes", "source code", "NotificationHost")
sys.path.insert(0, os.path.normpath(_HOST))

import paths                                   # noqa: E402

_TMP = tempfile.mkdtemp(prefix="hostint_")
paths.get_dump_folder = lambda: _TMP

from PyQt5.QtWidgets import QApplication       # noqa: E402

import capability                              # noqa: E402
import progress_jobs                           # noqa: E402
import NotificationHost as NH                  # noqa: E402

_FAILS = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          ("" if cond else " :: " + detail))
    if not cond:
        _FAILS.append(name)


def write_job(job_id, pid, progress):
    path = os.path.join(progress_jobs.get_jobs_dir(),
                        "job_{}.sexyDuck".format(job_id))
    with open(path, "w") as handle:
        json.dump({
            "job_id": "job_" + job_id, "pid": pid,
            "machine": progress_jobs.this_machine(),
            "title": "Deploying Families", "label": "Door_Single",
            "progress": progress, "counter": 3, "total": 10,
            "start_time": time.time(), "heartbeat": time.time(),
        }, handle)
    return path


def main():
    app = QApplication(sys.argv)
    host = NH.NotificationHost(app)
    app.processEvents()

    cap = capability.read()
    check("capability file written at construction", cap is not None)
    surfaces = (cap or {}).get("surfaces") or []
    check("advertises the progress surface", "progress" in surfaces,
          str(surfaces))
    check("does NOT advertise a chart renderer that does not exist",
          bool(surfaces) and "chart" not in surfaces,
          "surfaces=%s (an empty list would make this vacuous)" % surfaces)

    print("\n-- a live job raises a strip --")
    job_path = write_job("int1", os.getpid(), 35.0)
    host._poll_progress()
    app.processEvents()
    check("strip created", len(host._strips) == 1, str(list(host._strips)))
    strip = list(host._strips.values())[0] if host._strips else None
    check("strip carries the job progress",
          bool(strip) and abs(strip._progress - 35.0) < 0.01)
    check("strip is visible", bool(strip) and strip.isVisible())

    print("\n-- torn write (file briefly absent) must NOT kill the strip --")
    os.remove(job_path)
    host._poll_progress()
    app.processEvents()
    check("survives a single miss", len(host._strips) == 1,
          str(list(host._strips)))

    print("\n-- a second consecutive miss retires it --")
    host._poll_progress()
    app.processEvents()
    check("retired after two misses", len(host._strips) == 0,
          str(list(host._strips)))

    print("\n-- a dead-pid job never renders --")
    write_job("int2", 999999, 50.0)
    host._poll_progress()
    app.processEvents()
    check("dead pid not rendered", len(host._strips) == 0,
          str(list(host._strips)))

    print("\n-- an exception in the progress tick must not kill the daemon --")

    class Exploding(object):
        def poll(self):
            raise RuntimeError("synthetic")

    host._job_store = Exploding()
    try:
        host._poll_progress()
        check("progress exception contained (toast daemon survives)", True)
    except Exception as exc:
        check("progress exception contained (toast daemon survives)", False,
              repr(exc))

    host._clear_strips()
    print("\n" + ("ALL PASS" if not _FAILS else "FAILURES: " + ", ".join(_FAILS)))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
