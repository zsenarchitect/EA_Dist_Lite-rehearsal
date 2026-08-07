# -*- coding: utf-8 -*-
"""Scan logic and table row objects for the Ownership Inspect dialog.

Single consumer: ownership_inspect_script.py. The scan walks every instance
element once and feeds both tabs (elements + views) from the same pass.
"""

from collections import OrderedDict

from Autodesk.Revit import DB # pyright: ignore

from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION

# GetWorksharingTooltipInfo is a per-element worksharing-history lookup and
# dominates the scan cost (monster models would otherwise hold the UI thread
# for tens of minutes). RevitSlave caps its bulk worksharing queries the same
# way.
TOOLTIP_CALL_CAP = 50000

# The full result set stays in memory; only the bound ItemsSource is capped so
# the DataGrid never tries to host six-digit row counts.
MAX_DISPLAY_ROWS = 5000

PROGRESS_STEP = 500


def row_matches_keyword(row, keyword):
    """Decide if one table row survives the search box.

    v1 strategy (shipped 2026-06-10, tune freely - only the search box calls
    this): case-insensitive token AND. Every whitespace-separated token must
    appear somewhere in the row, so "john wall" finds John's walls even though
    the words live in different columns.
    """
    tokens = keyword.lower().split()
    if not tokens:
        return True
    haystack = " ".join([str(field) for field in row.searchable_fields()]).lower()
    for token in tokens:
        if token not in haystack:
            return False
    return True


def filter_rows_by_keyword(rows, keyword):
    if not keyword or not keyword.strip():
        return rows
    return [row for row in rows if row_matches_keyword(row, keyword)]


def get_element_name(element):
    try:
        name = element.Name
    except Exception:
        name = ""
    return name or ""


class ElementOwnershipRow(object):
    def __init__(self, element, name, creator, owner, last_changed_by, view_name, workset):
        self.element_id = element.Id
        self.owner_view_id = element.OwnerViewId if element.ViewSpecific else None
        self.id_text = str(REVIT_APPLICATION.get_element_id_value(element.Id))
        self.category = element.Category.Name
        self.name = name
        self.creator = creator
        self.owner = owner
        self.last_changed_by = last_changed_by
        self.view_name = view_name
        self.workset = workset

    def searchable_fields(self):
        return [self.category, self.name, self.creator, self.owner,
                self.last_changed_by, self.view_name, self.workset, self.id_text]

    def get_element_ids(self):
        return [self.element_id]


class CollapsedOwnershipRow(object):
    """One row standing in for N element rows that read identically."""

    def __init__(self, rows):
        first = rows[0]
        self.category = first.category
        self.name = first.name
        self.creator = first.creator
        self.owner = first.owner
        self.last_changed_by = first.last_changed_by
        self.view_name = first.view_name
        self.workset = first.workset
        self.owner_view_id = first.owner_view_id
        self.count = len(rows)
        self.id_text = "{} items".format(len(rows))
        self.element_ids = [row.element_id for row in rows]

    def searchable_fields(self):
        return [self.category, self.name, self.creator, self.owner,
                self.last_changed_by, self.view_name, self.workset, self.id_text]

    def get_element_ids(self):
        return self.element_ids


def collapse_similar(rows):
    """Group rows whose display columns all read the same into one row each.

    Singles keep their real Id; groups show '<N> items' and carry every
    member id, so Select / Zoom act on the whole group. Input order wins.
    """
    groups = OrderedDict()
    for row in rows:
        key = (row.category, row.name, row.creator, row.owner,
               row.last_changed_by, row.view_name, row.workset)
        groups.setdefault(key, []).append(row)
    collapsed = []
    for members in groups.values():
        if len(members) == 1:
            collapsed.append(members[0])
        else:
            collapsed.append(CollapsedOwnershipRow(members))
    return collapsed


class ViewOwnershipRow(object):
    def __init__(self, view, creator, owner, last_changed_by):
        self.element_id = view.Id
        if isinstance(view, DB.ViewSheet):
            self.view_name = "{} - {}".format(view.SheetNumber, get_element_name(view))
            self.view_type = "Sheet"
        else:
            self.view_name = get_element_name(view)
            self.view_type = str(view.ViewType)
        if view.IsTemplate:
            self.view_type += " (Template)"
        self.creator = creator
        self.owner = owner
        self.last_changed_by = last_changed_by

    def searchable_fields(self):
        return [self.view_name, self.view_type, self.creator, self.owner,
                self.last_changed_by]


def scan_model(doc, progress_update=None, view_ids=None):
    """Build rows for both tabs in one pass.

    progress_update: callable(done, total, unit_label, unit_count) returning
        True to cancel, or None. unit_label/unit_count describe the view (or
        whole model) currently being walked, for progress messengers.
    view_ids: None scans the whole model; a list of view ElementIds scans only
        elements VISIBLE in those views (view-scoped collectors), and the
        Views tab then lists just the scanned views.
    Returns (element_rows, view_rows, capped, cancelled).
    """
    workset_table = doc.GetWorksetTable()
    workset_names = {}

    def get_workset_name(workset_id):
        key = REVIT_APPLICATION.get_element_id_value(workset_id)
        if key not in workset_names:
            try:
                workset_names[key] = workset_table.GetWorkset(workset_id).Name
            except Exception:
                workset_names[key] = ""
        return workset_names[key]

    view_names = {}

    def get_view_name(view_id):
        key = REVIT_APPLICATION.get_element_id_value(view_id)
        if key not in view_names:
            view = doc.GetElement(view_id)
            view_names[key] = get_element_name(view) if view else ""
        return view_names[key]

    element_rows = []
    view_rows = []
    capped = False
    cancelled = False
    tooltip_calls = 0
    seen = set()

    if view_ids is None:
        total = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().GetElementCount()
        scan_units = [("whole model", total,
                       DB.FilteredElementCollector(doc).WhereElementIsNotElementType())]
    else:
        # Scoped mode: the scanned views themselves are the Views tab; the
        # view-scoped collectors below never return the View element itself.
        total = 0
        scan_units = []
        for view_id in view_ids:
            view = doc.GetElement(view_id)
            if not view or not isinstance(view, DB.View):
                continue
            try:
                creator, last_changed_by, owner = REVIT_SELECTION.get_ownership_info(doc, view_id)
                tooltip_calls += 1
                view_rows.append(ViewOwnershipRow(view, creator, owner, last_changed_by))
            except Exception:
                pass
            unit_count = DB.FilteredElementCollector(doc, view_id).WhereElementIsNotElementType().GetElementCount()
            total += unit_count
            scan_units.append(("view [{}]".format(get_element_name(view)), unit_count,
                               DB.FilteredElementCollector(doc, view_id).WhereElementIsNotElementType()))

    done = -1
    for unit_label, unit_count, collector in scan_units:
        if capped or cancelled:
            break
        if progress_update:
            # announce each unit as we enter it, even before its first element
            if progress_update(done + 1, total, unit_label, unit_count):
                cancelled = True
                break
        for element in collector:
            done += 1
            if progress_update and done % PROGRESS_STEP == 0:
                if progress_update(done, total, unit_label, unit_count):
                    cancelled = True
                    break

            key = REVIT_APPLICATION.get_element_id_value(element.Id)
            if key in seen:
                continue
            seen.add(key)

            is_view = isinstance(element, DB.View)
            if not is_view and not element.Category:
                continue

            if tooltip_calls >= TOOLTIP_CALL_CAP:
                capped = True
                break
            try:
                creator, last_changed_by, owner = REVIT_SELECTION.get_ownership_info(doc, element.Id)
            except Exception:
                continue
            tooltip_calls += 1

            if is_view:
                view_rows.append(ViewOwnershipRow(element, creator, owner, last_changed_by))
            else:
                if element.ViewSpecific:
                    view_name = get_view_name(element.OwnerViewId)
                else:
                    view_name = "(Model)"
                element_rows.append(ElementOwnershipRow(element,
                                                        get_element_name(element),
                                                        creator,
                                                        owner,
                                                        last_changed_by,
                                                        view_name,
                                                        get_workset_name(element.WorksetId)))

    element_rows.sort(key=lambda row: (row.category, row.name))
    view_rows.sort(key=lambda row: row.view_name)
    return element_rows, view_rows, capped, cancelled
