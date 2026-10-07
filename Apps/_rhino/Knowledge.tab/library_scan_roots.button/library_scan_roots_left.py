__title__ = ["LibraryScanRoots"]
__doc__ = """Validate the catalog scan roots.

Key Features:
- Checks every configured scan root for missing or unreadable paths
- Warn-and-continue: reports all problems at once, flags possibly-offline shares"""
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


def _validate_root(raw_root):
    """Returns (ok, kind, message). Never raises.

    Mirrors the GH LibraryScanRootValidator: missing roots (typo, moved
    folder, offline share) and unreadable roots (permissions) become problem
    entries; the caller warns and continues instead of aborting.
    """
    root = str(raw_root).strip() if raw_root is not None else ""
    if not root:
        return False, "RootNotFound", "Scan root is empty."
    try:
        exists = os.path.isdir(root)
    except Exception as ex:
        return False, "RootUnreadable", "Could not check scan root '{0}': {1}".format(root, ex)
    if not exists:
        return False, "RootNotFound", (
            "Scan root not found: '{0}'. Check the path for typos or an offline network share.".format(root))
    try:
        # Existence alone does not prove readability -- force a minimal listing.
        os.listdir(root)
    except Exception:
        return False, "RootUnreadable", (
            "Scan root exists but cannot be listed (access denied): '{0}'.".format(root))
    return True, None, "OK"


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_scan_roots():
    if CATALOG is None:
        rs.MessageBox("Shared catalog library not found (Apps/_rhino/Library/catalog.py). "
                      "Merge the shared-lib PR first.")
        return
    _index_path, settings_path = CATALOG.find_catalog_paths()
    settings = CATALOG.load_settings(settings_path) if settings_path else {}
    roots = _ci_get(settings, "scanRoots")
    if roots is None and _index_path:
        roots = _ci_get(CATALOG.load_index(_index_path), "scanRoots")
    if isinstance(roots, _STRING_TYPES):
        roots = [roots]
    roots = [r for r in (roots or []) if isinstance(r, _STRING_TYPES)]
    if not roots:
        rs.MessageBox("No scan roots configured in the library settings.")
        return

    # Warn-and-continue: every root is checked; problems are reported, never fatal.
    lines = []
    problems = 0
    for root in roots:
        ok, kind, message = _validate_root(root)
        if ok:
            lines.append("OK    {0}".format(root))
        else:
            problems += 1
            lines.append("WARN [{0}] {1}: {2}".format(kind, root or "(empty)", message))

    header = "{0} of {1} scan root(s) have problems.".format(problems, len(roots)) \
        if problems else "All {0} scan root(s) are reachable.".format(len(roots))
    rs.ListBox(lines, "Library - Scan Roots", header)
    if problems:
        RHINO_FORMS.notification(title="Library - Scan Roots",
                                 main_text=header,
                                 sub_text="Possibly-offline shares were flagged, not fatal.")
    print(header)


if __name__ == "__main__":
    library_scan_roots()
