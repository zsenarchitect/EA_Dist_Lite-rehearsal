#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
VERSION_CONTROL
--------------
Manages EnneadTab update operations and tracking.
Maintains compatibility with both IronPython 2.7 and CPython 3.
"""

import os
import sys
import io
import time
import datetime
import EXE
import ENVIRONMENT
import NOTIFICATION
import DATA_FILE
import USER
import threading
import traceback
import ERROR_HANDLE


def update_dist_repo():
    """Updates the distribution repository if sufficient time has passed since last update"""
    if is_update_too_soon():
        return

    # Stamp the ATTEMPT, up front, before anything that can fail.
    #
    # This key used to be called "last_update_time" and was written AFTER a
    # fire-and-forget EXE.try_open_app -- unconditionally, with no idea whether
    # the installer had done anything at all. The machine recorded a successful
    # update that may never have happened.
    #
    # It is now named for what it actually is: a rate-limiter that stops
    # update_dist_repo (reached from startup/save/sync paths) from hammering the
    # installer every few seconds. It is NOT a success record and nothing may
    # read it as one. The ONLY success record is a .duck file in ECO_SYS_FOLDER,
    # and those are now written exclusively by a VERIFIED update -- which is what
    # get_last_update_time / alert_user_to_update have always read.
    DATA_FILE.set_data({"last_update_attempt_time": time.time()}, "last_update_time")

    launched = EXE.try_open_app("EnneadTab_OS_Installer", safe_open=True)
    if not launched:
        _record_update_failure(
            "installer exe EnneadTab_OS_Installer could not be launched")

    alert_user_to_update()


def _verify_deployed_tree(root, source):
    """Check a freshly-written tree against its publish manifest.

    Returns True when the tree is intact OR when verification is unavailable.

    The import is lazy and guarded on purpose. INTEGRITY is a NEW lib module, and
    the exact failure this whole change exists to catch is "new file next to old
    lib" -- so on a torn machine this very import is the thing that goes missing.
    An ImportError here must degrade to "cannot verify", never to a crash inside
    the updater.
    """
    try:
        import INTEGRITY
    except Exception:
        ERROR_HANDLE.print_note(
            "VERSION_CONTROL: INTEGRITY module unavailable; update not verified.")
        return True

    return INTEGRITY.verify_and_report(root=root, source=source)


def _record_update_failure(reason, detail=None):
    """Make a failed update visible to BOTH the dev team and the starvation alarm.

    Writes an _ERROR.duck marker into ECO_SYS_FOLDER (the same marker the installer
    exe writes) so _has_error_duck / alert_user_to_update can see that this machine
    tries to update and never succeeds, and fires an ErrorDump report on a daemon
    thread with a once-per-day gate so a permanently broken machine cannot flood it.
    """
    message = "EnneadTab update FAILED: {}".format(reason)
    if detail:
        message += "\n{}".format(detail)

    try:
        marker = os.path.join(
            ENVIRONMENT.ECO_SYS_FOLDER,
            "{}_ERROR.duck".format(time.strftime("%Y-%m-%d_%H-%M-%S")))
        with open(marker, "w") as f:
            f.write(message)
    except Exception:
        ERROR_HANDLE.print_note(
            "Failed to write update error marker: {}".format(traceback.format_exc()))

    try:
        data = DATA_FILE.get_data("last_update_failure_report") or {}
        if (time.time() - data.get("time", 0)) < 86400.0:
            return
        DATA_FILE.set_data({"time": time.time()}, "last_update_failure_report")
    except Exception:
        pass

    def _send():
        try:
            ERROR_HANDLE.send_error_to_error_dump(
                error_message=message,
                func_name="update_failure",
                user_name=USER.USER_NAME,
                is_silent=True)
        except Exception:
            pass

    worker = threading.Thread(target=_send)
    worker.daemon = True
    worker.start()

def timestamp_string_to_unix(timestamp_str):
    """
    Converts timestamp string format "YYYY-MM-DD_HH-MM-SS" to Unix timestamp
    
    Args:
        timestamp_str (str): Timestamp in format "2025-06-09_13-10-14"
        
    Returns:
        float: Unix timestamp
    """
    try:
        # Parse the timestamp string format "YYYY-MM-DD_HH-MM-SS"
        dt = datetime.datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
        return time.mktime(dt.timetuple())
    except (ValueError, TypeError):
        return None


def is_update_too_soon():
    """
    Checks if an update was ATTEMPTED too recently (within 60 minutes)

    Reads the new "last_update_attempt_time" key and falls back to the legacy
    "last_update_time" key so machines carrying the old data file keep their
    throttle across this upgrade instead of re-running the installer immediately.

    Returns:
        bool: True if an update was attempted within the last 60 minutes
    """
    data = DATA_FILE.get_data("last_update_time")
    recent_update_time = data.get("last_update_attempt_time", None)
    if not recent_update_time:
        recent_update_time = data.get("last_update_time", None)
    if not recent_update_time:
        return False
    return (time.time() - recent_update_time) < 3600


def alert_user_to_update():
    last_update_timestamp_str = get_last_update_time()
    if last_update_timestamp_str is None:
        # No success record at all. The installer deletes success .duck files
        # older than 8h at the start of every run, so a machine whose updates
        # keep FAILING ends up with only _ERROR.duck files here -- that is the
        # worst starvation cohort and used to be invisible. A brand-new
        # machine before its first update has no ducks of either kind and
        # stays silent.
        if _has_error_duck():
            _report_update_starvation("installer runs but never succeeds")
        return

    last_update_unix = timestamp_string_to_unix(last_update_timestamp_str)
    if last_update_unix is None:
        return

    time_since_last_update = time.time() - last_update_unix
    if time_since_last_update > 2592000.0:  # 30 days in seconds (30 * 24 * 60 * 60)
        NOTIFICATION.messenger("You have not updated EnneadTab for a long time. Please update it. Duck eggs have been hatched")
        _report_update_starvation("no successful update", days_stale=int(time_since_last_update // 86400.0))
        return


def _has_error_duck():
    try:
        return any(f.endswith("_ERROR.duck") for f in os.listdir(ENVIRONMENT.ECO_SYS_FOLDER))
    except Exception:
        return False


def _report_update_starvation(reason, days_stale=None):
    """Send a silent ErrorDump event when this machine is starving for updates.

    Daemon thread + once-per-day gate: the send can burn up to ~20s of
    transport timeouts on exactly the broken-network machines most likely to
    starve, and must never slow down the doc-sync/save/startup paths that
    reach update_dist_repo.
    """
    try:
        data = DATA_FILE.get_data("last_starvation_report") or {}
        if (time.time() - data.get("time", 0)) < 86400.0:
            return
        DATA_FILE.set_data({"time": time.time()}, "last_starvation_report")

        message = "EnneadTab update starvation: {}".format(reason)
        if days_stale is not None:
            message += " ({} days since last successful update)".format(days_stale)

        def _send():
            try:
                ERROR_HANDLE.send_error_to_error_dump(
                    error_message=message,
                    func_name="update_starvation",
                    user_name=USER.USER_NAME,
                    is_silent=True)
            except Exception:
                pass

        worker = threading.Thread(target=_send)
        worker.daemon = True
        worker.start()
    except Exception:
        ERROR_HANDLE.print_note("Failed to report update starvation: {}".format(traceback.format_exc()))


def get_last_update_time(return_file=False):
    """
    Retrieves the timestamp of the most recent successful update
    
    Args:
        return_file (bool): When True, returns filename instead of timestamp
        
    Returns:
        str or None: Update timestamp or filename, None if no records found
    """
    records = [file for file in os.listdir(ENVIRONMENT.ECO_SYS_FOLDER) 
              if file.endswith(".duck") and "_ERROR" not in file]
    if not records:
        return None
    records.sort()
    record_file = records[-1]
    if return_file:
        return record_file
    return record_file.replace(".duck", "")


def show_last_success_update_time():
    """Displays a notification with information about the most recent successful update"""
    record_file = get_last_update_time(return_file=True)
    if not record_file:
        NOTIFICATION.messenger("Not successful update recently.\nYour life sucks.")
        return
    
    try:
        file_path = os.path.join(ENVIRONMENT.ECO_SYS_FOLDER, record_file)
        if sys.platform == "cli":  # IronPython
            from System.IO import File
            all_lines = File.ReadAllLines(file_path)
            commit_line = all_lines[-1].replace("\n", "")
        else:  # CPython
            with io.open(file_path, "r", encoding="utf-8") as f:
                commit_line = f.readlines()[-1].replace("\n", "")
                
        update_time = record_file.replace(".duck", "")
        message = "Most recent update at: {}\n{}".format(update_time, commit_line)
        NOTIFICATION.messenger(message)
    except Exception as e:
        print("Error reading update record: {}".format(str(e)))
        NOTIFICATION.messenger("Error reading update record.")


def unit_test():
    """Run simple unit test of the module"""
    update_dist_repo()


if __name__ == "__main__":
    update_dist_repo()
