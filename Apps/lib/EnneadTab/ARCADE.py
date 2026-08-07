# -*- coding: utf-8 -*-
"""Bridge to the EnneadTab-Arcade desktop app (the game you play while Revit syncs).

Revit's UI thread is FROZEN during a sync-to-central or a document open, so nothing running
inside Revit can pop UI mid-wait. The trick (same shape as LastSyncMonitor): the hook that
runs at the START of the wait writes a flag file and spawns a tiny DETACHED watcher, then
returns so the wait can begin. Sixty-odd seconds later the watcher - alive outside Revit -
checks whether the flag is still there and still old enough (the hook that runs at the END
of the wait deletes it). Only a wait that genuinely lasted past the threshold opens the
arcade; a normal quick sync deletes the flag before the watcher ever looks.

CROSS-STACK CONTRACT (this module writes, the watcher + the Electron app read):
    flag file: <local dump folder>/arcade_wait_flag.json
    content:   {"kind": "sync"|"open", "doc": <title>, "ts": <unix seconds>}
    lifecycle: written at wait start, DELETED at wait end. The watcher fires only when the
               file exists AND is older than WAIT_THRESHOLD_SECONDS (a rewrite by a newer
               wait resets the age, so back-to-back syncs cannot inherit a stale timer).

The watcher launches the INSTALLED app only. Never a browser mid-wait - an uninstalled
user gets nothing, not a surprise webpage. IronPython 2.7 file: no f-strings, ASCII only.
"""

import json
import os
import subprocess
import time

try:
    from EnneadTab import CONFIG, ERROR_HANDLE, FOLDER
except Exception:
    import CONFIG  # pyright: ignore
    import ERROR_HANDLE  # pyright: ignore
    import FOLDER  # pyright: ignore

WAIT_THRESHOLD_SECONDS = 60
FLAG_FILE_NAME = "arcade_wait_flag.json"

# Windows process-creation flags so the watcher survives Revit and shows no console.
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def is_hate_arcade():
    """Per-user opt-out, same pattern as REVIT_SYNC.is_hate_sync_monitor."""
    return CONFIG.get_setting("radio_bt_arcade_never", False)


def get_flag_path():
    return FOLDER.get_local_dump_folder_file(FLAG_FILE_NAME)


def get_installed_arcade_exe():
    """Public form of _get_installed_arcade_exe, for callers that want to offer
    the arcade themselves (SYNC_SUMMARY's card action) rather than arm a watcher."""
    return _get_installed_arcade_exe()


def _get_installed_arcade_exe():
    """The NSIS per-user install location, or None. Checked at WATCH time too (the
    PowerShell re-tests existence), but checking here means an uninstalled machine
    never even spawns the watcher."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return None
    for folder_name in ["EnneadTab-Arcade", "enneadtab-arcade"]:
        exe = os.path.join(local_app_data, "Programs", folder_name, "EnneadTab-Arcade.exe")
        if os.path.exists(exe):
            return exe
    return None


@ERROR_HANDLE.try_catch_error(is_silent=True)
def start_wait_watch(kind, doc_title):
    """Call at the START of a long-capable wait (before sync / before open).

    Writes the flag and spawns the detached watcher. Fast and silent by design: it must
    never delay the sync it is decorating, and every failure path is swallowed into the
    error handler - a broken arcade bridge may not break syncing.
    """
    if is_hate_arcade():
        return
    exe = _get_installed_arcade_exe()
    if exe is None:
        return

    flag_path = get_flag_path()
    flag = {"kind": kind, "doc": doc_title or "", "ts": time.time()}
    with open(flag_path, "w") as f:
        json.dump(flag, f)

    # The watcher: sleep past the threshold, then fire ONLY IF the flag still exists and
    # was not rewritten by a newer wait (age check). At most one launch per spawn, and the
    # app itself holds a single-instance lock, so even overlapping watchers cannot stack
    # windows. Plain PowerShell so there is nothing to compile or distribute.
    ps = (
        "Start-Sleep -Seconds {threshold}; "
        "$flag = '{flag}'; "
        "if (Test-Path $flag) {{ "
        "$age = (New-TimeSpan -Start (Get-Item $flag).LastWriteTime -End (Get-Date)).TotalSeconds; "
        "if ($age -ge {min_age}) {{ Start-Process -FilePath '{exe}' }} "
        "}}"
    ).format(
        threshold=WAIT_THRESHOLD_SECONDS + 5,
        flag=flag_path.replace("'", "''"),
        min_age=WAIT_THRESHOLD_SECONDS,
        exe=exe.replace("'", "''"),
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
    )


@ERROR_HANDLE.try_catch_error(is_silent=True)
def end_wait_watch():
    """Call at the END of the wait (after sync / after open). Deleting the flag is what
    tells any pending watcher the wait resolved in time."""
    flag_path = get_flag_path()
    if os.path.exists(flag_path):
        os.remove(flag_path)


if __name__ == "__main__":
    pass
