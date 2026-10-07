# -*- coding: utf-8 -*-
__title__ = "LibraryAddress"
__doc__ = """Show a library entry's address stamp and check it for updates.

Pick a catalog entry to see its library address (entry id plus catalog
version — the revision entry the Grasshopper importer stamps onto documents)
and run update recognition: the catalog's recorded file hash is compared
against the file on disk, flagging local changes with an asterisk, and an
optional "version you have" answer produces the "v3 available — you have v2*"
report. Ports the address stamp from the Grasshopper library explorer
(EnneadTab-For-Grasshopper PR #46).

Reads the shared Grasshopper definition catalog through
Apps/_rhino/Library/catalog.py."""
__is_popular__ = False

import os
import sys

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION

try:
    import hashlib
except ImportError:
    hashlib = None


# Shared definition-catalog reader, added by the sibling PR
# `sen/osrhino-shared-catalog-lib` as Apps/_rhino/Library/catalog.py.
# A toolbar script runs with its own .button folder on sys.path, not the
# _rhino root, so anchor the Library package to this file's location first
# (the same sys.path.append-then-import shape .button scripts already use
# for sibling-folder modules; the lib PR's README documents
# `from Library import catalog`).
_BUTTON_DIR = os.path.dirname(os.path.abspath(__file__))
_RHINO_DIR = os.path.normpath(os.path.join(_BUTTON_DIR, os.pardir, os.pardir))
if _RHINO_DIR not in sys.path:
    sys.path.append(_RHINO_DIR)

try:
    from Library import catalog as _catalog
    _CATALOG_IMPORT_ERROR = None
except ImportError as _import_error:
    _catalog = None
    _CATALOG_IMPORT_ERROR = str(_import_error)


def _utext(value):
    """Coerce to unicode for report building (IronPython 2.7)."""
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if isinstance(value, bool):
        return u"True" if value else u"False"
    if isinstance(value, float):
        if value.is_integer():
            return unicode(int(value))
        return unicode(repr(value))
    if isinstance(value, (int, long)):
        return unicode(value)
    try:
        return unicode(value)
    except Exception:
        pass
    try:
        return str(value).decode("utf-8", "replace")
    except Exception:
        return u"?"


def _ci_get(mapping, name):
    """Case-insensitive dict read, mirroring the shared lib's convention:
    the GH index JSON is camelCase, but accept any casing."""
    if not isinstance(mapping, dict):
        return None
    wanted = name.lower()
    for key in mapping:
        try:
            if key.lower() == wanted:
                return mapping[key]
        except AttributeError:
            continue
    return None


def _load_catalog():
    """Returns (entries, raw_index, error_message)."""
    if _catalog is None:
        return (None, None,
                u"The shared library catalog reader is not available.\n\n{0}\n\n"
                u"Merge the shared-catalog lib PR first, then retry.".format(
                    _utext(_CATALOG_IMPORT_ERROR)))
    try:
        index_path, _settings_path = _catalog.find_catalog_paths()
    except Exception as err:
        return (None, None,
                u"Could not resolve the catalog location: {0}".format(_utext(err)))
    if not index_path:
        return (None, None,
                u"No Grasshopper library index was found.\n\n"
                u"Expected %LOCALAPPDATA%\\EnneadTab\\Grasshopper\\library-index.json "
                u"(written by the EnneadTab for Grasshopper plugin's Refresh), or set "
                u"ENNEAD_LIBRARY_INDEX to point at one.")
    index = _catalog.load_index(index_path)
    entries = _catalog.iter_entries(index)
    if not entries:
        return (None, None,
                u"The library index at\n{0}\ncontains no entries. Run Refresh in the "
                u"Grasshopper library explorer first.".format(_utext(index_path)))
    entries = _catalog.sort_entries(entries, key="title", direction="asc")
    return (entries, index, None)


def _entry_display_title(entry):
    title = entry.get("title")
    if title:
        return _utext(title)
    return _utext(entry.get("id")) or u"(untitled)"


def _build_labels(entries, suffix_fn=None):
    titles = [_entry_display_title(entry) for entry in entries]
    counts = {}
    for title in titles:
        counts[title] = counts.get(title, 0) + 1
    labels = []
    for entry, title in zip(entries, titles):
        label = title
        if counts[title] > 1:
            label = u"{0} [{1}]".format(title, _utext(entry.get("id")) or u"?")
        if suffix_fn is not None:
            suffix = suffix_fn(entry)
            if suffix:
                label = u"{0} ({1})".format(label, suffix)
        labels.append(label)
    return labels


def _pick_entry(entries, labels, message, dialog_title):
    picked_label = RHINO_FORMS.select_from_list(
        labels,
        title=dialog_title,
        message=message,
        button_names=["Show"],
        width=650,
        height=550,
        multi_select=False)
    if not picked_label:
        return None
    for entry, label in zip(entries, labels):
        if label == picked_label:
            return entry
    return None


def _show_report(title, text):
    rs.MessageBox(message=text, buttons=0, title=title)


def _raw_entry(index, entry_id):
    """Raw index row for a normalized entry id (for fields the shared lib
    does not normalize, e.g. version)."""
    raw_entries = _ci_get(index, "entries") or []
    wanted = _utext(entry_id)
    for raw in raw_entries:
        if isinstance(raw, dict) and _utext(_ci_get(raw, "id")) == wanted:
            return raw
    return None


# --- Library address stamp / update recognition (ports GH PR #46) -----------
# LibraryAddressStamp: the (entry id, version) revision entry identifying
# where a definition came from. LibraryVersions: best-effort ordering of
# human version strings. LibraryAddressUpdate: the "v3 available — you have
# v2*" report, with "*" marking local changes.

_CONTENT_HASH_MAX_BYTES = 32 * 1024 * 1024


def _parse_version(text):
    """int components of a human version string, or None when unparseable
    (mirrors LibraryVersions: leading v/V ignored, numeric dotted
    components compare numerically)."""
    core = _utext(text).strip()
    while core[:1].lower() == u"v":
        core = core[1:]
    core = core.strip()
    if not core:
        return None
    parts = []
    for chunk in core.split(u"."):
        digits = u""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            return None
        try:
            parts.append(int(digits))
        except ValueError:
            return None
    return parts


def _compare_versions(a, b):
    """Negative when a < b, zero when equal, positive when a > b, None
    when either side is unparseable (mirrors LibraryVersions.Compare)."""
    parsed_a = _parse_version(a)
    parsed_b = _parse_version(b)
    if parsed_a is None or parsed_b is None:
        return None
    width = max(len(parsed_a), len(parsed_b))
    for i in range(width):
        x = parsed_a[i] if i < len(parsed_a) else 0
        y = parsed_b[i] if i < len(parsed_b) else 0
        if x != y:
            return -1 if x < y else 1
    return 0


def _display_version(version):
    """Single leading-v display form: "v3" stays "v3", "3" becomes "v3"."""
    trimmed = _utext(version).strip()
    while trimmed[:1].lower() == u"v":
        trimmed = trimmed[1:]
    return u"v" + trimmed.strip()


def _mtime_token(mtime, length):
    return u"mtime:{0}:{1}".format(int(mtime * 1000), length)


def _fingerprint(path):
    """Catalog file-hash token for the file on disk, or None when it
    cannot be computed (mirrors LibraryFileFingerprint: SHA-256 of bytes,
    mtime+size token for large/unreadable files)."""
    if not path:
        return None
    try:
        if not os.path.isfile(path):
            return None
        length = os.path.getsize(path)
        mtime = os.path.getmtime(path)
    except Exception:
        return None
    if length > _CONTENT_HASH_MAX_BYTES:
        return _mtime_token(mtime, length)
    if hashlib is None:
        return _mtime_token(mtime, length)
    try:
        with open(path, "rb") as handle:
            return _utext(hashlib.sha256(handle.read()).hexdigest())
    except Exception:
        return _mtime_token(mtime, length)


def _has_local_changes(catalog_hash, current_hash):
    """True when both hashes are present and differ (mirrors
    LibraryAddressUpdate.HasLocalChanges; missing hashes never count)."""
    catalog_hash = _utext(catalog_hash).strip()
    current_hash = _utext(current_hash).strip()
    if not catalog_hash or not current_hash:
        return False
    return catalog_hash != current_hash


def _describe_update(stamp_entry_id, stamp_version, catalog_entry,
                     has_local_changes):
    """The update line for a stamped version, or None when there is nothing
    to report (mirrors LibraryAddressUpdate.Describe)."""
    catalog_id = _utext(catalog_entry.get("id"))
    if _utext(stamp_entry_id) != catalog_id:
        return None
    raw = catalog_entry.get("_raw_version")
    catalog_version = _utext(raw).strip()
    if not catalog_version:
        return None
    star = u"*" if has_local_changes else u""
    have = _display_version(stamp_version) + star
    comparison = _compare_versions(catalog_version, stamp_version)
    if comparison is None:
        if catalog_version == _utext(stamp_version).strip():
            if has_local_changes:
                return u"you have {0} \u2014 local changes not in the catalog".format(have)
            return None
        return u"{0} available \u2014 you have {1}".format(
            _display_version(catalog_version), have)
    if comparison > 0:
        return u"{0} available \u2014 you have {1}".format(
            _display_version(catalog_version), have)
    if comparison == 0 and has_local_changes:
        return u"you have {0} \u2014 local changes not in the catalog".format(have)
    return None


def _format_address(entry, raw_index):
    raw = _raw_entry(raw_index, entry.get("id")) if raw_index else None
    version = _utext(_ci_get(raw, "version")).strip() if raw else u""
    entry_id = _utext(entry.get("id"))
    source_path = _utext(entry.get("path"))
    catalog_hash = _utext(entry.get("fileHash")).strip()
    disk_hash = _fingerprint(entry.get("path"))
    local_changes = _has_local_changes(catalog_hash, disk_hash)

    lines = [u"Library address (revision entry):",
             u"  Entry id: {0}".format(entry_id or u"(none)"),
             u"  Title:    {0}".format(_entry_display_title(entry)),
             u"  Version:  {0}".format(_display_version(version) if version else u"(none)"),
             u"  Source:   {0}".format(source_path or u"(none)"),
             u"  Indexed:  {0}".format(_utext(entry.get("indexedAt")) or u"(unknown)"),
             u"",
             u"File check (catalog snapshot vs file on disk):",
             u"  Catalog hash: {0}".format(catalog_hash or u"(none recorded)"),
             u"  Disk hash:    {0}".format(disk_hash or u"(file not found or unreadable)"),
             u"  Local changes: {0}".format(u"yes *" if local_changes else u"no"),
             u""]

    # Update recognition: compare the catalog version against the version
    # the user currently has (the stamp a GH import would carry).
    have_version = rs.GetString(
        "Library address check — version you currently have "
        "(Enter to skip the update comparison)")
    if have_version is None:
        return None
    have_version = _utext(have_version).strip()
    lines.append(u"Update recognition:")
    if not have_version:
        lines.append(u"  (skipped — no stamped version given)")
    elif not version:
        lines.append(u"  (no catalog version to compare — entry is unversioned)")
    else:
        catalog_entry = {"id": entry_id, "_raw_version": version}
        update = _describe_update(entry_id, have_version, catalog_entry, local_changes)
        if update is None:
            lines.append(u"  you have {0} \u2014 matches the catalog".format(
                _display_version(have_version)))
        else:
            lines.append(u"  " + update)
    return u"\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_address():
    entries, raw_index, error = _load_catalog()
    if error is not None:
        NOTIFICATION.messenger(main_text=error, title=__title__,
                               level="warning", sticky=True)
        return
    labels = _build_labels(entries)
    entry = _pick_entry(entries,
                        labels,
                        "Pick a catalog entry to see its address stamp and check for updates.",
                        "Library Address Stamp")
    if entry is None:
        return
    report = _format_address(entry, raw_index)
    if report is None:
        return
    _show_report(u"Address stamp \u2014 {0}".format(_entry_display_title(entry)),
                 report)


if __name__ == "__main__":
    library_address()
