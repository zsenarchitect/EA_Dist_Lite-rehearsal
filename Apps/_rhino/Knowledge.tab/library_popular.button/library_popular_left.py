__title__ = "LibraryPopular"
__doc__ = """Catalog definitions ranked by usage.

Key Features:
- Reads the Grasshopper usage store (library-usage.json)
- Ranked by opens, then solves
- Display only: never writes usage data"""
__is_popular__ = False

import os
import sys
import json

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE


# Shared catalog lib (PR #283 sen/osrhino-shared-catalog-lib):
# Apps/_rhino/Library/catalog.py. The documented import is
# "from Library import catalog"; Apps/_rhino is added to sys.path here
# because the lib PR does not touch startup.py.
_RHINO_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _RHINO_DIR not in sys.path:
    sys.path.insert(0, _RHINO_DIR)
try:
    from Library import catalog as _catalog # pyright: ignore
except ImportError:
    # Fallback for a flat layout: import catalog.py directly.
    _LIBRARY_DIR = os.path.join(_RHINO_DIR, "Library")
    if _LIBRARY_DIR not in sys.path:
        sys.path.insert(0, _LIBRARY_DIR)
    import catalog as _catalog # pyright: ignore


# Mirrors the Grasshopper LibraryUsageStore file format (GH PR #31):
# a JSON array of {entryId, opens, solves, errors} (camelCase).
_USAGE_FILE_NAME = "library-usage.json"


def _usage_store_candidates(settings_path):
    candidates = []
    folder = os.path.dirname(settings_path) if settings_path else ""
    if folder:
        candidates.append(os.path.join(folder, _USAGE_FILE_NAME))
    # GH default: %AppData%/EnneadTab.Grasshopper/library-usage.json
    app_data = os.environ.get("APPDATA") or ""
    if app_data:
        candidates.append(os.path.join(
            app_data, "EnneadTab.Grasshopper", _USAGE_FILE_NAME))
    return candidates


def _load_usage_counters():
    # Like GH's LibraryUsageStore.Load: missing file -> empty store;
    # malformed JSON -> empty store so a corrupt file never breaks this.
    _, settings_path = _catalog.find_catalog_paths()
    for path in _usage_store_candidates(settings_path):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (IOError, OSError, ValueError):
            return []
        return _normalize_counters(data)
    return []


def _normalize_counters(data):
    counters = []
    if isinstance(data, dict):
        # Tolerate an id-keyed object as well as the GH array shape.
        items = []
        for entry_id, value in data.items():
            if isinstance(value, dict):
                item = dict(value)
                item["entryId"] = entry_id
                items.append(item)
        data = items
    if not isinstance(data, list):
        return []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry_id = item.get("entryId")
        if not entry_id:
            continue
        counters.append({
            "entryId": str(entry_id),
            "opens": _non_negative(item.get("opens")),
            "solves": _non_negative(item.get("solves")),
            "errors": _non_negative(item.get("errors")),
        })
    # Usage-based ranking: opens first, then solves, then id for stability.
    counters.sort(key=lambda c: (-c["opens"], -c["solves"], c["entryId"]))
    return counters


def _non_negative(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_popular():
    index_path, _ = _catalog.find_catalog_paths()
    entries = []
    if index_path and os.path.isfile(index_path):
        entries = list(_catalog.iter_entries(_catalog.load_index(index_path)))
    by_id = {}
    for entry in entries:
        entry_id = entry.get("id")
        if entry_id and entry_id not in by_id:
            by_id[entry_id] = entry

    counters = _load_usage_counters()
    if not counters:
        rs.MessageBox("No usage data found yet.\n"
                      "Usage is recorded when definitions are opened or "
                      "solved from the Grasshopper library.",
                      buttons=0, title=__title__)
        return

    options = []
    for rank, counter in enumerate(counters, 1):
        entry = by_id.get(counter["entryId"])
        if entry is not None:
            title = entry.get("title") or counter["entryId"]
        else:
            title = "{0} (not in catalog)".format(counter["entryId"])
        options.append(
            "{0}. {1} -- {2} opens, {3} solves, {4} errors".format(
                rank, title,
                counter["opens"], counter["solves"], counter["errors"]))

    RHINO_FORMS.select_from_list(
        options,
        title="EnneadTab Library Popular",
        message="Catalog definitions ranked by usage (display only).",
        button_names=["Close"],
        multi_select=False)


if __name__ == "__main__":
    library_popular()
