#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """See who created, owns and last changed every element in a workshared model.

One scan builds a searchable table so you know exactly whom to ask before you touch
something, and which view an annotation actually lives in.

Features:
- Search bar, category filter and an owned-by-me-only toggle
- Separate tab listing views and their owners
- Select, zoom to, or open the host view straight from the table
- Read-only: nothing in the model is changed"""
__title__ = "Ownership\nInspect"
__tip__ = True

import clr # pyright: ignore
clr.AddReference("WindowsBase")

import System # pyright: ignore
from System.Windows.Threading import DispatcherTimer # pyright: ignore

from Autodesk.Revit import DB # pyright: ignore
from Autodesk.Revit.UI import ExternalEvent # pyright: ignore

from pyrevit import forms
from pyrevit import script
from pyrevit.forms import WPFWindow

import proDUCKtion # pyright: ignore
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, IMAGE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_EVENT, REVIT_FORMS, REVIT_SELECTION, REVIT_VIEW

import ownership_data

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()

__persistentengine__ = True

ALL_CATEGORIES = "All Categories"

SCOPE_WHOLE_MODEL = "Whole Model"
SCOPE_ACTIVE_VIEW = "Active View"
SCOPE_PICK_VIEWS = "Pick Views..."
SCAN_SCOPES = [SCOPE_WHOLE_MODEL, SCOPE_ACTIVE_VIEW, SCOPE_PICK_VIEWS]


def count_elements(view_ids):
    """Cheap element count for the confirmation dialogs - no ownership reads."""
    if view_ids is None:
        return DB.FilteredElementCollector(DOC).WhereElementIsNotElementType().GetElementCount()
    total = 0
    for view_id in view_ids:
        total += DB.FilteredElementCollector(DOC, view_id).WhereElementIsNotElementType().GetElementCount()
    return total


def confirm_scan(count, description):
    res = REVIT_FORMS.dialogue(title="EnneadTab Ownership Inspect",
                               main_text="You are about to scan {} elements in {}.".format(count, description),
                               sub_text="Ownership history is read element by element, so this can take a while on large scopes. Are you sure you want to proceed?",
                               options=["Scan Now", "Cancel"])
    return res == "Scan Now"


def make_messenger_reporter():
    """Throttled scan narrator: 'Scanning view [x] with N elements. X/Y'.

    messenger spawns an external exe, so the toasts keep coming even while a
    rescan holds the Revit UI thread (where no in-process progress bar can
    paint). Throttled to roughly 10 updates per scan, plus one whenever the
    scan moves to the next view.
    """
    state = {"last_done": None, "last_label": None}

    def report(done, total, unit_label, unit_count):
        if total <= 0:
            return False
        step = max(2000, total // 10)
        if unit_label != state["last_label"] or state["last_done"] is None or done - state["last_done"] >= step:
            state["last_label"] = unit_label
            state["last_done"] = done
            NOTIFICATION.messenger("Scanning {} with {} elements.\n{} / {} done".format(
                unit_label, unit_count, done, total))
        return False

    return report


def pick_views_and_confirm():
    """Returns (view_ids, description), or (None, None) when the user backs out."""
    views = DB.FilteredElementCollector(DOC).OfClass(DB.View).WhereElementIsNotElementType().ToElements()
    views = sorted([view for view in views if not view.IsTemplate],
                   key=lambda view: view.Name)
    picked = forms.SelectFromList.show(views,
                                       name_attr="Name",
                                       multiselect=True,
                                       title="Pick views to scan")
    if not picked:
        return None, None
    view_ids = [view.Id for view in picked]
    description = "{} selected views".format(len(view_ids))
    if not confirm_scan(count_elements(view_ids), description):
        return None, None
    return view_ids, description


class OwnershipInspectWindow(WPFWindow):

    def pre_actions(self):
        # ExternalEvent.Create needs valid API context, so every handler is
        # registered here, before Show(). Revit work triggered from this
        # modeless window goes ONLY through these events - never directly in a
        # WPF callback, and never by reading handler.OUT after Raise().
        self.select_handler = REVIT_EVENT.SimpleEventHandler(self._do_select)
        self.select_event = ExternalEvent.Create(self.select_handler)

        self.zoom_handler = REVIT_EVENT.SimpleEventHandler(self._do_zoom)
        self.zoom_event = ExternalEvent.Create(self.zoom_handler)

        self.open_view_handler = REVIT_EVENT.SimpleEventHandler(self._do_open_view)
        self.open_view_event = ExternalEvent.Create(self.open_view_handler)

        self.rescan_handler = REVIT_EVENT.SimpleEventHandler(self._do_rescan)
        self.rescan_event = ExternalEvent.Create(self.rescan_handler)

    @ERROR_HANDLE.try_catch_error()
    def __init__(self, view_ids, scope):
        self.pre_actions()
        WPFWindow.__init__(self, "OwnershipInspect.xaml")

        self.title_text.Text = "EnneadTab Ownership Inspect"
        self.sub_text.Text = "Who created it, who is holding it, who touched it last - element by element, view by view."
        self.Title = "EnneadTab Ownership Inspect"
        logo_file = IMAGE.get_image_path_by_name("logo_vertical_light.png")
        self.set_image_source(self.logo_img, logo_file)

        self.all_element_rows = []
        self.all_view_rows = []

        self.combo_scope.ItemsSource = SCAN_SCOPES
        self.combo_scope.SelectedItem = scope

        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = System.TimeSpan.FromMilliseconds(300)
        self.search_timer.Tick += self.search_timer_tick

        self.scan_with_progress(view_ids)
        self.refresh_category_options()
        self.apply_filters()
        self.Show()

    def scan_with_progress(self, view_ids):
        # First scan runs in script-launch API context; the progress bar only
        # works here (later rescans run inside ExternalEvent on the UI thread,
        # where nothing repaints).
        messenger_report = make_messenger_reporter()
        with forms.ProgressBar(title="Reading ownership... ({value} of {max_value})",
                               step=ownership_data.PROGRESS_STEP,
                               cancellable=True) as pb:

            def progress_update(done, total, unit_label, unit_count):
                pb.update_progress(done, total)
                messenger_report(done, total, unit_label, unit_count)
                return pb.cancelled

            element_rows, view_rows, capped, cancelled = ownership_data.scan_model(DOC, progress_update, view_ids)

        self.all_element_rows = element_rows
        self.all_view_rows = view_rows
        if capped:
            NOTIFICATION.messenger("Stopped after {} ownership lookups to keep Revit alive. Results are partial.".format(ownership_data.TOOLTIP_CALL_CAP), sticky=True)
            self.debug_textbox.Text = "Scan capped - table shows partial results."
        elif cancelled:
            self.debug_textbox.Text = "Scan cancelled - table shows partial results."

    def refresh_category_options(self):
        previous = self.combo_category.SelectedItem
        categories = sorted(set([row.category for row in self.all_element_rows]))
        options = [ALL_CATEGORIES] + categories
        self.combo_category.ItemsSource = options
        if previous in options:
            self.combo_category.SelectedItem = previous
        else:
            self.combo_category.SelectedIndex = 0

    def format_count(self, kept, total):
        shown = min(kept, ownership_data.MAX_DISPLAY_ROWS)
        text = "Showing {} of {}".format(shown, total)
        if kept > shown:
            text += " (display capped - narrow the search)"
        return text

    @ERROR_HANDLE.try_catch_error()
    def apply_filters(self, *args):
        # Always rebuild from the master lists and reassign ItemsSource in one
        # shot - in-place mutation of a bound collection is how grids get weird.
        rows = self.all_element_rows
        category = self.combo_category.SelectedItem
        if category and category != ALL_CATEGORIES:
            rows = [row for row in rows if row.category == category]
        if self.checkbox_owned_only.IsChecked:
            rows = [row for row in rows if row.owner]
        filtered = ownership_data.filter_rows_by_keyword(rows, self.tbox_search_elements.Text)
        if self.checkbox_collapse_similar.IsChecked:
            grouped = ownership_data.collapse_similar(filtered)
            self.grid_elements.ItemsSource = grouped[:ownership_data.MAX_DISPLAY_ROWS]
            text = "Showing {} groups ({} elements) of {}".format(
                min(len(grouped), ownership_data.MAX_DISPLAY_ROWS),
                len(filtered),
                len(self.all_element_rows))
            if len(grouped) > ownership_data.MAX_DISPLAY_ROWS:
                text += " (display capped - narrow the search)"
            self.tblock_element_count.Text = text
        else:
            self.grid_elements.ItemsSource = filtered[:ownership_data.MAX_DISPLAY_ROWS]
            self.tblock_element_count.Text = self.format_count(len(filtered), len(self.all_element_rows))

        view_rows = ownership_data.filter_rows_by_keyword(self.all_view_rows, self.tbox_search_views.Text)
        self.grid_views.ItemsSource = view_rows[:ownership_data.MAX_DISPLAY_ROWS]
        self.tblock_view_count.Text = self.format_count(len(view_rows), len(self.all_view_rows))

    @ERROR_HANDLE.try_catch_error()
    def search_changed(self, sender, args):
        # Debounce: master lists can be huge, no point filtering per keystroke.
        self.search_timer.Stop()
        self.search_timer.Start()

    def search_timer_tick(self, sender, args):
        self.search_timer.Stop()
        self.apply_filters()

    @ERROR_HANDLE.try_catch_error()
    def filter_changed(self, sender, args):
        self.apply_filters()

    def _selected_element_ids(self):
        rows = self.grid_elements.SelectedItems
        if not rows:
            return []
        element_ids = []
        for row in rows:
            element_ids.extend(row.get_element_ids())
        return element_ids

    # ---- Revit-side actions, all running inside ExternalEvent.Execute ----

    def _do_select(self, element_ids):
        elements = [DOC.GetElement(element_id) for element_id in element_ids]
        REVIT_SELECTION.set_selection([element for element in elements if element])

    def _do_zoom(self, element_ids):
        elements = [DOC.GetElement(element_id) for element_id in element_ids]
        REVIT_SELECTION.zoom_selection([element for element in elements if element])

    def _do_open_view(self, view_id):
        view = DOC.GetElement(view_id)
        if not view:
            NOTIFICATION.messenger("That view is no longer in the model.")
            return
        REVIT_VIEW.set_active_view(view, DOC)

    def _do_rescan(self, scope):
        # ExternalEvent.Execute runs on the Revit UI thread: API reads are
        # legal and so is touching the WPF controls, but nothing repaints
        # until this returns.
        if scope == SCOPE_ACTIVE_VIEW:
            active_view = DOC.ActiveView
            view_ids = [active_view.Id]
            description = "the active view [{}]".format(active_view.Name)
        elif scope == SCOPE_PICK_VIEWS:
            view_ids, description = pick_views_and_confirm()
            if view_ids is None:
                self.debug_textbox.Text = "Rescan cancelled."
                return
        else:
            view_ids = None
            description = "the whole model"

        if scope != SCOPE_PICK_VIEWS:
            # pick_views_and_confirm already confirmed its own selection
            if not confirm_scan(count_elements(view_ids), description):
                self.debug_textbox.Text = "Rescan cancelled."
                return

        element_rows, view_rows, capped, cancelled = ownership_data.scan_model(
            DOC, make_messenger_reporter(), view_ids)
        self.all_element_rows = element_rows
        self.all_view_rows = view_rows
        self.refresh_category_options()
        self.apply_filters()
        self.debug_textbox.Text = "Rescanned {}.".format(description) + (" Results are partial (capped)." if capped else "")
        NOTIFICATION.messenger("Ownership scan finished:\n{} elements, {} views tabled.".format(
            len(element_rows), len(view_rows)))

    # ---- WPF callbacks: package args, Raise, return ----

    @ERROR_HANDLE.try_catch_error()
    def select_click(self, sender, args):
        element_ids = self._selected_element_ids()
        if not element_ids:
            self.debug_textbox.Text = "Pick one or more rows first."
            return
        self.select_handler.args = (element_ids,)
        self.select_event.Raise()

    @ERROR_HANDLE.try_catch_error()
    def zoom_click(self, sender, args):
        element_ids = self._selected_element_ids()
        if not element_ids:
            self.debug_textbox.Text = "Pick one or more rows first."
            return
        self.zoom_handler.args = (element_ids,)
        self.zoom_event.Raise()

    @ERROR_HANDLE.try_catch_error()
    def open_element_view_click(self, sender, args):
        row = self.grid_elements.SelectedItem
        if not row:
            self.debug_textbox.Text = "Pick a row first."
            return
        if not row.owner_view_id:
            self.debug_textbox.Text = "Model element - it lives in every view, nothing to open."
            return
        self.open_view_handler.args = (row.owner_view_id,)
        self.open_view_event.Raise()

    @ERROR_HANDLE.try_catch_error()
    def open_view_view_click(self, sender, args):
        row = self.grid_views.SelectedItem
        if not row:
            self.debug_textbox.Text = "Pick a view row first."
            return
        self.open_view_handler.args = (row.element_id,)
        self.open_view_event.Raise()

    @ERROR_HANDLE.try_catch_error()
    def refresh_click(self, sender, args):
        self.debug_textbox.Text = "Rescanning - Revit will be busy for a moment..."
        self.rescan_handler.args = (self.combo_scope.SelectedItem,)
        self.rescan_event.Raise()

    @ERROR_HANDLE.try_catch_error()
    def close_click(self, sender, args):
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        sender.DragMove()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    if not DOC.IsWorkshared:
        NOTIFICATION.messenger("Ownership only exists in workshared models - this document is not workshared.")
        return

    active_view = DOC.ActiveView
    whole_count = count_elements(None)
    active_count = count_elements([active_view.Id])

    res = REVIT_FORMS.dialogue(
        title="EnneadTab Ownership Inspect",
        main_text="Who owns what, in which view?",
        sub_text="This tool reads the worksharing history of every element in scope and tables who CREATED it, "
                 "who currently OWNS it (has it checked out), and who LAST CHANGED it - handy for finding who is "
                 "holding the element you cannot edit, or reviewing modeling responsibility.\n\n"
                 "Ownership is read element by element, so scanning is heavy. Pick a scope:",
        options=[
            ["Scan Active View [{}]".format(active_view.Name),
             "{} visible elements - quick look at who owns this view".format(active_count)],
            ["Scan Whole Model",
             "{} elements - the complete picture; this will take a while on big models".format(whole_count)],
            ["Pick Views...",
             "choose specific views, see the element count, then decide"],
            "Cancel",
        ])

    if not res or res == "Cancel":
        return
    if res == "Scan Whole Model":
        view_ids = None
        scope = SCOPE_WHOLE_MODEL
    elif res.startswith("Scan Active View"):
        view_ids = [active_view.Id]
        scope = SCOPE_ACTIVE_VIEW
    else:
        view_ids, _ = pick_views_and_confirm()
        if view_ids is None:
            return
        scope = SCOPE_PICK_VIEWS

    OwnershipInspectWindow(view_ids, scope)


################## main code below #####################
output = script.get_output()
output.close_others()

if __name__ == "__main__":
    main()
