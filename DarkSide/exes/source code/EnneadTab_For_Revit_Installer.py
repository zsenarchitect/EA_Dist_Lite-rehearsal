"""
EnneadTab for Revit — Installer (modern guided wizard).

Thin entry point: business logic lives in enneadtab_for_revit_core, the GUI in
_revit_wizard. Attaches EnneadTab to pyRevit so the ribbon appears in Revit.
"""

from _revit_wizard import run

if __name__ == "__main__":
    raise SystemExit(run(is_installing=True))
