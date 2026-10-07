__title__ = "Revit2RhinoImport"
__doc__ = """Brings the geometry exported by the Revit2Rhino button into this Rhino file.

Finds the latest export by itself, so there is no file to browse for.
The new objects are grouped under one layer and selected so you can move them right away.

Features:
- Imports the newest export made by the Revit2Rhino button
- Asks before importing an export that is more than half a day old
- Warns when blocks with the same names already exist in this file

Usage:
1. In Revit, run Revit2Rhino on the view you want
2. Come here and run this command"""

import os

import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino  # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE
from EnneadTab import NOTIFICATION, FOLDER, DATA_FILE, ENVIRONMENT
from EnneadTab import REVIT2RHINO


def _pick_dwg_units(entry):
    """Rhino unit word for a DWG. Uses the Revit record, else asks (no default: a wrong guess scales the model)."""
    units = REVIT2RHINO.units_for_revit_unit(entry.get("units") if entry else None)
    if units:
        return units
    options = ["Millimeters", "Feet", "Inches", "Meters"]
    return rs.ListBox(options, "Which unit was the DWG exported in?", "Import Units")


def _all_objects():
    return set(rs.AllObjects(include_lights=True, include_grips=False) or [])


def _import_one(file_info, units):
    """Import one file. Returns the objects that are new in the document (may be empty).

    The new objects are found by comparing the document before and after: Rhino's importer
    gives no handle on what it made (same approach as get_earth).
    """
    before = _all_objects()
    rs.Command(REVIT2RHINO.import_command(file_info, units), echo=False)
    return list(_all_objects() - before)


def _clashing_block_names(path):
    """Names of blocks in a 3dm that already exist in this document.

    A scripted -Import does not stop on these: Rhino keeps both and renames the new ones.
    """
    try:
        source = Rhino.FileIO.File3dm.Read(path)
    except Exception:
        return []
    if source is None:
        return []
    try:
        return [d.Name for d in source.InstanceDefinitions
                if d.Name and sc.doc.InstanceDefinitions.Find(d.Name) is not None]
    except Exception:
        return []
    finally:
        source.Dispose()


def _is_this_document(path):
    """True if path is the file that is open right now (importing it would duplicate everything)."""
    doc_path = sc.doc.Path
    if not doc_path:
        return False
    return os.path.normcase(os.path.abspath(doc_path)) == os.path.normcase(os.path.abspath(path))


def _regroup(objects, view_name):
    """Move the imported objects under one parent layer so Revit layers stay out of the user's own tree.

    Layers left behind are not deleted: block contents may still use them.
    """
    parent = REVIT2RHINO.import_parent_layer(view_name)
    moved = 0
    for obj in objects:
        try:
            current = rs.ObjectLayer(obj)
            destination = parent + "::" + current
            if not rs.IsLayer(destination):
                rs.AddLayer(destination, rs.LayerColor(current))
            rs.ObjectLayer(obj, destination)
            moved += 1
        except Exception:
            continue
    return moved


def _export_age_hours(files, source, entry):
    if source == "entry":
        return REVIT2RHINO.age_hours(entry.get("created"))
    return REVIT2RHINO.age_hours(REVIT2RHINO.legacy_timestamp(files[0]["path"], ENVIRONMENT.PLUGIN_NAME))


def _describe_age(hours):
    if hours is None or hours < 0:
        return "of unknown age"
    return "{:.0f} hours old".format(hours)


def _confirm_import(files, source, entry):
    """Ask before importing an old export, or one that is not the latest. True to go ahead."""
    hours = _export_age_hours(files, source, entry)
    lost = source == "legacy_older"
    if not lost and not REVIT2RHINO.needs_confirmation(hours):
        return True
    lines = []
    if lost:
        lines.append("The latest export is gone (the file was deleted).")
        lines.append("Only an older one is left.")
        lines.append("")
    lines.append("Export: {}".format(os.path.basename(files[0]["path"])))
    if source == "entry" and entry:
        if entry.get("project"):
            lines.append("Project: {}".format(entry["project"]))
        if entry.get("view"):
            lines.append("View: {}".format(entry["view"]))
    lines.append("Made {}.".format(_describe_age(hours)))
    lines.append("")
    lines.append("Import it anyway?")
    # 4 = Yes/No buttons, 32 = question icon, 6 = Yes
    return rs.MessageBox("\n".join(lines), 4 | 32, __title__) == 6


def _browse_for_export():
    """Last resort when nothing is recorded: let the user pick an export file."""
    path = rs.OpenFileName("Pick a Revit2Rhino export",
                           "Revit2Rhino export (*.3dm;*.dwg)|*.3dm;*.dwg||",
                           FOLDER.DUMP_FOLDER)
    if not path:
        return []
    extension = os.path.splitext(path)[1].lower().lstrip(".")
    if extension not in REVIT2RHINO.SUPPORTED_FORMATS:
        return []
    return [{"path": path, "format": extension}]


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def revit2rhino_import():
    data = DATA_FILE.get_data(REVIT2RHINO.KEY)
    files, source, entry = REVIT2RHINO.resolve_import_files(data, FOLDER.DUMP_FOLDER, ENVIRONMENT.PLUGIN_NAME)

    if not files:
        files = _browse_for_export()
        if not files:
            NOTIFICATION.messenger(main_text="Nothing to import.\nRun Revit2Rhino in Revit first.", sticky=True)
            return
        source = "picked"
    elif not _confirm_import(files, source, entry):
        return

    skipped = [f["path"] for f in files if _is_this_document(f["path"])]
    if skipped:
        files = [f for f in files if f["path"] not in skipped]
        if not files:
            NOTIFICATION.messenger(main_text="This file is the export itself.\nOpen your working Rhino file and run this command there.", sticky=True)
            return

    units = None
    if any(f["format"] == "dwg" for f in files):
        units = _pick_dwg_units(entry if source == "entry" else None)
        if not units:
            return

    clashes = []
    for file_info in files:
        if file_info["format"] == "3dm":
            clashes.extend(_clashing_block_names(file_info["path"]))

    NOTIFICATION.messenger(main_text="Importing {}...\nThis can take a while for a big view.".format(
        os.path.basename(files[0]["path"])))

    imported = []
    failed = []
    rs.EnableRedraw(False)
    try:
        for file_info in files:
            objs = _import_one(file_info, units)
            if objs:
                imported.extend(objs)
            else:
                failed.append(file_info["path"])
        if imported:
            _regroup(imported, entry.get("view") if (entry and source == "entry") else None)
    finally:
        rs.EnableRedraw(True)

    if imported:
        rs.UnselectAllObjects()
        rs.SelectObjects(imported)
        rs.ZoomSelected()

    message = "Imported {} objects from {}.".format(len(imported), os.path.basename(files[0]["path"]))
    if len(files) > 1:
        message = "Imported {} objects from {} file(s).".format(len(imported), len(files) - len(failed))
    if clashes:
        message += "\n{} block(s) already existed here. Rhino kept both and renamed the new ones.".format(len(set(clashes)))
    if failed:
        message += "\nCould not import:\n" + "\n".join(failed)
    NOTIFICATION.messenger(main_text=message, sticky=bool(failed or clashes))


if __name__ == "__main__":
    revit2rhino_import()
