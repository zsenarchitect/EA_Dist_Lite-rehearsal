# -*- coding: utf-8 -*-
__title__ = "LibraryExamine"
__doc__ = """Read-only detail view of one catalog entry -- opens nothing, changes nothing.

Pick a Grasshopper library catalog entry to see a read-only summary: title,
category, tags, parameter contract summary, provenance (scan root, index
time, file hash, convention check), and the purpose note from its sidecar.

Ports the read-only "Examine" preview idea from EnneadTab-For-Grasshopper
PR #48. On the Rhino side the preview is a single detail dialog instead of a
locked Grasshopper canvas: a definition is never opened and nothing is
modified. Depends on PR #283 (shared catalog lib); degrades gracefully if
unmerged."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, sys, json
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


def _utext(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        pass
    try:
        return str(value).decode("utf-8", "replace")
    except Exception:
        return u"?"


def _ci_get(mapping, name):
    """Case-insensitive dict read (the GH index/sidecar JSON is camelCase)."""
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


def _entry_title(entry):
    title = _utext(entry.get("title"))
    return title if title else (_utext(entry.get("id")) or u"(untitled)")


def _build_labels(entries):
    titles = [_entry_title(entry) for entry in entries]
    counts = {}
    for title in titles:
        counts[title] = counts.get(title, 0) + 1
    labels = []
    for entry, title in zip(entries, titles):
        label = title
        if counts[title] > 1:
            label = u"{0} [{1}]".format(title, _utext(entry.get("id")) or u"?")
        category = _utext(entry.get("category"))
        if category:
            label = u"{0}  ({1})".format(label, category)
        labels.append(label)
    return labels


def _format_parameters(entry):
    """Parameter contract summary from the index's normalized parameters."""
    params = entry.get("parameters")
    if not isinstance(params, (list, tuple)):
        params = []
    named = []
    for param in params:
        if isinstance(param, dict):
            name = _utext(_ci_get(param, "name"))
        else:
            name = _utext(param)
        if name:
            named.append(name)
    if not named:
        return u"(no parameters recorded in the index)"
    shown = u", ".join(named[:12])
    if len(named) > 12:
        shown += u"  (+{0} more)".format(len(named) - 12)
    return u"{0} parameter(s): {1}".format(len(named), shown)


def _format_provenance(entry):
    lines = []
    scan_root = _utext(entry.get("scanRoot"))
    lines.append(u"Scan root: {0}".format(scan_root if scan_root else u"(unknown)"))
    indexed_at = _utext(entry.get("indexedAt"))
    lines.append(u"Indexed at: {0}".format(indexed_at if indexed_at else u"(unknown)"))
    file_hash = _utext(entry.get("fileHash"))
    lines.append(u"File hash: {0}".format(file_hash[:16] + u"..." if len(file_hash) > 16 else (file_hash or u"(unknown)")))
    if entry.get("conventionOk"):
        lines.append(u"Convention check: OK")
    else:
        notes = _utext(entry.get("conventionNotes"))
        lines.append(u"Convention check: needs attention{0}".format(
            u" -- " + notes if notes else u""))
    plugins = entry.get("pluginsRequired") or []
    if plugins:
        lines.append(u"Plugins required: {0}".format(u", ".join(_utext(p) for p in plugins)))
    definition_path = _utext(entry.get("path"))
    lines.append(u"Definition: {0}".format(definition_path if definition_path else u"(no path)"))
    return u"\n".join(lines)


def _format_detail(entry):
    sidecar = catalog.load_sidecar(entry) or {}
    lines = [u"Definition: {0}".format(_entry_title(entry)),
             u"Id: {0}".format(_utext(entry.get("id")) or u"(none)"),
             u""]
    category = _utext(entry.get("category"))
    lines.append(u"Category: {0}".format(category if category else u"(uncategorized)"))
    tags = entry.get("tags") or []
    lines.append(u"Tags: {0}".format(u", ".join(_utext(t) for t in tags) if tags else u"(none)"))
    lines.append(u"")
    lines.append(u"Parameter contract summary:")
    lines.append(u"  {0}".format(_format_parameters(entry)))
    lines.append(u"")
    lines.append(u"Provenance:")
    for line in _format_provenance(entry).split(u"\n"):
        lines.append(u"  " + line)
    lines.append(u"")
    purpose = _utext(_ci_get(sidecar, "description")) or _utext(entry.get("description"))
    lines.append(u"Purpose note:")
    lines.append(u"  {0}".format(purpose if purpose else u"(no purpose note in the sidecar)"))
    return u"\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_examine():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT); return

    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        rs.MessageBox(u"No Grasshopper library index was found.\n\n"
                      u"Expected %LOCALAPPDATA%\\EnneadTab\\Grasshopper\\library-index.json "
                      u"(written by the EnneadTab for Grasshopper plugin's Refresh), or set "
                      u"ENNEAD_LIBRARY_INDEX to point at one.")
        return
    entries = catalog.iter_entries(catalog.load_index(index_path))
    if not entries:
        rs.MessageBox(u"The library index contains no entries.")
        return
    entries = catalog.sort_entries(entries, key="title", direction="asc")

    labels = _build_labels(entries)
    picked = RHINO_FORMS.select_from_list(
        labels,
        title=u"Library Examine",
        message=u"Pick a catalog entry to preview. Read-only: nothing is opened "
                u"and nothing is modified.",
        button_names=[u"Examine"],
        width=650,
        height=550,
        multi_select=False)
    if not picked:
        return
    entry = entries[labels.index(picked)]

    # Read-only by construction: the detail view below opens no documents and
    # writes no files -- it only reads the index row and its sidecar.
    rs.MessageBox(_format_detail(entry),
                  buttons=0,
                  title=u"Examine (read-only) -- {0}".format(_entry_title(entry)))


library_examine()
