__title__ = "LibrarySort"
__doc__ = """Sort the local library catalog by title, category, or path.

Key Features:
- Ascending / descending sort on title, category, or path
- Remembers the last sort choice in the library settings
- Shows the sorted catalog in a pick list

Ports EnneadTab-For-Grasshopper#13 (SortBy/SortDirection)."""
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


_SORT_OPTIONS = [
    ("Title (A to Z)", "title", "asc"),
    ("Title (Z to A)", "title", "desc"),
    ("Category (A to Z)", "category", "asc"),
    ("Category (Z to A)", "category", "desc"),
    ("Path (A to Z)", "path", "asc"),
    ("Path (Z to A)", "path", "desc"),
]

_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not "
                     "installed yet. This button needs the shared-catalog-lib PR "
                     "(sen/osrhino-shared-catalog-lib) merged first.")


def _load_entries_and_settings():
    index_path, settings_path = catalog.find_catalog_paths()
    index = catalog.load_index(index_path)
    settings = catalog.load_settings(settings_path) or {}
    entries = list(catalog.iter_entries(index))
    return entries, settings, settings_path


def _remembered_sort(settings):
    prefs = settings.get("rhino", {})
    sort = prefs.get("sort", {})
    return sort.get("key", "title"), sort.get("direction", "asc")


def _save_sort(settings, settings_path, key, direction):
    prefs = settings.get("rhino", {})
    prefs["sort"] = {"key": key, "direction": direction}
    settings["rhino"] = prefs
    folder = os.path.dirname(settings_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(settings_path, "w") as handle:
        json.dump(settings, handle, indent=2, sort_keys=True)


def _display_line(entry):
    title = entry.get("title") or "(untitled)"
    category = entry.get("category") or "Uncategorized"
    return "[{0}] {1}".format(category, title)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_sort():
    if catalog is None:
        RHINO_FORMS.notification(main_text=_MISSING_LIB_TEXT)
        return

    try:
        entries, settings, settings_path = _load_entries_and_settings()
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not load the library index: {0}".format(ex))
        return

    if not entries:
        RHINO_FORMS.notification(main_text="The library index has no entries to sort.")
        return

    key, direction = _remembered_sort(settings)
    labels = [label for label, _key, _direction in _SORT_OPTIONS]
    current = None
    for label, opt_key, opt_direction in _SORT_OPTIONS:
        if opt_key == key and opt_direction == direction:
            current = label
            break

    picked = RHINO_FORMS.select_from_list(labels,
                                          title="EnneadTab Library Sort",
                                          message="Last sort: {0}".format(current or "none yet"),
                                          button_names=["Sort"],
                                          multi_select=False)
    if not picked:
        return

    for label, opt_key, opt_direction in _SORT_OPTIONS:
        if label == picked[0]:
            key, direction = opt_key, opt_direction
            break

    try:
        sorted_entries = list(catalog.sort_entries(entries, key=key, direction=direction))
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Sort failed: {0}".format(ex))
        return

    try:
        _save_sort(settings, settings_path, key, direction)
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Sorted, but the choice could not be remembered: {0}".format(ex))

    lines = [_display_line(entry) for entry in sorted_entries]
    RHINO_FORMS.select_from_list(lines,
                                 title="EnneadTab Library Sort",
                                 message="Sorted by {0} - {1} entries. Choice remembered.".format(picked[0], len(lines)),
                                 button_names=["Done"],
                                 multi_select=False)


if __name__ == "__main__":
    library_sort()
