# -*- coding: utf-8 -*-
__title__ = "ActivateEnneadTab"
__doc__ = """Restore EnneadTab functionality.

Key Features:
- Prefers git repo (developers) over EA_Dist (users)
- System path verification
- Component activation
- Path configuration
- Startup script setup"""
__FONDATION__ = True

import os
import rhinoscriptsyntax as rs
import sys

try:
    import EnneadTab
    is_tab_loaded_originally = True
except:
    is_tab_loaded_originally = False


def add_search_path():
    """Register EnneadTab lib path. Priority:
    1. If this script is running from inside a git repo, use that repo's Apps/lib (active working copy)
    2. Git repo (EnneadTab-OS) developer checkouts under ~/github or ~/github/ennead-llp
    3. EA_Dist (EnneadTab Ecosystem) - for all other users
    """
    home = os.environ.get("USERPROFILE", os.environ.get("HOME", ""))
    _app_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    this_lib = os.path.join(_app_folder, "lib")
    _repo_root = os.path.dirname(_app_folder)

    if os.path.isdir(os.path.join(_repo_root, ".git")) and os.path.isdir(this_lib) and "EA_Dist" not in _repo_root:
        lib_path = this_lib
    else:
        candidate_paths = [
            os.path.join(home, "github", "EnneadTab-OS", "Apps", "lib"),
            os.path.join(home, "github", "ennead-llp", "EnneadTab-OS", "Apps", "lib"),
        ]
        lib_path = this_lib
        for candidate in candidate_paths:
            if os.path.isdir(candidate):
                lib_path = candidate
                break

    for p in list(sys.path):
        if "EnneadTab" in p and "lib" in p and p != lib_path:
            sys.path.remove(p)

    rs.AddSearchPath(lib_path)
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

if not is_tab_loaded_originally:
    add_search_path()

def activate_enneadtab():
    if not is_tab_loaded_originally:
        from EnneadTab import NOTIFICATION
        NOTIFICATION.messenger("EnneadTab Activated")
        from EnneadTab.RHINO import RHINO_RUI
        RHINO_RUI.add_startup_script()


if __name__ == "__main__":
    activate_enneadtab()
