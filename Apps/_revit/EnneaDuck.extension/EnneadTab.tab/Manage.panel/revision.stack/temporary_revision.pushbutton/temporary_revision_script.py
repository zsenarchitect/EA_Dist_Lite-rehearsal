#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = "Temporarily hide selected revisions (titleblock impact) and restore later."
__title__ = "Temporary Revision"

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, DATA_FILE, NOTIFICATION, DATA_CONVERSION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION
from Autodesk.Revit import DB # pyright: ignore 
from pyrevit import forms

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


class TemporaryRevisionManager(object):
    STORAGE_FILE = "temporary_revision_records"

    def __init__(self, doc):
        self.doc = doc
        self.mode = None  # 'hide' or 'restore'
        self.is_showing = None  # True to unhide, False to hide

    # ---------- UI ----------
    def pick_mode(self):
        options = [
            "Temporary Hide Revisions",
            "Restore Temporarily Hidden Revisions"
        ]
        choice = forms.SelectFromList.show(options, multiselect=False, title=__title__, button_name='Select')
        return choice

    def pick_revisions(self):
        revisions = list(DB.FilteredElementCollector(self.doc).OfClass(DB.Revision).WhereElementIsNotElementType().ToElements())
        if not revisions:
            return []

        class RevisionOption(forms.TemplateListItem):
            @property
            def name(self):
                rev_num = getattr(self.item, 'RevisionNumber', None)
                desc = getattr(self.item, 'Description', '')
                if rev_num is None:
                    return str(REVIT_APPLICATION.get_element_id_value(self.item.Id))
                return "{} - {}".format(rev_num, desc)

        if self.mode == "hide":
            title = "Select revisions to temporarily hide from titleblocks"
            button = 'Hide Selected Revisions'
        else:
            # Keeping for future enhancement if restore needs filtering
            title = "Select revisions to restore visibility"
            button = 'Restore Selected Revisions'

        sel = forms.SelectFromList.show([RevisionOption(x) for x in revisions], multiselect=True, title=title, button_name=button)
        if not sel:
            return []
        # sel may return raw element or TemplateListItem
        return [getattr(x, 'item', x) for x in sel]

    # ---------- Helpers ----------
    def _get_document_guid(self):
        if hasattr(self.doc, 'IsWorkshared') and self.doc.IsWorkshared:
            return str(DB.WorksharingUtils.GetModelGUID(self.doc))
        return "DOC:" + self.doc.Title

    def _read_storage(self):
        data = DATA_FILE.get_data(self.STORAGE_FILE, is_local=False) or {}
        key = self._get_document_guid()
        return data.get(key, {})

    def _write_storage(self, per_sheet_map):
        with DATA_FILE.update_data(self.STORAGE_FILE, is_local=False) as data:
            key = self._get_document_guid()
            data[key] = per_sheet_map

    def _collect_all_revision_clouds(self):
        return list(DB.FilteredElementCollector(self.doc).OfCategory(DB.BuiltInCategory.OST_RevisionClouds).WhereElementIsNotElementType().ToElements())

    def _get_views_with_dependents(self, view):
        views_to_do = [view]
        dependent_view_ids = list(view.GetDependentViewIds())
        if dependent_view_ids:
            views_to_do.extend([self.doc.GetElement(x) for x in dependent_view_ids])
        return views_to_do

    def _hide_or_unhide_in_owner_and_dependents(self, element):
        owner_view_id = getattr(element, 'OwnerViewId', None)
        if not owner_view_id or owner_view_id == DB.ElementId.InvalidElementId:
            return
        owner_view = self.doc.GetElement(owner_view_id)
        if not owner_view:
            return
        for current_view in self._get_views_with_dependents(owner_view):
            if not current_view:
                continue
            if not REVIT_SELECTION.is_changable(current_view):
                continue
            ids = DATA_CONVERSION.list_to_system_list([element.Id])
            if self.is_showing:
                current_view.UnhideElements(ids)
            else:
                current_view.HideElements(ids)

    def _record_and_uncheck_sheet_revisions(self, bad_revision_ids):
        # Build map: sheet.UniqueId -> {sheet_number, sheet_name, revisions:[revision.UniqueId,...]}
        result = {}
        sheets = list(DB.FilteredElementCollector(self.doc).OfClass(DB.ViewSheet).WhereElementIsNotElementType().ToElements())
        for sheet in sheets:
            add_ids = list(sheet.GetAdditionalRevisionIds())
            # Record current state as UniqueIds
            recorded_rev_uids = []
            for eid in add_ids:
                rev = self.doc.GetElement(eid)
                if rev is not None:
                    try:
                        recorded_rev_uids.append(rev.UniqueId)
                    except:
                        pass

            # Remove bad revisions from AdditionalRevisionIds
            new_ids = [x for x in add_ids if x not in bad_revision_ids]
            if len(new_ids) != len(add_ids):
                sheet.SetAdditionalRevisionIds(DATA_CONVERSION.list_to_system_list(new_ids))

            result[sheet.UniqueId] = {
                "sheet_number": sheet.SheetNumber,
                "sheet_name": sheet.Name,
                "revisions": recorded_rev_uids
            }
        return result

    # ---------- Modes ----------
    def run_hide_mode(self):
        self.mode = "hide"
        self.is_showing = False
        picked_revisions = self.pick_revisions()
        if not picked_revisions:
            NOTIFICATION.messenger("No revisions selected.")
            return

        bad_rev_ids = set([x.Id for x in picked_revisions])

        t = DB.Transaction(self.doc, "Hide selected revisions and update sheets")
        t.Start()
        # Step 1: hide all clouds referencing bad revisions
        hidden_clouds = 0
        for cloud in self._collect_all_revision_clouds():
            if cloud.RevisionId and cloud.RevisionId in bad_rev_ids:
                self._hide_or_unhide_in_owner_and_dependents(cloud)
                hidden_clouds += 1

        # Step 2: uncheck sheet-specific AdditionalRevisionIds for bad revisions and record per-sheet state
        record_map = self._record_and_uncheck_sheet_revisions(bad_rev_ids)
        t.Commit()

        # Persist record
        self._write_storage(record_map)
        NOTIFICATION.messenger("Hidden {} clouds and updated {} sheets. Stored per-sheet revision settings for restore.".format(hidden_clouds, len(record_map)))

    def run_restore_mode(self):
        self.mode = "restore"
        self.is_showing = True
        data = self._read_storage()
        if not data:
            NOTIFICATION.messenger("No stored temporary revision data found for this model.")
            return

        # Build lookup from revision UniqueId to ElementId
        all_revs = list(DB.FilteredElementCollector(self.doc).OfClass(DB.Revision).WhereElementIsNotElementType().ToElements())
        rev_uid_to_id = dict([(r.UniqueId, r.Id) for r in all_revs])

        t = DB.Transaction(self.doc, "Restore temporarily hidden revisions")
        t.Start()

        # Step 1: unhide every revision cloud in all owner/dependent views
        unhidden_clouds = 0
        for cloud in self._collect_all_revision_clouds():
            self._hide_or_unhide_in_owner_and_dependents(cloud)
            unhidden_clouds += 1

        # Step 2: reassign recorded sheet AdditionalRevisionIds
        updated_sheets = 0
        iterator = data.iteritems() if hasattr(data, 'iteritems') else data.items()
        for sheet_uid, payload in iterator:
            sheet = self._get_element_by_unique_id_safe(sheet_uid)
            if sheet is None:
                continue

            wanted_rev_uids = payload.get("revisions", [])
            wanted_ids = [rev_uid_to_id[uid] for uid in wanted_rev_uids if uid in rev_uid_to_id]
            sheet.SetAdditionalRevisionIds(DATA_CONVERSION.list_to_system_list(wanted_ids))
            updated_sheets += 1

        t.Commit()
        NOTIFICATION.messenger("Restore completed: unhid {} clouds and updated {} sheets.".format(unhidden_clouds, updated_sheets))

    def _get_element_by_unique_id_safe(self, unique_id):
        return self.doc.GetElement(unique_id)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def temporary_revision(doc):
    manager = TemporaryRevisionManager(doc)
    mode = manager.pick_mode()
    if mode == "Temporary Hide Revisions":
        manager.run_hide_mode()
    elif mode == "Restore Temporarily Hidden Revisions":
        manager.run_restore_mode()
    else:
        NOTIFICATION.messenger("No action taken.")



################## main code below #####################
if __name__ == "__main__":
    temporary_revision(DOC)







