__title__ = "LibraryPalette"
__doc__ = """Keyboard-first quick launcher for the library catalog.

Key Features:
- One filter-as-you-type list combining pinned favorites and recently-opened definitions
- Favorites carry their one-keystroke shelf labels [1]..[9],[0] (GH feature 30)
- Enter opens the chosen definition in Grasshopper; Esc dismisses
- Opened entries are recorded at the front of the recent list

Ports EnneadTab-For-Grasshopper#60 (keyboard-first palette + favorites shelf)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, sys, json, shutil, zipfile, time
from collections import OrderedDict
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path: sys.path.append(_library_dir)
try:
    import catalog
except ImportError:
    catalog = None
from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE
_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")

# Mirrors the Grasshopper JsonLibrarySettingsStore keys (GH PRs #26 and #22):
# camelCase "favoriteEntryIds" (pin order) and "recentEntryIds" (newest first).
_FAVORITES_KEY = "favoriteEntryIds"
_MRU_KEY = "recentEntryIds"
_MRU_CAP = 10
# Mirrors GH LibraryShelfKeys (GH PR #60): digits 1-9,0 activate the 1st-10th favorite.
_MAX_SHELF_SIZE = 10


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
    # Mirrors GH NormalizeFavorites (LibraryFavorites port): trim, drop
    # blanks, dedupe case-insensitively, keep first occurrence, preserve pin order.
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


def _normalize_recent(ids):
    # Mirrors GH NormalizeRecentEntryIds (LibraryRecent port): trim, drop
    # blanks, dedupe (case-sensitive, like GH's Ordinal compare), cap at 10.
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
    # Mirrors GH LibrarySettings.RecordRecentEntry (LibraryRecent port):
    # move the id to the front, dedupe, cap. Blank ids are ignored.
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


def _shelf_key(index):
    # Mirrors GH LibraryShelfKeys.KeyForIndex: 0->"1" ... 8->"9", 9->"0".
    if 0 <= index <= 8:
        return str(index + 1)
    if index == 9:
        return "0"
    return None


def _unique_label(label, used):
    candidate = label
    suffix = 2
    while candidate in used:
        candidate = "{0} ({1})".format(label, suffix)
        suffix += 1
    return candidate


def _build_palette(entries, favorites, recents):
    # One combined list: favorites first (in pin order, with their shelf-key
    # labels), then recents (newest first, not already listed), then the rest
    # of the catalog sorted by title. Returns (options, by_label).
    by_id = {}
    for entry in entries:
        eid = (entry.get("id") or "").strip()
        if eid and eid.lower() not in by_id:
            by_id[eid.lower()] = entry

    combined = []
    used_ids = set()

    shelf_index = 0
    for entry_id in favorites:
        entry = by_id.get(entry_id.lower())
        if entry is None:
            continue
        key = _shelf_key(shelf_index)
        if key is None:
            break
        title = entry.get("title") or entry_id
        combined.append(("[{0}] {1}".format(key, title), entry))
        used_ids.add(entry_id.lower())
        shelf_index += 1

    for entry_id in recents:
        if entry_id.lower() in used_ids:
            continue
        entry = by_id.get(entry_id.lower())
        if entry is None:
            continue
        title = entry.get("title") or entry_id
        combined.append(("[recent] {0}".format(title), entry))
        used_ids.add(entry_id.lower())

    rest = [e for e in entries if (e.get("id") or "").strip().lower() not in used_ids]
    rest.sort(key=lambda e: (e.get("title") or e.get("id") or "").lower())
    for entry in rest:
        title = entry.get("title") or entry.get("id") or "?"
        combined.append((title, entry))

    options = []
    by_label = {}
    for label, entry in combined:
        unique = _unique_label(label, by_label)
        options.append(unique)
        by_label[unique] = entry
    return options, by_label


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_palette():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT); return
    index_path, settings_path = catalog.find_catalog_paths()
    if not index_path or not os.path.isfile(index_path):
        rs.MessageBox("No catalog index found yet.\n"
                      "Refresh the Grasshopper library first, then try again.",
                      buttons=0, title=__title__)
        return

    settings_path = _settings_write_path(index_path, settings_path)
    settings = _load_settings(settings_path)
    entries = list(catalog.iter_entries(catalog.load_index(index_path)))
    if not entries:
        rs.MessageBox("The catalog index is empty.",
                      buttons=0, title=__title__)
        return

    favorites = _normalize_favorites(settings.get(_FAVORITES_KEY))
    recents = _normalize_recent(settings.get(_MRU_KEY))
    options, by_label = _build_palette(entries, favorites, recents)

    picked = RHINO_FORMS.select_from_list(
        options,
        title="EnneadTab Library Palette",
        message="Type to filter \xc2\xb7 Enter opens in Grasshopper \xc2\xb7 Esc dismisses\n"
                "Favorites show their shelf keys [1]..[9],[0]; recents show [recent].",
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

library_palette()
