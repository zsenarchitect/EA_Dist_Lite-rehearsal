# -*- coding: utf-8 -*-
import os
import sys
import time
import rhinoscriptsyntax as rs
import Rhino # pyright: ignore


def add_search_path():
    """Register EnneadTab lib path. Priority:
    1. Git repo (EnneadTab-OS) - for developers with the repo cloned
    2. EA_Dist (EnneadTab Ecosystem) - for all other users

    2026-04-08: Added git repo priority so developers always load
    the latest code from their working copy, not the stale EA_Dist.
    """
    # Primary: git repo at ~/github/ennead-llp/EnneadTab-OS/Apps/lib
    # Use USERPROFILE (not HOME) to avoid enterprise $HOME=/p/ bug
    home = os.environ.get("USERPROFILE", os.environ.get("HOME", ""))
    git_lib = os.path.join(home, "github", "ennead-llp", "EnneadTab-OS", "Apps", "lib")

    # Fallback: EA_Dist (where this script is running from)
    _app_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    dist_lib = os.path.join(_app_folder, "lib")

    # Pick the best available source
    if os.path.isdir(git_lib):
        lib_path = git_lib
    else:
        lib_path = dist_lib

    # Remove any stale EnneadTab lib paths, then add the chosen one at front
    for p in list(sys.path):
        if "EnneadTab" in p and "lib" in p and p != lib_path:
            sys.path.remove(p)

    rs.AddSearchPath(lib_path)
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


time_start = time.time()
add_search_path()


__title__ = "GetLatest"
__doc__ = """Update EnneadTab to latest version.

Key Features:
- Prefers git repo (developers) over EA_Dist (users)
- Automatic version detection
- Core module updates
- System path configuration
- Component synchronization
- Installation verification"""
__FONDATION__ = True
from EnneadTab import ERROR_HANDLE
from EnneadTab import VERSION_CONTROL, NOTIFICATION
from EnneadTab.RHINO import RHINO_RUI, RHINO_ALIAS

# @LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def get_latest(is_silient=False):
    print("get_latest called")

    RHINO_ALIAS.register_alias_set()
    print("alias set registered")
    RHINO_RUI.update_my_rui()
    print("rui updated")
    RHINO_RUI.add_startup_script()
    print("startup script added")

    if not is_silient:
        NOTIFICATION.messenger("Latest EnneadTab-For-Rhino Loaded")
    else:
        print("Latest EnneadTab-For-Rhino Loaded")

    # Update EA_Dist in the background
    try:
        VERSION_CONTROL.update_dist_repo()
    except Exception as e:
        print("Error updating EA dist")
        print(e)


if __name__ == "__main__":
    get_latest()
