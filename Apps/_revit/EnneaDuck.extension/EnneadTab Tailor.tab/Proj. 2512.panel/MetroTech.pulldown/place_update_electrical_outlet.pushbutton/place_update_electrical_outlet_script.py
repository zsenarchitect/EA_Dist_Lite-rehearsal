#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Create or update electrical outlet instances from furniture markers.

No menu, no picking: running the button scans the current model AND every loaded
link for any furniture family that carries a `_para_map` marker, lets you
multi-select which of those discovered families to process, then creates or
corrects every outlet automatically.

Each marker instance names its own outlet family/type, mount height, AND search
target (see `target` in PARA_MAP_TEMPLATE -- "wall"/"floor"/"furniture_vertical"/
"furniture_horizontal", all four keys required) via its `_para_map` JSON parameter,
so markers nested in the same furniture instance can each place a different outlet
at a different height searching a different kind of host. The outlet instance
itself is always placed at its host level with zero elevation offset -- mount
height is instead written onto the outlet's Placement Height parameter (see
PLACEMENT_HEIGHT_PARAMETER_NAME), and the outlet family's own internal geometry
does the visual raising. For a wall/floor target the marker's raw position is never
used directly (markers are modeled above the furniture body on purpose, to stay
visible/pickable -- see the comment above PARA_MAP_TEMPLATE); a furniture target
DOES use the marker's raw position, since the target face can sit at any height on
the furniture body itself (see find_nearest_furniture_face).

Every outlet this tool creates is tagged with the marker that generated it (see
SOURCE_MARKER_TAG_PARAMETER_NAME), so a later run finds it by exact lookup instead
of guessing from position/type -- and can tell the three cases apart: already
correct (left alone), same family but wrong type (retyped in place), or a
completely different family (deleted and replaced). An outlet owned by another
user in a workshared model is left alone either way, and never duplicated.

Every run writes a timestamped debug log to the local dump folder (path printed at
the end) recording what was found, resolved, skipped, and placed -- open it when a
run gets stuck to see exactly what happened. If many markers of the SAME furniture
family in a row fail for the identical reason, that family's remaining markers are
skipped (other selected families are unaffected) instead of grinding through a
doomed setup; a per-marker error (e.g. a hand-edited _para_map typo) never aborts
more than that one marker.

A run only counts as fully successful when EVERY marker found resolved AND applied
cleanly -- any unresolved marker, apply-phase failure, missing-required-param
instance, or user cancellation means no. Only then does the tool offer (see
offer_save_run_selection) to save this run's touched outlets as a named Revit
selection, prefixed `EnneadTab-OutletRunner_<timestamp>_<your typed run intent>` --
the furniture family name is never a usable default here (one family commonly
carries more than one marker), so the run's intent must be typed by hand."""
__title__ = "Place/Update\nElectrical Outlet"

import datetime
import json
import math
import time

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

from Autodesk.Revit import DB  # pyright: ignore
from System.Collections.Generic import List  # pyright: ignore
import clr  # pyright: ignore
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import Application  # pyright: ignore
from pyrevit import forms

from EnneadTab import ERROR_HANDLE, FOLDER, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION, REVIT_FAMILY, REVIT_FILTER

from outlet_conflict_row import OutletPlacementTarget

DOC = REVIT_APPLICATION.get_doc()
UIDOC = REVIT_APPLICATION.get_uidoc()
__persistentengine__ = True

# The marker family carries position only, no dependable facing rotation, so the
# host wall/floor is found with a fan of rays cast outward from the marker point
# rather than trusting one axis of its orientation. Horizontal rays (evenly spaced
# around a full circle) cover walls; a straight-down and straight-up ray cover
# floors, which the horizontal fan alone would never hit.
MARKER_RAYCAST_FAN_COUNT = 16  # horizontal rays in the fan; higher = finer angular coverage

MARKER_RAYCAST_MAX_DISTANCE = 3.0  # feet; how far to ray-cast to find a host face
EXISTING_OUTLET_SEARCH_RADIUS = 1.0  # feet; how close counts as "already at this marker"
EXISTING_OUTLET_SAME_SPOT_TOLERANCE = 0.05  # feet; close enough to skip as a no-op

# Seconds to pause after each zoom_active_view_to_point call. The zoom only fires
# once every progress_step items (never per item -- see that constant's own
# comments), which on an 800+ item run can be as few as ~8 items apart; without a
# deliberate pause here, that many placements finish faster than the eye can
# register the frame DoEvents() just forced onto screen, so the zoom LOOKS like it
# never happened even though it did. This cost is bounded: at most ~100 pauses per
# run (one per progress_step tick), so total added time is small relative to the run.
ZOOM_PAUSE_SECONDS = 0.2

# Which furniture families carry markers is NEVER hardcoded here: discover_qualified_
# furniture_family_names() finds them live, by scanning for _para_map-carrying
# markers and walking each one up to its host furniture instance's family name (via
# SuperComponent), across the current model AND every loaded link (see
# get_search_scopes). This survives new furniture families getting markers added
# later with zero code changes, and place_from_markers lets the user multi-select a
# subset of the discovered names for a surgical run (e.g. re-running on just one
# furniture type after a model fix) instead of always processing every family.

# Shared fail-fast threshold for BOTH phases of a run:
# - resolve_marker_targets: if this many markers of the SAME furniture family in a
#   row fail with the EXACT SAME reason, that family's remaining markers are skipped.
# - apply_marker_outlets: if this many items in the SAME bucket (to_create/to_replace/
#   to_update/to_retag) in a row raise the EXACT SAME exception during actual
#   placement, that bucket's remaining items are skipped (see check_failure_streak).
# Either way, an identical repeated reason signals a systemic bug or setup problem,
# not a string of unrelated one-off issues, so nothing is gained by continuing --
# fail fast, fix the root cause, rerun. The streak is always scoped to one
# family/bucket, never global, so other families/buckets are unaffected.
CONSECUTIVE_UNRESOLVED_ABORT_THRESHOLD = 5

# Revit has no native JSON/dict parameter type, so a marker instance carries its
# per-instance info (which outlet family/type to place there, at what mount height)
# as one Multiline Text parameter holding a JSON-serialized dict. Multiline (not
# plain Text) so a human opening the marker instance inside the furniture family can
# actually read and hand-edit the indented JSON in the Properties palette. Read with
# get_marker_para_map, write with set_marker_para_map -- neither ever touches the
# parameter as a raw string anywhere else in this file.
PARA_MAP_PARAMETER_NAME = "_para_map"

# Template/default shape of that dict. "family_name"/"type_name" name the outlet to
# place at THIS marker; "mount_height" is the outlet's height in feet above its HOST
# FURNITURE INSTANCE's level (see resolve_marker_targets -- the furniture instance
# that directly nests this marker). All three keys are required: a marker missing any
# one of them cannot be placed. There is no marker-family-wide fallback for any of
# them -- each marker names its own outlet and height independently, even markers
# nested in the same furniture instance.
#
# WHY NOT THE MARKER'S RAW POSITION: markers are deliberately modeled ABOVE the
# furniture geometry, not at the outlet's real-world height. Many outlets sit low
# (floor boxes, base plugs); a marker placed at that real height would be buried
# inside or below the furniture body, making it hard to see and pick in views/3D. So
# the marker's raw Z is a MODELING/VISIBILITY convenience only -- it has no design
# meaning and must never be read as the outlet's height. The marker's X/Y are still
# trustworthy (that's real plan position) and are used as-is.
#
# WHY `mount_height` ISN'T BAKED INTO THE INSTANCE'S Z EITHER: the outlet instance is
# placed at its host level with ZERO elevation offset (see PLACEMENT_HEIGHT_PARAMETER_
# NAME below) -- `mount_height` is instead written onto that Placement Height instance
# parameter, and the outlet family's own internal geometry (an offset/extrusion driven
# by that parameter, set up in the Family Editor) does the actual visual raising. The
# ray-cast that finds the host wall/floor uses the level elevation as its target Z, not
# mount_height.
PARA_MAP_TEMPLATE = {
    "family_name": None,
    "type_name": None,
    "mount_height": None,
    "target": None,
}

# Which category of host geometry this marker's search is allowed to match --
# REQUIRED, same enforcement as family_name/type_name/mount_height (see
# _resolve_one_marker). Search direction is no longer inferred from the outlet
# family's own FamilyPlacementType -- target now drives that rule directly. "wall"/
# "floor" search the project-wide wall/floor intersector (find_nearest_host_face,
# unchanged); "furniture_vertical"/"furniture_horizontal" search the marker's OWN
# host furniture instance's geometry instead (find_nearest_furniture_face) -- never
# a neighboring furniture instance, even one that happens to be closer.
TARGET_WALL = "wall"
TARGET_FLOOR = "floor"
TARGET_FURNITURE_VERTICAL = "furniture_vertical"
TARGET_FURNITURE_HORIZONTAL = "furniture_horizontal"
VALID_TARGETS = (TARGET_WALL, TARGET_FLOOR, TARGET_FURNITURE_VERTICAL, TARGET_FURNITURE_HORIZONTAL)

# A furniture face counts as "horizontal" when its normal's Z component magnitude is
# at least this; "vertical" when at most FURNITURE_FACE_VERTICAL_NORMAL_Z_MAX. A
# sloped face in between matches neither furniture target -- see
# find_nearest_furniture_face.
FURNITURE_FACE_HORIZONTAL_NORMAL_Z_MIN = 0.9
FURNITURE_FACE_VERTICAL_NORMAL_Z_MAX = 0.1

# Written onto every OUTLET this tool creates (never onto the marker -- a marker can
# live inside a read-only link, so it can never be written to; the outlet always
# lives in the CURRENT/host document, which is always writable). Lets a later run
# look an outlet up by exact match instead of guessing from position/type, so it can
# tell "already correct" apart from "same family, wrong type" (retype in place) and
# "different family entirely" (delete and replace) -- see build_marker_tag and
# build_outlets_by_marker_tag.
#
# REQUIRED: this Text instance parameter must exist on every OUTLET family this tool
# targets -- there is no silent fallback. A marker whose target outlet type already
# has an existing instance without this parameter fails resolution up front (see
# check_outlet_type_supports_parameter) with a clear reason, before any ray-casting
# runs for it. A marker whose target type has NO existing instance yet cannot be
# checked that early, so the check happens at creation time instead: if the newly
# placed instance turns out to have no such parameter, apply_marker_outlets deletes
# it again and reports the item failed, rather than leaving an untracked outlet
# behind.
SOURCE_MARKER_TAG_PARAMETER_NAME = "_source_marker_tag"

# REQUIRED, same enforcement as SOURCE_MARKER_TAG_PARAMETER_NAME above. The outlet
# instance itself is placed AT ITS HOST LEVEL with zero elevation offset -- the
# instance's actual Z is never raised to the marker's mount_height. Instead, this
# Length instance parameter is set to that mount_height value, and the outlet
# family's own internal geometry (an offset/extrusion driven by this parameter, set
# up in the Family Editor) is what visually raises the outlet to the right height.
# This keeps the real placement level-hosted and lets Revit schedule/tag the height
# as a normal parameter, instead of it only being implicit in the instance's raw Z.
PLACEMENT_HEIGHT_PARAMETER_NAME = "Placement Height"


def get_marker_para_map(marker):
    """Read and JSON-parse `marker`'s _para_map text parameter.

    Returns PARA_MAP_TEMPLATE's shape with every key defaulted to None, overlaid with
    whatever the parameter actually holds -- missing keys, a missing/empty parameter,
    or unparsable JSON all fall back to the all-None default rather than raising, since
    the vast majority of markers are expected to carry no override at all.
    """
    data = dict(PARA_MAP_TEMPLATE)
    param = marker.LookupParameter(PARA_MAP_PARAMETER_NAME)
    raw = param.AsString() if param else None
    if not raw:
        return data
    try:
        parsed = json.loads(raw)
    except ValueError:
        debug_log(
            "Marker [{}]'s {} is not valid JSON, ignoring: {}".format(
                marker.Id, PARA_MAP_PARAMETER_NAME, raw))
        return data
    if isinstance(parsed, dict):
        data.update(parsed)
    else:
        debug_log(
            "Marker [{}]'s {} parsed as valid JSON but is not an object ({}: {!r}), ignoring.".format(
                marker.Id, PARA_MAP_PARAMETER_NAME, type(parsed).__name__, parsed))
    return data


def set_marker_para_map(marker, data):
    """JSON-serialize `data` and write it into `marker`'s _para_map text parameter.

    Indented (not compact) so a human opening this marker instance inside the
    furniture family sees readable, multi-line JSON in the Properties palette --
    the parameter is Multiline Text specifically to make that legible.

    Must run inside an open transaction. No-ops (with a note) if the marker's family
    has no such parameter -- e.g. an older loaded instance of the family predating
    this parameter's addition.
    """
    param = marker.LookupParameter(PARA_MAP_PARAMETER_NAME)
    if not param:
        ERROR_HANDLE.print_note(
            "Marker [{}] has no {} parameter, cannot write.".format(marker.Id, PARA_MAP_PARAMETER_NAME))
        return
    param.Set(json.dumps(data, indent=2))


def build_marker_tag(scope_doc, marker):
    """Build a string identifying `marker` uniquely, even across documents (the host
    model and any number of links), for tagging the OUTLET it generates.

    Never written to the marker itself -- only ever read from it. `scope_doc.Title`
    disambiguates `marker.UniqueId` (a GUID unique within its own document) across
    documents; the outlet-side tag is what actually gets persisted, always in the
    host document, which is always writable.
    """
    return "{}::{}".format(scope_doc.Title, marker.UniqueId)


def get_outlet_source_marker_tag(instance):
    param = instance.LookupParameter(SOURCE_MARKER_TAG_PARAMETER_NAME)
    return param.AsString() if param else None


def _set_required_outlet_param(instance, param_name, value):
    """Write `value` onto `instance`'s `param_name` parameter (a plain .Set, no type
    coercion beyond what the caller passes in).

    Shared by set_outlet_source_marker_tag and set_outlet_placement_height: both
    parameters are REQUIRED on the outlet family -- a missing parameter here is
    treated as a hard setup error by every caller (see
    check_outlet_type_supports_parameter and apply_marker_outlets), not a silent
    fallback. This function only writes and reports whether it could; it never
    decides what to do about a failure.

    Returns:
        bool: True if the value was written, False if the outlet family has no such
        parameter.
    """
    param = instance.LookupParameter(param_name)
    if not param:
        return False
    param.Set(value)
    return True


def set_outlet_source_marker_tag(instance, tag):
    """Write `tag` (see build_marker_tag) onto `instance`'s source-marker-tag
    parameter. See _set_required_outlet_param for the required-parameter contract.
    """
    return _set_required_outlet_param(instance, SOURCE_MARKER_TAG_PARAMETER_NAME, tag)


def get_outlet_placement_height(instance):
    param = instance.LookupParameter(PLACEMENT_HEIGHT_PARAMETER_NAME)
    return param.AsDouble() if param else None


def set_outlet_placement_height(instance, mount_height):
    """Write `mount_height` onto `instance`'s Placement Height parameter -- the
    family's own internal geometry uses this to visually raise the outlet, since the
    instance itself is placed at its host level with zero elevation offset (see
    PLACEMENT_HEIGHT_PARAMETER_NAME). See _set_required_outlet_param for the
    required-parameter contract.
    """
    return _set_required_outlet_param(instance, PLACEMENT_HEIGHT_PARAMETER_NAME, mount_height)


def set_outlet_schedule_level(instance, level):
    """Best-effort: set `instance`'s Schedule Level parameter to `level` (a DB.Level
    in the SAME document as `instance`).

    Face-based placement via NewFamilyInstance(Reference, ...) does not associate a
    level automatically the way level-hosted placement does -- this leaves Schedule
    Level (BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM) empty, and since
    "Elevation from Level" is CALCULATED from Schedule Level, it shows up empty too
    even though it's not a separate bug -- both symptoms trace to this one missing
    parameter.

    Deliberately best-effort, unlike SOURCE_MARKER_TAG_PARAMETER_NAME/PLACEMENT_
    HEIGHT_PARAMETER_NAME: not every category necessarily exposes this exact
    BuiltInParameter, and a missing Schedule Level is a schedule-correctness issue,
    not a placement-correctness one -- never worth deleting an otherwise
    successfully placed outlet over.

    Returns:
        bool: True if the parameter was found and set, False otherwise.
    """
    param = instance.get_Parameter(DB.BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM)
    if not param:
        return False
    param.Set(level.Id)
    return True


def check_outlet_type_supports_parameter(doc, family_name, type_name, param_name, cache):
    """Return whether an outlet of (family_name, type_name) already placed in `doc`
    has the required `param_name` parameter.

    Returns:
        True/False if an existing instance answered the question definitively, or
        None if no instance of this type exists yet in `doc` -- in that case the
        answer is unknown until the first one is created (apply_marker_outlets
        enforces it there instead; see its to_create handling).

    `cache` is a plain dict the caller owns and reuses across every marker in one
    run, keyed by (family_name, type_name, param_name); only definitive True/False
    answers are cached, never the "unknown" case, since a later marker of the same
    type earlier in the SAME run cannot have created an instance yet either.
    """
    key = (family_name, type_name, param_name)
    if key in cache:
        return cache[key]
    instances = REVIT_FAMILY.get_family_instances_by_family_name_and_type_name(family_name, type_name, doc=doc)
    if not instances:
        return None
    supported = instances[0].LookupParameter(param_name) is not None
    cache[key] = supported
    return supported


def build_outlets_by_marker_tag(doc):
    """One project-wide pass over `doc` (the HOST document -- outlets always live
    there, never in a link), grouping every tagged instance by its
    SOURCE_MARKER_TAG_PARAMETER_NAME value.

    Returns:
        dict {marker_tag (str): DB.FamilyInstance}
    """
    instances = DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).WhereElementIsNotElementType().ToElements()
    by_tag = {}
    for instance in instances:
        tag = get_outlet_source_marker_tag(instance)
        if tag:
            by_tag[tag] = instance
    return by_tag


_run_log_lines = []
_run_log_path = None
_run_log_file = None


def start_run_log():
    """Reset the debug log buffer, pick a fresh timestamped file path, and open it
    for LIVE writing -- every debug_log call below writes and flushes immediately, so
    the file on disk can be tailed WHILE the run is still in progress (e.g. in a
    second window, or by this session checking mid-run), not only after it finishes.
    Call once, at the start of one "Place From Marker" run.
    """
    global _run_log_lines, _run_log_path, _run_log_file
    _run_log_lines = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _run_log_path = FOLDER.get_local_dump_folder_file("MetroTechOutlet_{}.log".format(timestamp))
    try:
        _run_log_file = open(_run_log_path, "w")
    except Exception as e:
        _run_log_file = None
        ERROR_HANDLE.print_note("Failed to open debug log for live writing: {}".format(e))
    for key in _zoom_diagnostics_logged:
        _zoom_diagnostics_logged[key] = False


def debug_log(message):
    """Append one line to this run's debug log, flush it to disk immediately, and
    echo it via ERROR_HANDLE.print_note.

    Unlike print_note (gated on USER.IS_DEVELOPER), the buffered/written copy is
    never gated: the whole point of this per-run log file is that whoever is testing
    the tool can open it WHILE the run is still going (immediate flush) or afterward,
    and see exactly what happened -- not just a developer watching the pyRevit output
    window live.
    """
    _run_log_lines.append(message)
    if _run_log_file is not None:
        try:
            _run_log_file.write(message + "\n")
            _run_log_file.flush()
        except Exception:
            pass
    try:
        ERROR_HANDLE.print_note(message)
    except Exception:
        pass


def save_run_log():
    """Close this run's live log file handle.

    debug_log already writes and flushes every line to disk immediately, so this is
    no longer what actually persists the content -- it just closes the handle
    cleanly. Kept as the caller-facing "finish the log" step (called from
    place_from_markers's `finally`) and to report the final path. Quietly no-ops if
    start_run_log() was never called or nothing was logged.

    Returns:
        str or None: the file path written, or None if there was nothing to save.
    """
    global _run_log_file
    if not _run_log_path or not _run_log_lines:
        return None
    if _run_log_file is not None:
        try:
            _run_log_file.close()
        except Exception as e:
            ERROR_HANDLE.print_note("Failed to close debug log: {}".format(e))
        _run_log_file = None
    return _run_log_path


def type_name_of(family_type):
    return family_type.LookupParameter("Type Name").AsString()


def get_any_3d_view(doc):
    """Return an existing non-template, non-section-boxed 3D view, or create one.

    A view is required by DB.ReferenceIntersector for the marker-driven raycast; a
    plan/section view cannot be used for it. DB.ReferenceIntersector only finds
    geometry inside the view's active section box, if one is set -- a view like a
    "working" view scoped down to one area of the building would silently make every
    ray-cast outside that area come up with zero hits, indistinguishable from "no wall
    nearby" (this is exactly what an out-of-range probe in find_nearest_host_face
    caught: real, plausible coordinates, correct category visibility, correct phase,
    yet nothing found even at unlimited distance -- a section box is the one thing
    that crops visible geometry independently of all of those). So a section-boxed
    view is skipped entirely rather than risked.

    The created view is NOT deleted after use -- it becomes a permanent addition to
    the project (there's no reliable way to "borrow" a view for a single ray-cast and
    clean it back up mid-transaction). Creating a view is a document change and must
    run inside an open transaction, so this opens its own single-purpose one only
    when the fallback is actually needed.
    """
    views = DB.FilteredElementCollector(doc).OfClass(DB.View3D).WhereElementIsNotElementType().ToElements()
    for view in views:
        if not view.IsTemplate and not view.IsSectionBoxActive:
            return view
    view_family_type = next(
        (v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType).ToElements()
         if v.ViewFamily == DB.ViewFamily.ThreeDimensional),
        None)
    if view_family_type is None:
        return None
    t = DB.Transaction(doc, "Create 3D View For Outlet Ray-Cast")
    t.Start()
    try:
        view3d = DB.View3D.CreateIsometric(doc, view_family_type.Id)
        t.Commit()
        return view3d
    except Exception:
        t.RollBack()
        raise


def element_int_id(element):
    """Return an element's ElementId as a plain int (Revit 2026 uses .Value)."""
    try:
        return element.Id.Value
    except AttributeError:
        return element.Id.IntegerValue


def get_level_name(instance, doc):
    level_id = getattr(instance, "LevelId", None)
    if not level_id or level_id == DB.ElementId.InvalidElementId:
        host = getattr(instance, "Host", None)
        level_id = getattr(host, "LevelId", None) if host else None
    if level_id and level_id != DB.ElementId.InvalidElementId:
        level = doc.GetElement(level_id)
        if level:
            return level.Name
    return None


def get_instance_level(doc, instance):
    """Return `instance`'s hosting DB.Level, or None.

    Tries LevelId first (most family instances, including Level-hosted furniture),
    then Host.LevelId (a host-based instance, e.g. wall-hosted). Used to turn a
    marker's _para_map mount_height (feet above its host furniture's level) into an
    absolute Z -- see resolve_marker_targets.
    """
    level_id = getattr(instance, "LevelId", None)
    if not level_id or level_id == DB.ElementId.InvalidElementId:
        host = getattr(instance, "Host", None)
        level_id = getattr(host, "LevelId", None) if host else None
    if level_id and level_id != DB.ElementId.InvalidElementId:
        return doc.GetElement(level_id)
    return None


def build_wall_floor_intersector(view3d):
    """Build the DB.ReferenceIntersector used by every ray of every marker in one run.

    Constructing a ReferenceIntersector is NOT free -- Revit builds a spatial index
    over the view's walls/floors -- so it must be built ONCE per run and reused, not
    rebuilt per ray. Reusing one instance here is a straight ~18x cut to
    intersector-construction overhead versus rebuilding it per ray
    (MARKER_RAYCAST_FAN_COUNT + 2 rays per marker).
    """
    categories = List[DB.BuiltInCategory]([DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_Floors])
    multi_filter = DB.ElementMulticategoryFilter(categories)
    intersector = DB.ReferenceIntersector(multi_filter, DB.FindReferenceTarget.Face, view3d)
    intersector.FindReferencesInRevitLinks = False
    return intersector


def find_host_face_along_ray(doc, intersector, point, direction, avoid_normal_parallel_to=None):
    """Ray-cast from `point` along `direction` for the nearest wall/floor face.

    `intersector` is built once per run by build_wall_floor_intersector and reused
    across every ray of every marker -- see that function's docstring for why.

    `avoid_normal_parallel_to`, if given (e.g. DB.XYZ.BasisZ), rejects this hit when
    the face's own normal is nearly parallel to it (dot product magnitude > 0.99) --
    used for face-based (WorkPlaneBased) placement, where NewFamilyInstance's
    referenceDirection must lie roughly WITHIN the face's plane, not along its
    normal. Without this, a horizontal face (a floor/ceiling/soffit -- nothing
    restricts a WorkPlaneBased family's ray-cast to walls only, unlike a wall-hosted
    OneLevelBasedHosted one) can win the fan-cast and then crash placement with
    "Reference direction is parallel to face normal at insertion point." Rejecting it
    here instead lets a DIFFERENT ray's hit (typically an actual wall) win instead.

    Returns:
        tuple (DB.Element host, DB.Face face, DB.XYZ hit_point, str stable_ref), or
        (None, None, None, None) when nothing is hit within MARKER_RAYCAST_MAX_DISTANCE
        (or the only hit was rejected by avoid_normal_parallel_to).
        `stable_ref` is the Reference's stable representation, so the exact face can
        be re-resolved later (via DB.Reference.ParseFromStableRepresentation) without
        holding the live Face/Reference object across a modeless dialog's idle time.
    """
    hits = intersector.Find(point, direction)
    best = None
    for hit in hits:
        if hit.Proximity > MARKER_RAYCAST_MAX_DISTANCE:
            continue
        if best is None or hit.Proximity < best.Proximity:
            best = hit
    if best is None:
        return None, None, None, None
    reference = best.GetReference()
    host = doc.GetElement(reference)
    face = host.GetGeometryObjectFromReference(reference)
    if avoid_normal_parallel_to is not None:
        try:
            uv = face.Project(reference.GlobalPoint).UVPoint
            normal = face.ComputeNormal(uv)
            if abs(normal.DotProduct(avoid_normal_parallel_to)) > 0.99:
                return None, None, None, None
        except Exception:
            pass  # if the normal can't be computed, don't block placement over a guard check
    stable_ref = reference.ConvertToStableRepresentation(doc)
    return host, face, reference.GlobalPoint, stable_ref


def build_fan_directions(horizontal_count):
    """Return `horizontal_count` evenly-spaced unit vectors around a full horizontal
    circle, plus straight-down and straight-up.

    Horizontal rays find walls; a marker's own rotation cannot be trusted to point
    at one (see MARKER_RAYCAST_FAN_COUNT), so every angle is tried and the nearest
    hit wins. Floors are horizontal planes, so only the vertical rays can hit one --
    no amount of horizontal fan density would.
    """
    directions = []
    for i in range(horizontal_count):
        angle = 2.0 * math.pi * i / horizontal_count
        directions.append(DB.XYZ(math.cos(angle), math.sin(angle), 0.0))
    directions.append(DB.XYZ(0.0, 0.0, -1.0))
    directions.append(DB.XYZ(0.0, 0.0, 1.0))
    return directions


def _log_out_of_range_probe(doc, intersector, point, directions, required_host_type):
    """Diagnostic only -- never affects resolution. Called from find_nearest_host_face
    when the normal fan-cast (bounded by MARKER_RAYCAST_MAX_DISTANCE) finds nothing, to
    re-cast the SAME directions with no distance limit and log the nearest matching
    element actually out there, if any.

    This distinguishes two very different failure modes that otherwise look identical
    ("0 rays hit"): NOTHING found at any distance in any direction (something is
    fundamentally off -- the 3D view's Walls/Floors category visibility or phase
    filter, or the furniture link's placement/shared-coordinates not lining up with
    this document) versus something found just past MARKER_RAYCAST_MAX_DISTANCE (the
    marker really is near a wall/floor, just farther than expected -- a distance-tuning
    problem, not a setup problem).
    """
    nearest = None
    for direction in directions:
        for hit in intersector.Find(point, direction):
            reference = hit.GetReference()
            element = doc.GetElement(reference)
            if required_host_type is not None and not isinstance(element, required_host_type):
                continue
            if nearest is None or hit.Proximity < nearest[0]:
                nearest = (hit.Proximity, element)
    if nearest is None:
        debug_log(
            "  (diagnostic: no matching wall/floor found in ANY direction at ANY distance -- check the 3D "
            "view's category visibility/phase filter for Walls and Floors, and whether the furniture link's "
            "placement (shared coordinates) actually lines up with this document.)")
    else:
        proximity, element = nearest
        debug_log(
            "  (diagnostic: nearest matching element is {} ft away (past the {} ft limit) -- host [{}]. If "
            "this is the intended wall/floor, MARKER_RAYCAST_MAX_DISTANCE may need to be larger.)".format(
                round(proximity, 2), MARKER_RAYCAST_MAX_DISTANCE, element.Id))


def find_nearest_host_face(doc, intersector, point, required_host_type=None, avoid_normal_parallel_to=None):
    """Cast a fan of rays outward from `point` and return the nearest wall/floor hit.

    The marker only carries a position, not a dependable facing rotation, so the
    direction to the host wall/floor cannot be read off its orientation the way a
    single trusted axis would. Trying every direction in the fan and keeping the
    globally nearest hit finds the host regardless of which way the marker sits.

    `intersector` is built once per run by build_wall_floor_intersector and passed
    through here -- see that function's docstring for why it must not be rebuilt per
    ray or per marker.

    `required_host_type`, if given (e.g. DB.Wall), restricts which hits count: a hit
    on a host that is NOT an instance of this type is ignored even if it is the
    nearest ray overall. This matters for a wall-hosted (OneLevelBasedHosted) outlet,
    whose family API can only host on a wall -- without this filter, a floor that
    happens to be marginally closer than the nearest wall would win the fan-cast, and
    placement would then silently fail downstream with no host type to attach to.

    `avoid_normal_parallel_to`, if given (e.g. DB.XYZ.BasisZ), is passed straight
    through to find_host_face_along_ray -- see its docstring. Used for face-based
    (WorkPlaneBased) placement to reject horizontal faces the ray-cast would
    otherwise be free to match, since nothing else restricts that placement type to
    walls only.

    Returns:
        tuple (DB.Element host, DB.Face face, DB.XYZ hit_point, str stable_ref), or
        (None, None, None, None) when nothing matching is hit within
        MARKER_RAYCAST_MAX_DISTANCE in any direction.
    """
    directions = build_fan_directions(MARKER_RAYCAST_FAN_COUNT)
    best = None
    best_distance = None
    hit_count = 0
    for direction in directions:
        host, face, hit_point, stable_ref = find_host_face_along_ray(
            doc, intersector, point, direction, avoid_normal_parallel_to=avoid_normal_parallel_to)
        if host is None:
            continue
        hit_count += 1
        if required_host_type is not None and not isinstance(host, required_host_type):
            continue
        distance = point.DistanceTo(hit_point)
        if best_distance is None or distance < best_distance:
            best = (host, face, hit_point, stable_ref)
            best_distance = distance
    if best is None:
        debug_log(
            "Fan-cast from ({}, {}, {}): 0 of {} rays hit a{} within {} ft".format(
                round(point.X, 2), round(point.Y, 2), round(point.Z, 2), len(directions),
                " matching" if required_host_type is not None else " wall/floor",
                MARKER_RAYCAST_MAX_DISTANCE))
        _log_out_of_range_probe(doc, intersector, point, directions, required_host_type)
        return None, None, None, None
    host, face, hit_point, stable_ref = best
    debug_log(
        "Fan-cast from ({}, {}, {}): {} of {} rays hit; nearest host [{}] at {} ft".format(
            round(point.X, 2), round(point.Y, 2), round(point.Z, 2),
            hit_count, len(directions), host.Id, round(best_distance, 3)))
    return best


def log_view3d_raycast_diagnostics(doc, view3d):
    """Log once per run whether Walls/Floors are actually visible in `view3d` and what
    phase it's showing.

    DB.ReferenceIntersector only finds geometry that is VISIBLE in the view it was built
    from (build_wall_floor_intersector) -- a category hidden by V/G overrides, or a phase
    filter that hides not-yet-existing/demolished elements, makes every ray-cast in the
    whole run come up empty with no error at all, which looks identical to "the marker
    really isn't near a wall/floor." This is a fact worth ruling out up front rather than
    rediscovering it one fan-cast miss at a time -- and unlike _log_out_of_range_probe,
    it does not depend on the view-bound intersector, so it still tells the truth even
    when the category IS hidden (a case the probe alone cannot distinguish from "nothing
    is really there").
    """
    for bic in (DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_Floors):
        category = DB.Category.GetCategory(doc, bic)
        try:
            hidden = view3d.GetCategoryHidden(category.Id) if category else "category not found"
        except Exception as e:
            hidden = "could not check ({})".format(e)
        debug_log("View3D [{}] '{}': {} hidden = {}".format(view3d.Id, view3d.Name, bic, hidden))
    phase = doc.GetElement(view3d.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).AsElementId()) \
        if view3d.get_Parameter(DB.BuiltInParameter.VIEW_PHASE) else None
    debug_log("View3D [{}] '{}': phase = {}".format(
        view3d.Id, view3d.Name, phase.Name if phase else "(none)"))
    # A section box crops which geometry is visible in the view independently of
    # category visibility and phase -- get_any_3d_view already skips a section-boxed
    # view when picking one, but this confirms it explicitly in the log rather than
    # leaving it implicit, in case every existing view happened to have one active.
    debug_log("View3D [{}] '{}': section box active = {}".format(
        view3d.Id, view3d.Name, view3d.IsSectionBoxActive))


def to_host_point(point, link_transform):
    """Map `point` from its scope document's own local space into host-doc
    coordinates via `link_transform`, or return it unchanged when link_transform is
    None (the point already belongs to the host doc). Shared by the marker/furniture
    sanity-check log and zoom_active_view_to_point, so both agree on exactly how a
    link-local point becomes a host-space one.
    """
    return link_transform.OfPoint(point) if link_transform is not None else point


def find_host_level_by_elevation(doc, elevation, cache):
    """Return the DB.Level in `doc` (the HOST document) whose Elevation is closest
    to `elevation` (host-doc-space Z).

    Matches by ELEVATION rather than by level NAME on purpose: different
    consultants/trades often name what is physically the same floor slightly
    differently across linked files (e.g. "4TH FLOOR" vs "Level 4" vs "04 - Fourth
    Floor"), so a name-based match can silently miss or mismatch across documents.
    Elevation is a physical, shared-coordinate-system value every discipline's
    levels should agree on for the same floor, making it the more reliable match
    key -- and Level ElementIds can never be referenced across documents at all, so
    this always resolves against the HOST doc's own levels regardless of which
    document the furniture/marker actually came from.

    `cache` is a plain dict the caller owns, keyed by elevation rounded to 0.01 ft,
    reused across a whole run so repeated markers on the same floor don't re-scan
    every level each time.

    Returns:
        DB.Level or None if `doc` has no levels at all.
    """
    cache_key = round(elevation, 2)
    if cache_key not in cache:
        levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
        best = None
        best_diff = None
        for level in levels:
            diff = abs(level.Elevation - elevation)
            if best_diff is None or diff < best_diff:
                best = level
                best_diff = diff
        cache[cache_key] = best
        if best is not None and best_diff > 1.0:
            debug_log(
                "Host-doc level match: nearest level to elevation {} ft is [{}] '{}' at {} ft -- {} ft off. "
                "If this looks wrong, the host document may be missing a level near this elevation.".format(
                    round(elevation, 2), best.Id, best.Name, round(best.Elevation, 2), round(best_diff, 2)))
    return cache[cache_key]


def find_host_plan_view_for_level(doc, level, cache):
    """Return a non-template 2D plan view in `doc` associated with `level`, cached
    by level.Id across the whole run. Prefers a FloorPlan over other plan view
    types (CeilingPlan, etc.) when more than one exists for the same level.

    Used so zoom_active_view_to_point can switch to a real 2D plan for whichever
    level is currently being processed -- 3D navigation reads poorly for "watch it
    work," and a single fixed 3D camera can't usefully frame one floor at a time
    across a run spanning many levels.

    Returns:
        DB.ViewPlan or None if no plan view in `doc` is associated with this level.
    """
    if level.Id in cache:
        return cache[level.Id]
    views = DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan).WhereElementIsNotElementType().ToElements()
    candidates = [v for v in views if not v.IsTemplate and v.GenLevel is not None and v.GenLevel.Id == level.Id]
    best = next((v for v in candidates if v.ViewType == DB.ViewType.FloorPlan), None)
    if best is None and candidates:
        best = candidates[0]
    cache[level.Id] = best
    return best


_zoom_diagnostics_logged = {"no_match": False, "error": False, "success": False}
_zoom_plan_view_cache = {}
_zoom_last_view_id = [None]


def zoom_active_view_to_point(point, margin=10.0, level=None, fallback_view=None):
    """Best-effort: pan/zoom whatever UIView is showing the active view to frame
    `point` (host-doc coordinates), so a long run is visually watchable instead of a
    frozen screen while it works. Called at the same throttled cadence as the
    progress bar's own updates (progress_step), never per item -- zooming/repainting
    on every single marker across an 800+ item run would be a real performance cost,
    working directly against the fail-fast/iterate-fast goal this tool is built for.

    `level`, if given (a DB.Level in the HOST doc), switches the active view to that
    level's own 2D plan view (find_host_plan_view_for_level) before zooming, so the
    marker/outlet is framed on a real floor plan instead of navigating a single 3D
    camera around the whole building. Falls back to `fallback_view` (the 3D view
    built for ray-casting) if this level has no plan view in the host doc. The view
    is only actually switched when it differs from whatever's already active, to
    avoid a needless view-change (and its own repaint cost) on every call.

    On failure this must never interrupt or fail the run -- but it used to swallow
    EVERY exception with zero logging, which made a silent no-op indistinguishable
    from a working-but-invisible zoom. Each distinct outcome (no matching UIView, an
    exception, or the first confirmed success) is now logged ONCE per run via
    _zoom_diagnostics_logged, so a run where nothing visibly zoomed leaves a clear
    reason in the log instead of just silence.

    RefreshActiveView() alone only REQUESTS a repaint; Revit's UI thread doesn't
    actually paint it until it gets to process its Windows message queue, which a
    tight Python loop never yields to on its own -- without pumping messages here,
    nothing visibly changes on screen until the whole run finishes. Application.
    DoEvents() forces that pump immediately, so the pan/zoom is actually visible
    live instead of a frozen screen that jumps to its final state at the very end.
    """
    try:
        target_view = find_host_plan_view_for_level(DOC, level, _zoom_plan_view_cache) if level is not None else None
        if target_view is None:
            target_view = fallback_view
        if target_view is not None and _zoom_last_view_id[0] != element_int_id(target_view):
            UIDOC.RequestViewChange(target_view)
            _zoom_last_view_id[0] = element_int_id(target_view)

        active_view = UIDOC.ActiveView
        active_id = active_view.Id
        matched = False
        for ui_view in UIDOC.GetOpenUIViews():
            if ui_view.ViewId == active_id:
                matched = True
                corner1 = DB.XYZ(point.X - margin, point.Y - margin, point.Z - margin)
                corner2 = DB.XYZ(point.X + margin, point.Y + margin, point.Z + margin)
                ui_view.ZoomAndCenterRectangle(corner1, corner2)
                break
        if matched and not _zoom_diagnostics_logged["success"]:
            debug_log(
                "zoom_active_view_to_point: first zoom succeeded, on active view [{}] '{}' ({}).".format(
                    active_id, active_view.Name, active_view.ViewType))
            _zoom_diagnostics_logged["success"] = True
        if not matched and not _zoom_diagnostics_logged["no_match"]:
            debug_log(
                "zoom_active_view_to_point: active view [{}] '{}' ({}) has no open UIView -- nothing to zoom. "
                "Keep that exact view open and active for the whole run to see it live.".format(
                    active_id, active_view.Name, active_view.ViewType))
            _zoom_diagnostics_logged["no_match"] = True
        UIDOC.RefreshActiveView()
        Application.DoEvents()
        if matched:
            time.sleep(ZOOM_PAUSE_SECONDS)
    except Exception as e:
        if not _zoom_diagnostics_logged["error"]:
            debug_log("zoom_active_view_to_point failed (logged once, run continues): {}".format(e))
            _zoom_diagnostics_logged["error"] = True


def set_progress_title(pb, verb, level_name, family_name=None, type_name=None, mount_height=None):
    """Update `pb.title` with the CURRENT item's context (level, and when available
    outlet family/type/mount height), so the progress bar itself shows what's being
    worked on instead of just a bare item count.

    Safe to call every iteration regardless of progress_step: setting a Python
    attribute is cheap, and pyRevit's own forms.ProgressBar only actually repaints
    the title on screen every `step` calls to update_progress() (the same step value
    this tool already passes as progress_step) -- see forms.ProgressBar._update_pbar
    and .update_progress in pyRevit's own source. So this piggybacks on throttling
    pyRevit already does internally, rather than needing its own progress_step gate.

    `{{value}}`/`{{max_value}}` (escaped braces) are left as literal `{value}`/
    `{max_value}` placeholders for pyRevit's OWN renderer to fill in on the next
    actual repaint -- see forms.ProgressBar._update_pbar, which formats `pb.title`
    against those two keys.
    """
    level_label = level_name or "?"
    if family_name and type_name and mount_height is not None:
        detail = "{} - {} @ {} ({} ft)".format(family_name, type_name, level_label, mount_height)
    elif family_name and type_name:
        detail = "{} - {} @ {}".format(family_name, type_name, level_label)
    else:
        detail = level_label
    pb.title = "{}: {} ({{value}} of {{max_value}})".format(verb, detail)


def get_search_scopes(doc):
    """Return every (search_doc, link_transform, link_instance) scope to search for
    furniture/markers: the host document itself (link_transform=None,
    link_instance=None), plus one entry per loaded, resolvable RevitLinkInstance
    PLACEMENT in the host document -- not one per unique linked file, since the same
    link file placed more than once (e.g. a repeated site/context link) needs its own
    transform applied to each placement separately. An unloaded link
    (GetLinkDocument() returns None) is skipped.

    `link_instance` (the placement element itself, not just its transform) is needed
    by find_nearest_furniture_face's caller to build a combined link Reference
    (Reference.CreateLinkReference) when a furniture_vertical/furniture_horizontal
    target's host furniture instance lives inside a link -- a bare Reference obtained
    from geometry inside the link document is not resolvable against the HOST
    document on its own.
    """
    scopes = [(doc, None, None)]
    link_instances = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance).WhereElementIsNotElementType().ToElements()
    for link_instance in link_instances:
        link_doc = link_instance.GetLinkDocument()
        if link_doc is None:
            continue
        scopes.append((link_doc, link_instance.GetTotalTransform(), link_instance))
    return scopes


def discover_qualified_furniture_family_names(doc):
    """Scan `doc` for every family instance carrying a _para_map parameter (a marker,
    by convention), walk each one up to its host furniture instance via
    SuperComponent, and return the distinct furniture family names found.

    This is the whole reason a furniture family name is never hardcoded in this file:
    any family that happens to nest a _para_map-carrying marker qualifies
    automatically, so a new furniture family with markers needs zero code changes --
    it just shows up in the picker place_from_markers shows next.
    """
    instances = DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).WhereElementIsNotElementType().ToElements()
    names = set()
    for instance in instances:
        if instance.LookupParameter(PARA_MAP_PARAMETER_NAME) is None:
            continue
        furniture = getattr(instance, "SuperComponent", None)
        if furniture is None:
            continue
        # Walk all the way to the TOP-level host: a marker nested more than one
        # FamilyInstance level deep (furniture -> sub-assembly -> marker) must still
        # report the true top-level furniture family, not an intermediate one.
        while getattr(furniture, "SuperComponent", None) is not None:
            furniture = furniture.SuperComponent
        name = REVIT_FAMILY.get_family_name(furniture)
        if name:
            names.add(name)
    return sorted(names)


def get_furniture_instances(doc, family_names):
    """Return every top-level FamilyInstance in `doc` whose family name is in
    `family_names` (a subset picked from discover_qualified_furniture_family_names).
    """
    instances = DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).WhereElementIsNotElementType().ToElements()
    return [instance for instance in instances if REVIT_FAMILY.get_family_name(instance) in family_names]


def build_para_map_markers_by_furniture_id(doc):
    """One project-wide pass over `doc`: group every _para_map-carrying instance by
    its top-level host furniture instance's ElementId (walking SuperComponent all the
    way up, same as discover_qualified_furniture_family_names).

    Returns:
        dict {furniture_id (int): [marker, ...]}

    Deliberately a project-wide collector + SuperComponent walk-up, NOT
    host_instance.GetDependentElements() per furniture instance. This matches the
    library's own established pattern for Shared nested families --
    REVIT_FAMILY.get_shared_nested_instances_by_family_name's docstring explicitly
    says a Shared nested family "registers as its own first-class element... found
    directly with a project-wide collector INSTEAD OF walking every host's
    dependents." A marker needs to be independently selectable/editable in the model
    (to hand-edit its _para_map, see that parameter's own comment above), which is
    exactly what marking a nested family Shared is for -- so this file never assumes
    GetDependentElements reliably surfaces it, and does one full-document scan per
    search scope instead (cheap relative to the ray-casting this run already does).
    """
    instances = DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).WhereElementIsNotElementType().ToElements()
    by_furniture_id = {}
    for instance in instances:
        if instance.LookupParameter(PARA_MAP_PARAMETER_NAME) is None:
            continue
        top = instance
        while getattr(top, "SuperComponent", None) is not None:
            top = top.SuperComponent
        if top.Id == instance.Id:
            continue  # not nested inside anything -- not a marker under this convention
        by_furniture_id.setdefault(element_int_id(top), []).append(instance)
    return by_furniture_id


def resolve_outlet_symbol(doc, family_name, type_name, cache):
    """Resolve an outlet family/type by name, once per (family_name, type_name) pair.

    `cache` is a plain dict the caller owns and reuses across every marker in one run,
    since many markers typically name the same outlet family/type in their _para_map.

    Returns:
        tuple (DB.Family family, DB.FamilySymbol family_type); either may be None.
    """
    key = (family_name, type_name)
    if key not in cache:
        family = REVIT_FAMILY.get_family_by_name(family_name, doc=doc)
        family_type = REVIT_FAMILY.get_family_type_by_name(family_name, type_name, doc=doc) if family else None
        cache[key] = (family, family_type)
    return cache[key]


def get_instance_solid_faces(instance):
    """Yield tuple (face, transform) for every Face of every Solid in `instance`'s
    own geometry.

    Uses GetSymbolGeometry() on GeometryInstance objects so that face.Reference
    points to the true original symbol geometry (required by Revit API for
    face-based hosting and CreateLinkReference), and accumulates the spatial
    transform so callers can evaluate positions in scope_doc space.
    """
    options = DB.Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = DB.ViewDetailLevel.Fine
    geometry = instance.get_Geometry(options)
    if geometry is None:
        return
    stack = [(geometry, DB.Transform.Identity)]
    while stack:
        current_elem, current_transform = stack.pop()
        for geom_object in current_elem:
            if isinstance(geom_object, DB.Solid):
                if geom_object.Faces.Size == 0 or getattr(geom_object, "Volume", 1.0) <= 0.0001:
                    continue
                for face in geom_object.Faces:
                    if face.Reference is not None:
                        yield (face, current_transform)
            elif isinstance(geom_object, DB.GeometryInstance):
                try:
                    inst_transform = current_transform.Multiply(geom_object.Transform)
                    symbol_geom = geom_object.GetSymbolGeometry()
                    if symbol_geom is not None:
                        stack.append((symbol_geom, inst_transform))
                except Exception:
                    pass


def find_nearest_furniture_face(furniture, point, want_vertical):
    """Scan `furniture`'s own solid geometry for the nearest face whose normal is
    vertical (`want_vertical=True`) or horizontal (`False`), within
    MARKER_RAYCAST_MAX_DISTANCE of `point` (in scope_doc space).

    Uses GetSymbolGeometry() via get_instance_solid_faces to preserve original
    symbol face references for NewFamilyInstance hosting, while transforming test
    points into local symbol coordinates for geometric projection. For vertical
    faces, automatically clamps the probe Z to within the face's vertical limits so
    markers modeled above the furniture body do not miss the face due to boundary loops.

    Returns:
        tuple (DB.Face, DB.XYZ nearest_point_on_face) or (None, None) if nothing
        qualifying is within range. `nearest_point_on_face` is in scope_doc space.
    """
    best_face = None
    best_point = None
    best_distance = None
    best_is_planar = False
    evaluated_count = 0
    for face, transform in get_instance_solid_faces(furniture):
        evaluated_count += 1
        try:
            inv_transform = transform.Inverse
            pt_local = inv_transform.OfPoint(point)
        except Exception:
            continue

        is_planar = isinstance(face, DB.PlanarFace)
        scope_normal = None
        if is_planar:
            try:
                local_normal = face.FaceNormal
                scope_normal = transform.OfVector(local_normal).Normalize()
            except Exception:
                scope_normal = None

        if scope_normal is not None:
            normal_z = abs(scope_normal.Z)
            if want_vertical and normal_z > FURNITURE_FACE_VERTICAL_NORMAL_Z_MAX:
                continue
            if not want_vertical and normal_z < FURNITURE_FACE_HORIZONTAL_NORMAL_Z_MIN:
                continue

        test_pt = pt_local
        if want_vertical:
            try:
                mesh = face.Triangulate()
                if mesh is not None and mesh.Vertices.Count > 0:
                    min_z = min(v.Z for v in mesh.Vertices)
                    max_z = max(v.Z for v in mesh.Vertices)
                    if max_z - min_z > 0.02:
                        clamped_z = max(min_z + 0.01, min(max_z - 0.01, pt_local.Z))
                        test_pt = DB.XYZ(pt_local.X, pt_local.Y, clamped_z)
            except Exception:
                test_pt = pt_local

        candidate_local = None
        try:
            proj = face.Project(test_pt)
            if proj is not None:
                candidate_local = proj.XYZPoint
        except Exception:
            proj = None

        if candidate_local is None:
            best_edge_dist = None
            try:
                for edge_loop in face.EdgeLoops:
                    for edge in edge_loop.Edges:
                        eproj = edge.Project(test_pt)
                        if eproj is not None:
                            edist = test_pt.DistanceTo(eproj.XYZPoint)
                            if best_edge_dist is None or edist < best_edge_dist:
                                best_edge_dist = edist
                                candidate_local = eproj.XYZPoint
            except Exception:
                pass
            if candidate_local is None or (best_edge_dist is not None and best_edge_dist > 1.0):
                continue

        if scope_normal is None:
            try:
                proj_uv = face.Project(candidate_local)
                uv = proj_uv.UVPoint if proj_uv else DB.UV(0.5, 0.5)
                local_normal = face.ComputeNormal(uv)
                scope_normal = transform.OfVector(local_normal).Normalize()
            except Exception:
                continue
            normal_z = abs(scope_normal.Z)
            if want_vertical and normal_z > FURNITURE_FACE_VERTICAL_NORMAL_Z_MAX:
                continue
            if not want_vertical and normal_z < FURNITURE_FACE_HORIZONTAL_NORMAL_Z_MIN:
                continue

        candidate_scope = transform.OfPoint(candidate_local)
        distance = point.DistanceTo(candidate_scope)
        if distance > MARKER_RAYCAST_MAX_DISTANCE:
            continue

        if best_distance is None:
            better = True
        elif is_planar and not best_is_planar:
            better = True
        elif not is_planar and best_is_planar:
            better = False
        else:
            better = distance < best_distance

        if better:
            best_face = face
            best_point = candidate_scope
            best_distance = distance
            best_is_planar = is_planar

    if best_face is not None:
        debug_log(
            "  (furniture [{}] {} face match: evaluated {} faces, best planar={}, distance={} ft, hit_point={})".format(
                furniture.Id, "vertical" if want_vertical else "horizontal", evaluated_count,
                best_is_planar, round(best_distance, 3),
                (round(best_point.X, 2), round(best_point.Y, 2), round(best_point.Z, 2))))
    return best_face, best_point


def _resolve_one_marker(doc, scope_doc, link_transform, link_instance, furniture, furniture_level, marker,
                         intersector, symbol_cache, tag_support_cache):
    """Resolve one marker to its outlet symbol and host face, or the reason it can't be.

    `link_instance` is the RevitLinkInstance PLACEMENT `furniture` was found under, or
    None when `furniture` lives directly in the host document (see get_search_scopes).
    Needed only by the furniture_vertical/furniture_horizontal branch, to build a
    combined link Reference when the target face itself lives inside a link.

    Isolated into its own function so resolve_marker_targets can wrap a single call in
    try/except: a per-marker error (e.g. a hand-edited _para_map with a non-numeric
    mount_height) must fail that ONE marker, never abort the whole run.

    Returns:
        tuple (reason, host, face, hit_point, stable_ref, family, family_type,
        mount_height, level_name, is_horizontal, host_level_elevation).
        `reason` is None on success; every other field is None (or False) when
        `reason` is set.
    """
    para_map = get_marker_para_map(marker)
    if any(value is not None for value in para_map.values()):
        debug_log("Marker [{}] {}: {}".format(marker.Id, PARA_MAP_PARAMETER_NAME, para_map))

    outlet_family_name = para_map.get("family_name")
    outlet_type_name = para_map.get("type_name")
    mount_height = para_map.get("mount_height")
    target = para_map.get("target")
    def _fail(reason):
        return (reason, None, None, None, None, None, None, None, None, False, None)

    if not outlet_family_name or not outlet_type_name or mount_height is None or not target:
        return _fail("{} needs family_name, type_name, mount_height, and target all set".format(PARA_MAP_PARAMETER_NAME))
    if target not in VALID_TARGETS:
        return _fail("{} has invalid target {!r} -- must be one of {}".format(
            PARA_MAP_PARAMETER_NAME, target, VALID_TARGETS))

    family, family_type = resolve_outlet_symbol(doc, outlet_family_name, outlet_type_name, symbol_cache)
    if not family or not family_type:
        return _fail("outlet [{}] - [{}] is not loaded".format(outlet_family_name, outlet_type_name))

    # SOURCE_MARKER_TAG_PARAMETER_NAME and PLACEMENT_HEIGHT_PARAMETER_NAME are both
    # required, no silent fallback. If an outlet of this exact type already exists,
    # check both now and fail fast before any ray-casting; if none exists yet, this
    # can't be known until the first one is created (apply_marker_outlets enforces it
    # there instead).
    for required_param_name in (SOURCE_MARKER_TAG_PARAMETER_NAME, PLACEMENT_HEIGHT_PARAMETER_NAME):
        supported = check_outlet_type_supports_parameter(
            doc, outlet_family_name, outlet_type_name, required_param_name, tag_support_cache)
        if supported is False:
            return _fail("outlet [{}] - [{}] is missing the required {} parameter -- add it to the family in the "
                         "Family Editor, then rerun".format(outlet_family_name, outlet_type_name, required_param_name))

    if family.FamilyPlacementType not in (DB.FamilyPlacementType.WorkPlaneBased, DB.FamilyPlacementType.OneLevelBasedHosted):
        return _fail("outlet [{}] is neither face-based nor wall-hosted".format(outlet_family_name))

    # target drives the search rule, but it must still be mechanically possible for
    # THIS outlet family to be placed that way. Only a wall-hosted (OneLevelBasedHosted)
    # family is placed via place_instance_by_wall (do_create) -- every other target
    # (floor, and both furniture targets) needs a face Reference, which only a
    # face-based (WorkPlaneBased) family can use.
    if target != TARGET_WALL and family.FamilyPlacementType != DB.FamilyPlacementType.WorkPlaneBased:
        return _fail("outlet [{}] target {!r} needs a face-based (WorkPlaneBased) family, but it is wall-hosted "
                     "(OneLevelBasedHosted)".format(outlet_family_name, target))

    if furniture_level is None:
        return _fail("host furniture [{}] has no level".format(furniture.Id))

    local_point, _orientation = REVIT_FAMILY.get_nested_instance_placement(marker)
    if local_point is None:
        return _fail("no location available")

    # The outlet is placed AT its host level, zero elevation offset -- mount_height is
    # never baked into the instance's real Z. Instead it gets written onto the
    # PLACEMENT_HEIGHT_PARAMETER_NAME parameter (see apply_marker_outlets), and the
    # outlet family's own internal geometry is what visually raises it to that height.
    # So the ray-cast target Z here is just the furniture's level elevation.
    corrected_point = DB.XYZ(local_point.X, local_point.Y, furniture_level.Elevation)
    if link_transform is not None:
        corrected_point = link_transform.OfPoint(corrected_point)
    debug_log(
        "Marker [{}]: furniture [{}] level [{}] (elev {}) -> corrected point {} (mount_height {} goes onto "
        "the {} parameter, not the instance Z)".format(
            marker.Id, furniture.Id, furniture_level.Name, round(furniture_level.Elevation, 2),
            (round(corrected_point.X, 2), round(corrected_point.Y, 2), round(corrected_point.Z, 2)),
            mount_height, PLACEMENT_HEIGHT_PARAMETER_NAME))

    # Sanity check, diagnostic only: the furniture instance's OWN position, mapped
    # through the same link_transform used for the marker. The marker should land a
    # few feet from its own host furniture -- if this distance is huge (tens/hundreds
    # of feet, or a wildly different Z), the bug is in resolving marker/furniture
    # coordinates through the link, not in the wall/floor search that follows.
    furniture_point = get_instance_point(furniture)
    if furniture_point is not None:
        furniture_point_in_host = to_host_point(furniture_point, link_transform)
        debug_log(
            "  (sanity check: furniture [{}] itself is at {} in host coordinates -- {} ft from the marker's "
            "corrected point above; if that's more than a few feet, marker/furniture coordinate resolution "
            "through the link is the bug, not the wall/floor search.)".format(
                furniture.Id,
                (round(furniture_point_in_host.X, 2), round(furniture_point_in_host.Y, 2),
                 round(furniture_point_in_host.Z, 2)),
                round(furniture_point_in_host.DistanceTo(corrected_point), 2)))

    if target in (TARGET_WALL, TARGET_FLOOR):
        required_host_type = DB.Wall if target == TARGET_WALL else DB.Floor
        # Face-based placement always uses DB.XYZ.BasisZ as its reference_direction
        # (do_create -- Place on Vertical Face), which Revit rejects if it's parallel
        # to the matched face's own normal (a horizontal face -- floor/ceiling/soffit).
        # Only guards the wall search: a floor target WANTS a horizontal face.
        avoid_normal_parallel_to = DB.XYZ.BasisZ if target == TARGET_WALL else None
        host, face, hit_point, stable_ref = find_nearest_host_face(
            doc, intersector, corrected_point, required_host_type=required_host_type,
            avoid_normal_parallel_to=avoid_normal_parallel_to)
        if host is None:
            return _fail("no {} within {} ft in any direction".format(target, MARKER_RAYCAST_MAX_DISTANCE))
    else:
        # furniture_vertical / furniture_horizontal: search the marker's OWN host
        # furniture instance's geometry only (find_nearest_furniture_face), never a
        # neighboring instance even if closer.
        want_vertical = target == TARGET_FURNITURE_VERTICAL
        search_point = local_point
        if want_vertical and furniture_level is not None:
            # Markers are deliberately modeled above furniture geometry (for visibility
            # and pickability). For vertical faces, projecting a point whose Z is above the
            # top edge of the face results in Face.Project returning None (outside face
            # boundary). We probe at the intended mount height (furniture_level.Elevation + mount_height)
            # which is within the vertical face's Z bounds.
            probe_z = furniture_level.Elevation + (mount_height or 0.0)
            search_point = DB.XYZ(local_point.X, local_point.Y, probe_z)

        face, local_hit_point = find_nearest_furniture_face(furniture, search_point, want_vertical)
        if face is None and search_point != local_point:
            face, local_hit_point = find_nearest_furniture_face(furniture, local_point, want_vertical)

        if face is None:
            return _fail("no {} furniture face within {} ft on host furniture [{}]".format(
                "vertical" if want_vertical else "horizontal", MARKER_RAYCAST_MAX_DISTANCE, furniture.Id))
        host = furniture
        hit_point = local_hit_point if link_transform is None else link_transform.OfPoint(local_hit_point)
        # A bare face.Reference is only resolvable against the document it was
        # computed in. When `furniture` lives inside a link, that reference must be
        # wrapped into a combined link reference (valid against the HOST doc) before
        # it can ever be parsed back and used for NewFamilyInstance placement.
        if face.Reference is None:
            return _fail("host furniture [{}] face has no valid Revit reference".format(furniture.Id))
        elif link_instance is None:
            stable_ref = face.Reference.ConvertToStableRepresentation(doc)
        else:
            stable_ref = face.Reference.CreateLinkReference(link_instance).ConvertToStableRepresentation(doc)

    is_horizontal = (target in (TARGET_FLOOR, TARGET_FURNITURE_HORIZONTAL))
    host_level_elevation = to_host_point(
        DB.XYZ(0, 0, furniture_level.Elevation), link_transform).Z if furniture_level else None

    return (None, host, face, hit_point, stable_ref, family, family_type, mount_height,
            furniture_level.Name, is_horizontal, host_level_elevation)


def resolve_marker_targets(doc, furniture_family_names, view3d, symbol_cache, scopes):
    """Find every instance of `furniture_family_names` across every search scope (the
    host document plus every loaded link -- see get_search_scopes), and within each
    one, every nested marker (build_para_map_markers_by_furniture_id). Each marker's
    own _para_map names the outlet family/type and mount height to place there, so
    this also resolves that outlet symbol and fan-casts the marker's corrected point
    to its host face (see _resolve_one_marker for the per-marker logic).

    A furniture instance can nest more than one marker (each independently naming its
    own outlet/height), so the ray-cast target Z always comes from the FURNITURE
    instance's own level elevation (zero offset) -- never the marker's raw Z. Only
    the marker's X/Y are taken as-is. The outlet's real-world height is never baked
    into its instance Z at all; mount_height is written onto
    PLACEMENT_HEIGHT_PARAMETER_NAME instead (see apply_marker_outlets), and the
    outlet family's own internal geometry does the visual raising.

    `scopes` is a list of (search_doc, link_transform) pairs from get_search_scopes;
    the corrected point is built in each entry's own `search_doc` local space (X/Y
    raw, Z corrected) and only mapped into host-doc space via `link_transform` when
    it is not None, since the ray-cast and every downstream placement always target
    the CURRENT (host) document's walls/floors -- never a link's.
    `symbol_cache` is a plain dict the caller owns, passed straight through to
    resolve_outlet_symbol so repeated (family_name, type_name) pairs are only looked
    up once for the whole run.

    Fails fast, scoped PER FURNITURE FAMILY: if CONSECUTIVE_UNRESOLVED_ABORT_THRESHOLD
    markers of the SAME selected furniture family in a row hit the exact same
    unresolved reason, that family's remaining markers are skipped -- a repeated
    identical reason is a systemic setup problem for that family, not independent
    one-off marker issues, so continuing wastes time without finding anything new.
    Other selected families are entirely unaffected (each gets its own fresh streak).

    Returns:
        tuple (resolved, unresolved):
          resolved   -- list of (marker, marker_tag, host, face, hit_point, stable_ref,
                        family, family_type, mount_height, level_name, is_horizontal,
                        host_level_elevation)
          unresolved -- list of (marker, reason) for markers that can't be placed
    """
    entries_by_family = {}
    for family_name in furniture_family_names:
        entries_by_family[family_name] = []

    for scope_doc, link_transform, link_instance in scopes:
        furniture_instances = get_furniture_instances(scope_doc, furniture_family_names)
        markers_by_furniture_id = build_para_map_markers_by_furniture_id(scope_doc)
        debug_log("Found {} furniture instance(s) of {} in [{}]".format(
            len(furniture_instances), furniture_family_names, scope_doc.Title))
        for furniture in furniture_instances:
            furniture_level = get_instance_level(scope_doc, furniture)
            markers = markers_by_furniture_id.get(element_int_id(furniture), [])
            furniture_family_name = REVIT_FAMILY.get_family_name(furniture)
            debug_log("Furniture [{}] ({}) in [{}]: {} marker(s), level [{}]".format(
                furniture.Id, furniture_family_name, scope_doc.Title, len(markers),
                furniture_level.Name if furniture_level else "NONE"))
            entries_by_family.setdefault(furniture_family_name, [])
            for marker in markers:
                entries_by_family[furniture_family_name].append(
                    (furniture, furniture_level, marker, scope_doc, link_transform, link_instance))

    intersector = build_wall_floor_intersector(view3d)
    tag_support_cache = {}
    level_by_elevation_cache = {}

    resolved = []
    unresolved = []

    total_markers = sum(len(entries) for entries in entries_by_family.values())
    # step > 1 for a large batch: a live repaint on every single marker (e.g. all 800+
    # of them) is wasted UI overhead once the bar is already fine-grained enough to be
    # useful -- one visible tick per ~1% of the run reads just as smoothly.
    progress_step = max(1, total_markers // 100)
    processed = 0
    user_cancelled = False

    with forms.ProgressBar(
            title="Resolving outlet markers... ({value} of {max_value})",
            step=1, cancellable=True) as pb:

        for family_name in furniture_family_names:
            if user_cancelled:
                break
            entries = entries_by_family.get(family_name, [])
            streak_reason = None
            streak_count = 0

            for index, (furniture, furniture_level, marker, scope_doc, link_transform, link_instance) in enumerate(entries):
                try:
                    reason, host, face, hit_point, stable_ref, family, family_type, mount_height, level_name, \
                        is_horizontal, host_level_elevation = _resolve_one_marker(
                            doc, scope_doc, link_transform, link_instance, furniture, furniture_level, marker,
                            intersector, symbol_cache, tag_support_cache)
                except Exception as e:
                    reason = "internal error: {}".format(e)
                    host = face = hit_point = stable_ref = family = family_type = mount_height = level_name = \
                        host_level_elevation = None
                    is_horizontal = False

                processed += 1
                set_progress_title(
                    pb, "Resolving", level_name or (furniture_level.Name if furniture_level else None),
                    family.Name if family else None, type_name_of(family_type) if family_type else None,
                    mount_height)
                pb.update_progress(processed, total_markers)
                if processed % progress_step == 0:
                    furniture_point = get_instance_point(furniture)
                    if furniture_point is not None and furniture_level is not None:
                        host_furniture_point = to_host_point(furniture_point, link_transform)
                        host_level_elev_for_zoom = host_level_elevation if host_level_elevation is not None else to_host_point(
                            DB.XYZ(0, 0, furniture_level.Elevation), link_transform).Z
                        host_level = find_host_level_by_elevation(
                            doc, host_level_elev_for_zoom, level_by_elevation_cache)
                        zoom_active_view_to_point(host_furniture_point, level=host_level, fallback_view=view3d)

                if reason is None:
                    marker_tag = build_marker_tag(scope_doc, marker)
                    resolved.append(
                        (marker, marker_tag, host, face, hit_point, stable_ref, family, family_type, mount_height,
                         level_name, is_horizontal, host_level_elevation))
                    streak_reason = None
                    streak_count = 0
                else:
                    unresolved.append((marker, reason))
                    if reason == streak_reason:
                        streak_count += 1
                    else:
                        streak_reason = reason
                        streak_count = 1
                    if streak_count >= CONSECUTIVE_UNRESOLVED_ABORT_THRESHOLD:
                        remaining = len(entries) - index - 1
                        debug_log(
                            "Aborting furniture family [{}] early: {} consecutive markers failed with the same "
                            "reason [{}] -- likely a systemic model/family setup issue for this family, not "
                            "independent per-marker problems. Skipping its remaining {} marker(s); other selected "
                            "families are unaffected. Fix the root cause and rerun.".format(
                                family_name, streak_count, reason, remaining))
                        break

                if pb.cancelled:
                    user_cancelled = True
                    debug_log(
                        "User cancelled resolving after {} of {} marker(s); {} family/families not yet reached "
                        "are skipped entirely, and the current family's remaining markers are skipped too.".format(
                            processed, total_markers, len(furniture_family_names)))
                    break

    debug_log("resolve_marker_targets: {} resolved, {} unresolved{}".format(
        len(resolved), len(unresolved), " (cancelled early)" if user_cancelled else ""))
    return resolved, unresolved


def get_instance_point(instance):
    location = getattr(instance, "Location", None)
    point = getattr(location, "Point", None) if location else None
    if point is None and hasattr(instance, "GetTransform"):
        point = instance.GetTransform().Origin
    return point


def find_nearby_instance(point, instances, radius):
    nearest = None
    nearest_distance = None
    for instance in instances:
        instance_point = get_instance_point(instance)
        if instance_point is None:
            continue
        distance = point.DistanceTo(instance_point)
        if distance <= radius and (nearest_distance is None or distance < nearest_distance):
            nearest = instance
            nearest_distance = distance
    return nearest, nearest_distance


def apply_marker_outlets(to_create, to_replace, to_update, to_retag, view3d):
    """Create, replace, move/retype, or retag outlets in one transaction.

    Called directly and synchronously from place_from_markers, which is itself
    already running in Revit's API context (the button's own entry point) -- there
    is no modeless review step in this flow, so no ExternalEvent is needed.

    - `to_create`: list of (OutletPlacementTarget, marker_tag) -- nothing exists for
      this marker yet; place it (at its host level, zero elevation offset -- see
      OutletPlacementTarget), tag it, and set its Placement Height.
    - `to_replace`: list of (old_instance_id, OutletPlacementTarget, marker_tag) --
      the tagged/matched existing instance is a DIFFERENT FAMILY than the marker now
      targets; Revit cannot reassign an instance across families (only across types
      within the same family), so the old one is deleted and a new one created,
      tagged, and height-set in its place.
    - `to_update`: list of (instance_id, target_point, new_type_name_or_None,
      marker_tag, mount_height, level_name) -- the existing instance is already the
      correct family. If `new_type_name_or_None` is set, its type differs and gets
      swapped via `Symbol =` (same-family retype, no delete needed); either way it is
      moved to `target_point`, re-tagged, and its Placement Height is (re)set to
      `mount_height` -- this can be the ONLY thing that changed, since mount_height no
      longer affects `target_point` at all (see PLACEMENT_HEIGHT_PARAMETER_NAME).
    - `to_retag`: list of (instance_id, marker_tag, mount_height, level_name) -- a
      legacy, untagged instance that already exactly matches its marker's target
      family/type/position (found by position+type proximity, which never checks
      height); the tag AND Placement Height are (re)written unconditionally, so a
      future run finds it directly instead of falling back to position/type matching
      again, and its height is guaranteed correct rather than assumed.

    `level_name` (the HOST FURNITURE's level, e.g. "4TH FLOOR") is carried purely for
    the per-level summary this function returns -- see level_stats below.

    Returns:
        tuple (result, stats):
          result -- the human-readable summary string (also written to the debug log).
          stats  -- dict {"touched_ids": [int, ...], "failed_count": int,
                    "required_param_failed": int, "user_cancelled": bool}, used by
                    place_from_markers to decide whether the run counts as fully
                    successful and, if so, what to offer saving as a Revit selection
                    (see offer_save_run_selection).
    """
    doc = DOC
    symbol_cache = {}

    def resolve_symbol(family_name, type_name):
        key = (family_name, type_name)
        if key not in symbol_cache:
            family = REVIT_FAMILY.get_family_by_name(family_name, doc=doc)
            family_type = REVIT_FAMILY.get_family_type_by_name(family_name, type_name, doc=doc) if family else None
            symbol_cache[key] = family_type
        return symbol_cache[key]

    level_by_elevation_cache = {}
    _schedule_level_missing_logged = [False]

    def apply_schedule_level(instance, elevation):
        """Best-effort: set `instance`'s Schedule Level to the host-doc level nearest
        `elevation` (see find_host_level_by_elevation and set_outlet_schedule_level).
        Silently no-ops (after one log line for the whole run) if the host doc has no
        levels at all -- never blocks or fails the item over this, since it's a
        schedule-correctness nicety, not a placement one.

        Returns:
            DB.Level or None -- the matched host level, so callers (the zoom call
            right after) can switch to its plan view without a duplicate lookup.
        """
        host_level = find_host_level_by_elevation(doc, elevation, level_by_elevation_cache) \
            if elevation is not None else None
        if host_level is None:
            if not _schedule_level_missing_logged[0]:
                debug_log(
                    "Could not find any host-doc level to set as Schedule Level (logged once) -- Schedule "
                    "Level/Elevation from Level will stay empty.")
                _schedule_level_missing_logged[0] = True
            return None
        set_outlet_schedule_level(instance, host_level)
        return host_level

    def do_create(item):
        family_type = resolve_symbol(item.family_name, item.type_name)
        if not family_type:
            debug_log("Outlet [{}] - [{}] is no longer loaded, skipping host [{}].".format(
                item.family_name, item.type_name, item.host_id))
            return None
        host = doc.GetElement(DB.ElementId(item.host_id))
        point = DB.XYZ(item.point[0], item.point[1], item.point[2])
        if item.stable_ref:
            reference = DB.Reference.ParseFromStableRepresentation(doc, item.stable_ref)
            # Pass the Reference straight to NewFamilyInstance rather than extracting a
            # DB.Face from it first (host.GetGeometryObjectFromReference(reference)) --
            # that Face's internal .Reference isn't reliably populated for every host
            # face type, which fails with "The Reference of the input face is null"
            # even though the Face DID come from a Reference (see
            # REVIT_FAMILY.place_instance_by_reference's docstring).
            # For vertical faces (walls, furniture panels), DB.XYZ.BasisZ keeps the
            # instance plumb ("Place on Vertical Face"). For horizontal faces (floors,
            # desk tops), BasisZ is parallel to the face normal and Revit throws:
            # "Reference direction is parallel to face normal at insertion point."
            # Passing BasisX avoids this crash while keeping the instance aligned on the plane.
            ref_dir = DB.XYZ.BasisX if getattr(item, "is_horizontal", False) else DB.XYZ.BasisZ
            return REVIT_FAMILY.place_instance_by_reference(
                family_type, reference, point, reference_direction=ref_dir, doc=doc)
        if isinstance(host, DB.Wall):
            level = doc.GetElement(host.LevelId)
            return REVIT_FAMILY.place_instance_by_wall(family_type, point, host, level=level, doc=doc)
        debug_log(
            "Cannot place outlet [{}] - [{}] on host [{}]: no face reference and host is not a wall "
            "(host type: {}).".format(item.family_name, item.type_name, item.host_id, type(host).__name__))
        return None

    def apply_required_params_or_delete(instance, marker_tag, mount_height, item):
        """Set both required parameters on a NEWLY CREATED `instance`; if the family
        lacks either one, delete `instance` again rather than leave an incompletely
        configured outlet behind (SOURCE_MARKER_TAG_PARAMETER_NAME and
        PLACEMENT_HEIGHT_PARAMETER_NAME are both required, no silent fallback for a
        brand-new placement -- see those constants' comments). Returns True on
        success, False if it deleted the instance.
        """
        tag_ok = set_outlet_source_marker_tag(instance, marker_tag)
        height_ok = set_outlet_placement_height(instance, mount_height)
        if tag_ok and height_ok:
            return True
        missing = [name for ok, name in (
            (tag_ok, SOURCE_MARKER_TAG_PARAMETER_NAME), (height_ok, PLACEMENT_HEIGHT_PARAMETER_NAME)) if not ok]
        debug_log(
            "Outlet family [{}] is missing the required {} parameter(s) -- deleting the outlet just placed "
            "for type [{}] and marking it failed. Add {} to the family, then rerun.".format(
                item.family_name, " and ".join(missing), item.type_name, " and ".join(missing)))
        doc.Delete(instance.Id)
        return False

    # Per-level breakdown for the run summary (see level_summary_lines below), keyed
    # by the HOST FURNITURE's level name -- an outlet at a furniture with no level
    # cannot exist (_resolve_one_marker already fails that marker), so this key is
    # never None in practice, but "(no level)" is the fallback just in case.
    level_stats = {}

    # Every instance id actually touched (created/replaced/updated/retagged) this
    # run -- used by place_from_markers to build the post-run save-selection set (see
    # offer_save_run_selection). Never includes already_placed (a true no-op) or
    # anything in `failed`.
    touched_ids = []

    def bump_level_stat(level_name, key):
        stats = level_stats.setdefault(level_name or "(no level)", {
            "created": 0, "replaced": 0, "updated": 0, "retagged": 0, "needs_attention": 0})
        stats[key] += 1

    def check_failure_streak(streak_state, reason, bucket_name, total_in_bucket, index):
        """Update `streak_state` (a mutable [reason, count] pair, one per bucket) with
        one more exception `reason`, and return True if that bucket should stop
        processing its remaining items now.

        Mirrors resolve_marker_targets's per-family fail-fast, applied here to the
        APPLY phase instead: resolve's circuit breaker only ever sees ray-cast/lookup
        failures, since it never calls NewFamilyInstance -- an exception during actual
        placement (e.g. a bad API call, a corrupt host face) is invisible to it and
        was previously caught per-item with no streak-based abort at all, so a
        systemic bug would silently fail on every single item without ever stopping
        early (see the "Reference of the input face is null" incident this was built
        to catch). CONSECUTIVE_UNRESOLVED_ABORT_THRESHOLD identical exception messages
        in a row -> abort just THIS bucket's remaining items; the other three buckets
        are unaffected, since each gets its own streak_state.
        """
        if reason == streak_state[0]:
            streak_state[1] += 1
        else:
            streak_state[0] = reason
            streak_state[1] = 1
        if streak_state[1] >= CONSECUTIVE_UNRESOLVED_ABORT_THRESHOLD:
            remaining = total_in_bucket - index - 1
            debug_log(
                "Aborting '{}' early: {} consecutive item(s) failed with the same error [{}] -- likely a "
                "systemic bug or setup issue, not independent per-item problems. Skipping its remaining {} "
                "item(s); other buckets are unaffected. Fix the root cause and rerun.".format(
                    bucket_name, streak_state[1], reason, remaining))
            return True
        return False

    created = 0
    replaced = 0
    updated = 0
    retagged = 0
    required_param_failed = 0
    failed = []

    total_items = len(to_create) + len(to_replace) + len(to_update) + len(to_retag)
    progress_step = max(1, total_items // 100)
    processed = 0
    user_cancelled = False

    t = DB.Transaction(doc, "Place/Update Electrical Outlet From Marker")
    t.Start()
    try:
        with forms.ProgressBar(
                title="Placing/updating outlets... ({value} of {max_value})",
                step=1, cancellable=True) as pb:

            create_streak = [None, 0]
            if not user_cancelled:
                for index, (item, marker_tag) in enumerate(to_create):
                    if user_cancelled:
                        break
                    host_level = None
                    try:
                        instance = do_create(item)
                        if instance and apply_required_params_or_delete(instance, marker_tag, item.mount_height, item):
                            level_elev = getattr(item, "level_elevation", None)
                            host_level = apply_schedule_level(instance, level_elev if level_elev is not None else item.point[2])
                            created += 1
                            bump_level_stat(item.level_name, "created")
                            touched_ids.append(element_int_id(instance))
                            debug_log("Placed outlet [{}] - [{}]/[{}] on host [{}] at {} (height {}), tagged.".format(
                                instance.Id, item.family_name, item.type_name, item.host_id, item.point,
                                item.mount_height))
                        else:
                            failed.append(item.host_id)
                            bump_level_stat(item.level_name, "needs_attention")
                    except Exception as e:
                        debug_log("Failed to place outlet on host [{}]: {}".format(item.host_id, e))
                        failed.append(item.host_id)
                        bump_level_stat(item.level_name, "needs_attention")
                        if check_failure_streak(create_streak, str(e), "to_create", len(to_create), index):
                            break
                    processed += 1
                    set_progress_title(pb, "Placing", item.level_name, item.family_name, item.type_name,
                                        item.mount_height)
                    pb.update_progress(processed, total_items)
                    if processed % progress_step == 0:
                        zoom_active_view_to_point(DB.XYZ(*item.point), level=host_level, fallback_view=view3d)
                    if pb.cancelled:
                        user_cancelled = True
                        break

            replace_streak = [None, 0]
            if not user_cancelled:
                for index, (old_instance_id, item, marker_tag) in enumerate(to_replace):
                    if user_cancelled:
                        break
                    host_level = None
                    try:
                        instance = do_create(item)
                        if instance and apply_required_params_or_delete(instance, marker_tag, item.mount_height, item):
                            doc.Delete(DB.ElementId(old_instance_id))
                            level_elev = getattr(item, "level_elevation", None)
                            host_level = apply_schedule_level(
                                instance, level_elev if level_elev is not None else item.point[2])
                            replaced += 1
                            bump_level_stat(item.level_name, "replaced")
                            touched_ids.append(element_int_id(instance))
                            debug_log("Replaced outlet [{}] with [{}] - [{}]/[{}] at {} (height {}), tagged.".format(
                                old_instance_id, instance.Id, item.family_name, item.type_name, item.point,
                                item.mount_height))
                        else:
                            failed.append(old_instance_id)
                            bump_level_stat(item.level_name, "needs_attention")
                    except Exception as e:
                        debug_log("Failed to replace outlet [{}]: {}".format(old_instance_id, e))
                        failed.append(old_instance_id)
                        bump_level_stat(item.level_name, "needs_attention")
                        if check_failure_streak(replace_streak, str(e), "to_replace", len(to_replace), index):
                            break
                    processed += 1
                    set_progress_title(pb, "Replacing", item.level_name, item.family_name, item.type_name,
                                        item.mount_height)
                    pb.update_progress(processed, total_items)
                    if processed % progress_step == 0:
                        zoom_active_view_to_point(DB.XYZ(*item.point), level=host_level, fallback_view=view3d)
                    if pb.cancelled:
                        user_cancelled = True
                        break

            update_streak = [None, 0]
            if not user_cancelled:
                for index, (instance_id, target_point_tuple, new_type_name, marker_tag, mount_height, level_name) \
                        in enumerate(to_update):
                    if user_cancelled:
                        break
                    existing = None
                    host_level = None
                    try:
                        existing = doc.GetElement(DB.ElementId(instance_id))
                        if existing is None:
                            failed.append(instance_id)
                            bump_level_stat(level_name, "needs_attention")
                            continue
                        if new_type_name is not None:
                            family_name = REVIT_FAMILY.get_family_name(existing)
                            new_type = resolve_symbol(family_name, new_type_name)
                            if new_type:
                                existing.Symbol = new_type
                        current_point = get_instance_point(existing)
                        target_point = DB.XYZ(target_point_tuple[0], target_point_tuple[1], target_point_tuple[2])
                        if current_point is not None:
                            DB.ElementTransformUtils.MoveElement(doc, existing.Id, target_point - current_point)
                        # This instance PRE-EXISTED (not created by this run), so a missing
                        # required parameter here does not undo the move/retype that already
                        # succeeded -- deleting someone's existing outlet over a bookkeeping
                        # gap would be far worse than just flagging it loudly.
                        tag_ok = set_outlet_source_marker_tag(existing, marker_tag)
                        height_ok = set_outlet_placement_height(existing, mount_height)
                        host_level = apply_schedule_level(existing, target_point_tuple[2])
                        updated += 1
                        bump_level_stat(level_name, "updated")
                        touched_ids.append(instance_id)
                        if not (tag_ok and height_ok):
                            required_param_failed += 1
                            bump_level_stat(level_name, "needs_attention")
                            missing = [name for ok, name in (
                                (tag_ok, SOURCE_MARKER_TAG_PARAMETER_NAME),
                                (height_ok, PLACEMENT_HEIGHT_PARAMETER_NAME)) if not ok]
                            debug_log(
                                "Outlet [{}]'s family has no required {} parameter(s) -- moved/retyped it, but "
                                "could not fully configure it. Add {} to the family, then rerun.".format(
                                    instance_id, " and ".join(missing), " and ".join(missing)))
                        debug_log("Updated outlet [{}]{} to {} (height {}).".format(
                            instance_id, " (retyped to [{}])".format(new_type_name) if new_type_name else "",
                            target_point_tuple, mount_height))
                    except Exception as e:
                        debug_log("Failed to update outlet [{}]: {}".format(instance_id, e))
                        failed.append(instance_id)
                        bump_level_stat(level_name, "needs_attention")
                        if check_failure_streak(update_streak, str(e), "to_update", len(to_update), index):
                            break
                    processed += 1
                    if existing is not None:
                        set_progress_title(pb, "Updating", level_name, REVIT_FAMILY.get_family_name(existing),
                                            type_name_of(existing.Symbol), mount_height)
                    else:
                        set_progress_title(pb, "Updating", level_name)
                    pb.update_progress(processed, total_items)
                    if processed % progress_step == 0:
                        zoom_active_view_to_point(
                            DB.XYZ(*target_point_tuple), level=host_level, fallback_view=view3d)
                    if pb.cancelled:
                        user_cancelled = True
                        break

            retag_streak = [None, 0]
            if not user_cancelled:
                for index, (instance_id, marker_tag, mount_height, level_name) in enumerate(to_retag):
                    if user_cancelled:
                        break
                    existing = None
                    host_level = None
                    try:
                        existing = doc.GetElement(DB.ElementId(instance_id))
                        if existing is None:
                            failed.append(instance_id)
                            bump_level_stat(level_name, "needs_attention")
                            continue
                        tag_ok = set_outlet_source_marker_tag(existing, marker_tag)
                        height_ok = set_outlet_placement_height(existing, mount_height)
                        existing_point_for_level = get_instance_point(existing)
                        host_level = apply_schedule_level(
                            existing, existing_point_for_level.Z if existing_point_for_level else None)
                        touched_ids.append(instance_id)
                        if tag_ok and height_ok:
                            retagged += 1
                            bump_level_stat(level_name, "retagged")
                        else:
                            required_param_failed += 1
                            bump_level_stat(level_name, "needs_attention")
                            missing = [name for ok, name in (
                                (tag_ok, SOURCE_MARKER_TAG_PARAMETER_NAME),
                                (height_ok, PLACEMENT_HEIGHT_PARAMETER_NAME)) if not ok]
                            debug_log(
                                "Outlet [{}]'s family has no required {} parameter(s) -- left it as-is (already "
                                "correct position/type), but could not fully configure it. Add {} to the family, "
                                "then rerun.".format(instance_id, " and ".join(missing), " and ".join(missing)))
                    except Exception as e:
                        debug_log("Failed to tag existing outlet [{}]: {}".format(instance_id, e))
                        failed.append(instance_id)
                        bump_level_stat(level_name, "needs_attention")
                        if check_failure_streak(retag_streak, str(e), "to_retag", len(to_retag), index):
                            break
                    processed += 1
                    if existing is not None:
                        set_progress_title(pb, "Tagging", level_name, REVIT_FAMILY.get_family_name(existing),
                                            type_name_of(existing.Symbol), mount_height)
                    else:
                        set_progress_title(pb, "Tagging", level_name)
                    pb.update_progress(processed, total_items)
                    if processed % progress_step == 0 and existing is not None:
                        existing_point = get_instance_point(existing)
                        if existing_point is not None:
                            zoom_active_view_to_point(existing_point, level=host_level, fallback_view=view3d)
                    if pb.cancelled:
                        user_cancelled = True
                        break

            if user_cancelled:
                debug_log(
                    "User cancelled placing/updating after {} of {} item(s); everything applied so far is still "
                    "committed -- nothing is rolled back, the remaining items just weren't reached yet.".format(
                        processed, total_items))

        t.Commit()
    except Exception:
        t.RollBack()
        raise

    lines = ["Total: Placed {} | Replaced {} | Updated {} | Tagged {}".format(created, replaced, updated, retagged)]
    if user_cancelled:
        lines.append("Cancelled by user after {} of {} item(s); already-applied changes were kept.".format(
            processed, total_items))
    if required_param_failed:
        lines.append(
            "{} instance(s) updated/adopted but could not be fully configured (family missing {} and/or {} "
            "parameter).".format(
                required_param_failed, SOURCE_MARKER_TAG_PARAMETER_NAME, PLACEMENT_HEIGHT_PARAMETER_NAME))
    if failed:
        lines.append("Failed on {} item(s), see output for detail.".format(len(failed)))

    if level_stats:
        lines.append("By level:")
        for level_name in sorted(level_stats.keys()):
            s = level_stats[level_name]
            level_line = "  {}: Placed {} | Replaced {} | Updated {} | Tagged {}".format(
                level_name, s["created"], s["replaced"], s["updated"], s["retagged"])
            if s["needs_attention"]:
                level_line += " | Needs attention {}".format(s["needs_attention"])
            lines.append(level_line)

    result = "\n".join(lines)
    debug_log(result)
    stats = {
        "touched_ids": touched_ids,
        "failed_count": len(failed),
        "required_param_failed": required_param_failed,
        "user_cancelled": user_cancelled,
    }
    return result, stats


RUN_SELECTION_NAME_PREFIX = "EnneadTab-OutletRunner"

# Revit rejects any element name containing these characters -- validated up front so
# a bad name is caught before create_selection_filter ever runs, not surfaced as a
# raw API exception.
_INVALID_SELECTION_NAME_CHARS = set("\\:{}[]|;<>?`~")


def _is_valid_selection_name_suffix(suffix):
    if not suffix or not suffix.strip():
        return False
    return not any(char in _INVALID_SELECTION_NAME_CHARS for char in suffix)


def offer_save_run_selection(doc, touched_ids):
    """After a run counts as FULLY successful (see run_fully_successful in
    place_from_markers -- every marker found this run resolved AND applied cleanly,
    no failures, no missing-required-param instances, no user cancellation), ask for
    a short run-intent suffix and save this run's touched outlets as a named Revit
    selection (DB.SelectionFilterElement -- see REVIT_FILTER.create_selection_filter),
    plus set them as the live selection (REVIT_SELECTION.set_selection).

    A furniture family name is NOT a usable default here: one furniture family
    commonly carries more than one marker per instance (each naming a different
    outlet -- see PARA_MAP_TEMPLATE), so there is no single reliable auto-derived
    name for "this run's intent" (which floors/rooms/pass this was) -- the user must
    type it. The full saved name is always RUN_SELECTION_NAME_PREFIX + a
    yyyymmdd-hhmmss timestamp + that typed suffix.

    Never blocks or fails the run itself -- this runs strictly AFTER the run's own
    NOTIFICATION.messenger summary, as a nicety. Cancelling the prompt (Escape/Cancel,
    forms.ask_for_string returns None) skips saving with no error. Submitting empty,
    invalid-character, or already-used text re-prompts instead -- every saved
    selection here must have a valid, non-overlapping name, never a silently broken
    or silently overwritten one.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    default_suffix = ""
    full_name = None
    while True:
        suffix = forms.ask_for_string(
            default=default_suffix,
            prompt="Save this run's {} outlet(s) as a Revit selection?\n\n"
                   "Full name will be: {}_{}_<your text below>\n\n"
                   "Describe this run's intent (e.g. which floors/rooms/pass) -- "
                   "Cancel to skip saving.".format(len(touched_ids), RUN_SELECTION_NAME_PREFIX, timestamp),
            title="Save Run As Selection")
        if suffix is None:
            debug_log("Run selection not saved (user cancelled the save-selection prompt).")
            return
        suffix = suffix.strip()
        if not _is_valid_selection_name_suffix(suffix):
            forms.alert(
                "Name must be non-empty and cannot contain any of: {}".format(
                    " ".join(sorted(_INVALID_SELECTION_NAME_CHARS))),
                title="Invalid Name")
            default_suffix = suffix
            continue
        candidate_name = "{}_{}_{}".format(RUN_SELECTION_NAME_PREFIX, timestamp, suffix)
        if REVIT_FILTER.get_selection_filter_by_name(doc, candidate_name) is not None:
            forms.alert(
                "A selection named '{}' already exists -- choose a different name.".format(candidate_name),
                title="Name Already Used")
            default_suffix = suffix
            continue
        full_name = candidate_name
        break

    elements = [doc.GetElement(DB.ElementId(element_id)) for element_id in touched_ids]
    elements = [element for element in elements if element is not None]

    t = DB.Transaction(doc, "Save MetroTech Outlet Run Selection")
    t.Start()
    try:
        REVIT_FILTER.create_selection_filter(doc, full_name, elements)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    REVIT_SELECTION.set_selection(elements)
    debug_log("Saved {} outlet(s) to selection [{}].".format(len(elements), full_name))
    NOTIFICATION.messenger("Saved {} outlet(s) to selection '{}'.".format(len(elements), full_name))


def place_from_markers(doc):
    scopes = get_search_scopes(doc)

    qualified_names = set()
    for scope_doc, _link_transform, _link_instance in scopes:
        qualified_names.update(discover_qualified_furniture_family_names(scope_doc))
    qualified_names = sorted(qualified_names)
    if not qualified_names:
        NOTIFICATION.messenger(
            "No furniture family in this model or its links carries a {} marker.".format(PARA_MAP_PARAMETER_NAME))
        return

    selected_names = forms.SelectFromList.show(
        qualified_names,
        multiselect=True,
        title="Select Furniture Families To Process",
        button_name="Process Selected")
    if not selected_names:
        return
    furniture_label = " / ".join(selected_names)

    view3d = get_any_3d_view(doc)
    if view3d is None:
        NOTIFICATION.messenger("No 3D view available and none could be created; cannot ray-cast to a host face.")
        return

    start_run_log()

    # zoom_active_view_to_point switches to each item's OWN level's 2D plan view as it
    # goes (preferred over one fixed 3D camera -- 3D navigation reads poorly for
    # "watch it work," and a run spans many different levels a single 3D view can't
    # usefully frame one at a time), falling back to view3d only if a level has no
    # plan view in the host doc. No initial forced view switch is needed here.
    try:
        debug_log("Host document: [{}]".format(doc.Title))
        log_view3d_raycast_diagnostics(doc, view3d)
        symbol_cache = {}
        resolved, unresolved = resolve_marker_targets(doc, selected_names, view3d, symbol_cache, scopes)
        for marker, reason in unresolved:
            print("Marker [{}]: {}".format(marker.Id, reason))
        if not resolved:
            NOTIFICATION.messenger(
                "Found {} marker(s) across [{}], but none resolved to a placeable outlet.".format(
                    len(unresolved), furniture_label))
            return

        outlets_by_marker_tag = build_outlets_by_marker_tag(doc)
        existing_instances_cache = {}  # (family_name, type_name) -> list of DB.FamilyInstance

        def get_existing_instances(family, family_type):
            key = (family.Name, type_name_of(family_type))
            if key not in existing_instances_cache:
                # editable_only is intentionally NOT passed (defaults False): an
                # outlet owned by another workshared user must still be found here so
                # this marker is never treated as empty and given a duplicate right
                # on top of it. Ownership is only checked separately, below, when
                # actually deciding whether to move/retype/replace one.
                existing_instances_cache[key] = REVIT_FAMILY.get_family_instances_by_family_name_and_type_name(
                    family.Name, type_name_of(family_type), doc=doc)
            return existing_instances_cache[key]

        to_create = []        # (OutletPlacementTarget, marker_tag)
        to_replace = []       # (old_instance_id, OutletPlacementTarget, marker_tag)
        to_update = []        # (instance_id, target_point, new_type_name_or_None, marker_tag, mount_height, level_name)
        to_retag = []         # (instance_id, marker_tag, mount_height, level_name)
        already_placed = []   # existing instance, no action needed
        skipped_foreign = []  # existing instance nearby but owned by another user
        for marker, marker_tag, host, face, hit_point, stable_ref, family, family_type, mount_height, level_name, \
                is_horizontal, host_level_elev in resolved:
            point_tuple = (hit_point.X, hit_point.Y, hit_point.Z)
            type_name = type_name_of(family_type)
            use_stable_ref = stable_ref if family.FamilyPlacementType == DB.FamilyPlacementType.WorkPlaneBased else None
            target = OutletPlacementTarget(
                element_int_id(host), point_tuple, family.Name, type_name, mount_height, level_name, use_stable_ref,
                is_horizontal=is_horizontal, level_elevation=host_level_elev)

            existing = outlets_by_marker_tag.get(marker_tag)
            if existing is None:
                # No tagged outlet yet for this marker -- fall back to a position+type
                # check so a pre-existing, untagged, already-correct instance (hand
                # placed, or placed by this tool before tagging existed) is adopted
                # (tagged) rather than duplicated.
                candidates = get_existing_instances(family, family_type)
                legacy, _distance = find_nearby_instance(hit_point, candidates, EXISTING_OUTLET_SAME_SPOT_TOLERANCE)
                if legacy is not None:
                    already_placed.append(legacy)
                    to_retag.append((element_int_id(legacy), marker_tag, mount_height, level_name))
                else:
                    to_create.append((target, marker_tag))
                continue

            if not REVIT_SELECTION.is_changable(existing):
                skipped_foreign.append(existing)
                debug_log(
                    "Outlet tagged for marker [{}] is owned by another user; leaving it in place, not "
                    "creating a duplicate or changing it.".format(marker.Id))
                continue

            existing_family_name = REVIT_FAMILY.get_family_name(existing)
            existing_type_name = type_name_of(existing.Symbol)
            existing_point = get_instance_point(existing)
            same_position = (
                existing_point is not None and existing_point.DistanceTo(hit_point) <= EXISTING_OUTLET_SAME_SPOT_TOLERANCE)
            # Height is no longer part of the ray-cast target (see PLACEMENT_HEIGHT_
            # PARAMETER_NAME) -- so same_position alone can no longer tell "nothing to
            # do" apart from "mount_height changed in the marker but the wall/floor
            # target didn't move." Both must match for a true no-op.
            existing_height = get_outlet_placement_height(existing)
            same_height = existing_height is not None and abs(existing_height - mount_height) < 0.001

            existing_host = getattr(existing, "Host", None)
            host_changed = existing_host is not None and element_int_id(existing_host) != target.host_id

            if existing_family_name != family.Name or host_changed:
                to_replace.append((element_int_id(existing), target, marker_tag))
            elif existing_type_name == type_name and same_position and same_height:
                already_placed.append(existing)
            elif existing_type_name == type_name:
                to_update.append((element_int_id(existing), point_tuple, None, marker_tag, mount_height, level_name))
            else:
                to_update.append(
                    (element_int_id(existing), point_tuple, type_name, marker_tag, mount_height, level_name))

        result, apply_stats = apply_marker_outlets(to_create, to_replace, to_update, to_retag, view3d)
        lines = ["Furniture: [{}]".format(furniture_label), result]
        if already_placed:
            lines.append("{} outlet(s) already sat exactly on their marker, left untouched".format(len(already_placed)))
        if skipped_foreign:
            lines.append(
                "{} outlet(s) near a marker are owned by another user, left untouched".format(len(skipped_foreign)))
        if unresolved:
            lines.append("{} marker(s) could not be placed, see output for detail".format(len(unresolved)))
        NOTIFICATION.messenger(main_text="\n".join(lines))

        # Strict success gate for the save-selection offer below: every marker found
        # this run must have resolved AND applied cleanly -- a marker left unresolved,
        # an apply-phase failure, an incompletely-configured (missing required param)
        # instance, or a user cancellation all count as NOT successful, even if most
        # of the run went fine. "Found 100 markers, placed 100 outlets" is the bar.
        run_fully_successful = (
            not unresolved
            and not apply_stats["user_cancelled"]
            and apply_stats["failed_count"] == 0
            and apply_stats["required_param_failed"] == 0)
        if run_fully_successful and apply_stats["touched_ids"]:
            offer_save_run_selection(doc, apply_stats["touched_ids"])
    finally:
        log_path = save_run_log()
        if log_path:
            print("Debug log saved to: {}".format(log_path))


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main(doc):
    place_from_markers(doc)


################## main code below #####################
if __name__ == "__main__":
    main(DOC)
