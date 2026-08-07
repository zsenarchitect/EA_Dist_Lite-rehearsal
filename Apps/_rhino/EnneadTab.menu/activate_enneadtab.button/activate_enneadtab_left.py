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
    1. Git repo (EnneadTab-OS) - for developers with the repo cloned
    2. EA_Dist (EnneadTab Ecosystem) - for all other users
    """
    home = os.environ.get("USERPROFILE", os.environ.get("HOME", ""))
    git_lib = os.path.join(home, "github", "ennead-llp", "EnneadTab-OS", "Apps", "lib")

    _app_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    dist_lib = os.path.join(_app_folder, "lib")

    if os.path.isdir(git_lib):
        lib_path = git_lib
    else:
        lib_path = dist_lib

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
