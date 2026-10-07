"""
EnneadTab for Rhino -- UnInstaller (modern guided wizard).

Thin entry point: business logic lives in enneadtab_for_rhino_core, the GUI in
_rhino_wizard. Detaches EnneadTab from Rhino (closes the toolbar, removes the
startup registration).
"""

from _rhino_wizard import run

if __name__ == "__main__":
    raise SystemExit(run(is_installing=False))
