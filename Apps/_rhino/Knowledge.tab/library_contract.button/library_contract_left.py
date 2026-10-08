# -*- coding: utf-8 -*-
__title__ = "LibraryContract"
__doc__ = """Show a library definition's Hops-style input/output contract.

Pick a catalog entry to see the contract the Grasshopper plugin derived at
index time: inputs grouped by control kind (sliders, toggles, value lists,
panels, referenced geometry, Get components) with type, default, domain, and
required/optional flags, followed by terminal outputs. Ports the auto-derived
parameter contract from the Grasshopper library explorer
(EnneadTab-For-Grasshopper PR #37).

The live Grasshopper derivation needs a running Grasshopper document, so from
Rhino this button shows the contract stored in the catalog index; entries
indexed before contract derivation report that none is stored."""
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


# --- Hops-style contract display (ports GH PR #37) ---------------------------
# The GH plugin's live derivation (HopsStyleContractDeriver, C#) is not
# reachable from Rhino/IronPython, so this button renders the derived
# contract the plugin stored in the catalog index (entry `derivedContract`:
# inputs/outputs with name, componentName, type, defaultValue, domainMin,
# domainMax, required, controlKind, direction). The shared lib normalizes the
# common entry fields only, so the contract is read from the raw index row.

_INPUT_GROUP_ORDER = (u"slider", u"toggle", u"value_list", u"panel",
                      u"geometry", u"get_component", u"unknown")

_INPUT_GROUP_LABELS = {
    u"slider": u"Sliders",
    u"toggle": u"Toggles",
    u"value_list": u"Value Lists",
    u"panel": u"Panels",
    u"geometry": u"Referenced Geometry",
    u"get_component": u"Get Components",
    u"unknown": u"Other",
}


def _norm_control_kind(value):
    kind = _utext(value).lower()
    if kind == u"valuelist":
        return u"value_list"
    if kind == u"getcomponent":
        return u"get_component"
    return kind


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


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, long)):
        return value != 0
    text = _utext(value).lower()
    return text in (u"true", u"yes", u"1")


def _raw_entry(index, entry_id):
    """Raw index row for a normalized entry id (for fields the shared lib
    does not normalize, e.g. derivedContract)."""
    raw_entries = _ci_get(index, "entries") or []
    wanted = _utext(entry_id)
    for raw in raw_entries:
        if isinstance(raw, dict) and _utext(_ci_get(raw, "id")) == wanted:
            return raw
    return None


def _format_contract_param(param):
    name = _utext(_ci_get(param, "name"))
    component = _utext(_ci_get(param, "componentName")).strip()
    if component:
        name = u"{0} [{1}]".format(name, component)
    param_type = _ci_get(param, "type")
    if _utext(param_type).lower() == u"geometry":
        default_text = u"(null \u2014 runtime pick)"
    else:
        default_text = _format_scalar(_ci_get(param, "defaultValue"))
    domain = u""
    domain_min = _ci_get(param, "domainMin")
    domain_max = _ci_get(param, "domainMax")
    if domain_min is not None or domain_max is not None:
        domain = u" domain=[{0}, {1}]".format(
            _format_scalar(domain_min).replace(u"null", u"\u2013"),
            _format_scalar(domain_max).replace(u"null", u"\u2013"))
    required = u""
    if _utext(_ci_get(param, "direction")).lower() == u"input":
        required = u" required" if _as_bool(_ci_get(param, "required")) else u" optional"
    return u"{0}  type={1}  default={2}{3}{4}".format(
        name, _display_type(param_type), default_text, domain, required)


def _format_contract(entry, raw_index):
    lines = [u"Definition: {0}".format(_entry_display_title(entry)),
             u"Id: {0}".format(_utext(entry.get("id"))),
             u"",
             u"Parameter contract (Hops-style derivation):"]
    raw = _raw_entry(raw_index, entry.get("id")) if raw_index else None
    contract = _ci_get(raw, "derivedContract") if raw else None
    if not isinstance(contract, dict):
        lines.append(u"  (no derived contract in the index for this entry \u2014 Refresh the "
                     u"Grasshopper library with contract derivation to add one)")
        return u"\n".join(lines)
    inputs = [p for p in (_ci_get(contract, "inputs") or []) if isinstance(p, dict)]
    outputs = [p for p in (_ci_get(contract, "outputs") or []) if isinstance(p, dict)]
    lines.append(u"  Inputs ({0}):".format(len(inputs)))
    if not inputs:
        lines.append(u"    (none)")
    else:
        for kind in _INPUT_GROUP_ORDER:
            group = [p for p in inputs
                     if _norm_control_kind(_ci_get(p, "controlKind")) == kind]
            if not group:
                continue
            lines.append(u"    {0} ({1}):".format(_INPUT_GROUP_LABELS[kind], len(group)))
            for param in group:
                lines.append(u"      " + _format_contract_param(param))
    lines.append(u"  Outputs ({0}):".format(len(outputs)))
    if not outputs:
        lines.append(u"    (none)")
    else:
        for param in outputs:
            lines.append(u"    " + _format_contract_param(param))
    return u"\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_contract():
    entries, raw_index, error = _load_catalog()
    if error is not None:
        NOTIFICATION.messenger(main_text=error, title=__title__,
                               level="warning", sticky=True)
        return
    labels = _build_labels(entries)
    entry = _pick_entry(entries,
                        labels,
                        "Pick a definition to see its Hops-style input/output contract.",
                        "Library Contract")
    if entry is None:
        return
    report = _format_contract(entry, raw_index)
    _show_report(u"Contract \u2014 {0}".format(_entry_display_title(entry)),
                 report)


if __name__ == "__main__":
    library_contract()
