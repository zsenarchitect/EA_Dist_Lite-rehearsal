"""
EnneadTab for Rhino -- Installer (modern guided wizard).

Thin entry point: business logic lives in enneadtab_for_rhino_core, the GUI in
_rhino_wizard. Attaches EnneadTab to Rhino so the toolbar appears -- no more
dragging EnneadTab_For_Rhino_Installer.rui by hand.
"""

from _rhino_wizard import run

if __name__ == "__main__":
    raise SystemExit(run(is_installing=True))
