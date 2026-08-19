"""
Self-contained EnneadTab OS uninstall teardown.

No imports of SYSTEM / INFRAWATCH / ENVIRONMENT (import side effects).
Only deletes allowlisted user-install paths — never developer github clones.
"""

from __future__ import annotations

import codecs
import configparser
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

PLUGIN_NAME = "EnneadTab"
STATUS_DIR = os.path.join("C:\\", "temp", "{}_Dump".format(PLUGIN_NAME))
STATUS_JSON = os.path.join(STATUS_DIR, "os_uninstaller_status.json")
STATUS_TXT = os.path.join(STATUS_DIR, "os_uninstaller_report.txt")

# shortcut_name -> optional task_name
CLEANUP_ENTRIES = [
    ("EnneadTab_OS_Installer", "EnneadTab_OS_Installer_Task"),
    ("EnneadTab_Cache_Cleaner", None),
    ("EnneadTab_Acc_Auto_Restarter", None),
    ("EnneadTab_Auto_Reconnect_Drives", "EnneadTab_Auto_Reconnect_Drives_Task"),
    ("EnneadTab_Auto_Reconnect_Drives_StartUp", None),
    ("EnneadTab_Rhino8RuiUpdater", "EnneadTab_Rhino8RuiUpdater_Task"),
    ("EnneadTab_InfraWatch_Collect", "EnneadTab_InfraWatch_Collect_Task"),
    ("EnneadTab_InfraWatch_Events", "EnneadTab_InfraWatch_Events_Task"),
    ("EnneadTab_InfraWatch_Heavy", "EnneadTab_InfraWatch_Heavy_Task"),
    ("EnneadTab_Journal_Collect", "EnneadTab_Journal_Collect_Task"),
    ("WhatTheLunch", "WhatTheLunch_Daily"),
    ("AvdResourceMonitor", "AvdResourceMonitor"),
    ("AboutMe_ComputerInfo_Silent", None),
]

LEGACY_TASK_NAMES = [
    "InfraWatch-Heavy",
    "InfraWatch-Events",
]

# Process names (without .exe) — never include Revit or Rhino
KILL_ALLOWLIST = [
    "EnneadTab_OS_Installer",
    "RegisterAutoStartup",
    "ClearRevitRhinoCache",
    "Rhino8RuiUpdater",
    "WhatTheLunch",
    "AccAutoRestarter",
    "AutoReconnectDrive",
    "AvdResourceMonitor",
    "AboutMe_ComputerInfo_Silent",
    "InfraWatch_Collect",
]

LogFn = Callable[[str], None]


def _log(message: str, log: Optional[LogFn] = None) -> None:
    if log:
        log(message)
    else:
        print(message)


def user_profile() -> str:
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


def appdata_roaming() -> str:
    return os.environ.get("APPDATA") or os.path.join(user_profile(), "AppData", "Roaming")


def documents_folder() -> str:
    return os.path.join(user_profile(), "Documents")


def ecosystem_folder() -> str:
    return os.path.join(documents_folder(), "{} Ecosystem".format(PLUGIN_NAME))


def startup_folder() -> str:
    return os.path.join(
        appdata_roaming(),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )


def allowlisted_delete_targets() -> List[str]:
    """User-install paths only. Never includes github clones."""
    profile = user_profile()
    docs = documents_folder()
    appdata = appdata_roaming()
    targets = [
        ecosystem_folder(),
        os.path.join(docs, "{}-Ecosystem".format(PLUGIN_NAME)),
        os.path.join(
            profile,
            "OneDrive - Ennead Architects",
            "Documents",
            "{} Ecosystem".format(PLUGIN_NAME),
        ),
        os.path.join(
            profile,
            "OneDrive - Ennead Architects",
            "Documents",
            "{}-Ecosystem".format(PLUGIN_NAME),
        ),
        os.path.join(appdata, PLUGIN_NAME),
        os.path.join(appdata, "Ennead+", PLUGIN_NAME),
        os.path.join(appdata, "EnneadTabAgent"),
        STATUS_DIR,
    ]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for path in targets:
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            seen.add(norm)
            unique.append(os.path.abspath(path))
    return unique


def is_unsafe_delete_path(path: str) -> Tuple[bool, str]:
    """Return (unsafe, reason). Blocks github clones and any .git working tree."""
    if not path:
        return True, "empty path"
    abs_path = os.path.abspath(path)
    norm = abs_path.replace("/", "\\").lower()

    allow_norm = {
        os.path.normcase(os.path.abspath(p)) for p in allowlisted_delete_targets()
    }
    if os.path.normcase(abs_path) not in allow_norm:
        return True, "not on allowlist"

    if "\\github\\" in norm or norm.endswith("\\github"):
        return True, "path under github"

    if os.path.isdir(os.path.join(abs_path, ".git")):
        return True, "git working tree (.git present)"

    # Refuse deleting a parent that is itself a repo root named EnneadTab-OS
    base = os.path.basename(abs_path).lower()
    if base in ("enneadtab-os", "ennead-llp") and os.path.isdir(
        os.path.join(abs_path, ".git")
    ):
        return True, "developer repo name"

    return False, ""


def path_under_ecosystem(path: str) -> bool:
    if not path:
        return False
    norm = os.path.abspath(path).replace("/", "\\").lower()
    markers = (
        "enneadtab ecosystem",
        "\\ea_dist\\",
        "\\ea_dist/",
    )
    return any(m in norm for m in markers)


def maybe_relocate_and_relaunch() -> bool:
    """
    If running from inside the user ecosystem, copy EXE to temp and relaunch.
    Returns True if this process should exit (relaunch started).
    """
    if not getattr(sys, "frozen", False):
        return False

    exe_path = os.path.abspath(sys.executable)
    if not path_under_ecosystem(exe_path):
        return False

    if "--relocated" in sys.argv:
        return False

    os.makedirs(STATUS_DIR, exist_ok=True)
    dest = os.path.join(STATUS_DIR, "EnneadTab_OS_UnInstaller_relocated.exe")
    try:
        shutil.copy2(exe_path, dest)
    except Exception as exc:
        _log("Failed to copy uninstaller out of ecosystem: {}".format(exc))
        return False

    try:
        subprocess.Popen([dest, "--relocated"], close_fds=True)
        return True
    except Exception as exc:
        _log("Failed to relaunch relocated uninstaller: {}".format(exc))
        return False


def _is_dev_github_path(path):
    norm = os.path.normcase(os.path.abspath(path))
    return "\\github\\" in norm or norm.endswith("\\github")


def should_self_remove_exe(exe_path=None):
    """
    True when this UnInstaller copy is safe to delete after a wipe.
    Never deletes developer github checkouts.
    """
    if not getattr(sys, "frozen", False):
        return False
    exe_path = os.path.abspath(exe_path or sys.executable)
    if _is_dev_github_path(exe_path):
        return False
    if "--relocated" in sys.argv:
        return True
    if path_under_ecosystem(exe_path):
        return True
    status_root = os.path.normcase(os.path.abspath(STATUS_DIR))
    if os.path.normcase(exe_path).startswith(status_root + os.sep) or os.path.normcase(
        os.path.dirname(exe_path)
    ) == status_root:
        return True
    downloads = os.path.normcase(os.path.join(user_profile(), "Downloads"))
    if os.path.normcase(exe_path).startswith(downloads + os.sep):
        return True
    temp = os.path.normcase(os.environ.get("TEMP", "") or os.environ.get("TMP", ""))
    if temp and os.path.normcase(exe_path).startswith(temp + os.sep):
        return True
    return False


def schedule_uninstaller_self_cleanup(log=None):
    """
    After Close: delete relocated/temp/Downloads UnInstaller copies.
    Leaves github/dev and shared Installation package copies alone.
    """
    if not getattr(sys, "frozen", False):
        return False

    targets = []
    exe_path = os.path.abspath(sys.executable)
    if should_self_remove_exe(exe_path):
        targets.append(exe_path)

    relocated = os.path.join(STATUS_DIR, "EnneadTab_OS_UnInstaller_relocated.exe")
    if os.path.isfile(relocated) and not _is_dev_github_path(relocated):
        if os.path.normcase(relocated) not in {os.path.normcase(t) for t in targets}:
            targets.append(relocated)

    if not targets:
        if log:
            log("UnInstaller left in place (shared or developer copy).")
        return False

    # ping delay lets this process exit so Windows can unlock the EXE
    parts = ['ping 127.0.0.1 -n 3 >nul']
    for path in targets:
        parts.append('del /f /q "{}"'.format(path))
    cmd = " & ".join(parts)
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(cmd, shell=True, creationflags=flags, close_fds=True)
        if log:
            log("Scheduled removal of UnInstaller helper.")
        return True
    except Exception as exc:
        if log:
            log("Could not schedule UnInstaller cleanup: {}".format(exc))
        return False


# Exact host app process names (ignore helpers like RevitAccelerator.exe).
REVIT_HOST_NAMES = frozenset({"revit.exe"})
RHINO_HOST_NAMES = frozenset({
    "rhino.exe",
    "rhino5.exe",
    "rhino6.exe",
    "rhino7.exe",
    "rhino8.exe",
    "rhino9.exe",
})


def hosts_running() -> Dict[str, object]:
    """Detect actual Revit / Rhino apps (not accelerators or helpers).

    Returns:
        {
          "revit": bool,
          "rhino": bool,
          "revit_processes": [str, ...],
          "rhino_processes": [str, ...],
        }
    """
    result = {
        "revit": False,
        "rhino": False,
        "revit_processes": [],
        "rhino_processes": [],
    }  # type: Dict[str, object]
    if psutil is None:
        return result
    try:
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name") or ""
            low = name.lower()
            if low in REVIT_HOST_NAMES:
                result["revit"] = True
                result["revit_processes"].append(name)
            elif low in RHINO_HOST_NAMES:
                result["rhino"] = True
                result["rhino_processes"].append(name)
    except Exception:
        pass
    return result


def task_exists(task_name: str) -> bool:
    cmd = 'schtasks /query /tn "{}" >nul 2>&1'.format(task_name)
    return subprocess.run(cmd, shell=True).returncode == 0


def remove_task(task_name: str, log: Optional[LogFn] = None) -> bool:
    if not task_name:
        return True
    if not task_exists(task_name):
        return True
    try:
        subprocess.run(
            'schtasks /delete /f /tn "{}"'.format(task_name),
            shell=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        if log:
            log("Could not turn off one automatic update (continuing)")
        return False


def remove_shortcut(shortcut_name: str, log: Optional[LogFn] = None) -> bool:
    path = os.path.join(startup_folder(), "{}.lnk".format(shortcut_name))
    if not os.path.exists(path):
        return True
    try:
        os.remove(path)
        return True
    except Exception:
        if log:
            log("Could not remove one startup item (continuing)")
        return False


def unregister_self_heal(log: Optional[LogFn] = None) -> List[str]:
    failures = []
    for shortcut_name, task_name in CLEANUP_ENTRIES:
        if not remove_shortcut(shortcut_name, log):
            failures.append("shortcut:{}".format(shortcut_name))
        if task_name and not remove_task(task_name, log):
            failures.append("task:{}".format(task_name))
    for legacy in LEGACY_TASK_NAMES:
        if not remove_task(legacy, log):
            failures.append("task:{}".format(legacy))
    return failures


def kill_allowlisted_processes(log: Optional[LogFn] = None) -> List[str]:
    failures = []
    if psutil is None:
        return failures

    allow = {n.lower() for n in KILL_ALLOWLIST}
    stopped = 0
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            name = proc.info.get("name") or ""
            base = os.path.splitext(name)[0].lower()
            if base not in allow:
                continue
            if proc.info.get("pid") == os.getpid():
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
                stopped += 1
            except Exception:
                try:
                    proc.kill()
                    stopped += 1
                except Exception:
                    failures.append(name)
    except Exception:
        pass
    if stopped and log:
        log("Stopped EnneadTab background helpers")
    return failures


def pyrevit_config_paths() -> List[str]:
    paths = [
        os.path.join(appdata_roaming(), "pyRevit", "pyRevit_config.ini"),
    ]
    program_data = os.getenv("PROGRAMDATA")
    if program_data:
        paths.append(os.path.join(program_data, "pyRevit", "pyRevit_config.ini"))
    return paths


def detach_revit(log: Optional[LogFn] = None) -> bool:
    """Clear userextensions to [] without resolving EnneadTab paths."""
    found_any = False
    for config_path in pyrevit_config_paths():
        if not os.path.exists(config_path):
            continue
        found_any = True
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            if "core" not in config:
                config.add_section("core")
            config.set("core", "userextensions", "[]")
            with codecs.open(config_path, "w", encoding="utf-8") as handle:
                config.write(handle)
        except Exception:
            if log:
                log("Could not update Revit settings (continuing)")
            return False
    if found_any and log:
        log("Removed EnneadTab from Revit")
    return True


def _win_long_path(path: str) -> str:
    r"""Prefix \\?\ so Windows can delete paths longer than MAX_PATH."""
    abs_path = os.path.abspath(path)
    if os.name != "nt":
        return abs_path
    if abs_path.startswith("\\\\?\\"):
        return abs_path
    if abs_path.startswith("\\\\"):
        # UNC: \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


def _clear_readonly(path: str) -> None:
    try:
        mode = os.stat(path).st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(path, mode | stat.S_IWRITE)
    except Exception:
        pass


def _force_remove_file(path: str) -> bool:
    target = _win_long_path(path)
    _clear_readonly(target)
    try:
        os.remove(target)
        return True
    except Exception:
        pass
    # Second try: rename then delete (helps some locked/OneDrive cases)
    try:
        trash = target + ".ennead_delete"
        os.rename(target, trash)
        _clear_readonly(trash)
        os.remove(trash)
        return True
    except Exception:
        return False


def _force_remove_dir(path: str) -> bool:
    target = _win_long_path(path)
    _clear_readonly(target)
    try:
        os.rmdir(target)
        return True
    except Exception:
        return False


def _force_rmtree(path: str, log: Optional[LogFn] = None, passes: int = 3) -> bool:
    """Aggressive bottom-up delete with long-path support and retries."""
    if not os.path.exists(path):
        return True

    failed_files = []
    for attempt in range(1, passes + 1):
        failed_files = []
        # Walk deepest files/dirs first
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                full = os.path.join(root, name)
                if not _force_remove_file(full):
                    failed_files.append(full)
            for name in dirs:
                full = os.path.join(root, name)
                if os.path.isdir(full) and not _force_remove_dir(full):
                    # leave for later pass; contents may still exist
                    pass
        if os.path.isdir(path) and not _force_remove_dir(path):
            pass
        if not os.path.exists(path):
            return True
        if attempt < passes:
            time.sleep(0.4 * attempt)

    # Last resort
    try:
        shutil.rmtree(_win_long_path(path), ignore_errors=True)
    except Exception:
        pass

    if not os.path.exists(path):
        return True

    if failed_files:
        sample = failed_files[:3]
        _log(
            "Some files were still in use and could not be deleted ({} remaining). Examples:".format(
                len(failed_files)
            ),
            log,
        )
        for item in sample:
            _log("  {}".format(item), log)
    return False

def safe_rmtree(path, log=None, preserve_names=None):
    if not os.path.exists(path):
        return True
    unsafe, _reason = is_unsafe_delete_path(path)
    if unsafe:
        return False
    preserve_names = preserve_names or []
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(STATUS_DIR)):
        return _clean_status_dir(preserve_names)
    return _force_rmtree(path, log=None)


def _clean_status_dir(preserve_names=None):
    if not os.path.isdir(STATUS_DIR):
        return True
    preserve = set(preserve_names or []) | {
        os.path.basename(STATUS_JSON),
        os.path.basename(STATUS_TXT),
        "EnneadTab_OS_UnInstaller_relocated.exe",
    }
    ok = True
    for name in os.listdir(STATUS_DIR):
        if name in preserve:
            continue
        full = os.path.join(STATUS_DIR, name)
        try:
            if os.path.isdir(full):
                _force_rmtree(full, log=None)
            else:
                _force_remove_file(full)
        except Exception:
            ok = False
    return ok


def folder_label(path):
    labels = {
        os.path.normcase(os.path.abspath(ecosystem_folder())): "Documents install folder",
        os.path.normcase(os.path.abspath(os.path.join(documents_folder(), "{}-Ecosystem".format(PLUGIN_NAME)))): "Older Documents folder",
        os.path.normcase(os.path.abspath(os.path.join(user_profile(), "OneDrive - Ennead Architects", "Documents", "{} Ecosystem".format(PLUGIN_NAME)))): "OneDrive install folder",
        os.path.normcase(os.path.abspath(os.path.join(user_profile(), "OneDrive - Ennead Architects", "Documents", "{}-Ecosystem".format(PLUGIN_NAME)))): "Older OneDrive folder",
        os.path.normcase(os.path.abspath(os.path.join(appdata_roaming(), PLUGIN_NAME))): "Saved settings",
        os.path.normcase(os.path.abspath(os.path.join(appdata_roaming(), "Ennead+", PLUGIN_NAME))): "Older settings",
        os.path.normcase(os.path.abspath(os.path.join(appdata_roaming(), "EnneadTabAgent"))): "Assistant data",
        os.path.normcase(os.path.abspath(STATUS_DIR)): "Temporary files",
    }
    return labels.get(os.path.normcase(os.path.abspath(path)), "EnneadTab folder")


def delete_user_trees(log=None):
    leftovers = []
    for path in allowlisted_delete_targets():
        if not os.path.exists(path):
            continue
        label = folder_label(path)
        if safe_rmtree(path):
            if log:
                log("Removed {}".format(label))
        elif os.path.exists(path):
            leftovers.append(path)
            if log:
                log("Could not fully remove {} — some files were still in use".format(label))
    return leftovers


def scan_detected_items():
    task_count = 0
    for _, task_name in CLEANUP_ENTRIES:
        if task_name and task_exists(task_name):
            task_count += 1
    for legacy in LEGACY_TASK_NAMES:
        if task_exists(legacy):
            task_count += 1

    shortcut_count = 0
    for shortcut_name, _ in CLEANUP_ENTRIES:
        path = os.path.join(startup_folder(), "{}.lnk".format(shortcut_name))
        if os.path.exists(path):
            shortcut_count += 1

    folders = []
    for path in allowlisted_delete_targets():
        if os.path.exists(path):
            folders.append(folder_label(path))

    return {
        "task_count": task_count,
        "shortcut_count": shortcut_count,
        "folders": folders,
    }


def write_status(payload):
    os.makedirs(STATUS_DIR, exist_ok=True)
    with open(STATUS_JSON, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    status = payload.get("status")
    if status == "success":
        headline = "EnneadTab was removed from this PC."
    elif status == "partial":
        headline = "EnneadTab was mostly removed. A few files were still in use."
    else:
        headline = "Uninstall did not finish completely."

    lines = [
        "EnneadTab UnInstaller",
        "",
        headline,
        "Finished: {}".format(payload.get("end_time") or ""),
        "",
    ]

    leftovers = payload.get("leftovers") or []
    if leftovers:
        lines.append("Still on this PC:")
        for item in leftovers:
            lines.append("  • {}".format(folder_label(item)))
        lines.append("")
        lines.append("What to do next:")
        lines.append("  1. Close Revit, Rhino, and File Explorer windows open to those folders")
        lines.append("  2. Restart Windows if needed")
        lines.append("  3. Run this UnInstaller again")
        lines.append("")

    notes = payload.get("notes") or []
    if notes:
        lines.append("Notes:")
        for note in notes:
            lines.append("  • {}".format(note))
        lines.append("")

    support_log = payload.get("log") or []
    if support_log:
        lines.append("---")
        lines.append("Support details (for Design Technology):")
        for line in support_log:
            lines.append("  {}".format(line))

    with open(STATUS_TXT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def run_uninstall(log=None, rhino_skipped=False):
    start = datetime.now().isoformat()
    log_lines = []

    def _user(msg):
        log_lines.append(msg)
        if log:
            log(msg)

    write_status({
        "status": "running",
        "details": "Uninstall in progress",
        "start_time": start,
        "end_time": None,
        "log": log_lines,
    })

    failures = []

    _user("Turning off automatic EnneadTab updates…")
    failures.extend(unregister_self_heal(log=None))

    _user("Stopping EnneadTab helpers…")
    failures.extend(kill_allowlisted_processes(_user))

    _user("Removing EnneadTab from Revit…")
    if not detach_revit(_user):
        failures.append("revit_detach")

    _user("Removing EnneadTab folders…")
    leftovers = delete_user_trees(_user)

    notes = []
    if rhino_skipped:
        notes.append("Rhino cleanup was skipped — EnneadTab items in Rhino may still appear until cleaned in Rhino.")
    notes.append("If EnneadTab still opens in AutoCAD, remove it from AutoCAD's startup apps.")
    notes.append("pyRevit stays installed; only EnneadTab was removed from it.")
    notes.append("Your project files on network drives were not changed.")
    if leftovers:
        notes.append("Close other apps, restart if needed, then run this UnInstaller again.")

    status = "success" if not leftovers else "partial"
    end = datetime.now().isoformat()
    payload = {
        "status": status,
        "details": "finished",
        "start_time": start,
        "end_time": end,
        "log": log_lines,
        "failures": failures,
        "leftovers": leftovers,
        "notes": notes,
        "report_path": STATUS_TXT,
        "summary": (
            "EnneadTab was removed from this PC."
            if status == "success"
            else "Almost done — a few files were still in use."
        ),
    }
    write_status(payload)
    if status == "success":
        _user("Done. EnneadTab has been removed.")
    else:
        _user("Finished, but a few files were still in use.")
    return payload
