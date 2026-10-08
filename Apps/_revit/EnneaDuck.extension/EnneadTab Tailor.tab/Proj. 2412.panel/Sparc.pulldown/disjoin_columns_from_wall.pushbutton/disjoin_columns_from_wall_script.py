#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Detach columns from any walls they are currently joined to.

This utility checks the current selection first; if no columns are selected it will process
all editable architectural and structural columns in the active document.

A detailed log is printed to the console so you can review which joins were removed or skipped."""
__title__ = "Disjoin Columns\nFrom Walls"

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION
from Autodesk.Revit import DB  # pyright: ignore


UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()

ARCH_COLUMN_CAT_ID = int(DB.BuiltInCategory.OST_Columns)
STRUCT_COLUMN_CAT_ID = int(DB.BuiltInCategory.OST_StructuralColumns)
WALL_CAT_ID = int(DB.BuiltInCategory.OST_Walls)


def _is_column(element):
    if element is None:
        return False
    category = element.Category
    if category is None:
        return False
    category_id = category.Id
    if category_id is None:
        return False
    cat_value = REVIT_APPLICATION.get_element_id_value(category_id)
    return cat_value in (ARCH_COLUMN_CAT_ID, STRUCT_COLUMN_CAT_ID)


def _collect_columns_from_selection(selection):
    columns = []
    for element in selection:
        if _is_column(element):
            columns.append(element)
    return columns


def _collect_all_columns(doc):
    columns = []
    arch_columns = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Columns).WhereElementIsNotElementType().ToElements()
    struct_columns = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType().ToElements()
    seen_ids = set()
    for column in arch_columns:
        column_id_value = REVIT_APPLICATION.get_element_id_value(column.Id)
        if column_id_value not in seen_ids:
            seen_ids.add(column_id_value)
            columns.append(column)
    for column in struct_columns:
        column_id_value = REVIT_APPLICATION.get_element_id_value(column.Id)
        if column_id_value not in seen_ids:
            seen_ids.add(column_id_value)
            columns.append(column)
    return columns


def _is_wall(element):
    if element is None:
        return False
    category = element.Category
    if category is None:
        return False
    category_id = category.Id
    if category_id is None:
        return False
    return REVIT_APPLICATION.get_element_id_value(category_id) == WALL_CAT_ID


def _get_wall_candidates(doc, column):
    """Gather wall elements related to the given column via joins, cuts, or hosting."""
    candidate_ids = []
    host = getattr(column, "Host", None)
    if host is not None and host.IsValidObject and _is_wall(host):
        candidate_ids.append(host.Id)
    try:
        joined_ids = DB.JoinGeometryUtils.GetJoinedElements(doc, column)
    except Exception:
        joined_ids = None
    if joined_ids:
        candidate_ids.extend(joined_ids)
    # Attempt to gather any solid-solid cut relationships (column cutting or being cut)
    # Older Revit builds may not expose all utility members, so guard each call.
    try:
        cutting_ids = DB.SolidSolidCutUtils.GetCuttingSolids(column)
    except Exception:
        cutting_ids = None
    if cutting_ids:
        candidate_ids.extend(cutting_ids)
    # Some API versions provide GetElementsBeingCut; ignore if unavailable.
    try:
        get_elements_being_cut = getattr(DB.SolidSolidCutUtils, "GetElementsBeingCut")
    except Exception:
        get_elements_being_cut = None
    if get_elements_being_cut is not None:
        try:
            target_ids = get_elements_being_cut(column)
        except Exception:
            target_ids = None
        if target_ids:
            candidate_ids.extend(target_ids)
    unique_ids = []
    seen = set()
    for item in candidate_ids:
        if item is None:
            continue
        if isinstance(item, DB.ElementId):
            key = REVIT_APPLICATION.get_element_id_value(item)
            if key in seen:
                continue
            seen.add(key)
            unique_ids.append(item)
        elif hasattr(item, "Id"):
            key = REVIT_APPLICATION.get_element_id_value(item.Id)
            if key in seen:
                continue
            seen.add(key)
            unique_ids.append(item.Id)
    wall_elements = []
    for element_id in unique_ids:
        try:
            element = doc.GetElement(element_id)
        except Exception:
            element = None
        if element is None or not element.IsValidObject:
            continue
        if _is_wall(element):
            wall_elements.append(element)
    return wall_elements


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def disjoin_columns_from_walls(doc):
    selection = REVIT_SELECTION.get_selection()
    selected_columns = _collect_columns_from_selection(selection)
    used_selection = bool(selected_columns)

    if used_selection:
        print("Processing {0} column(s) from current selection.".format(len(selected_columns)))
        columns = selected_columns
    else:
        columns = _collect_all_columns(doc)
        print("No columns found in the current selection.")
        print("Processing all editable columns instead: {0} found.".format(len(columns)))

    # Filter columns to those we can modify
    columns = list(REVIT_SELECTION.filter_elements_changable(columns))
    if not columns:
        NOTIFICATION.messenger("No editable columns available to process.")
        return

    transaction = DB.Transaction(doc, __title__)
    transaction.Start()
    total_columns = 0
    disjoined_pairs = 0
    columns_without_walls = 0
    solid_cut_pairs = 0
    skipped_locked = 0
    failure_pairs = 0
    solid_cut_failures = 0
    try:
        for column in columns:
            if column is None or not column.IsValidObject:
                continue

            if getattr(column, "IsReadOnly", False):
                skipped_locked += 1
                print("    Skipping column {0}; element is read-only.".format(column.Id))
                continue
            try:
                if hasattr(doc, "IsElementModifiable") and not doc.IsElementModifiable(column.Id):
                    skipped_locked += 1
                    print("    Skipping column {0}; element is not modifiable.".format(column.Id))
                    continue
            except Exception:
                pass

            total_columns += 1
            wall_candidates = _get_wall_candidates(doc, column)
            if not wall_candidates:
                columns_without_walls += 1
                print("    Column {0} has no wall joins or cuts to remove.".format(column.Id))
                continue

            disjoined_this_column = 0
            solid_cuts_this_column = 0
            for joined_element in wall_candidates:
                try:
                    if DB.JoinGeometryUtils.AreElementsJoined(doc, column, joined_element):
                        DB.JoinGeometryUtils.UnjoinGeometry(doc, column, joined_element)
                        disjoined_pairs += 1
                        disjoined_this_column += 1
                        print("        Disjoined column {0} from wall {1}.".format(column.Id, joined_element.Id))
                except Exception as exc:
                    failure_pairs += 1
                    print("        Failed to disjoin column {0} and wall {1}: {2}".format(column.Id, joined_element.Id, exc))
                try:
                    # SolidSolidCutUtils.AreElementsCut is not part of the Revit API
                    # (absent from RevitAPI.xml 2022-2026), so the old hasattr guard
                    # always skipped this branch. The documented call is
                    # CutExistsBetweenElements(first, second, out firstCutsSecond);
                    # IronPython returns (exists, first_cuts_second) for the out param.
                    cut_exists, column_cuts_wall = DB.SolidSolidCutUtils.CutExistsBetweenElements(column, joined_element)
                    if cut_exists:
                        DB.SolidSolidCutUtils.RemoveCutBetweenSolids(doc, column, joined_element)
                        solid_cut_pairs += 1
                        solid_cuts_this_column += 1
                        if column_cuts_wall:
                            print("        Removed solid-solid cut between column {0} and wall {1}.".format(column.Id, joined_element.Id))
                        else:
                            print("        Removed solid-solid cut between wall {0} and column {1}.".format(joined_element.Id, column.Id))
                except Exception as exc:
                    solid_cut_failures += 1
                    print("        Failed to remove solid-solid cut between column {0} and wall {1}: {2}".format(column.Id, joined_element.Id, exc))
            if disjoined_this_column == 0:
                if solid_cuts_this_column == 0:
                    columns_without_walls += 1
                    print("    Column {0} had no wall joins or cuts to remove.".format(column.Id))
                else:
                    print("    Column {0} had solid cuts removed but no join state to clear.".format(column.Id))
    except Exception:
        transaction.RollBack()
        raise
    else:
        transaction.Commit()

    summary_lines = []
    if used_selection:
        summary_lines.append("Selection used: {0} columns".format(len(selected_columns)))
    summary_lines.append("Columns processed: {0}".format(total_columns))
    summary_lines.append("Column-wall joins removed: {0}".format(disjoined_pairs))
    if solid_cut_pairs:
        summary_lines.append("Solid-solid cuts removed: {0}".format(solid_cut_pairs))
    if columns_without_walls:
        summary_lines.append("Columns without wall joins: {0}".format(columns_without_walls))
    if skipped_locked:
        summary_lines.append("Locked/read-only columns skipped: {0}".format(skipped_locked))
    if failure_pairs:
        summary_lines.append("Failed disjoin attempts: {0}".format(failure_pairs))
    if solid_cut_failures:
        summary_lines.append("Failed solid-solid cut removals: {0}".format(solid_cut_failures))

    NOTIFICATION.messenger("\n".join(summary_lines))


################## main code below #####################
if __name__ == "__main__":
    disjoin_columns_from_walls(DOC)






