#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Export the Revit elements of your choice to a Rhino file.

Pick the categories to export (walls, floors, windows, furniture, curtain panels...), then choose which family / type combinations to include. Each element is converted into a Rhino block instance placed at its original location, with the geometry (Breps, or Meshes as fallback) organized on layers by Category / Family / Subcategory.

Blocks are named after the family and type (a short suffix is added when the same type differs by parameters, or for system families such as walls). The export file name contains a timestamp, and Rhino opens when the export finishes. In Rhino, the Revit2RhinoImport command brings the same export into a file you already have open.

Tip: An architectural view (such as a 3D view) must be active. Only elements visible in the active view are listed. Elements from linked models are not exported. You can also export the whole 3D view as a DWG. If the block export is not available on your machine, the DWG export runs directly. Either way, the Revit2RhinoImport command in Rhino brings the result in.
"""

__title__ = "Revit2Rhino"

import clr  # pyright: ignore
import logging

# Configure logging. The action module shares this logger name and configures
# its own handler, so only add a console handler here if none exists yet
# (avoids duplicate log lines).
logger = logging.getLogger("Revit2Rhino")
logger.setLevel(logging.INFO)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(console_handler)


def enable_debug_logging():
    """Raise the shared Revit2Rhino logger AND every handler attached to it
    (including the one the action module adds) to DEBUG."""
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers:
        handler.setLevel(logging.DEBUG)
    logger.debug("Debug logging enabled")


IMPORT_ERROR = None
try:
    import System  # pyright: ignore
    clr.AddReference('RhinoCommon')
    import Rhino  # pyright: ignore
    clr.AddReference('RhinoInside.Revit')
    from RhinoInside.Revit.Convert.Geometry import GeometryDecoder as RIR_DECODER  # pyright: ignore
    IMPORT_OK = True
except Exception as e:
    IMPORT_OK = False
    IMPORT_ERROR = str(e)


import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, USER
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_VIEW, REVIT_FORMS

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()

MODE_DWG = "Export the whole 3D view as DWG"
MODE_BLOCKS = "Pick families, export as Rhino blocks"


def choose_export_mode():
    """Let the user choose how to send the model to Rhino. Returns "dwg", "blocks" or None (cancelled)."""
    options = [
        [MODE_DWG, "Quick and simple. Everything visible in the active 3D view, solids kept as solids. No extra setup."],
        [MODE_BLOCKS, "Choose categories and families first. Each family type becomes a Rhino block placed at its original location."],
    ]
    result = REVIT_FORMS.dialogue(title="Revit2Rhino",
                                  main_text="How do you want to send this to Rhino?",
                                  sub_text="Then run Revit2RhinoImport in Rhino to bring it in.",
                                  options=options,
                                  icon="info")
    choice = result[0] if isinstance(result, tuple) else result
    if choice == MODE_DWG:
        return "dwg"
    if choice == MODE_BLOCKS:
        return "blocks"
    return None


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def revit2rhino(doc):
    """Main entry point for Revit to Rhino export."""
    if REVIT_VIEW.is_focused_on_system_view():
        NOTIFICATION.messenger("You are focused on either ProjectBrower or PropetyPanel. Please activate an Architectural View such as 3D View.")
        return
    
    if not REVIT_VIEW.is_archi_view(doc.ActiveView):
        NOTIFICATION.messenger("Please activate an Architectural View such as 3D View.")
        return
    
    # Without Rhino.Inside the block exporter cannot run. The DWG path needs neither it
    # nor Rhino, so export the active view that way instead of asking the user to set anything up.
    if not IMPORT_OK:
        logger.info("Rhino.Inside is not available ({}); using the DWG export.".format(IMPORT_ERROR))
        import revit2rhino_dwg
        revit2rhino_dwg.export_active_view_to_dwg(doc)
        return

    # Both ways work here, so let the user choose.
    mode = choose_export_mode()
    if mode is None:
        return
    if mode == "dwg":
        import revit2rhino_dwg
        revit2rhino_dwg.export_active_view_to_dwg(doc)
        return

    # Launch the UI - everything else is handled by the UI.
    # Import first so the action module has attached its handler, then enable
    # debug logging so every handler on the shared logger is raised.
    import revit2rhino_UI
    if USER.IS_DEVELOPER:
        enable_debug_logging()
    revit2rhino_UI.show_dialog()


if __name__ == "__main__":
    revit2rhino(DOC)
