#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Handoff contract between the Revit2Rhino export (Revit side) and import (Rhino side).

Follows the same convention as Rhino2Revit: the exporting side records what it
wrote with DATA_FILE.set_data(entry, KEY) and puts the geometry files in
FOLDER.DUMP_FOLDER; the importing side reads DATA_FILE.get_data(KEY).

This module is pure Python (no Revit, Rhino or EnneadTab imports) so both host
apps and plain CPython tests can use it. It must stay IronPython 2.7 safe, because
Rhino 8 (the primary target) runs CPython and Rhino 7 and Revit run IronPython 2.7.

Schema version 1, stored under KEY:
    {
        "schema": 1,
        "created": "20260930_131500",      # time.strftime("%Y%m%d_%H%M%S")
        "project": "My Project",           # optional, display only
        "view": "3D View - Main",          # optional, display only
        "units": "feet",                   # Revit length unit name, see units_for_revit_unit
        "files": [
            {"path": "C:\\\\...\\\\Dump\\\\EnneadTab_Revit2Rhino_20260930_131500.3dm",
             "format": "3dm"},             # "3dm" or "dwg"
        ],
        "elements": [ {...}, ... ],        # optional, reserved for per-element identity
    }                                      # (for example UniqueId) to support a round trip later.
                                           # Nothing writes or reads it yet; read_entry keeps it.
"""

import os
import re
import time

try:
    _STRING_TYPES = (basestring,)  # IronPython 2.7
except NameError:
    _STRING_TYPES = (str,)

KEY = "revit2rhino_out_paths"
SCHEMA_VERSION = 1
SUPPORTED_FORMATS = ("3dm", "dwg")

# Files written by the original Revit2Rhino exporter before it recorded KEY.
LEGACY_FILE_MARKER = "_Revit2Rhino_"
_STAMP_RE = re.compile(r"^\d{8}_\d{6}$")
# An export older than this is confirmed with the user before it is imported.
STALE_AFTER_HOURS = 12


def build_entry(files, units, created, project=None, view=None, elements=None):
    """Build a schema v1 entry. files is a list of paths; format comes from the extension."""
    entry = {
        "schema": SCHEMA_VERSION,
        "created": created,
        "units": units,
        "files": [{"path": p, "format": _format_of(p)} for p in files],
    }
    if project:
        entry["project"] = project
    if view:
        entry["view"] = view
    if elements:
        entry["elements"] = list(elements)
    return entry


def _format_of(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext


def units_for_revit_unit(revit_unit):
    """Map a Revit length unit name to the ModelUnits word Rhino's Import command expects.

    Returns None when the unit is unknown, so the caller can ask instead of guessing.
    """
    if not revit_unit:
        return None
    key = str(revit_unit).strip().lower()
    if key == "millimeters":
        return "Millimeters"
    if key in ("feet", "feet, feet & inches", "feet & inches", "feetfractionalinches"):
        return "Feet"
    if key in ("inches", "inches, feet & inches"):
        return "Inches"
    if key == "meters":
        return "Meters"
    return None


# Rhino import word -> Revit DB.ExportUnit member name
_EXPORT_UNIT_MEMBERS = {
    "Millimeters": "Millimeter",
    "Feet": "Foot",
    "Inches": "Inch",
    "Meters": "Meter",
}


def export_unit_member(revit_unit):
    """Name of the Revit DB.ExportUnit member that matches a Revit length unit name.

    None when the unit is unknown (leave the DWG export unit at Default and let the
    Rhino side ask).
    """
    return _EXPORT_UNIT_MEMBERS.get(units_for_revit_unit(revit_unit))


def export_stem(plugin_name, stamp):
    """File name without extension for an export. Same shape the 3dm exporter uses."""
    return "{}{}{}".format(plugin_name, LEGACY_FILE_MARKER, stamp)


def read_entry(data):
    """Validate the stored dict. Returns a clean entry, or None if there is nothing usable.

    DATA_FILE.get_data creates an empty dict for a missing key, so {} means "never exported".
    Entries with an unknown newer schema are refused, not half-read.
    """
    if not data or not isinstance(data, dict):
        return None
    schema = data.get("schema")
    if schema != SCHEMA_VERSION:
        return None
    files = []
    for item in data.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, _STRING_TYPES) or not path:
            continue
        fmt = item.get("format") or _format_of(path)
        if not isinstance(fmt, _STRING_TYPES):
            continue
        fmt = fmt.lower()
        if fmt not in SUPPORTED_FORMATS:
            continue
        files.append({"path": path, "format": fmt})
    if not files:
        return None
    clean = {
        "created": data.get("created"),
        "project": data.get("project"),
        "view": data.get("view"),
        "units": data.get("units"),
        "files": files,
    }
    elements = data.get("elements")
    if isinstance(elements, list):
        clean["elements"] = [e for e in elements if isinstance(e, dict)]
    return clean


def existing_files(entry):
    """Files in the entry that are still on disk, in recorded order."""
    return [f for f in entry["files"] if os.path.isfile(f["path"])]


def _legacy_name_pattern(plugin_name):
    return re.compile(r"^{}{}(\d{{8}}_\d{{6}})\.3dm$".format(re.escape(plugin_name), re.escape(LEGACY_FILE_MARKER)), re.IGNORECASE)


def legacy_timestamp(path, plugin_name):
    """The YYYYMMDD_HHMMSS stamp in an exporter file name, or None if the name does not match."""
    match = _legacy_name_pattern(plugin_name).match(os.path.basename(path or ""))
    return match.group(1) if match else None


def newest_legacy_file(folder, plugin_name):
    """Newest <plugin>_Revit2Rhino_<timestamp>.3dm in folder, or None.

    Lets the Rhino button work with exports made before the exporter wrote KEY.
    Only exact exporter names count (a copy such as "... - Copy.3dm" is ignored).
    "Newest" is decided by the stamp in the name, not by the whole name.
    """
    if not folder or not os.path.isdir(folder):
        return None
    pattern = _legacy_name_pattern(plugin_name)
    found = []
    for name in os.listdir(folder):
        match = pattern.match(name)
        if match:
            found.append((match.group(1), name))
    if not found:
        return None
    return os.path.join(folder, sorted(found)[-1][1])


def age_hours(stamp, now=None):
    """Hours between a YYYYMMDD_HHMMSS stamp (local time) and now. None if the stamp is unusable."""
    try:
        then = time.mktime(time.strptime(stamp, "%Y%m%d_%H%M%S"))
    except Exception:
        # IronPython's strptime is .NET backed and may raise other types on odd input.
        return None
    if now is None:
        now = time.time()
    return (now - then) / 3600.0


def needs_confirmation(hours):
    """True if an export of this age should be confirmed with the user first.

    Unknown age and a stamp in the future (clock skew) are not "fresh".
    """
    if hours is None or hours < 0:
        return True
    return hours > STALE_AFTER_HOURS


def import_command(file_info, units):
    """The Rhino command line that imports one exported file.

    DWG: the unit word comes from the Revit record, same shape as revit_drafter.
    3dm: Rhino reads the units stored in the file, so there is no unit option. Two
    Enters, like the repo's other scripted 3dm imports (bind_worksession).
    """
    path = file_info["path"]
    if file_info["format"] == "dwg":
        return "_-Import \"{}\" _ModelUnits={} _Enter _Enter".format(path, units)
    return "_-Import \"{}\" _Enter _Enter".format(path)


_BAD_LAYER_CHARS = re.compile(r"[:\\/*?\"<>|]")


def import_parent_layer(view_name):
    """Name of the layer the imported Revit objects are grouped under in Rhino."""
    cleaned = _BAD_LAYER_CHARS.sub("-", view_name) if isinstance(view_name, _STRING_TYPES) else ""
    cleaned = cleaned.strip()
    return "[Revit2Rhino] {}".format(cleaned or "Import")


def recorded_ok(getter, entry):
    """True if reading the record back (getter(KEY)) gives what was just written.

    DATA_FILE.set_data returns nothing on its local path, so a failed write is silent.
    Pass DATA_FILE.get_data as getter.
    """
    try:
        back = getter(KEY)
    except Exception:
        return False
    if not isinstance(back, dict):
        return False
    return back.get("created") == entry.get("created") and back.get("files") == entry.get("files")


def resolve_import_files(data, folder, plugin_name):
    """Decide what to import.

    Returns (files, source, entry) where files is a list of {"path", "format"},
    entry is the clean record (or None), and source is:
      "entry"         the recorded export
      "legacy"        the newest exporter file found by name (no usable record)
      "legacy_older"  the record's files are gone and only an OLDER exporter file is left
      None            nothing to import
    The record wins unless it has no usable stamp or an exporter file is newer than it
    (an older exporter build writes the file but no record).
    """
    entry = read_entry(data)
    legacy = newest_legacy_file(folder, plugin_name)
    legacy_stamp = legacy_timestamp(legacy, plugin_name) if legacy else None
    created = entry.get("created") if entry else None
    created_ok = isinstance(created, _STRING_TYPES) and bool(_STAMP_RE.match(created))

    if entry:
        files = existing_files(entry)
        if files:
            if legacy_stamp and (not created_ok or legacy_stamp > created):
                return [{"path": legacy, "format": "3dm"}], "legacy", entry
            return files, "entry", entry
        if legacy:
            older = created_ok and legacy_stamp is not None and legacy_stamp < created
            return [{"path": legacy, "format": "3dm"}], ("legacy_older" if older else "legacy"), entry
    elif legacy:
        return [{"path": legacy, "format": "3dm"}], "legacy", entry
    return [], None, entry
