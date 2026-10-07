# -*- coding: utf-8 -*-
__title__ = "LibraryParamPreview"
__doc__ = """Show a library definition's parameter contract, grouped by parameter group.

Pick a catalog entry to see its parameter summary header (total plus per-group
counts) followed by one name/type/default table per group, in first-seen group
order. Ports the grouped parameter preview from the Grasshopper library
explorer (EnneadTab-For-Grasshopper PR #15).

Reads the shared Grasshopper definition catalog through
Apps/_rhino/Library/catalog.py; parameters come from the catalog index."""
__is_popular__ = False

import os
import sys

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION


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


# --- Grouped parameter preview (ports GH PR #15) -----------------------------

def _param_group(param):
    group = _ci_get(param, "group")
    text = _utext(group).strip()
    return text if text else u"(ungrouped)"


def _pad(text, width):
    text = _utext(text)
    if len(text) >= width:
        return text[:width]
    return text + u" " * (width - len(text))


def _display_type(param_type):
    text = _utext(param_type).strip()
    if not text:
        return u"Unknown"
    return text[:1].upper() + text[1:]


def _format_scalar(value):
    if value is None:
        return u"null"
    text = _utext(value)
    return text if text else u"null"


def _format_default(param):
    if _utext(_ci_get(param, "type")).lower() == u"geometry":
        return u"(null \u2014 runtime pick)"
    return _format_scalar(_ci_get(param, "defaultValue"))


def _format_param_preview(entry):
    params = [p for p in (entry.get("parameters") or []) if isinstance(p, dict)]
    total = len(params)
    noun = u"parameter" if total == 1 else u"parameters"
    lines = [u"Definition: {0}".format(_entry_display_title(entry)),
             u"Id: {0}".format(_utext(entry.get("id"))),
             u""]
    if total == 0:
        lines.append(u"Parameters (ParameterSchema) \u2014 0 parameters:")
        lines.append(u"  (none)")
        return u"\n".join(lines)
    # Groups in first-seen order, case-insensitive (mirrors GH).
    groups = []
    group_index = {}
    for param in params:
        label = _param_group(param)
        key = label.lower()
        if key not in group_index:
            group_index[key] = len(groups)
            groups.append([label, []])
        groups[group_index[key]][1].append(param)
    counts = u", ".join(u"{0}={1}".format(label, len(members))
                        for label, members in groups)
    lines.append(u"Parameters (ParameterSchema) \u2014 {0} {1} ({2}):".format(
        total, noun, counts))
    for label, members in groups:
        lines.append(u"  [{0}] ({1}):".format(label, len(members)))
        lines.append(u"    {0} {1} Default".format(_pad(u"Name", 20), _pad(u"Type", 11)))
        lines.append(u"    {0} {1} {2}".format(u"-" * 20, u"-" * 11, u"-" * 20))
        for param in members:
            lines.append(u"    {0} {1} {2}".format(
                _pad(_ci_get(param, "name"), 20),
                _pad(_display_type(_ci_get(param, "type")), 11),
                _format_default(param)))
    return u"\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_param_preview():
    entries, _raw_index, error = _load_catalog()
    if error is not None:
        NOTIFICATION.messenger(main_text=error, title=__title__,
                               level="warning", sticky=True)
        return
    labels = _build_labels(entries)
    entry = _pick_entry(entries,
                        labels,
                        "Pick a definition to preview its grouped parameter contract.",
                        "Library Parameter Preview")
    if entry is None:
        return
    report = _format_param_preview(entry)
    _show_report(u"Parameter preview \u2014 {0}".format(_entry_display_title(entry)),
                 report)


if __name__ == "__main__":
    library_param_preview()
