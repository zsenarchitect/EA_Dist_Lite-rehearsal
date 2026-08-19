#!/usr/bin/python
# -*- coding: utf-8 -*-
"""InfraWatch_Collect.exe — silent unified collector entry point.

Lives in DarkSide/ (dev-only source). Built into EA_Dist as
`Apps/lib/ExeProducts/InfraWatch_Collect.exe` via EXEMaker, then registered
on every install by `SYSTEM.py.APPS` (the `EnneadTab_OS_Installer_Task`
reconciles the list every 45 min, so new EA_Dist installs auto-register
this scheduled task within an hour of publish).

Runs the unified collector in `Apps/lib/DumpScripts/collectors/collect_all.py`
which POSTs drive-health + machine-spec + events to enneadtab.com/infra/api/ingest/*
in one sweep. Replaces the four legacy collectors (MonitorDriveSilent,
MonitorDriveDecoderSilent, DriveStorageHistory, MonitorBlueScreen) — all of
which were already disabled (active=False) and wrote static HTML
that nobody read.

Silent by design — no console (PyInstaller `console: false`), no popups,
no log files. Failures surface to ErrorDump so they appear in the night-grow
audit pipeline.
"""

import os
import sys


def _find_collectors_dir():
    """Locate the collectors package whether running as .exe or as .py.

    PyInstaller: __file__ is the unpacked _MEI temp dir; we need to walk up
    to find the EnneadTab-OS install root. EnneadTab installs to a known
    location via the installer; fall back to APPDATA-relative path.
    """
    candidates = []
    # Frozen PyInstaller exe
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        # Apps/lib/ExeProducts/InfraWatch_Collect.exe → Apps/lib/DumpScripts/collectors/
        candidates.append(os.path.normpath(os.path.join(
            exe_dir, "..", "DumpScripts", "collectors")))
    # Dev-mode (running .py directly) — DarkSide sibling layout
    candidates.append(os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "Apps", "lib", "DumpScripts", "collectors")))
    # Standard EnneadTab install root (matches ENVIRONMENT.PRIMARY_APP_FOLDER pattern)
    appdata = os.environ.get("APPDATA") or os.environ.get("USERPROFILE") or ""
    if appdata:
        candidates.append(os.path.join(
            appdata, "Ennead+", "EnneadTab", "Apps", "lib", "DumpScripts", "collectors"))
    for c in candidates:
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, "collect_all.py")):
            return c
    return None


def main():
    collectors_dir = _find_collectors_dir()
    if not collectors_dir:
        # Silent failure — log via ErrorDump if reachable, otherwise no-op.
        try:
            import urllib.request
            urllib.request.urlopen(
                "https://enneadtab.com/error-dump/api/ingest",
                data=b'{"source_app":"InfraWatch_Collect","level":"error",'
                     b'"message":"collectors dir not found"}',
                timeout=5)
        except Exception:
            pass
        return 1

    sys.path.insert(0, collectors_dir)
    try:
        import collect_all  # noqa: E402 — sys.path mutation above
        collect_all.main()
        return 0
    except Exception as ex:
        try:
            import json
            import urllib.request
            payload = json.dumps({
                "source_app": "InfraWatch_Collect",
                "level": "error",
                "message": "collect_all.run_all() raised",
                "details": str(ex),
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://enneadtab.com/error-dump/api/ingest",
                data=payload,
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
