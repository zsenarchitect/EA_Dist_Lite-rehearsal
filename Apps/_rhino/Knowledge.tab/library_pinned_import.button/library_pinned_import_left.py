__title__ = "LibraryPinnedImport"
__doc__ = """Import a library definition at a pinned version.

Key Features:
- Pick a catalog entry and one pinned version from its sidecar history
  ("versions": [{version, diffNote, publishedAt, sourcePath, fileHash}, ...])
- Copy that version's .gh file to a user-chosen folder (file name stamped with
  the version), or open it in Grasshopper
- Rhino-side equivalent of the GH pinned import (cluster/Hops/snippet): the copy
  is a frozen snapshot -- library updates never change it

Ports EnneadTab-For-Grasshopper#52 (pinned-version import as cluster/Hops/snippet)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os
import sys
import json
import shutil
import re
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
                                          title="EnneadTab Library Pinned Import",
                                          message="Pick a definition to import at a pinned version",
                                          button_names=["Pick"],
                                          multi_select=False)
    if not picked:
        return None
    return results[lines.index(picked[0])]


def _pick_version(entry, versions):
    lines = [_version_label(version) for version in versions]
    picked = RHINO_FORMS.select_from_list(lines,
                                          title="EnneadTab Library Pinned Import",
                                          message="Pick the pinned version of '{0}'".format(
                                              entry.get("title") or "(untitled)"),
                                          button_names=["Pick"],
                                          multi_select=False)
    if not picked:
        return None
    return versions[lines.index(picked[0])]


def _sanitize(value):
    return re.sub(r"[^A-Za-z0-9._-]", "_", value or "")


def _copy_to_folder(entry, version, src_path):
    folder = rs.BrowseForFolder(message="Choose a folder for the pinned copy")
    if not folder:
        return
    version_name = _sanitize(str(_get_ci(version, "version") or "pinned"))
    stem = os.path.splitext(os.path.basename(src_path))[0]
    ext = os.path.splitext(src_path)[1] or ".gh"
    dest_name = "{0}_v{1}{2}".format(_sanitize(stem), version_name, ext)
    dest_path = os.path.join(folder, dest_name)
    if os.path.exists(dest_path):
        overwrite = RHINO_FORMS.notification(title="EnneadTab Library Pinned Import",
                                             main_text="File already exists:\n{0}\n\nOverwrite it?".format(dest_path),
                                             button_name="Overwrite")
        if not overwrite:
            return
    try:
        shutil.copy2(src_path, dest_path)
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Copy failed: {0}".format(ex))
        return
    RHINO_FORMS.notification(main_text="Pinned copy saved:\n{0}".format(dest_path),
                             sub_text="Frozen snapshot of version '{0}' -- library updates will not change it.".format(
                                 _get_ci(version, "version") or "?"))


def _open_in_grasshopper(entry, version, src_path):
    # Grasshopper command syntax is hand-unverified in this sandbox; rs.Command
    # returns False on failure and we degrade to a manual instruction.
    rs.Command("_Grasshopper")
    ok = rs.Command('_-GrasshopperOpen "{0}" _Enter'.format(src_path.replace('"', '')))
    if not ok:
        RHINO_FORMS.notification(main_text="Could not open the file in Grasshopper automatically.\n"
                                 "Open this file manually:\n{0}".format(src_path))
    else:
        RHINO_FORMS.notification(main_text="Opened version '{0}' of '{1}' in Grasshopper.".format(
            _get_ci(version, "version") or "?", entry.get("title") or "(untitled)"))


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_pinned_import():
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
        RHINO_FORMS.notification(main_text="No pinned versions are recorded for '{0}'.".format(
            entry.get("title") or "(untitled)"))
        return

    version = _pick_version(entry, versions)
    if version is None:
        return

    src_path = _get_ci(version, "sourcePath") or ""
    src_path = src_path.strip() if isinstance(src_path, str) else ""
    if not src_path:
        RHINO_FORMS.notification(main_text="Version '{0}' has no recorded file path -- add "
                                 "\"sourcePath\" to its sidecar entry to enable pinned import.".format(
                                     _get_ci(version, "version") or "?"))
        return
    if not os.path.isfile(src_path):
        RHINO_FORMS.notification(main_text="The pinned version's file no longer exists:\n{0}".format(src_path))
        return

    action = RHINO_FORMS.select_from_list(["Copy version file to a folder", "Open in Grasshopper"],
                                          title="EnneadTab Library Pinned Import",
                                          message="Import '{0}' at pinned version {1}".format(
                                              entry.get("title") or "(untitled)",
                                              _get_ci(version, "version") or "?"),
                                          button_names=["Go"],
                                          multi_select=False)
    if not action:
        return
    if action[0] == "Copy version file to a folder":
        _copy_to_folder(entry, version, src_path)
    else:
        _open_in_grasshopper(entry, version, src_path)

library_pinned_import()
