__title__ = "LibraryRecent"
__doc__ = """Recently-opened catalog definitions (MRU list).

Key Features:
- Newest-first list of opened definitions, capped at 10
- Opening an entry re-records it at the front
- Stored in the shared library-settings.json (recentEntryIds)"""
__is_popular__ = False

import os
import sys
import json
from collections import OrderedDict

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


# Mirrors the Grasshopper LibrarySettings key (GH PR #22): camelCase
# "recentEntryIds", newest first, deduplicated, capped at 10.
_MRU_KEY = "recentEntryIds"
_MRU_CAP = 10


def _settings_write_path(index_path, settings_path):
    # find_catalog_paths() returns None for a settings file that does not
    # exist yet; fall back to the catalog default layout where the settings
    # live next to the index (%LOCALAPPDATA%/EnneadTab/Grasshopper).
    if settings_path:
        return settings_path
    return os.path.join(os.path.dirname(index_path), "library-settings.json")


def _load_settings(settings_path):
    try:
        with open(settings_path, "r") as f:
            return json.load(f, object_pairs_hook=OrderedDict)
    except (IOError, OSError, ValueError):
        return OrderedDict()


def _save_settings(settings_path, settings):
    folder = os.path.dirname(settings_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def _normalize_recent(ids):
    # Mirrors GH NormalizeRecentEntryIds: trim, drop blanks, dedupe
    # (case-sensitive, like GH's Ordinal compare), keep first, cap at 10.
    seen = set()
    out = []
    for raw in ids or []:
        if raw is None:
            continue
        item = str(raw).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= _MRU_CAP:
            break
    return out


def _record_recent(settings, entry_id):
    # Mirrors GH LibrarySettings.RecordRecentEntry: move the id to the
    # front, dedupe, cap. Blank ids are ignored.
    entry_id = (entry_id or "").strip()
    ids = []
    if entry_id:
        ids.append(entry_id)
    for existing in _normalize_recent(settings.get(_MRU_KEY)):
        if len(ids) >= _MRU_CAP:
            break
        if existing != entry_id:
            ids.append(existing)
    settings[_MRU_KEY] = ids
    return ids


def _resolve_entries(entries, ids):
    # Ids that are no longer in the index are skipped (GH does the same
    # when rebuilding its Recent dropdown).
    resolved = []
    for entry_id in ids:
        for entry in entries:
            if (entry.get("id") or "") == entry_id:
                resolved.append(entry)
                break
    return resolved


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_recent():
    index_path, settings_path = _catalog.find_catalog_paths()
    if not index_path or not os.path.isfile(index_path):
        rs.MessageBox("No catalog index found yet.\n"
                      "Refresh the Grasshopper library first, then try again.",
                      buttons=0, title=__title__)
        return

    settings_path = _settings_write_path(index_path, settings_path)
    entries = list(_catalog.iter_entries(_catalog.load_index(index_path)))
    settings = _load_settings(settings_path)
    recent_ids = _normalize_recent(settings.get(_MRU_KEY))

    action = RHINO_FORMS.select_from_list(
        ["Open a recent definition...", "Clear recent list"],
        title="EnneadTab Library Recent",
        message="Recently-opened catalog definitions (newest first).",
        button_names=["Go"],
        multi_select=False)
    if not action:
        return

    if action == "Clear recent list":
        if not recent_ids:
            rs.MessageBox("The recent list is already empty.",
                          buttons=0, title=__title__)
            return
        answer = rs.MessageBox(
            "Clear all {0} recentl{1} opened {2}?".format(
                len(recent_ids),
                "y" if len(recent_ids) == 1 else "ies",
                "entry" if len(recent_ids) == 1 else "entries"),
            buttons=4, title=__title__)
        if answer == 6:  # Yes
            settings[_MRU_KEY] = []
            _save_settings(settings_path, settings)
            rs.MessageBox("Recent list cleared.",
                          buttons=0, title=__title__)
        return

    # Open a recent definition...
    recent = _resolve_entries(entries, recent_ids)
    if not recent:
        rs.MessageBox("No recently-opened definitions yet.\n"
                      "Open a catalog definition and it will show up here.",
                      buttons=0, title=__title__)
        return

    options = []
    by_label = {}
    for entry in recent:
        label = "{0}".format(entry.get("title") or entry.get("id"))
        suffix = 2
        while label in by_label:
            label = "{0} ({1})".format(
                entry.get("title") or entry.get("id"), suffix)
            suffix += 1
        options.append(label)
        by_label[label] = entry
    picked = RHINO_FORMS.select_from_list(
        options,
        title="EnneadTab Library Recent",
        message="Pick a definition to open. It is re-recorded at the front.",
        button_names=["Open"],
        multi_select=False)
    if not picked:
        return

    entry = by_label.get(picked)
    if entry is None:
        return
    entry_path = entry.get("path") or ""
    if entry_path and os.path.isfile(entry_path):
        try:
            os.startfile(entry_path)
        except (OSError, WindowsError):
            rs.MessageBox("Could not open:\n{0}".format(entry_path),
                          buttons=0, title=__title__)
            return
    else:
        rs.MessageBox("File not found:\n{0}".format(entry_path),
                      buttons=0, title=__title__)
        return

    # Recorded on open from the Rhino side too (GH PR #22 behavior).
    _record_recent(settings, entry.get("id"))
    _save_settings(settings_path, settings)


if __name__ == "__main__":
    library_recent()
