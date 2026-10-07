__title__ = ["LibraryOpenWithInputs"]
__doc__ = """Open a catalog definition with its annotated inputs.

Key Features:
- Pick a Grasshopper definition from the shared library catalog
- Fill Player-style annotated inputs (min/max clamp, presets) in a Rhino form
- Opens the definition in Grasshopper and applies the values to matching sliders"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc

import os
import sys

from EnneadTab import LOG, ERROR_HANDLE, ENVIRONMENT
from EnneadTab.RHINO import RHINO_FORMS

_LIBRARY_DIR = os.path.join(ENVIRONMENT.RHINO_FOLDER, "Library")
if _LIBRARY_DIR not in sys.path:
    sys.path.append(_LIBRARY_DIR)

try:
    import catalog as CATALOG  # Apps/_rhino/Library/catalog.py (shared lib)
except ImportError:
    CATALOG = None


def _ci_get(mapping, name):
    if not isinstance(mapping, dict):
        return None
    if name in mapping:
        return mapping[name]
    lowered = name.lower()
    for key in mapping:
        try:
            if key.lower() == lowered:
                return mapping[key]
        except Exception:
            continue
    return None


def _get_catalog_entries():
    """Returns (entries, error)."""
    if CATALOG is None:
        return None, ("Shared catalog library not found "
                      "(Apps/_rhino/Library/catalog.py). Merge the shared-lib PR first.")
    index_path, _settings_path = CATALOG.find_catalog_paths()
    if not index_path:
        return None, "No catalog index found. Refresh the Grasshopper library first."
    entries = CATALOG.iter_entries(CATALOG.load_index(index_path))
    if not entries:
        return None, "Catalog index is empty: {0}".format(index_path)
    return entries, None


def _pick_entry(entries):
    query = rs.GetString("Catalog filter (blank shows all)", "")
    if query is None:
        return None
    matches = CATALOG.search_entries(entries, query=query) if query else list(entries)
    matches = CATALOG.sort_entries(matches, key="title", direction="asc")
    if not matches:
        rs.MessageBox("No catalog entries match '{0}'.".format(query))
        return None
    labels = []
    for entry in matches:
        title = entry.get("title") or os.path.basename(entry.get("path") or "") or "(untitled)"
        labels.append("{0}   <{1}>".format(title, entry.get("path") or "?"))
    picked = RHINO_FORMS.select_from_list(labels,
                                          title="Library - Open With Inputs",
                                          message="Pick a definition to open with inputs:",
                                          button_names=["Open"],
                                          multi_select=False)
    if not picked:
        return None
    return matches[labels.index(picked)]


def _get_annotations(sidecar):
    """Returns [(parameter_name, annotation_dict)] from the sidecar.

    Mirrors the GH sidecar 'inputAnnotations' map (parameter name ->
    {parameterName, min, max, presets, atMost}, camelCase). Tolerates a list
    shape too. NOTE: the shared lib's validate_sidecar() only knows the five
    curation fields, so it reports 'inputAnnotations' as unknown -- that is a
    known lib gap, not a sidecar error.
    """
    raw = _ci_get(sidecar, "inputAnnotations")
    result = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                name = _ci_get(value, "parameterName") or key
                if name:
                    result.append((name, value))
    elif isinstance(raw, (list, tuple)):
        for value in raw:
            if isinstance(value, dict):
                name = _ci_get(value, "parameterName")
                if name:
                    result.append((name, value))
    return result


def _contract_inputs(entry):
    inputs = []
    for param in entry.get("parameters") or []:
        if isinstance(param, dict) and _ci_get(param, "name"):
            inputs.append(param)
    return inputs


def _clamp(value, min_v, max_v):
    if min_v is not None and value < min_v:
        return min_v
    if max_v is not None and value > max_v:
        return max_v
    return value


def _ask_value(name, annotation, contract):
    """Returns (value, cancelled)."""
    presets = [p for p in (_ci_get(annotation, "presets") or []) if p not in (None, "")]
    min_v = _ci_get(annotation, "min")
    max_v = _ci_get(annotation, "max")
    try:
        at_most = _ci_get(annotation, "atMost")
        at_most = int(at_most) if at_most is not None else None
    except Exception:
        at_most = None
    default = _ci_get(contract, "defaultValue")
    ptype = _ci_get(contract, "type")
    ptype = str(ptype).strip().lower() if ptype is not None else ""

    if presets:
        picked = RHINO_FORMS.select_from_list(
            ["{0}".format(p) for p in presets],
            title="Library Input - {0}".format(name),
            message="Pick a preset for '{0}':".format(name),
            button_names=["Use"],
            multi_select=False)
        if picked is None:
            return None, True
        return picked, False

    numeric = min_v is not None or max_v is not None or ptype in ("number", "integer")
    multi = at_most is not None and at_most > 1
    hint = ""
    if min_v is not None or max_v is not None:
        hint += " [{0}..{1}]".format("no min" if min_v is None else min_v,
                                     "no max" if max_v is None else max_v)
    if multi:
        hint += " (comma-separated, at most {0})".format(at_most)
    default_text = "" if default is None else "{0}".format(default)

    while True:
        raw = rs.GetString("Value for '{0}'{1}".format(name, hint), default_text)
        if raw is None:
            return None, True
        raw = raw.strip()
        if not raw:
            if default is None:
                rs.MessageBox("'{0}' needs a value.".format(name))
                continue
            raw = default_text
        parts = [p.strip() for p in raw.split(",")] if multi else [raw]
        if multi and len(parts) > at_most:
            rs.MessageBox("'{0}' accepts at most {1} values; extras were dropped.".format(name, at_most))
            parts = parts[:at_most]
        values = []
        ok = True
        for part in parts:
            if numeric:
                try:
                    number = float(part)
                except ValueError:
                    rs.MessageBox("'{0}' is not a number.".format(part))
                    ok = False
                    break
                number = _clamp(number, min_v, max_v)
                if ptype == "integer":
                    number = int(round(number))
                values.append(number)
            else:
                values.append(part)
        if not ok:
            continue
        return values[0] if not multi else values, False


def _grasshopper_plugin():
    import Rhino
    try:
        return Rhino.RhinoApp.GetPlugInObject("Grasshopper")
    except Exception:
        return None


def _open_in_grasshopper(path):
    """Returns (ok, error)."""
    if not path or not os.path.isfile(path):
        return False, "Definition file not found: {0}".format(path)
    gh = _grasshopper_plugin()
    if gh is None:
        return False, "Grasshopper plug-in is not loaded."
    try:
        opened = gh.OpenDocument(path)
    except Exception as ex:
        return False, str(ex)
    if not opened:
        return False, "Grasshopper refused to open the document."
    try:
        gh.ShowEditor()
    except Exception:
        pass
    return True, None


def _apply_values_to_sliders(path, values):
    """Best-effort: set matching GH number sliders (nickname, case-insensitive).

    Mirrors the GH open-with-inputs behavior of applying initial values to the
    opened document; unknown names are skipped, one bad value never fails the
    open. Returns the number of sliders updated.
    """
    applied = 0
    try:
        import clr
        clr.AddReference("Grasshopper")
        import Grasshopper
        import System
    except Exception:
        return 0
    try:
        target = os.path.normcase(os.path.abspath(path))
        doc = None
        for open_doc in Grasshopper.Instances.DocumentServer:
            try:
                file_path = open_doc.FilePath
            except Exception:
                file_path = None
            if file_path and os.path.normcase(os.path.abspath(file_path)) == target:
                doc = open_doc
                break
        if doc is None:
            return 0
        wanted = {}
        for name, value in values.items():
            wanted[str(name).lower()] = value
        slider_type = Grasshopper.Kernel.Special.GH_NumberSlider
        for obj in doc.Objects:
            try:
                if not isinstance(obj, slider_type):
                    continue
                nick = obj.NickName
            except Exception:
                continue
            if not nick or str(nick).lower() not in wanted:
                continue
            value = wanted[str(nick).lower()]
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            try:
                number = float(value)
            except Exception:
                continue
            try:
                obj.SetSliderValue(System.Decimal(number))
                applied += 1
            except Exception:
                continue
    except Exception:
        pass
    return applied


def _run_solver():
    gh = _grasshopper_plugin()
    if gh is None:
        return
    try:
        gh.RunSolver(True)
    except Exception:
        pass


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_open_with_inputs():
    entries, err = _get_catalog_entries()
    if err:
        rs.MessageBox(err)
        return
    entry = _pick_entry(entries)
    if entry is None:
        return

    sidecar = CATALOG.load_sidecar(entry)
    annotations = _get_annotations(sidecar)
    contracts = _contract_inputs(entry)

    by_name = {}
    for param in contracts:
        key = str(_ci_get(param, "name")).lower()
        if key not in by_name:
            by_name[key] = param
    ann_by_name = {}
    for name, annotation in annotations:
        key = str(name).lower()
        if key not in ann_by_name:
            ann_by_name[key] = annotation

    ordered = []
    seen = set()
    for param in contracts:
        name = _ci_get(param, "name")
        ordered.append(name)
        seen.add(str(name).lower())
    for name, _annotation in annotations:
        if str(name).lower() not in seen:
            ordered.append(name)
            seen.add(str(name).lower())

    values = {}
    for name in ordered:
        key = str(name).lower()
        value, cancelled = _ask_value(name, ann_by_name.get(key, {}), by_name.get(key, {}))
        if cancelled:
            return
        values[name] = value

    ok, err = _open_in_grasshopper(entry.get("path") or "")
    if not ok:
        rs.MessageBox("Could not open in Grasshopper: {0}".format(err))
        return
    applied = _apply_values_to_sliders(entry.get("path") or "", values)
    if applied:
        _run_solver()
    rs.MessageBox("Opened '{0}' in Grasshopper ({1} slider(s) updated).".format(
        entry.get("title") or entry.get("path"), applied))


if __name__ == "__main__":
    library_open_with_inputs()
