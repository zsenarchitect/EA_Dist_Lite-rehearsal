"""
EnneadTab for Revit — UnInstaller (modern guided wizard).

Thin entry point: business logic lives in enneadtab_for_revit_core, the GUI in
_revit_wizard. Detaches EnneadTab from pyRevit (clears userextensions); leaves
pyRevit and other extensions untouched.
"""

from _revit_wizard import run

if __name__ == "__main__":
    raise SystemExit(run(is_installing=False))
