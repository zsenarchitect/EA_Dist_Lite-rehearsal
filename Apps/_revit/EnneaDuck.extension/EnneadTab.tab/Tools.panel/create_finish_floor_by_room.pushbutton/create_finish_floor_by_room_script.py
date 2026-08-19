#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Create finish floors from picked Rooms.

Pick rooms in the model, choose a floor type (ranked by your recent usage,
then alphabetical), set a level offset (mm and inch are tied), then create
one finish floor per room. All floors land in a single undo step.

- While picking, Rooms and Room Tags are temporarily isolated in the active
  view so they are easy to select; the view is restored afterwards.
- Uses each room's own Level; the offset is written to 'Height Offset From Level'.
- Only the outer room boundary is used (solid finish floor, inner loops ignored).
- Rooms already given a finish floor by this tool are skipped (no duplicates).
- Rooms with no boundary / no level / bad geometry are skipped and reported.
"""
__title__ = "Finish Floor\nby Room"

import math
import traceback

from pyrevit.forms import WPFWindow
from pyrevit import script

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent  # pyright: ignore
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter  # pyright: ignore
from Autodesk.Revit.Exceptions import OperationCanceledException  # pyright: ignore

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

from EnneadTab import DATA_FILE, DATA_CONVERSION, IMAGE, ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_UNIT
from Autodesk.Revit import DB  # pyright: ignore

uidoc = REVIT_APPLICATION.get_uidoc()
doc = REVIT_APPLICATION.get_doc()
__persistentengine__ = True

SETTINGS_KEY = "finish_floor_by_room"
MARK_PREFIX = "EA_FinishFloor_"   # written to floor 'Comments' for dedup
RECENT_CAP = 15

output = script.get_output()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
# single source of truth - ElementId-to-int lives in the shared lib
get_id_value = REVIT_APPLICATION.get_element_id_value


def get_type_name(floor_type):
    """Floor type display name, robust across API shapes."""
    try:
        name = DB.Element.Name.GetValue(floor_type)
        if name:
            return name
    except Exception:
        pass
    param = floor_type.LookupParameter("Type Name")
    if param:
        return param.AsString()
    return None


def parse_float(text):
    """Return float or None. Half-typed input ('1.', '', '-') yields None, never 0."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except (ValueError, TypeError):
        return None
    # reject inf / nan - they sail through float() and then poison the offset
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def inches_to_internal(value):
    try:
        return REVIT_UNIT.unit_to_internal(value, "inches")
    except Exception:
        return value / 12.0


def internal_to_inches(value):
    try:
        return REVIT_UNIT.internal_to_unit(value, "inches")
    except Exception:
        return value * 12.0


class RoomSelectionFilter(ISelectionFilter):
    """Allow only placed Rooms during PickObjects."""
    def AllowElement(self, elem):
        return isinstance(elem, DB.Architecture.Room)

    def AllowReference(self, ref, point):
        return False


class WarningSwallower(DB.IFailuresPreprocessor):
    """Delete Warning-severity failures (e.g. 'Floors overlap') so the batch
    does not hang on modal warning dialogs. Errors are left to surface."""
    def PreprocessFailures(self, failures_accessor):
        for fm in failures_accessor.GetFailureMessages():
            if fm.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(fm)
        return DB.FailureProcessingResult.Continue


# ---------------------------------------------------------------------------
# geometry / model helpers
# ---------------------------------------------------------------------------
def collect_floor_type_map(active_doc):
    """Return {type_name: FloorType} for all floor types in the doc."""
    types = DB.FilteredElementCollector(active_doc).OfClass(DB.FloorType).ToElements()
    result = {}
    for ft in types:
        name = get_type_name(ft)
        if name:
            result[name] = ft
    return result


def rank_type_names(current_names, recent_names):
    """Recent (most-recent-first) that still exist, then the rest alphabetical."""
    ranked = []
    seen = set()
    for name in recent_names:
        if name in current_names and name not in seen:
            ranked.append(name)
            seen.add(name)
    rest = sorted([n for n in current_names if n not in seen])
    return ranked + rest


def collect_existing_marks(active_doc):
    """Set of MARK strings already stamped on finish floors by this tool."""
    marks = set()
    floors = DB.FilteredElementCollector(active_doc)\
               .OfClass(DB.Floor)\
               .WhereElementIsNotElementType()\
               .ToElements()
    for f in floors:
        # BuiltInParameter, not LookupParameter("Comments") - the display name is
        # localized on non-English Revit, which would silently break dedup.
        cm = f.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if cm:
            value = cm.AsString()
            if value and value.startswith(MARK_PREFIX):
                marks.add(value)
    return marks


def build_outer_curveloop(room):
    """Outer boundary of a room as a CurveLoop, or None if unusable.

    Judges emptiness before indexing, and wraps Append (contiguity / zero-length
    / tolerance failures throw here, distinct from Floor.Create's own validation).
    """
    opts = DB.SpatialElementBoundaryOptions()   # default location = Finish
    loops = room.GetBoundarySegments(opts)
    if loops is None or loops.Count == 0:
        return None
    outer = loops[0]
    if outer is None or outer.Count == 0:
        return None
    curve_loop = DB.CurveLoop()
    try:
        for seg in outer:
            crv = seg.GetCurve()
            if crv is not None:
                curve_loop.Append(crv)
    except Exception:
        return None
    return curve_loop


def get_room_label(room):
    try:
        number = room.Number
    except Exception:
        number = ""
    try:
        name = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString()
    except Exception:
        name = ""
    label = "{} {}".format(number or "", name or "").strip()
    return label or "Room {}".format(get_id_value(room.Id))


# ---------------------------------------------------------------------------
# external event handler
# ---------------------------------------------------------------------------
class SimpleEventHandler(IExternalEventHandler):
    """Runs a callable inside a valid Revit API context. The callable receives
    the live uiapp so selection / transactions are done in-context."""
    def __init__(self, do_this):
        self.do_this = do_this

    def Execute(self, uiapp):
        try:
            self.do_this(uiapp)
        except Exception:
            print(traceback.format_exc())

    def GetName(self):
        return "EnneadTab Finish Floor by Room event"


# ---------------------------------------------------------------------------
# dialog
# ---------------------------------------------------------------------------
class FinishFloorByRoomForm(WPFWindow):

    def pre_actions(self):
        self.pick_handler = SimpleEventHandler(self.do_pick)
        self.pick_event = ExternalEvent.Create(self.pick_handler)
        self.create_handler = SimpleEventHandler(self.do_create)
        self.create_event = ExternalEvent.Create(self.create_handler)

    @ERROR_HANDLE.try_catch_error()
    def __init__(self):
        self.pre_actions()

        WPFWindow.__init__(self, "create_finish_floor_by_room_UI.xaml")

        self.title_text.Text = "Finish Floor by Room"
        self.sub_text.Text = ("Pick rooms, choose a floor type and a level offset, "
                              "then create one finish floor per room in a single undo.")
        self.Title = self.title_text.Text

        try:
            logo_file = IMAGE.get_image_path_by_name("logo_vertical_light.png")
            self.set_image_source(self.logo_img, logo_file)
        except Exception:
            pass

        self.host_doc = doc   # the dialog is bound to the doc it opened in
        self.picked_room_ids = []
        self.name_to_type_id = {}
        self._pending_type_name = None
        self._offset_internal = 0.0
        self._suppress = False

        self.populate_floor_types()
        self.load_setting()
        self.refresh_offset_boxes()
        self.update_selection_label()

        self.Show()

    # ---- floor type combo ----------------------------------------------
    @ERROR_HANDLE.try_catch_error()
    def populate_floor_types(self):
        type_map = collect_floor_type_map(doc)
        self.name_to_type_id = dict(
            (name, ft.Id) for name, ft in type_map.items())

        data = DATA_FILE.get_data(SETTINGS_KEY) or {}
        recent = data.get("recent_type_names", [])

        ranked = rank_type_names(set(type_map.keys()), recent)

        self.combo_floor_type.Items.Clear()
        for name in ranked:
            self.combo_floor_type.Items.Add(name)
        if ranked:
            self.combo_floor_type.SelectedIndex = 0

    # ---- settings ------------------------------------------------------
    @ERROR_HANDLE.try_catch_error()
    def load_setting(self):
        data = DATA_FILE.get_data(SETTINGS_KEY) or {}
        offset = data.get("last_offset_internal", 0.0)
        try:
            self._offset_internal = float(offset)
        except (ValueError, TypeError):
            self._offset_internal = 0.0

    @ERROR_HANDLE.try_catch_error()
    def save_offset_setting(self):
        data = DATA_FILE.get_data(SETTINGS_KEY) or {}
        data["last_offset_internal"] = self._offset_internal
        DATA_FILE.set_data(data, SETTINGS_KEY)

    @ERROR_HANDLE.try_catch_error()
    def record_recent_type(self, type_name):
        data = DATA_FILE.get_data(SETTINGS_KEY) or {}
        recent = data.get("recent_type_names", [])
        recent = [n for n in recent if n != type_name]
        recent.insert(0, type_name)
        data["recent_type_names"] = recent[:RECENT_CAP]
        DATA_FILE.set_data(data, SETTINGS_KEY)

    # ---- offset mm/inch tie --------------------------------------------
    def refresh_offset_boxes(self):
        self._suppress = True
        try:
            self.textbox_offset_mm.Text = "{:.1f}".format(
                REVIT_UNIT.internal_to_mm(self._offset_internal))
            self.textbox_offset_inch.Text = "{:.3f}".format(
                internal_to_inches(self._offset_internal))
        finally:
            self._suppress = False

    @ERROR_HANDLE.try_catch_error()
    def offset_mm_lost_focus(self, sender, e):
        if self._suppress:
            return
        value = parse_float(self.textbox_offset_mm.Text)
        if value is None:
            self.refresh_offset_boxes()
            return
        self._offset_internal = REVIT_UNIT.mm_to_internal(value)
        self.refresh_offset_boxes()

    @ERROR_HANDLE.try_catch_error()
    def offset_inch_lost_focus(self, sender, e):
        if self._suppress:
            return
        value = parse_float(self.textbox_offset_inch.Text)
        if value is None:
            self.refresh_offset_boxes()
            return
        self._offset_internal = inches_to_internal(value)
        self.refresh_offset_boxes()

    # ---- selection label ----------------------------------------------
    def update_selection_label(self):
        count = len(self.picked_room_ids)
        if count:
            self.debug_textbox.Text = "Selected {} room(s). Ready to create.".format(count)
        else:
            self.debug_textbox.Text = "No rooms picked yet. Click 'Pick Rooms'."

    # ---- pick rooms (via external event) -------------------------------
    @ERROR_HANDLE.try_catch_error()
    def pick_rooms_click(self, sender, e):
        self.Hide()
        self.pick_event.Raise()

    def _isolate_rooms(self, active_doc, view):
        """Temporarily isolate Rooms + Room Tags in the view so they are easy to
        pick. Returns True if isolation was applied (so it can be undone later)."""
        if view is None:
            return False
        try:
            if not view.CanUseTemporaryVisibilityModes():
                return False
            id_list = []
            for bic in (DB.BuiltInCategory.OST_Rooms, DB.BuiltInCategory.OST_RoomTags):
                collector = DB.FilteredElementCollector(active_doc, view.Id)\
                    .OfCategory(bic).WhereElementIsNotElementType()
                for el in collector:
                    id_list.append(el.Id)
            if not id_list:
                return False
            ids = DATA_CONVERSION.list_to_system_list(
                id_list, type=DATA_CONVERSION.DataType.ElementId, use_IList=False)
            t = DB.Transaction(active_doc, "Isolate rooms for picking")
            t.Start()
            try:
                view.IsolateElementsTemporary(ids)
                t.Commit()
                return True
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                return False
        except Exception:
            print(traceback.format_exc())
            return False

    def _restore_view(self, active_doc, view):
        """Drop the temporary isolate applied for picking."""
        if view is None:
            return
        try:
            t = DB.Transaction(active_doc, "Restore view after picking")
            t.Start()
            try:
                view.DisableTemporaryViewMode(
                    DB.TemporaryViewMode.TemporaryHideIsolate)
                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
        except Exception:
            print(traceback.format_exc())

    def do_pick(self, uiapp):
        sel_uidoc = uiapp.ActiveUIDocument
        if sel_uidoc is None or not sel_uidoc.Document.Equals(self.host_doc):
            NOTIFICATION.messenger(
                "Active document changed. Close and reopen this tool in the target model.")
            try:
                self.Show()
            except Exception:
                print(traceback.format_exc())
            return
        active_doc = sel_uidoc.Document
        view = active_doc.ActiveView
        isolated = self._isolate_rooms(active_doc, view)
        try:
            refs = sel_uidoc.Selection.PickObjects(
                ObjectType.Element, RoomSelectionFilter(),
                "Select rooms to create finish floors")
            self.picked_room_ids = [r.ElementId for r in refs]
        except OperationCanceledException:
            pass
        except Exception:
            print(traceback.format_exc())
        finally:
            # restore the view first, then the window. If Show() escapes here the
            # dialog becomes an invisible zombie and the user must restart Revit.
            if isolated:
                self._restore_view(active_doc, view)
            try:
                self.Show()
                self.update_selection_label()
            except Exception:
                print(traceback.format_exc())

    # ---- create (via external event) -----------------------------------
    @ERROR_HANDLE.try_catch_error()
    def create_click(self, sender, e):
        if not self.picked_room_ids:
            NOTIFICATION.messenger("Pick rooms first.")
            return
        selected_name = self.combo_floor_type.SelectedItem
        if not selected_name or selected_name not in self.name_to_type_id:
            NOTIFICATION.messenger("Choose a floor type first.")
            return

        # snapshot the validated type so do_create uses exactly what was checked
        # here (the combo could change in the async gap before Execute runs)
        self._pending_type_name = selected_name

        # make sure the latest typed offset is captured (button steals focus,
        # which fires LostFocus first, but re-read defensively)
        value = parse_float(self.textbox_offset_mm.Text)
        if value is not None:
            self._offset_internal = REVIT_UNIT.mm_to_internal(value)
        self.save_offset_setting()

        self.create_event.Raise()

    def do_create(self, uiapp):
        active_doc = uiapp.ActiveUIDocument.Document
        if active_doc is None or not active_doc.Equals(self.host_doc):
            NOTIFICATION.messenger(
                "Active document changed. Close and reopen this tool in the target model.")
            return

        selected_name = self._pending_type_name
        floor_type_id = self.name_to_type_id.get(selected_name)
        offset_internal = self._offset_internal

        existing_marks = collect_existing_marks(active_doc)
        results = []   # (status, label, detail)
        created = 0
        aborted = False
        swallower = WarningSwallower()   # stateless - one instance for the batch

        tg = DB.TransactionGroup(active_doc, "Create Finish Floors by Rooms")
        tg.Start()
        try:
            for rid in self.picked_room_ids:
                room = active_doc.GetElement(rid)
                if room is None or not room.IsValidObject:
                    # deleted between pick and create - report it, don't drop silently
                    results.append(("SKIP", "Room {}".format(get_id_value(rid)),
                                    "room no longer exists"))
                    continue
                label = get_room_label(room)

                if room.Area <= 0 or room.LevelId == DB.ElementId.InvalidElementId:
                    results.append(("SKIP", label, "unplaced / no level"))
                    continue

                mark = MARK_PREFIX + str(get_id_value(room.Id))
                if mark in existing_marks:
                    results.append(("SKIP", label, "floor already exists"))
                    continue

                curve_loop = build_outer_curveloop(room)
                if curve_loop is None:
                    results.append(("SKIP", label, "no / invalid boundary"))
                    continue

                t = DB.Transaction(active_doc, "Finish Floor - {}".format(label))
                t.Start()
                try:
                    fho = t.GetFailureHandlingOptions()
                    fho.SetFailuresPreprocessor(swallower)
                    t.SetFailureHandlingOptions(fho)

                    floor = DB.Floor.Create(
                        active_doc,
                        DATA_CONVERSION.list_to_system_list(
                            [curve_loop],
                            type=DATA_CONVERSION.DataType.CurveLoop,
                            use_IList=False),
                        floor_type_id,
                        room.LevelId)

                    notes = []
                    # inherit the room's own Base Offset so split-level / mezzanine
                    # rooms get their floor at the real room floor, then add the user value
                    base_offset = 0.0
                    bo_param = room.get_Parameter(DB.BuiltInParameter.ROOM_LOWER_OFFSET)
                    if bo_param:
                        base_offset = bo_param.AsDouble()
                    effective_offset = base_offset + offset_internal

                    offset_param = floor.get_Parameter(
                        DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                    if offset_param and not offset_param.IsReadOnly:
                        offset_param.Set(effective_offset)
                    elif effective_offset != 0.0:
                        notes.append("offset not applied (read-only)")

                    # BuiltInParameter avoids the localized-name dedup failure
                    comment_param = floor.get_Parameter(
                        DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                    if comment_param and not comment_param.IsReadOnly:
                        comment_param.Set(mark)
                    else:
                        notes.append("dedup mark not written - rerun may duplicate")

                    t.Commit()
                    created += 1
                    existing_marks.add(mark)
                    detail = get_id_value(floor.Id)
                    if notes:
                        results.append(("WARN", label, "{} ({})".format(detail, "; ".join(notes))))
                    else:
                        results.append(("OK", label, detail))
                except Exception as ex:
                    # RollBack itself can throw on a damaged state - never let it
                    # swallow the result record for this room.
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    results.append(("FAIL", label, str(ex)))

            if created > 0:
                tg.Assimilate()
            else:
                tg.RollBack()
        except Exception:
            # structural failure (not a single-room failure): the whole group
            # is rolled back, so nothing was actually created.
            aborted = True
            try:
                if tg.HasStarted() and not tg.HasEnded():
                    tg.RollBack()
            except Exception:
                pass
            print(traceback.format_exc())

        if aborted:
            created = 0

        if created > 0:
            self.record_recent_type(selected_name)

        self.report(results, created, selected_name, aborted)
        self.update_selection_label()

    # ---- reporting -----------------------------------------------------
    def report(self, results, created, type_name, aborted=False):
        output.close_others()
        output.print_md("# Finish Floor by Room")
        if aborted:
            output.print_md("## BATCH ABORTED - the group was rolled back, nothing was created.")
        output.print_md("Floor type: **{}**  |  Created: **{}** of {} room(s)".format(
            type_name, created, len(results)))
        table = [[status, label, str(detail)] for (status, label, detail) in results]
        if table:
            output.print_table(
                table_data=table,
                columns=["Status", "Room", "Floor Id / Reason"])
        if aborted:
            NOTIFICATION.messenger("Batch aborted - nothing created. See report.", sticky=True)
        else:
            NOTIFICATION.messenger("Created {} finish floor(s).".format(created))

    # ---- window chrome -------------------------------------------------
    @ERROR_HANDLE.try_catch_error()
    def close_click(self, sender, e):
        self.save_offset_setting()
        self.Close()

    @ERROR_HANDLE.try_catch_error()
    def mouse_down_main_panel(self, sender, e):
        self.DragMove()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    FinishFloorByRoomForm()


################## main code below #####################
if __name__ == "__main__":
    main()
