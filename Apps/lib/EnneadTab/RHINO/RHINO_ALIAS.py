# -*- coding: utf-8 -*-

import os

import ENVIRONMENT
import DATA_FILE


import rhinoscriptsyntax as rs
import Rhino # pyright: ignore


# Developer-machine detection. If a live source repo exists on this machine,
# every alias we register is rewritten to point at the repo instead of EA_Dist,
# so future Rhino sessions boot from the source of truth without waiting on
# AutoDist publish cycles. End users lack these folders entirely -- the search
# returns None in microseconds and alias registration falls through to the
# EA_Dist path that was walked. Keep the parent/org lists in sync with
# DarkSide/RuiWriter/MacroHandler.py so pushbutton macros and alias
# registration resolve to the same tree.
_DEV_PARENT_FOLDERS = ["github", "dev-repo", "duck-repo", "design-repo"]
_DEV_ORG_FOLDERS = ["", "ennead-llp", "Personal", "LakeHouse-LLP", "Toni-LLP", "TimeBank-llp", "zsenarchitect"]
_DEV_REPO_NAME = "EnneadTab-OS"


def _find_dev_apps_root():
    """Return the absolute path of <dev_repo>/Apps/ if a dev checkout exists, else None.
    Result is cached at module level after first call since it can't change within a session.
    """
    userprofile = os.environ.get("USERPROFILE", "")
    if not userprofile:
        return None
    for parent in _DEV_PARENT_FOLDERS:
        for org in _DEV_ORG_FOLDERS:
            parts = [userprofile, parent]
            if org:
                parts.append(org)
            parts.append(_DEV_REPO_NAME)
            parts.append("Apps")
            candidate = os.path.join(*parts)
            if os.path.isdir(candidate):
                return candidate
    return None


_DEV_APPS_ROOT = _find_dev_apps_root()


def _prefer_dev_path(full_path):
    """If full_path lives under Apps/, return the dev-repo equivalent when one exists.
    Otherwise return full_path unchanged. Idempotent: calling this on an already-dev
    path is a no-op. Safe to call in tight loops.
    """
    if _DEV_APPS_ROOT is None:
        return full_path
    # Split on the literal "Apps\" segment -- both EA_Dist and repo share the same
    # subtree layout below Apps/, so the remainder is directly transplantable.
    sep = os.sep + "Apps" + os.sep
    if sep not in full_path:
        return full_path
    rel = full_path.split(sep, 1)[1]  # "_rhino\\foo\\bar.py" or "lib\\EnneadTab\\X.py"
    dev_candidate = os.path.join(_DEV_APPS_ROOT, rel)
    if os.path.exists(dev_candidate):
        return dev_candidate
    return full_path


def remove_invalid_alias():
    exisitng_alias = rs.AliasNames()
    for alias in exisitng_alias:
        exisiting_macro = rs.AliasMacro(alias)
        if "RunPythonScript" not in exisiting_macro:
            continue
        exisiting_full_path = exisiting_macro.split('_-RunPythonScript "')[1].split('"')[0]
        if not os.path.exists(exisiting_full_path):
            rs.DeleteAlias(alias)

def register_alias_set():
    remove_invalid_alias()

    exisitng_alias = rs.AliasNames()
    
    data = DATA_FILE.get_data(ENVIRONMENT.KNOWLEDGE_RHINO_FILE, is_local=True)

    for root, dirs, files in os.walk(ENVIRONMENT.RHINO_FOLDER):
        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                # print (full_path)
                # print(full_path.split("_rhino\\")[1])

                
                if full_path.split(ENVIRONMENT.RHINO_FOLDER_KEYNAME + "\\")[1] not in data.keys():
                    continue
                


                alias_list = data.get(full_path.split(ENVIRONMENT.RHINO_FOLDER_KEYNAME + "\\")[1]).get('alias')


                if not isinstance(alias_list, list):
                    alias_list = [alias_list]

                for alias in alias_list:
                    if not alias:
                        continue

                    # Determine the actual alias name that will be registered
                    if alias == alias.upper():
                        actual_alias = alias
                    else:
                        actual_alias = ENVIRONMENT.PLUGIN_ABBR + "_" + alias

                    # Resolve the target path BEFORE the skip-check. On dev machines this
                    # rewrites EA_Dist paths to repo paths; on end-user machines it's a no-op.
                    # We compare the EXISTING alias against the RESOLVED path so that a stale
                    # EA_Dist-pointing alias gets upgraded to a repo-pointing one.
                    resolved_path = _prefer_dev_path(full_path)

                    # Check if alias already exists
                    if rs.IsAlias(actual_alias):
                        existing_macro = rs.AliasMacro(actual_alias)
                        # If it's already pointing to the RESOLVED path, skip (idempotent no-op)
                        if resolved_path in existing_macro:
                            continue
                        # If user has a personal alias (not EA_ prefixed) with same name, skip to avoid overwriting
                        if ENVIRONMENT.PLUGIN_ABBR + "_" not in actual_alias:
                            continue
                        # For EA_ aliases, we'll update them if they point to a different script

                    script_content = '! _-RunPythonScript "{}"'.format(resolved_path)
                    if os.path.exists(resolved_path):
                        if alias == alias.upper():
                            rs.AddAlias(alias, script_content)
                        else:
                            rs.AddAlias(ENVIRONMENT.PLUGIN_ABBR + "_" + alias, script_content)


def register_shortcut(key, command):
    """for full list
    https://developer.rhino3d.com/api/rhinocommon/rhino.applicationsettings.shortcutkey
    """
    keyboard_setting = Rhino.ApplicationSettings.ShortcutKeySettings
    keyboard_setting.SetMacro(Rhino.ApplicationSettings.ShortcutKey[key], 
                              command)

    
