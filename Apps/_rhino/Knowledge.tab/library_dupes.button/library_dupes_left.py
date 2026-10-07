# -*- coding: utf-8 -*-
__title__ = "LibraryDupes"
__doc__ = """Find duplicate file content across catalog entries and report the groups.

Rhino port of the Grasshopper library duplicate-content report
(EnneadTab-For-Grasshopper PR #27): entries whose files are byte-identical
but stored at different paths are grouped by content hash so the copies
can be cleaned up.

Key Features:
- SHA-256 content hash per entry file (no mtime/size fingerprints)
- Same-path repeats are collapsed, never reported as duplicates
- Groups ordered by hash; entries within a group ordered by path
- Pick a group to see every copy's path; full report on the command line"""
__is_popular__ = True

import hashlib
import os
import sys

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

# The shared catalog lib lives at Apps/_rhino/Library (added by the
# sen/osrhino-shared-catalog-lib PR). Toolbar scripts do not get _rhino on
# sys.path by themselves, so resolve it from this file's location.
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _rhino_folder not in sys.path:
    sys.path.insert(0, _rhino_folder)

from Library import catalog # pyright: ignore

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION


def _sha256_of_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_entry_path(entry, index_dir):
    path = entry.get("path") or ""
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(index_dir, path)
    if not os.path.isfile(path):
        return None
    return os.path.normpath(path)


def _entry_label(entry):
    return entry.get("id") or entry.get("title") or "?"


def _pick_one(options, title, message):
    picked = RHINO_FORMS.select_from_list(options,
                                          title = title,
                                          message = message,
                                          button_names = ["Show"],
                                          multi_select = False)
    if not picked:
        return None
    if isinstance(picked, (list, tuple)):
        return picked[0] if picked else None
    return picked


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_dupes():
    # find_catalog_paths() never raises; (None, None) means no catalog on disk.
    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        NOTIFICATION.messenger(main_text = "Library catalog not found.\nIndex the Grasshopper library first, then run again.")
        return

    index_dir = os.path.dirname(index_path)
    entries = list(catalog.iter_entries(catalog.load_index(index_path)))

    by_hash = {}
    for entry in entries:
        path = _resolve_entry_path(entry, index_dir)
        if path is None:
            continue
        try:
            digest = _sha256_of_file(path)
        except Exception:
            continue
        by_hash.setdefault(digest, []).append((path, entry))

    groups = []
    for digest in sorted(by_hash.keys()):
        # Same file listed twice (same path) is not a duplicate - collapse first.
        seen = {}
        for path, entry in by_hash[digest]:
            key = os.path.normcase(path)
            if key not in seen:
                seen[key] = (path, entry)
        unique = sorted(seen.values(), key = lambda item: item[0].lower())
        if len(unique) > 1:
            groups.append((digest, unique))

    if not groups:
        NOTIFICATION.messenger(
            main_text = "No duplicate content found.\n{} entries checked.".format(len(entries)))
        return

    total = sum(len(items) for _digest, items in groups)
    print("Library duplicate content: {} group(s), {} entries share content".format(len(groups), total))
    for digest, items in groups:
        print("  [{}]".format(digest[:16]))
        for path, entry in items:
            print("    {} ({})".format(path, _entry_label(entry)))

    options = ["{} - {} copies".format(digest[:12], len(items)) for digest, items in groups]
    picked = _pick_one(options,
                       title = "Library Duplicate Content",
                       message = "{} duplicate group(s), {} entries. Pick one to see every copy's path. Full report printed to the command line.".format(len(groups), total))
    if picked is None:
        return
    digest, items = groups[options.index(picked)]
    detail = "\n".join(["{}  ({})".format(path, _entry_label(entry)) for path, entry in items])
    RHINO_FORMS.notification(
        title = "Duplicate group {}".format(digest[:12]),
        main_text = "{} byte-identical copies:".format(len(items)),
        sub_text = detail,
        width = 700,
        height = 400)


if __name__ == "__main__":
    library_dupes()
