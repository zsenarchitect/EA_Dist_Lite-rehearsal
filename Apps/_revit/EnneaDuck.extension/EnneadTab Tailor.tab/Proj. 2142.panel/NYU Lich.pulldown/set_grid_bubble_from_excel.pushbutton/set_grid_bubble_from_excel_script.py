#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Match grid visibility and bubble placement across views using an Excel view list.

The spreadsheet names one source-of-truth view per level. In every other
view on that level, grid visibility is forced to follow the source view:
grids shown there are shown, grids hidden there are hidden. Bubble
positions and leaders are then copied across, so grids read the same way
on every drawing of that level."""
__title__ = "Set Grid Bubble From Excel"

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

import difflib
import os
import time

from pyrevit import script

from EnneadTab import ERROR_HANDLE, NOTIFICATION, EXCEL, DATA_CONVERSION, SHAREPOINT
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_VIEW
from Autodesk.Revit import DB  # pyright: ignore

doc = REVIT_APPLICATION.get_doc()

EXCEL_PATH = SHAREPOINT.get_project_file("2142/6_Team/BS/NYU-SUF View List.xlsx")
WORKSHEET = "Sheet1"
HEADER_ROW = 1

COL_LEVEL_NAME = "Level Name"
COL_VIEW_NAME = "View Name"
COL_SOURCE_OF_TRUTH = "Source of truth for this level"

REQUIRED_COLUMNS = [COL_LEVEL_NAME, COL_VIEW_NAME, COL_SOURCE_OF_TRUTH]
SOURCE_OF_TRUTH_VALUES = ("yes", "y", "1", "true")

# When True, log unbound/coincident curve errors as warnings and skip that grid end instead of aborting.
SKIP_CURVE_EXTENT_ERRORS = True

# When True, convert SOT ref view grids to 2D (view-specific) extent in the ref view before copying to targets.
CONVERT_REF_VIEW_GRIDS_TO_2D = True

# When True, use Revit's PropagateToViews() to copy grid 2D extents from ref view to target views (per level).
# This avoids "unbound or not coincident" errors from SetCurveInView when copying curves between views.
# Per-view we then only apply bubble and leader. If False, use SetCurveInView per view (may skip many).
USE_PROPAGATE_TO_VIEWS = True

# Limit views per run (0 = no limit). Use e.g. 20-30 if Revit crashes during view regeneration; re-run to process more.
MAX_VIEWS_PER_RUN = 0

# Level/view strings that are invalid (Excel artifacts or empty-like); skip rows with these.
# _x000D_ / _x000A_ are OOXML escapes for carriage return (U+000D) and line feed (U+000A).
INVALID_LEVEL_OR_VIEW = ("none", "_x000d_", "_x000a_", "")


def _normalize_cell(s):
    """Strip whitespace and control chars; return empty string if None or invalid."""
    if s is None:
        return ""
    t = str(s).replace("\r", "").replace("\n", "").strip()
    if t.lower() in INVALID_LEVEL_OR_VIEW:
        return ""
    return t


def _get_cell_value(data, row, col):
    """Get cell value from Excel data dict. Handles (row,col) 1-based and value as dict with 'value' key or plain."""
    key = (row, col)
    cell = data.get(key)
    if cell is None:
        return None
    if isinstance(cell, dict) and "value" in cell:
        return cell["value"]
    return cell


def parse_excel_to_mappings(data, header_to_col, output):
    """Build REF_VIEWS and VIEWS_TO_MODIFY. Abort on any validation failure."""
    if not isinstance(data, dict):
        msg = "parse_excel_to_mappings expects dict data (Excel return_dict=True). Abort."
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)
    rows_by_number = set()
    for (row, _) in data.keys():
        if row > HEADER_ROW:
            rows_by_number.add(row)
    data_rows = sorted(rows_by_number)

    if not data_rows:
        msg = "Empty data: no rows after header (row {}).".format(HEADER_ROW)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    ref_views = {}
    views_to_modify = []
    skipped_rows = []

    for row in data_rows:
        level_name = _get_cell_value(data, row, header_to_col[COL_LEVEL_NAME])
        view_name = _get_cell_value(data, row, header_to_col[COL_VIEW_NAME])
        sot_raw = _get_cell_value(data, row, header_to_col[COL_SOURCE_OF_TRUTH])

        level_str = _normalize_cell(level_name)
        view_str = _normalize_cell(view_name)
        sot = (str(sot_raw).strip().lower() if sot_raw is not None else "") in SOURCE_OF_TRUTH_VALUES

        if not level_str or not view_str:
            skipped_rows.append(row)
            continue

        if sot:
            if level_str in ref_views:
                if ref_views[level_str] != view_str:
                    msg = "Conflicting source-of-truth for level [{}]: view [{}] vs [{}] (Excel row {}). Abort.".format(
                        level_str, ref_views[level_str], view_str, row)
                    output.print_md("**ERROR:** " + msg)
                    raise RuntimeError(msg)
                # Same level + same view: redundant row, keep existing
            else:
                ref_views[level_str] = view_str
        else:
            views_to_modify.append((view_str, level_str, row))

    if skipped_rows:
        output.print_md("Skipped {} row(s) with empty or invalid Level Name or View Name (Excel rows: {}).".format(
            len(skipped_rows), ", ".join(str(r) for r in sorted(skipped_rows)[:15])))
        if len(skipped_rows) > 15:
            output.print_md("  ... and {} more.".format(len(skipped_rows) - 15))

    if not ref_views and not views_to_modify:
        msg = "No valid data rows: every row has empty Level Name or View Name, or no source-of-truth. Abort."
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    levels_to_modify = set(ln for (_, ln, _) in views_to_modify)
    level_to_rows = {}
    for (_, ln, r) in views_to_modify:
        level_to_rows.setdefault(ln, []).append(r)
    levels_without_ref = [ln for ln in levels_to_modify if ln not in ref_views]
    if levels_without_ref:
        parts = []
        for ln in levels_without_ref:
            rows_str = ", ".join(str(r) for r in sorted(level_to_rows.get(ln, [])))
            parts.append("[{}] (Excel row(s): {})".format(ln, rows_str))
        msg = "Level(s) have no source-of-truth row: {}. Abort.".format("; ".join(parts))
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    view_to_levels = {}
    for view_str, level_str, _ in views_to_modify:
        view_to_levels.setdefault(view_str, set()).add(level_str)
    duplicate_view_levels = [(v, list(s)) for v, s in view_to_levels.items() if len(s) > 1]
    if duplicate_view_levels:
        parts = ["View(s) appear for multiple levels (one view has one level in Revit):"]
        for view_str, levels in duplicate_view_levels:
            parts.append("  View [{}] -> levels {}".format(view_str, levels))
        msg = "\n".join(parts)
        output.print_md("**ERROR:** " + msg.replace("\n", "  \n"))
        raise RuntimeError(msg)

    return ref_views, views_to_modify


def _load_excel_and_parse(output):
    """Read Excel file, validate headers, parse to ref_views and views_to_modify. Raises on error."""
    if not os.path.isfile(EXCEL_PATH):
        msg = "Excel file not found or not a file: {}".format(EXCEL_PATH)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    raw_data = EXCEL.read_data_from_excel(EXCEL_PATH, worksheet=WORKSHEET, return_dict=True)
    if not raw_data:
        msg = "Failed to read Excel or worksheet '{}' is missing/empty.".format(WORKSHEET)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)
    if not isinstance(raw_data, dict):
        msg = "Excel read returned unexpected type (expected dict). Abort."
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    row_count = len(set(k[0] for k in raw_data.keys()))
    output.print_md("Read {} rows from Sheet1 ({} cells).".format(row_count, len(raw_data)))

    try:
        header_map = EXCEL.get_header_map(raw_data, header_row=HEADER_ROW)
    except (KeyError, TypeError) as e:
        msg = "Excel data format unexpected (cells may not have 'value' key). Check file. Detail: {}".format(str(e))
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    if not header_map:
        msg = "No headers found in row {}.".format(HEADER_ROW)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    missing = [c for c in REQUIRED_COLUMNS if c not in header_map.values()]
    if missing:
        msg = "Required column(s) missing: {}. Abort.".format(", ".join(missing))
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    header_to_col = EXCEL.flip_dict(header_map)
    for col_name in REQUIRED_COLUMNS:
        if col_name not in header_to_col:
            msg = "Required column missing after parse (duplicate header?): [{}]. Abort.".format(col_name)
            output.print_md("**ERROR:** " + msg)
            raise RuntimeError(msg)

    return parse_excel_to_mappings(raw_data, header_to_col, output)


def _resolve_ref_views(ref_views, output):
    """Resolve level -> view name to level -> View. Raises if any SOT view not in document."""
    ref_views_resolved = {}
    missing_refs = []
    for level_name, view_name in ref_views.items():
        view = REVIT_VIEW.get_view_by_name(view_name)
        if view is None:
            missing_refs.append((level_name, view_name))
        else:
            ref_views_resolved[level_name] = view

    if missing_refs:
        parts = ["Source-of-truth view not in document:"]
        for level_name, view_name in missing_refs:
            parts.append("  Level [{}] -> view [{}] not found.".format(level_name, view_name))
        msg = "\n".join(parts)
        output.print_md("**ERROR:** " + msg.replace("\n", "  \n"))
        raise RuntimeError(msg)

    return ref_views_resolved


def _get_all_view_names_with_sheet():
    """Return (list of view names in doc, dict view_name -> sheet number or None). Skips templates."""
    all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    view_names = []
    name_to_sheet = {}
    for v in all_views:
        if v.IsTemplate:
            continue
        if not v.Name:
            continue
        view_names.append(v.Name)
        sheet_param = v.LookupParameter("Sheet Number")
        if sheet_param and sheet_param.AsString() and sheet_param.AsString() != "---":
            name_to_sheet[v.Name] = sheet_param.AsString()
        else:
            name_to_sheet[v.Name] = None
    return view_names, name_to_sheet


def _fuzzy_suggestions(missing_name, view_names, name_to_sheet, n=3, cutoff=0.4):
    """Return list of suggested view names (raw names for lookup) for missing_name."""
    return difflib.get_close_matches(missing_name, view_names, n=n, cutoff=cutoff)


def _preflight_views_exist(ref_views, views_to_modify, output):
    """Ensure every view name (ref and target) exists in the document. List missing with 'Did you mean?' and raise if any."""
    ref_names = set(ref_views.values())
    target_names = {view_name for (view_name, _, _) in views_to_modify}
    all_names = ref_names | target_names
    missing = []
    for name in sorted(all_names):
        if REVIT_VIEW.get_view_by_name(name) is None:
            missing.append(name)
    if missing:
        view_names, name_to_sheet = _get_all_view_names_with_sheet()
        output.print_md("**ERROR:** The following views are not in the document:")
        for name in missing:
            output.print_md("  - [{}]".format(name))
            suggestion_names = _fuzzy_suggestions(name, view_names, name_to_sheet)
            if suggestion_names:
                links = []
                for sug_name in suggestion_names:
                    view = REVIT_VIEW.get_view_by_name(sug_name)
                    if view is None:
                        continue
                    title = "{} (Sheet {})".format(sug_name, name_to_sheet[sug_name]) if name_to_sheet.get(sug_name) else sug_name
                    links.append(output.linkify(view.Id, title=title))
                if links:
                    # Use raw HTML so linkify output is not escaped (print_md escapes < and >)
                    did_you_mean_html = "    <strong>Did you mean:</strong> " + ", ".join(links) + "?"
                    try:
                        output.print_html(did_you_mean_html)
                    except AttributeError:
                        output.print_md("    **Did you mean:** {}?".format(", ".join(links)))
        output.print_md("Abort. Fix view names in Excel or add views in Revit, then re-run.")
        raise RuntimeError("Preflight failed: {} view(s) not in document: {}.".format(len(missing), ", ".join(missing)))


def _convert_ref_view_grids_to_2d(ref_view, output):
    """Convert grids in ref_view from Model (3D) to ViewSpecific (2D) extent so copying to targets is more reliable.
    Returns (converted_count, error_count). Does not raise; logs warnings for failures."""
    converted = 0
    errors = 0
    ref_name = ref_view.Name
    grids = DB.FilteredElementCollector(doc, ref_view.Id).OfClass(DB.Grid).WhereElementIsNotElementType().ToElements()
    for grid in grids:
        for grid_end in [DB.DatumEnds.End0, DB.DatumEnds.End1]:
            try:
                extent_type = grid.GetDatumExtentTypeInView(grid_end, ref_view)
                if extent_type != DB.DatumExtentType.Model:
                    continue
                curves = grid.GetCurvesInView(extent_type, ref_view)
                if not curves:
                    continue
                grid.SetDatumExtentType(grid_end, ref_view, DB.DatumExtentType.ViewSpecific)
                grid.SetCurveInView(DB.DatumExtentType.ViewSpecific, ref_view, curves[0])
                converted += 1
            except Exception as e:
                errors += 1
                view_link = output.linkify(ref_view.Id, title=ref_name)
                grid_link = output.linkify(grid.Id, title=grid.Name)
                output.print_md("**WARNING:** Could not convert to 2D in ref view {}, grid {}, end [{}]: {}.".format(
                    view_link, grid_link, grid_end, str(e)))
    return converted, errors


def _element_id_set(view_ids):
    """Build ISet<ElementId> for PropagateToViews. Revit API requires ISet; use HashSet when available."""
    id_list = list(view_ids)
    try:
        from System.Collections.Generic import HashSet
        return HashSet[DB.ElementId](id_list)
    except Exception:
        return set(id_list)


def _propagate_extents_by_level(ref_views_resolved, views_to_modify, output):
    """Use Grid.PropagateToViews(ref_view, target_view_ids) per level to copy 2D extents without SetCurveInView.
    Only passes view IDs that are valid for propagation (via GetPropagationViews) to avoid invalid ElementId errors.
    Lists and explains any target views that are not valid for propagation.
    Returns (grids_propagated, grids_failed). Call inside a transaction."""
    level_to_target_view_ids = {}
    view_id_to_name = {}
    for view_name, level_name, _ in views_to_modify:
        if level_name not in ref_views_resolved:
            continue
        view = REVIT_VIEW.get_view_by_name(view_name)
        if view is None:
            continue
        level_to_target_view_ids.setdefault(level_name, set()).add(view.Id)
        view_id_to_name[view.Id] = view_name
    propagated = 0
    failed = 0
    skipped_propagation_count = 0
    for level_name in ref_views_resolved:
        ref_view = ref_views_resolved[level_name]
        target_ids = level_to_target_view_ids.get(level_name)
        if not target_ids or len(target_ids) == 0:
            continue
        grids = DB.FilteredElementCollector(doc, ref_view.Id).OfClass(DB.Grid).WhereElementIsNotElementType().ToElements()
        for grid in grids:
            try:
                valid_ids = grid.GetPropagationViews(ref_view)
                valid_set = set(valid_ids) if valid_ids else set()
                allowed = target_ids & valid_set
                excluded = target_ids - valid_set
                if excluded:
                    skipped_propagation_count += len(excluded)
                    ref_link = output.linkify(ref_view.Id, title=ref_view.Name)
                    grid_link = output.linkify(grid.Id, title=grid.Name)
                    excluded_list = []
                    for vid in excluded:
                        name = view_id_to_name.get(vid)
                        if name is None and doc is not None:
                            el = doc.GetElement(vid)
                            name = el.Name if el else str(vid)
                        elif name is None:
                            name = str(vid)
                        try:
                            excluded_list.append(output.linkify(vid, title=name))
                        except Exception:
                            excluded_list.append(name)
                    output.print_md("**Propagation skipped (not valid):** Grid {} in ref {} — target view(s) not valid for extent propagation: {}.".format(
                        grid_link, ref_link, ", ".join(excluded_list)))
                if not allowed:
                    continue
                view_set = _element_id_set(allowed)
                grid.PropagateToViews(ref_view, view_set)
                propagated += 1
            except Exception as e:
                failed += 1
                ref_link = output.linkify(ref_view.Id, title=ref_view.Name)
                grid_link = output.linkify(grid.Id, title=grid.Name)
                output.print_md("**WARNING:** PropagateToViews failed for grid {} in ref {}: {}.".format(
                    grid_link, ref_link, str(e)))
    if skipped_propagation_count:
        output.print_md("**Summary:** {} target view(s) were skipped for grid extent propagation (see list above).".format(skipped_propagation_count))
        output.print_md("**Why \"not valid\"?** Revit's *GetPropagationViews* returns only views that are **parallel** to the ref view and to which this grid's 2D extent can be propagated (e.g. same-level **plan** views). A target is skipped if it is not in that set — for example: section, elevation, drafting, 3D, or a plan where the grid is not a valid candidate. Bubble and leader are still applied per view later; only the 2D extent propagation was skipped for those pairs.")
    return propagated, failed


def _validate_target_view(view_name, level_name, ref_views_resolved, output):
    """Get view by name, validate level and GenLevel. Returns (view, ref_view). Raises on error."""
    view = REVIT_VIEW.get_view_by_name(view_name)
    if view is None:
        msg = "View not in document: [{}]. Abort.".format(view_name)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    if level_name not in ref_views_resolved:
        msg = "Level [{}] has no source-of-truth in REF_VIEWS. Abort.".format(level_name)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    ref_view = ref_views_resolved[level_name]
    if view.GenLevel is None:
        msg = "View [{}] has no associated level (e.g. drafting). Abort.".format(view_name)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    actual_level = view.GenLevel.Name
    if actual_level != level_name:
        msg = "View [{}] is on level [{}] in Revit but Excel says level [{}]. Abort.".format(
            view_name, actual_level, level_name)
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    return view, ref_view


def _apply_grid_visibility(view, ref_view, view_name, output):
    """Match grid visibility (hide/show) in view to ref_view. Raises on error."""
    all_grids = DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid).WhereElementIsNotElementType().ToElements()
    for grid in all_grids:
        try:
            ref_hidden = grid.IsHidden(ref_view)
            cur_hidden = grid.IsHidden(view)
            if ref_hidden != cur_hidden:
                grid_ids = DATA_CONVERSION.list_to_system_list([grid.Id])
                if ref_hidden:
                    view.HideElements(grid_ids)
                else:
                    view.UnhideElements(grid_ids)
        except Exception as e:
            view_link = output.linkify(view.Id, title=view_name)
            grid_link = output.linkify(grid.Id, title=grid.Name)
            msg = "Grid visibility failed: view {}, grid {}: {}.".format(view_link, grid_link, str(e))
            output.print_md("**ERROR:** " + msg)
            raise RuntimeError(msg)


def _print_curve_error_suggestions(output):
    """Print the standard suggestions for curve extent failures."""
    output.print_md("**Suggestions:**")
    output.print_md("1. Revit requires the curve to be **bound** and **coincident** with the grid's original 3D curve in the target view. Copying from another view can fail if crop, scope, or view extent differs.")
    output.print_md("2. Use Revit's built-in **Propagate Extents**: select the grid(s) in the source-of-truth view, then use Propagate Extents to the target view(s) to copy 2D extents manually.")
    output.print_md("3. Ensure the source-of-truth view and target view both show the same level and that the grid is visible and within crop in both.")
    output.print_md("4. If the grid was just revealed in the target view, try adjusting its 2D extent manually in the target view once, then re-run this tool.")


def _raise_curve_error(view, grid, grid_end, view_name, excel_row, err_str, output):
    """Print curve error with linkify and suggestions, then raise."""
    view_link = output.linkify(view.Id, title=view_name)
    grid_link = output.linkify(grid.Id, title=grid.Name)
    msg = (
        "Grid extent/curve from ref view cannot be applied in this view: "
        "view {}, grid {}, end [{}] (Excel row {}). "
        "The curve is unbound or not coincident with the datum in the target view. "
        "Revit error: {}."
    ).format(view_link, grid_link, grid_end, excel_row, err_str)
    output.print_md("**ERROR:** " + msg)
    _print_curve_error_suggestions(output)
    raise RuntimeError(msg)


def _apply_grid_bubble_and_extent(view, ref_view, view_name, excel_row, output, skip_curve_errors=False, apply_extent=True):
    """For each grid in view, apply bubble visibility and optionally extent per end from ref_view, then leader.
    When apply_extent=False (e.g. using PropagateToViews for extent), only bubble and leader are applied.
    Returns number of curve extent skips (when skip_curve_errors=True and apply_extent=True). Raises on other errors."""
    skipped = 0
    all_grids = DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid).WhereElementIsNotElementType().ToElements()
    for grid in all_grids:
        for grid_end in [DB.DatumEnds.End0, DB.DatumEnds.End1]:
            try:
                is_show_bubble = grid.IsBubbleVisibleInView(grid_end, ref_view)
                if is_show_bubble:
                    grid.ShowBubbleInView(grid_end, view)
                else:
                    grid.HideBubbleInView(grid_end, view)

                if apply_extent:
                    extent_type = grid.GetDatumExtentTypeInView(grid_end, ref_view)
                    curves = grid.GetCurvesInView(extent_type, ref_view)
                    if not curves:
                        msg = "Ref view has no curve for grid [{}] end [{}]. Abort.".format(grid.Name, grid_end)
                        output.print_md("**ERROR:** " + msg)
                        raise RuntimeError(msg)
                    grid.SetDatumExtentType(grid_end, view, extent_type)
                    grid.SetCurveInView(extent_type, view, curves[0])

                leader = grid.GetLeader(grid_end, ref_view)
                if leader and grid.IsLeaderValid(grid_end, view, leader):
                    current_leader = grid.GetLeader(grid_end, view)
                    if not current_leader:
                        grid.AddLeader(grid_end, view)
                    grid.SetLeader(grid_end, view, leader)
            except RuntimeError:
                raise
            except Exception as e:
                err_str = str(e)
                if apply_extent and ("unbound or not coincident" in err_str or "Parameter name: curve" in err_str):
                    if skip_curve_errors:
                        skipped += 1
                        continue
                    _raise_curve_error(view, grid, grid_end, view_name, excel_row, err_str, output)
                view_link = output.linkify(view.Id, title=view_name)
                grid_link = output.linkify(grid.Id, title=grid.Name)
                msg = "Grid/leader failed: view {}, grid {}, end [{}]: {}.".format(
                    view_link, grid_link, grid_end, err_str)
                output.print_md("**ERROR:** " + msg)
                raise RuntimeError(msg)
    return skipped


def _process_one_view(view_name, level_name, excel_row, ref_views_resolved, output, skip_curve_errors=False, apply_extent=True):
    """Validate target view, apply grid visibility from SOT, then grid bubble and optionally extent (and leader). Returns (view, curve_skipped_count). Raises on error."""
    view, ref_view = _validate_target_view(view_name, level_name, ref_views_resolved, output)
    _apply_grid_visibility(view, ref_view, view_name, output)
    skipped = _apply_grid_bubble_and_extent(
        view, ref_view, view_name, excel_row, output,
        skip_curve_errors=skip_curve_errors, apply_extent=apply_extent)
    return view, skipped


@ERROR_HANDLE.try_catch_error()
def set_grid_bubble_from_excel():
    output = script.get_output()
    output.close_others()

    output.print_md("**Set Grid Bubble From Excel** – reading {}".format(EXCEL_PATH))

    if doc is None:
        msg = "No Revit document open. Abort."
        output.print_md("**ERROR:** " + msg)
        raise RuntimeError(msg)

    ref_views, views_to_modify = _load_excel_and_parse(output)

    output.print_md("Parsed: **{}** levels with source-of-truth, **{}** views to modify.".format(
        len(ref_views), len(views_to_modify)))
    for level_name, view_name in ref_views.items():
        output.print_md("  Level [{}] -> ref view [{}]".format(level_name, view_name))

    _preflight_views_exist(ref_views, views_to_modify, output)
    output.print_md("Preflight OK: all views exist in document.")

    ref_views_resolved = _resolve_ref_views(ref_views, output)
    output.print_md("All ref views resolved.")
    if MAX_VIEWS_PER_RUN > 0 and len(views_to_modify) > MAX_VIEWS_PER_RUN:
        views_to_process = views_to_modify[:MAX_VIEWS_PER_RUN]
        output.print_md("Limiting to first **{}** views (MAX_VIEWS_PER_RUN). Re-run to process remaining {}.".format(
            MAX_VIEWS_PER_RUN, len(views_to_modify) - MAX_VIEWS_PER_RUN))
    else:
        views_to_process = views_to_modify
    output.print_md("Updating grid bubbles for **{}** views...".format(len(views_to_process)))

    t_group = DB.TransactionGroup(doc, __title__)
    t_group.Start()
    updated_count = 0
    total_curve_skipped = 0
    views_with_skips = []  # list of (view, skip_count) for views that had curve extent skips
    try:
        if CONVERT_REF_VIEW_GRIDS_TO_2D:
            t_convert = DB.Transaction(doc, "Convert ref grids to 2D")
            t_convert.Start()
            try:
                unique_ref_views = list(dict.fromkeys(ref_views_resolved.values()))
                total_converted = 0
                total_convert_errors = 0
                for ref_view in unique_ref_views:
                    converted, errs = _convert_ref_view_grids_to_2d(ref_view, output)
                    total_converted += converted
                    total_convert_errors += errs
                t_convert.Commit()
                output.print_md("Converted **{}** grid end(s) to 2D in SOT view(s).".format(total_converted))
                if total_convert_errors:
                    output.print_md("**WARNING:** {} grid end(s) could not be converted to 2D (see above).".format(total_convert_errors))
            except Exception:
                t_convert.RollBack()
                raise

        if USE_PROPAGATE_TO_VIEWS:
            t_propagate = DB.Transaction(doc, "Propagate grid extents to views")
            t_propagate.Start()
            try:
                grids_ok, grids_fail = _propagate_extents_by_level(ref_views_resolved, views_to_process, output)
                t_propagate.Commit()
                output.print_md("Propagated 2D extents for **{}** grid(s) (Revit PropagateToViews).".format(grids_ok))
                if grids_fail:
                    output.print_md("**WARNING:** {} grid(s) could not propagate (see above).".format(grids_fail))
            except Exception:
                t_propagate.RollBack()
                raise

        apply_extent = not USE_PROPAGATE_TO_VIEWS
        for view_name, level_name, excel_row in views_to_process:
            start_time = time.time()
            output.print_md("\nWorking on [{}] (level: {}, Excel row: {})".format(view_name, level_name, excel_row))
            t = DB.Transaction(doc, __title__)
            t.Start()
            try:
                view, curve_skipped = _process_one_view(
                    view_name, level_name, excel_row, ref_views_resolved, output,
                    skip_curve_errors=SKIP_CURVE_EXTENT_ERRORS, apply_extent=apply_extent)
                total_curve_skipped += curve_skipped
                if curve_skipped:
                    views_with_skips.append((view, curve_skipped))
                t.Commit()
            except Exception:
                t.RollBack()
                raise
            elapsed = time.time() - start_time
            output.print_md("  Done in {:.2f}s  {}".format(elapsed, output.linkify(view.Id, title=view.Name)))
            updated_count += 1
            NOTIFICATION.messenger("{}/{} done: {}".format(updated_count, len(views_to_process), view_name))

        t_group.Assimilate()
    except Exception:
        try:
            t_group.RollBack()
            output.print_md("**Transaction rolled back** due to error.")
        except Exception:
            pass
        raise

    output.print_md("\n**Finished.** Updated {} views.".format(updated_count))
    if MAX_VIEWS_PER_RUN > 0 and len(views_to_modify) > MAX_VIEWS_PER_RUN:
        output.print_md("(Limited to {} this run. {} views remaining – re-run to process more.)".format(
            updated_count, len(views_to_modify) - updated_count))
    if total_curve_skipped:
        output.print_md("Skipped **{}** grid extent(s). Detail below. All due to: curve unbound or not coincident with datum in target view.".format(total_curve_skipped))
        _print_curve_error_suggestions(output)
        if views_with_skips:
            output.print_md("**Views that had skips (jump to view):**")
            for view, skip_count in views_with_skips:
                link = output.linkify(view.Id, title="{} ({} skip(s))".format(view.Name, skip_count))
                try:
                    output.print_html("  - " + link)
                except AttributeError:
                    output.print_md("  - [{}] ({} skip(s))".format(view.Name, skip_count))
    NOTIFICATION.messenger("Done!")


if __name__ == "__main__":
    set_grid_bubble_from_excel()
