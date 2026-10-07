__title__ = ["LibraryAssert"]
__doc__ = """Run contract assertions for a catalog definition.

Key Features:
- Pick a Grasshopper definition from the shared library catalog
- Runs the author-declared red/green contract checks (PancakeContract-style)
- Uses live slider values when the definition is open in Grasshopper, else catalog defaults
- Warns before opening a definition whose checks fail"""
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


try:
    _STRING_TYPES = basestring  # IronPython 2.7
except NameError:
    _STRING_TYPES = str  # CPython 3 (test/dev only)


# Parameter-type names an Equals assertion may name instead of a value.
# Mirrors the GH ParameterType convenience in ContractAssertionEvaluator.
_ASSERTION_TYPE_NAMES = ("boolean", "integer", "number", "string", "text",
                         "geometry", "curve", "surface", "brep", "mesh",
                         "point", "vector", "plane", "colour", "color")


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
                                          title="Library - Contract Assertions",
                                          message="Pick a definition to check:",
                                          button_names=["Check"],
                                          multi_select=False)
    if not picked:
        return None
    return matches[labels.index(picked)]


try:
    _INT_TYPES = (int, long)  # IronPython 2.7
except NameError:
    _INT_TYPES = (int,)  # CPython 3 (test/dev only)


def _is_truthy(value):
    # Mirrors ContractAssertionEvaluator.IsTruthy.
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, _STRING_TYPES):
        return len(value) > 0
    if isinstance(value, _INT_TYPES + (float,)):
        return value != 0
    return True


def _try_float(value):
    # Mirrors ContractAssertionEvaluator.TryToDouble (bools are not numeric).
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _format_actual(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _STRING_TYPES):
        return "'{0}'".format(value)
    return "{0}".format(value)


def _eval_equals(ptype, actual, expected):
    exp_text = "" if expected is None else str(expected).strip()
    if exp_text and exp_text.lower() in _ASSERTION_TYPE_NAMES:
        want = exp_text.lower()
        ok = ptype == want
        detail = "type is {0}".format(ptype) if ok else "expected type {0}, got {1}".format(want, ptype or "?")
        return ok, detail
    if actual is None:
        ok = exp_text == ""
        return ok, "both null/empty" if ok else "expected '{0}', got null".format(exp_text)
    if isinstance(actual, bool):
        if exp_text.lower() in ("true", "false"):
            exp_bool = exp_text.lower() == "true"
            ok = actual == exp_bool
            detail = "{0} == {1}".format(actual, exp_bool) if ok else "expected {0}, got {1}".format(exp_bool, actual)
            return ok, detail
        return False, "expected 'true'/'false', got '{0}'".format(exp_text)
    actual_num = _try_float(actual)
    try:
        expected_num = float(exp_text)
    except Exception:
        expected_num = None
    if actual_num is not None and expected_num is not None:
        ok = abs(actual_num - expected_num) <= 1e-9 * max(1.0, abs(expected_num))
        detail = "{0} == {1}".format(actual_num, expected_num) if ok else "expected {0}, got {1}".format(expected_num, actual_num)
        return ok, detail
    actual_text = str(actual)
    ok = actual_text == exp_text
    detail = "'{0}' == '{1}'".format(actual_text, exp_text) if ok else "expected '{0}', got '{1}'".format(exp_text, actual_text)
    return ok, detail


def _eval_range(actual, min_v, max_v):
    value = _try_float(actual)
    if value is None:
        return False, "default is not numeric (got {0}).".format(_format_actual(actual))
    if min_v is not None:
        try:
            low = float(min_v)
        except Exception:
            low = None
        if low is not None and value < low:
            return False, "{0} < min {1}".format(value, min_v)
    if max_v is not None:
        try:
            high = float(max_v)
        except Exception:
            high = None
        if high is not None and value > high:
            return False, "{0} > max {1}".format(value, max_v)
    bounds = "[{0}, {1}]".format("-inf" if min_v is None else min_v,
                                 "inf" if max_v is None else max_v)
    return True, "{0} within {1}".format(value, bounds)


def _evaluate_one(param, assertion):
    """Returns (passed, detail). Mirrors ContractAssertionEvaluator."""
    kind = _ci_get(assertion, "kind")
    kind = str(kind).strip().lower() if kind is not None else ""
    pname = _ci_get(assertion, "parameterName") or ""
    expected = _ci_get(assertion, "expected")
    min_v = _ci_get(assertion, "min")
    max_v = _ci_get(assertion, "max")
    actual = _ci_get(param, "defaultValue")
    ptype = _ci_get(param, "type")
    ptype = str(ptype).strip().lower() if ptype is not None else ""

    if kind == "equals":
        return _eval_equals(ptype, actual, expected)
    if kind == "truthy":
        ok = _is_truthy(actual)
        return ok, "default is {0} ({1})".format("truthy" if ok else "falsy", _format_actual(actual))
    if kind == "falsy":
        ok = not _is_truthy(actual)
        return ok, "default is {0} ({1})".format("falsy" if ok else "truthy", _format_actual(actual))
    if kind == "range":
        return _eval_range(actual, min_v, max_v)
    if kind == "noerror":
        return True, "Resolved '{0}' (type {1}) without error.".format(
            _ci_get(param, "name"), ptype or "?")
    return False, "Unknown assertion kind '{0}'.".format(kind)


def _live_overrides(path):
    """Live parameter values from the definition's open GH document.

    The checks run against the active document when it is open (live slider /
    toggle values win); otherwise they fall back to the catalog defaults.
    Best-effort: never raises.
    """
    overrides = {}
    try:
        import clr
        clr.AddReference("Grasshopper")
        import Grasshopper
    except Exception:
        return overrides
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
            return overrides
        for obj in doc.Objects:
            try:
                nick = obj.NickName
            except Exception:
                continue
            if not nick:
                continue
            try:
                if isinstance(obj, Grasshopper.Kernel.Special.GH_NumberSlider):
                    overrides[str(nick).lower()] = float(obj.Slider.Value)
                elif isinstance(obj, Grasshopper.Kernel.Special.GH_BooleanToggle):
                    overrides[str(nick).lower()] = bool(obj.Value)
            except Exception:
                continue
    except Exception:
        pass
    return overrides


def _open_in_grasshopper(path):
    if not path or not os.path.isfile(path):
        rs.MessageBox("Definition file not found: {0}".format(path))
        return
    import Rhino
    try:
        gh = Rhino.RhinoApp.GetPlugInObject("Grasshopper")
    except Exception:
        gh = None
    if gh is None:
        rs.MessageBox("Grasshopper plug-in is not loaded.")
        return
    try:
        opened = gh.OpenDocument(path)
    except Exception as ex:
        rs.MessageBox("Could not open in Grasshopper: {0}".format(ex))
        return
    if not opened:
        rs.MessageBox("Grasshopper refused to open the document.")
        return
    try:
        gh.ShowEditor()
    except Exception:
        pass


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_assert():
    entries, err = _get_catalog_entries()
    if err:
        rs.MessageBox(err)
        return
    entry = _pick_entry(entries)
    if entry is None:
        return
    title = entry.get("title") or entry.get("path") or "(untitled)"

    sidecar = CATALOG.load_sidecar(entry)
    raw_assertions = _ci_get(sidecar, "assertions")
    if isinstance(raw_assertions, dict):
        raw_assertions = list(raw_assertions.values())
    assertions = [a for a in raw_assertions if isinstance(a, dict)] \
        if isinstance(raw_assertions, (list, tuple)) else []
    if not assertions:
        rs.MessageBox("'{0}' declares no contract assertions.".format(title))
        return

    by_name = {}
    for param in entry.get("parameters") or []:
        if isinstance(param, dict):
            name = _ci_get(param, "name")
            if name and str(name).lower() not in by_name:
                by_name[str(name).lower()] = param

    live = _live_overrides(entry.get("path") or "")
    results = []
    for assertion in assertions:
        check_name = _ci_get(assertion, "name") or "(unnamed)"
        pname = _ci_get(assertion, "parameterName") or ""
        param = by_name.get(str(pname).lower())
        if param is None:
            results.append((False, check_name,
                            "Parameter '{0}' not found in the definition contract.".format(pname)))
            continue
        if str(pname).lower() in live:
            param = dict(param)
            param["defaultValue"] = live[str(pname).lower()]
        passed, detail = _evaluate_one(param, assertion)
        message = _ci_get(assertion, "message")
        if message:
            detail = "{0} -- {1}".format(detail, message)
        results.append((passed, check_name, detail))

    passed_count = sum(1 for passed, _n, _d in results if passed)
    failed_count = len(results) - passed_count
    lines = ["{0}  {1} -- {2}".format("PASS" if passed else "FAIL", name, detail)
             for passed, name, detail in results]
    header = "Contract assertions for '{0}' ({1}/{2} passed{3}).".format(
        title, passed_count, len(results), ", live doc values" if live else "")
    rs.ListBox(lines, "Library - Contract Assertions", header)

    if failed_count:
        answer = rs.MessageBox(
            "{0} of {1} checks failed. Open '{2}' anyway?".format(failed_count, len(results), title),
            4, "Library - Contract Failed")
        if answer != 6:
            return
    else:
        RHINO_FORMS.notification(title="Library - Contract Assertions",
                                 main_text="All {0} checks passed.".format(len(results)),
                                 sub_text=title)
    _open_in_grasshopper(entry.get("path") or "")


if __name__ == "__main__":
    library_assert()
