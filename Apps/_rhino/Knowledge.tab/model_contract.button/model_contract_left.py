__title__ = "Model Contract"
__doc__ = """Edit the living model-contract description for a model context key, and propagate it to every Grasshopper catalog sidecar referencing that context.

A model contract describes what a definition expects from the model (for example which layers and user-text keys it reads). Catalog entries carry a modelContextKey; this tool edits the shared description once and writes it into every *.gh.ennead.json / *.ghx.ennead.json sidecar in your library folder whose modelContextKey matches, and stores it in this document's user text too.

Features:
- Pick an existing context key or create a new one
- Multiline editor for the contract description
- Stores the description in the document (user text key ET_ModelContract:<key>)
- Propagates to every matching catalog sidecar in a library folder
- Remembers the library folder between sessions

Rhino-side companion to the GH library's model-contract propagation (feature 17).
"""
__is_popular__ = False

import glob
import json
import os
import time

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.RHINO import ENVIRONMENT, RHINO_FORMS

REGISTRY_NAME = "model_contract_registry.json"
USER_TEXT_PREFIX = "ET_ModelContract:"
LIB_FOLDER_STICKY = "model_contract_library_folder"
NEW_KEY_OPTION = "< New context key... >"
CHANGE_FOLDER_OPTION = "< Change library folder... >"


def _registry_path():
    folder = ENVIRONMENT.DOCUMENT_FOLDER
    if not folder:
        return None
    return os.path.join(folder, REGISTRY_NAME)


def _load_registry():
    path = _registry_path()
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_registry(registry):
    path = _registry_path()
    if not path:
        return False
    try:
        with open(path, "w") as f:
            json.dump(registry, f, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


def _propagate(key, description, lib_folder):
    updated = 0
    unreadable = 0
    for pattern in ("*.gh.ennead.json", "*.ghx.ennead.json"):
        for path in glob.glob(os.path.join(lib_folder, pattern)):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except Exception:
                unreadable += 1
                continue
            if data.get("modelContextKey") != key:
                continue
            data["modelContractDescription"] = description
            try:
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
                updated += 1
            except Exception:
                unreadable += 1
    return updated, unreadable


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def model_contract():
    registry = _load_registry()
    keys = sorted(registry.keys())

    options = keys + [NEW_KEY_OPTION, CHANGE_FOLDER_OPTION]
    choice = RHINO_FORMS.select_from_list(
        options,
        title=__title__,
        message="Pick the model context to edit:")
    if choice is None:
        return

    if choice == CHANGE_FOLDER_OPTION:
        folder = rs.BrowseForFolder(title="Pick the GH library folder holding *.ennead.json sidecars")
        if folder:
            sc.sticky[LIB_FOLDER_STICKY] = folder
            print("Library folder set to: {}".format(folder))
        return

    if choice == NEW_KEY_OPTION:
        key = rs.StringBox(
            "New model context key (e.g. facade-panels):",
            title=__title__)
        if not key:
            return
        key = key.strip()
    else:
        key = choice

    stored = registry.get(key)
    current = stored.get("description", "") if isinstance(stored, dict) else ""
    if not current:
        current = rs.GetDocumentUserText(USER_TEXT_PREFIX + key) or ""

    description = rs.EditBox(
        current,
        "Contract description for '{}':".format(key),
        __title__)
    if description is None:
        return
    description = description.strip()

    entry = stored if isinstance(stored, dict) else {}
    entry["description"] = description
    entry["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    registry[key] = entry
    _save_registry(registry)
    rs.SetDocumentUserText(USER_TEXT_PREFIX + key, description)

    lib_folder = sc.sticky.get(LIB_FOLDER_STICKY)
    if not lib_folder or not os.path.isdir(lib_folder):
        lib_folder = rs.BrowseForFolder(
            title="Pick the GH library folder holding *.ennead.json sidecars")
        if not lib_folder:
            print("Contract saved to this document; skipped sidecar propagation (no library folder).")
            return
    sc.sticky[LIB_FOLDER_STICKY] = lib_folder

    updated, unreadable = _propagate(key, description, lib_folder)
    note = " ({} unreadable skipped)".format(unreadable) if unreadable else ""
    rs.MessageBox(
        "Contract '{}' saved.\nPropagated to {} sidecar(s){}.".format(key, updated, note),
        buttons=0,
        title=__title__)


if __name__ == "__main__":
    model_contract()
