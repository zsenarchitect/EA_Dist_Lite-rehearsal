# -*- coding: utf-8 -*-
__title__ = "LibraryInputSummary"
__doc__ = """Summarize a library definition's inputs, grouped by control type.

Pick a catalog entry to see its Inputs-group parameters grouped as sliders,
toggles, value lists, panels, referenced geometry, or other, with counts and
member names — the "drive 3 sliders" view from the Grasshopper library
explorer (EnneadTab-For-Grasshopper PR #42). The picker list itself shows the
compact summary (e.g. "2 sliders · 1 toggle") next to each entry.

Reads the shared Grasshopper definition catalog through
Apps/_rhino/Library/catalog.py; inputs come from the catalog index."""
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


# --- Input summary by control type (ports GH PR #42) -------------------------
# ParameterType -> user-facing control kind, mirroring the GH mapping
# (InputControlSummary.Classify): the schema cannot see the real canvas
# control, so this is the same documented heuristic.

_CONTROL_KIND_ORDER = (u"slider", u"toggle", u"value_list", u"panel",
                       u"referenced_geometry", u"other")

_CONTROL_KIND_LABELS = {
    u"slider": u"Slider",
    u"toggle": u"Toggle",
    u"value_list": u"Value List",
    u"panel": u"Panel",
    u"referenced_geometry": u"Referenced Geometry",
    u"other": u"Other",
}

_CONTROL_KIND_SINGULAR = {
    u"slider": u"slider",
    u"toggle": u"toggle",
    u"value_list": u"value list",
    u"panel": u"panel",
    u"referenced_geometry": u"geometry ref",
    u"other": u"other",
}


def _classify_control(param_type):
    param_type = _utext(param_type).lower()
    if param_type in (u"number", u"integer"):
        return u"slider"
    if param_type == u"boolean":
        return u"toggle"
    if param_type == u"string":
        return u"value_list"
    if param_type in (u"point", u"color"):
        return u"panel"
    if param_type == u"geometry":
        return u"referenced_geometry"
    return u"other"


def _plural_label(kind, count):
    singular = _CONTROL_KIND_SINGULAR.get(kind, u"other")
    if count == 1:
        return singular
    if kind == u"referenced_geometry":
        return u"geometry refs"
    return singular + u"s"


def _summarize_inputs(entry):
    """Non-empty control-kind groups over the Inputs-group params, in
    canonical kind order (mirrors InputControlSummary.SummarizeInputs)."""
    params = [p for p in (entry.get("parameters") or []) if isinstance(p, dict)]
    inputs = [p for p in params
              if _utext(_ci_get(p, "group")).lower() == u"inputs"]
    groups = []
    for kind in _CONTROL_KIND_ORDER:
        members = [p for p in inputs
                   if _classify_control(_ci_get(p, "type")) == kind]
        if members:
            groups.append((kind, members))
    return groups


def _format_compact(groups):
    return u" \u00b7 ".join(
        u"{0} {1}".format(len(members), _plural_label(kind, len(members)))
        for kind, members in groups)


def _format_input_summary(entry):
    groups = _summarize_inputs(entry)
    lines = [u"Definition: {0}".format(_entry_display_title(entry)),
             u"Id: {0}".format(_utext(entry.get("id"))),
             u""]
    if not groups:
        lines.append(u"Input summary (grouped by control type):")
        lines.append(u"  (none — this entry has no Inputs-group parameters)")
        return u"\n".join(lines)
    lines.append(u"Input summary (grouped by control type):")
    for kind, members in groups:
        names = u", ".join(_utext(_ci_get(p, "name")) for p in members)
        lines.append(u"  {0} ({1}): {2}".format(
            _CONTROL_KIND_LABELS[kind], len(members), names))
    return u"\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_input_summary():
    entries, _raw_index, error = _load_catalog()
    if error is not None:
        NOTIFICATION.messenger(main_text=error, title=__title__,
                               level="warning", sticky=True)
        return

    def _label_suffix(entry):
        return _format_compact(_summarize_inputs(entry))

    labels = _build_labels(entries, suffix_fn=_label_suffix)
    entry = _pick_entry(entries,
                        labels,
                        "Pick a definition to see its inputs grouped by control type.",
                        "Library Input Summary")
    if entry is None:
        return
    report = _format_input_summary(entry)
    _show_report(u"Input summary \u2014 {0}".format(_entry_display_title(entry)),
                 report)


if __name__ == "__main__":
    library_input_summary()
