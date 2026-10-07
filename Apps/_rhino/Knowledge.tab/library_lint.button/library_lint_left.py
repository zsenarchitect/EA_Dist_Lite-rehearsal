# -*- coding: utf-8 -*-
__title__ = "LibraryLint"
__doc__ = """Validate every catalog sidecar and report unknown or mistyped fields.

Rhino port of the Grasshopper library sidecar field warnings
(EnneadTab-For-Grasshopper PR #23): sidecars whose fields have the wrong
type or are unknown no longer fail silently - each problem is collected
as a structured warning so typos (e.g. 'catagory') surface instead of
being dropped.

Key Features:
- Checks all catalog entries through the shared Library catalog module
- Reports unknown sidecar fields
- Reports mistyped values (wrong JSON type for a known field)
- Full per-entry report printed to the command line"""
__is_popular__ = True

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


def _format_warning(warning):
    """Render one validate_sidecar() warning as a single line, whatever shape it has."""
    if isinstance(warning, dict):
        field = warning.get("field", "")
        kind = warning.get("kind", "")
        message = warning.get("message", "") or warning.get("text", "")
        if not message:
            message = str(warning)
        if field and kind:
            return "[{}] {}: {}".format(kind, field, message)
        if field:
            return "{}: {}".format(field, message)
        return message
    return str(warning)


def _entry_label(entry):
    return entry.get("id") or entry.get("title") or "(unknown entry)"


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_lint():
    # find_catalog_paths() never raises; (None, None) means no catalog on disk.
    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        NOTIFICATION.messenger(main_text = "Library catalog not found.\nIndex the Grasshopper library first, then run again.")
        return

    index = catalog.load_index(index_path)
    entries = list(catalog.iter_entries(index))

    findings = []
    for entry in entries:
        label = _entry_label(entry)
        try:
            sidecar = catalog.load_sidecar(entry)
        except Exception as exc:
            findings.append("{}: sidecar could not be loaded ({})".format(label, exc))
            continue
        if not sidecar:
            # Sidecars are optional curation; a missing sidecar is not a warning.
            continue
        for warning in catalog.validate_sidecar(sidecar) or []:
            findings.append("{}: {}".format(label, _format_warning(warning)))

    if not findings:
        NOTIFICATION.messenger(
            main_text = "Library sidecars are clean.\n{} entries checked, no warnings.".format(len(entries)))
        return

    print("Library sidecar lint: {} warning(s) in {} entries".format(len(findings), len(entries)))
    for line in findings:
        print("  " + line)

    shown = findings[:40]
    sub_text = "\n".join(shown)
    overflow = len(findings) - len(shown)
    if overflow > 0:
        sub_text += "\n... and {} more (see the command line for the full report)".format(overflow)
    RHINO_FORMS.notification(
        title = "Library Sidecar Lint",
        main_text = "{} warning(s) found. Full report printed to the command line.".format(len(findings)),
        sub_text = sub_text,
        width = 700,
        height = 450)


if __name__ == "__main__":
    library_lint()
