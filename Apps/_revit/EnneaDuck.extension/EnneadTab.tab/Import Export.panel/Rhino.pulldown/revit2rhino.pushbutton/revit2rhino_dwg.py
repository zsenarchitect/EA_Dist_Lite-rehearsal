#!/usr/bin/python
# -*- coding: utf-8 -*-

"""DWG export path for Revit2Rhino. Needs neither Rhino nor Rhino.Inside.

Exports the active 3D view with Revit's own DWG exporter (solids as ACIS, so they
open in Rhino as polysurfaces) into the EnneadTab dump folder, then records the file
under REVIT2RHINO.KEY so the Rhino import button finds it.
"""

import os
import time
import traceback
import logging

from Autodesk.Revit import DB  # pyright: ignore

from EnneadTab import ENVIRONMENT, NOTIFICATION, ERROR_HANDLE, DATA_FILE, DATA_CONVERSION, REVIT2RHINO
from EnneadTab.REVIT import REVIT_UNIT

# Same shared logger the launcher and exporter use.
logger = logging.getLogger("Revit2Rhino")


def _remove_print_setup_files(folder, stem):
    """Revit leaves <stem>*.pcp files next to a DWG export. Remove only this export's."""
    try:
        for name in os.listdir(folder):
            if name.startswith(stem) and name.lower().endswith(".pcp"):
                os.remove(os.path.join(folder, name))
    except Exception:
        logger.debug("Could not clean .pcp files: {}".format(traceback.format_exc()))


def _view_problem(view):
    """Why this view cannot be exported as a 3D DWG, or None if it can."""
    if not isinstance(view, DB.View3D) or view.IsTemplate:
        return "Please activate a 3D view. Solids are only exported from 3D views."
    if view.IsPerspective:
        return "Please activate an orthographic 3D view. Perspective views are not exported."
    if not view.CanBePrinted:
        return "This view cannot be exported. Please activate a printable 3D view."
    if view.IsInTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate):
        return "Temporary hide/isolate is ignored by the DWG export. Apply it permanently (or reset it) first."
    return None


def _free_stem(folder, stem):
    """Two exports in the same second must not share a file name."""
    candidate = stem
    counter = 1
    while os.path.exists(os.path.join(folder, candidate + ".dwg")):
        candidate = "{}_{}".format(stem, counter)
        counter += 1
    return candidate


def _find_written_file(folder, stem):
    """The DWG Revit wrote for this stem, or None. Revit may add a suffix to the name."""
    exact = os.path.join(folder, stem + ".dwg")
    if os.path.isfile(exact):
        return exact
    try:
        candidates = [n for n in os.listdir(folder) if n.startswith(stem) and n.lower().endswith(".dwg")]
    except Exception:
        return None
    if len(candidates) == 1:
        return os.path.join(folder, candidates[0])
    return None


@ERROR_HANDLE.try_catch_error()
def export_active_view_to_dwg(doc):
    """Export everything visible in the active 3D view to a DWG and record it for Rhino.

    Returns the DWG path, or None if nothing was exported.
    """
    view = doc.ActiveView
    problem = _view_problem(view)
    if problem:
        NOTIFICATION.messenger(problem)
        return None
    dwg_available = getattr(getattr(DB, "OptionalFunctionalityUtils", None), "IsDWGExportAvailable", None)
    if dwg_available is not None and not dwg_available():
        NOTIFICATION.messenger("DWG export is not available in this Revit.")
        return None

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    folder = ENVIRONMENT.DUMP_FOLDER
    stem = _free_stem(folder, REVIT2RHINO.export_stem(ENVIRONMENT.PLUGIN_NAME, stamp))

    # An unknown project unit is exported in millimeters and recorded as such, so the
    # Rhino side always knows the unit instead of guessing.
    unit_name = REVIT_UNIT.get_doc_length_unit_name(doc)
    member = REVIT2RHINO.export_unit_member(unit_name)
    export_unit = getattr(DB.ExportUnit, member or "", None)
    if export_unit is None:
        unit_name = "millimeters"
        export_unit = getattr(DB.ExportUnit, REVIT2RHINO.export_unit_member(unit_name), None)

    options = DB.DWGExportOptions()
    options.ExportOfSolids = DB.SolidGeometry.ACIS
    # One file named <stem>.dwg instead of one per view plus xrefs.
    options.MergedViews = True
    # Internal origin, same as the block (3dm) exporter, so both paths line up.
    options.SharedCoords = False
    if export_unit is not None:
        options.TargetUnit = export_unit

    logger.info("Exporting view '{}' to {}.dwg".format(view.Name, os.path.join(folder, stem)))
    started = time.time()
    try:
        exported = doc.Export(folder, stem, DATA_CONVERSION.list_to_system_list([view.Id]), options)
    finally:
        _remove_print_setup_files(folder, stem)
    logger.info("DWG export took {:.1f} seconds".format(time.time() - started))

    dwg_path = _find_written_file(folder, stem) if exported else None
    if not dwg_path:
        NOTIFICATION.messenger("DWG export failed. Check that the view can be exported and try again.", sticky=True)
        return None

    entry = REVIT2RHINO.build_entry([dwg_path],
                                    unit_name if export_unit is not None else None,
                                    stamp,
                                    project=doc.Title,
                                    view=view.Name)
    recorded = False
    try:
        DATA_FILE.set_data(entry, REVIT2RHINO.KEY)
        # set_data returns nothing on its local path, so read it back to be sure.
        recorded = REVIT2RHINO.recorded_ok(DATA_FILE.get_data, entry)
    except Exception:
        logger.warning("Could not record the export for the Rhino import button: {}".format(traceback.format_exc()))

    if recorded:
        NOTIFICATION.messenger("Exported the view as DWG.\nIn Rhino, run Revit2RhinoImport.\n{}".format(dwg_path))
    else:
        NOTIFICATION.messenger("Exported the view as DWG, but the Rhino button cannot find it.\nIn Rhino, run Revit2RhinoImport and pick this file:\n{}".format(dwg_path), sticky=True)
    return dwg_path


if __name__ == "__main__":
    pass
