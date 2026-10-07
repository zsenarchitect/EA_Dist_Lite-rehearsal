__title__ = "LibraryVersions"
__doc__ = """Version history for a library definition: update check + roll back.

Key Features:
- Pick a catalog entry and list its version history from the .ennead.json sidecar
  ("versions": [{version, diffNote, publishedAt, sourcePath, fileHash}, ...]);
  the live version is marked [current]
- Roll back: restores a versioned backup copy of the .gh + its sidecar over the
  live files; the live files are first backed up to .bak copies, and the button
  asks for confirmation before overwriting anything
- Update check: compares the live file's last-modified time against the latest
  version's publishedAt / recorded file and reports whether it looks current

Ports EnneadTab-For-Grasshopper#50 (version history + Update / Roll back)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os
import sys
import json
import shutil
import datetime
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


def _get_ci(mapping, name):
    if not isinstance(mapping, dict):
        return None
    for key, value in mapping.items():
        if isinstance(key, str) and key.lower() == name.lower():
            return value
    return None


def _get_versions(sidecar):
    versions = _get_ci(sidecar, "versions")
    if not isinstance(versions, (list, tuple)):
        return []
    return [v for v in versions if isinstance(v, dict)]


def _version_label(version):
    name = _get_ci(version, "version") or "(unnamed)"
    published = _get_ci(version, "publishedAt") or ""
    date = published[:10] if isinstance(published, str) and published else "(no date)"
    note = _get_ci(version, "diffNote") or ""
    label = "{0} -- {1}".format(name, date)
    if note:
        label += " -- {0}".format(note)
    return label


def _is_current(entry, version):
    """Mirrors GH LibraryVersionHistory.IsCurrent: matches the entry's live
    file path or its recorded file hash."""
    entry_path = (entry.get("path") or "").strip()
    version_path = _get_ci(version, "sourcePath") or ""
    version_path = version_path.strip() if isinstance(version_path, str) else ""
    if entry_path and version_path and entry_path.lower() == version_path.lower():
        return True
    entry_hash = (entry.get("fileHash") or "").strip()
    version_hash = _get_ci(version, "fileHash") or ""
    version_hash = version_hash.strip() if isinstance(version_hash, str) else ""
    return bool(entry_hash and version_hash and entry_hash.lower() == version_hash.lower())


def _latest(versions):
    """Mirrors GH LibraryVersionHistory.Latest: most recent publishedAt wins."""
    best = None
    best_key = ""
    for version in versions:
        published = _get_ci(version, "publishedAt") or ""
        key = published if isinstance(published, str) else ""
        if best is None or key >= best_key:
            best = version
            best_key = key
    return best


def _display_line(entry):
    title = entry.get("title") or "(untitled)"
    category = entry.get("category") or "Uncategorized"
    return "[{0}] {1}".format(category, title)


def _pick_entry(entries):
    query = rs.GetString("Search library definitions (blank = show all)")
    if query is None:
        return None
    results = list(catalog.search_entries(entries, query=query.strip() or None))
    if not results:
        RHINO_FORMS.notification(main_text="No library definitions match the search.")
        return None
    lines = [_display_line(entry) for entry in results]
    picked = RHINO_FORMS.select_from_list(lines,
                                          title="EnneadTab Library Versions",
                                          message="Pick a definition to see its version history",
                                          button_names=["Pick"],
                                          multi_select=False)
    if not picked:
        return None
    return results[lines.index(picked[0])]


def _pick_version(entry, versions):
    lines = []
    for version in versions:
        marker = " [current]" if _is_current(entry, version) else ""
        lines.append(_version_label(version) + marker)
    picked = RHINO_FORMS.select_from_list(lines,
                                          title="EnneadTab Library Versions",
                                          message="Version history for '{0}'".format(entry.get("title") or "(untitled)"),
                                          button_names=["Pick"],
                                          multi_select=False)
    if not picked:
        return None
    return versions[lines.index(picked[0])]


def _roll_back(entry, version):
    title = entry.get("title") or "(untitled)"
    live_path = entry.get("path") or ""
    src_path = _get_ci(version, "sourcePath") or ""
    src_path = src_path.strip() if isinstance(src_path, str) else ""
    if not src_path:
        RHINO_FORMS.notification(main_text="Version '{0}' has no recorded file path -- add "
                                 "\"sourcePath\" to its sidecar entry to enable roll back.".format(
                                     _get_ci(version, "version") or "?"))
        return
    if not os.path.isfile(src_path):
        RHINO_FORMS.notification(main_text="The recorded backup file no longer exists:\n{0}".format(src_path))
        return
    confirmed = RHINO_FORMS.notification(title="EnneadTab Library Versions",
                                         main_text="Roll back '{0}' to version '{1}'?".format(
                                             title, _get_ci(version, "version") or "?"),
                                         sub_text="The live file will be backed up to a .bak copy first.",
                                         button_name="Roll back")
    if not confirmed:
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        if live_path and os.path.isfile(live_path):
            shutil.copy2(live_path, live_path + ".bak-" + stamp)
            live_sidecar = live_path + ".ennead.json"
            if os.path.isfile(live_sidecar):
                shutil.copy2(live_sidecar, live_sidecar + ".bak-" + stamp)
        shutil.copy2(src_path, live_path)
        src_sidecar = src_path + ".ennead.json"
        if os.path.isfile(src_sidecar):
            shutil.copy2(src_sidecar, live_path + ".ennead.json")
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Roll back failed: {0}".format(ex))
        return
    RHINO_FORMS.notification(main_text="Rolled back '{0}' to version '{1}'.".format(
        title, _get_ci(version, "version") or "?"))


def _update_check(entry, versions):
    title = entry.get("title") or "(untitled)"
    live_path = entry.get("path") or ""
    latest = _latest(versions)
    lines = []
    if live_path and os.path.isfile(live_path):
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(live_path)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append("Live file: {0}".format(live_path))
        lines.append("Last modified: {0}".format(mtime))
    else:
        lines.append("Live file is missing: {0}".format(live_path or "(no path)"))
    if latest is not None:
        published = _get_ci(latest, "publishedAt") or "(no date)"
        lines.append("Latest recorded version: {0} ({1})".format(
            _get_ci(latest, "version") or "?", published))
        latest_path = _get_ci(latest, "sourcePath") or ""
        if latest_path and not os.path.isfile(latest_path):
            lines.append("WARNING: latest version's recorded file is missing: {0}".format(latest_path))
        if _is_current(entry, latest):
            lines.append("Status: the live file matches the latest recorded version.")
        else:
            lines.append("Status: the live file does NOT match the latest recorded version -- "
                         "consider rolling back or re-indexing.")
    RHINO_FORMS.notification(title="EnneadTab Library Versions",
                             main_text="Update check for '{0}'".format(title),
                             sub_text="\n".join(lines),
                             width=600,
                             height=250)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_versions():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    try:
        index_path, _ = catalog.find_catalog_paths()
        entries = list(catalog.iter_entries(catalog.load_index(index_path)))
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not load the library index: {0}".format(ex))
        return

    if not entries:
        RHINO_FORMS.notification(main_text="The library index has no entries.")
        return

    entry = _pick_entry(entries)
    if entry is None:
        return

    try:
        sidecar = catalog.load_sidecar(entry)
    except Exception:
        sidecar = {}
    if not isinstance(sidecar, dict):
        sidecar = {}
    versions = _get_versions(sidecar)
    if not versions:
        RHINO_FORMS.notification(main_text="No version history is recorded for '{0}'.".format(
            entry.get("title") or "(untitled)"))
        return

    version = _pick_version(entry, versions)
    if version is None:
        return

    if _is_current(entry, version):
        action = RHINO_FORMS.select_from_list(["Update check"],
                                              title="EnneadTab Library Versions",
                                              message="'{0}' is the current version.".format(_version_label(version)),
                                              button_names=["Go"],
                                              multi_select=False)
    else:
        action = RHINO_FORMS.select_from_list(["Roll back to this version", "Update check"],
                                              title="EnneadTab Library Versions",
                                              message="Picked: {0}".format(_version_label(version)),
                                              button_names=["Go"],
                                              multi_select=False)
    if not action:
        return
    if action[0] == "Roll back to this version":
        _roll_back(entry, version)
    else:
        _update_check(entry, versions)

library_versions()
