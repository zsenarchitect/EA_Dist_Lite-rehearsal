__title__ = "LibraryCopy"
__doc__ = """Copy a catalog entry's path or JSON to the clipboard.

Key Features:
- Pick an entry from the library catalog
- Copy Path: the entry's source path
- Copy JSON: the entry's full JSON (id, title, description, path, tags,
  category, parameters, sidecar)

Ports EnneadTab-For-Grasshopper#19 (explorer copy actions)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc

import os
import sys
import json

_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path:
    sys.path.append(_library_dir)

try:
    import catalog
except ImportError:
    catalog = None

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE


_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not "
                     "installed yet. This button needs the shared-catalog-lib PR "
                     "(sen/osrhino-shared-catalog-lib) merged first.")


def _to_clipboard(text):
    try:
        import System.Windows.Forms as WinForms
        WinForms.Clipboard.SetText(text or "")
        return True
    except Exception:
        return False


def _safe_sidecar(entry):
    try:
        sidecar = catalog.load_sidecar(entry)
    except Exception:
        return None
    if not isinstance(sidecar, dict):
        return None
    return sidecar


def _display_line(index, entry):
    title = entry.get("title") or "(untitled)"
    category = entry.get("category") or "Uncategorized"
    return "{0}. [{1}] {2}".format(index + 1, category, title)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_copy():
    if catalog is None:
        RHINO_FORMS.notification(main_text=_MISSING_LIB_TEXT)
        return

    try:
        index_path, _settings_path = catalog.find_catalog_paths()
        entries = list(catalog.iter_entries(catalog.load_index(index_path)))
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not load the library index: {0}".format(ex))
        return

    if not entries:
        RHINO_FORMS.notification(main_text="The library index has no entries.")
        return

    lines = [_display_line(i, entry) for i, entry in enumerate(entries)]
    picked = RHINO_FORMS.select_from_list(lines,
                                          title="EnneadTab Library Copy",
                                          message="Pick an entry to copy",
                                          button_names=["Next"],
                                          multi_select=False)
    if not picked:
        return
    entry = entries[lines.index(picked[0])]

    action = RHINO_FORMS.select_from_list(["Copy path", "Copy JSON"],
                                          title="EnneadTab Library Copy",
                                          message="Copy what for '{0}'?".format(entry.get("title") or "(untitled)"),
                                          button_names=["Copy"],
                                          multi_select=False)
    if not action:
        return

    if action[0] == "Copy path":
        path = entry.get("path") or ""
        if _to_clipboard(path):
            RHINO_FORMS.notification(main_text="Copied source path: {0}".format(path))
        else:
            RHINO_FORMS.notification(main_text="Copy failed: could not reach the clipboard.")
        return

    parameters = []
    for param in entry.get("parameters") or []:
        if isinstance(param, dict):
            parameters.append({"name": param.get("name"), "type": param.get("type")})
    payload = {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "description": entry.get("description"),
        "path": entry.get("path"),
        "tags": list(entry.get("tags") or []),
        "category": entry.get("category"),
        "parameters": parameters,
        "sidecar": _safe_sidecar(entry),
    }
    if _to_clipboard(json.dumps(payload, indent=2, sort_keys=True)):
        RHINO_FORMS.notification(main_text="Copied JSON for '{0}' ({1}).".format(entry.get("title"), entry.get("id")))
    else:
        RHINO_FORMS.notification(main_text="Copy failed: could not reach the clipboard.")


if __name__ == "__main__":
    library_copy()
