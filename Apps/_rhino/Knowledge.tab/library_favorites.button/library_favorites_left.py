__title__ = "LibraryFavorites"
__doc__ = """Pin and unpin catalog definitions as favorites.

Key Features:
- Pin entries so favorites sort first in pin order
- Pin order is preserved across sessions
- Stored in the shared library-settings.json (favoriteEntryIds)"""
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


# Mirrors the Grasshopper JsonLibrarySettingsStore key (GH PR #26):
# camelCase "favoriteEntryIds", pin order, trimmed, deduped.
_FAVORITES_KEY = "favoriteEntryIds"


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


def _normalize_favorites(ids):
    # Mirrors GH NormalizeFavorites: trim, drop blanks, dedupe
    # case-insensitively, keep first occurrence, preserve pin order.
    seen = set()
    out = []
    for raw in ids or []:
        if raw is None:
            continue
        item = str(raw).strip()
        if not item:
            continue
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(item)
    return out


def _get_favorites(settings):
    return _normalize_favorites(settings.get(_FAVORITES_KEY))


def _set_favorites(settings, favorites):
    settings[_FAVORITES_KEY] = _normalize_favorites(favorites)


def _entry_label(entry, pinned_ids):
    title = entry.get("title") or entry.get("id") or "?"
    if (entry.get("id") or "").lower() in pinned_ids:
        return "[PINNED] {0}".format(title)
    return title


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_favorites():
    index_path, settings_path = _catalog.find_catalog_paths()
    if not index_path or not os.path.isfile(index_path):
        rs.MessageBox("No catalog index found yet.\n"
                      "Refresh the Grasshopper library first, then try again.",
                      buttons=0, title=__title__)
        return

    settings_path = _settings_write_path(index_path, settings_path)
    entries = list(_catalog.iter_entries(_catalog.load_index(index_path)))
    if not entries:
        rs.MessageBox("The catalog index is empty.",
                      buttons=0, title=__title__)
        return

    settings = _load_settings(settings_path)

    action = RHINO_FORMS.select_from_list(
        ["Pin entries...", "Unpin entries...", "View pinned entries"],
        title="EnneadTab Library Favorites",
        message="Pin catalog definitions so favorites sort first.",
        button_names=["Go"],
        multi_select=False)
    if not action:
        return

    favorites = _get_favorites(settings)
    pinned_ids = set([f.lower() for f in favorites])
    by_label = {}

    if action == "Pin entries...":
        options = []
        for entry in entries:
            label = _entry_label(entry, pinned_ids)
            suffix = 2
            while label in by_label:
                label = "{0} ({1})".format(_entry_label(entry, pinned_ids),
                                           suffix)
                suffix += 1
            options.append(label)
            by_label[label] = entry
        picked = RHINO_FORMS.select_from_list(
            options,
            title="EnneadTab Library Favorites",
            message="Pick entries to pin (already-pinned ones are skipped).",
            button_names=["Pin"],
            multi_select=True)
        if not picked:
            return
        added = 0
        for label in picked:
            entry = by_label.get(label)
            if entry is None:
                continue
            entry_id = (entry.get("id") or "").strip()
            if entry_id and entry_id.lower() not in pinned_ids:
                favorites.append(entry_id)
                pinned_ids.add(entry_id.lower())
                added += 1
        _set_favorites(settings, favorites)
        _save_settings(settings_path, settings)
        rs.MessageBox("Pinned {0} entr{1}. {2} pinned in total.".format(
            added, "y" if added == 1 else "ies", len(favorites)),
            buttons=0, title=__title__)

    elif action == "Unpin entries...":
        if not favorites:
            rs.MessageBox("No pinned entries yet.",
                          buttons=0, title=__title__)
            return
        by_id = {}
        options = []
        for entry_id in favorites:
            entry = None
            for candidate in entries:
                if (candidate.get("id") or "").lower() == entry_id.lower():
                    entry = candidate
                    break
            label = (entry.get("title") if entry else entry_id) or entry_id
            options.append(label)
            by_id[label] = entry_id
        picked = RHINO_FORMS.select_from_list(
            options,
            title="EnneadTab Library Favorites",
            message="Pick pinned entries to unpin (shown in pin order).",
            button_names=["Unpin"],
            multi_select=True)
        if not picked:
            return
        doomed = set([by_id[label].lower() for label in picked
                      if label in by_id])
        favorites = [f for f in favorites if f.lower() not in doomed]
        _set_favorites(settings, favorites)
        _save_settings(settings_path, settings)
        rs.MessageBox("Unpinned {0} entr{1}. {2} pinned in total.".format(
            len(doomed), "y" if len(doomed) == 1 else "ies", len(favorites)),
            buttons=0, title=__title__)

    else:  # View pinned entries
        if not favorites:
            rs.MessageBox("No pinned entries yet.",
                          buttons=0, title=__title__)
            return
        lines = []
        for i, entry_id in enumerate(favorites, 1):
            title = entry_id
            for entry in entries:
                if (entry.get("id") or "").lower() == entry_id.lower():
                    title = entry.get("title") or entry_id
                    break
            lines.append("{0}. {1}".format(i, title))
        rs.MessageBox("Pinned entries (in pin order):\n\n" + "\n".join(lines),
                      buttons=0, title=__title__)


if __name__ == "__main__":
    library_favorites()
