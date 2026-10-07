#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Publish selected sheets from the open model onto BimRunner's pinup wall.

Exports each picked sheet to PDF and uploads it to the current cloud model's
project page on BimRunner, so a client or reviewer can see it without anyone
emailing a PDF around. Republishing the same sheet later updates its existing
entry instead of duplicating it, even if the sheet has since been renumbered.

The model is detected automatically from the open document -- there is
nothing to search for or type. If the model has never been synced to
BimRunner, or is not a cloud (ACC/BIM 360) model, publishing is blocked with
a clear message instead of guessing.

Usage:
1. Open a cloud-workshared model already tracked in BimRunner
2. Run the button and click "Pick Sheets to Publish"
3. Click "Publish to BimRunner" and watch the per-sheet status
4. Review the pass/fail summary in the status window"""
__title__ = "Publish to\nBimRunner"
__author__ = "EnneadTab"

import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import Application as WinFormsApplication

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.Exceptions import InvalidOperationException
from pyrevit.forms import WPFWindow
from pyrevit import forms, script

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()
from EnneadTab.REVIT import REVIT_APPLICATION
from EnneadTab import AUTH, IMAGE, NOTIFICATION, ERROR_HANDLE, LOG
from EnneadTab import WEB_REVIT
from EnneadTab.AI import _common

import os
import time
import traceback
from Autodesk.Revit import DB  # pyright: ignore
from System.Collections.Generic import List  # pyright: ignore

uidoc = REVIT_APPLICATION.get_uidoc()
doc = REVIT_APPLICATION.get_doc()
__persistentengine__ = True


# --- Revit-side helpers -----------------------------------------------------

def get_cloud_model_identity(document):
    """Returns (model_guid, project_guid) as strings, or (None, None) if the
    open document is not a cloud (ACC/BIM 360) model.

    Proven call site: ACE.panel/get_model_guids.pushbutton -- the same
    Document.GetWorksharingCentralModelPath() -> ModelPath.GetModelGUID()/
    GetProjectGUID() pair this repo already ships and uses live.
    """
    try:
        model_path = document.GetWorksharingCentralModelPath()
    except Exception:
        return None, None

    if not model_path or not getattr(model_path, "ServerPath", False):
        return None, None

    try:
        model_guid = str(model_path.GetModelGUID())
        project_guid = str(model_path.GetProjectGUID())
    except Exception:
        return None, None

    return model_guid, project_guid


class SheetPickerOption(forms.TemplateListItem):
    """Row wrapper for forms.SelectFromList -- same pattern content_transfer
    uses (MyOptionPickDoc). Never stores anything beyond a display label and
    the sheet's own Id.Value / UniqueId, per the DataGrid-adjacent crash-
    class checklist's "never hold a live element across a UI round trip"
    rule -- SelectFromList is safer than a hand-rolled DataGrid, but the
    same discipline still applies to what a row object carries."""

    @property
    def name(self):
        return "{} - {}".format(self.item.SheetNumber, self.item.Name)


def get_publishable_sheets(document):
    """Every ViewSheet in the document, sorted by sheet number. No shared-
    parameter pre-filter -- the DataGrid/SelectFromList selection itself IS
    the "which sheets" decision, per the approved design (manual per-row
    pick, not a flagged-in-advance subset)."""
    sheets = list(
        DB.FilteredElementCollector(document)
        .OfClass(DB.ViewSheet)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    sheets.sort(key=lambda s: s.SheetNumber)
    return sheets


def export_sheet_to_pdf(document, sheet, dest_folder):
    """Export one sheet to a PDF in dest_folder. Returns the PDF path.

    Proven, dialog-free call site: ACE.panel/AutoExporter.pushbutton/
    revit_export_logic.py export_pdf() -- that tool runs unattended
    overnight, so this exact DB.PDFExportOptions() + Document.Export(...)
    shape is already confirmed to never pop a modal options dialog.
    """
    safe_name = "".join(
        c if (c.isalnum() or c in "-_. ") else "_" for c in sheet.Name
    )
    filename_base = "{}_{}".format(sheet.SheetNumber, safe_name)
    pdf_path = os.path.join(dest_folder, filename_base + ".pdf")

    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except Exception:
            pass

    export_options = DB.PDFExportOptions()
    export_options.HideCropBoundaries = True
    export_options.HideScopeBoxes = True
    export_options.HideReferencePlane = True
    export_options.Combine = False
    export_options.StopOnError = False

    view_ids = List[DB.ElementId]()
    view_ids.Add(sheet.Id)

    document.Export(dest_folder, view_ids, export_options)

    if not os.path.exists(pdf_path):
        raise Exception(
            "Revit did not create the expected PDF: {}".format(pdf_path))

    return pdf_path


def get_export_temp_folder():
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "EnneadTab_publish_to_bimrunner")
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder


# --- ExternalEvent plumbing (write-adjacent Revit API calls only) -----------
# Matches content_transfer.pushbutton's SimpleEventHandler pattern. Reading
# sheets (get_publishable_sheets) runs directly from the click handler, same
# as content_transfer's pick_* methods -- only the export+upload sequence,
# which touches document.Export() and file I/O, goes through ExternalEvent.

class SimpleEventHandler(IExternalEventHandler):
    def __init__(self, do_this):
        self.do_this = do_this
        self.kwargs = None
        self.OUT = None

    def Execute(self, uiapp):  # noqa: N802 (Revit API casing)
        try:
            try:
                self.OUT = self.do_this(*self.kwargs)
            except Exception:
                self.OUT = ("__EXCEPTION__", traceback.format_exc())
        except InvalidOperationException:
            self.OUT = ("__EXCEPTION__", "InvalidOperationException")

    def GetName(self):  # noqa: N802
        return "publish_to_bimrunner event handler"


# --- Modeless form -----------------------------------------------------

class publish_to_bimrunner_ModelessForm(WPFWindow):

    def pre_actions(self):
        self.publish_event_handler = SimpleEventHandler(self._publish_one_sheet)
        self.ext_event_publish = ExternalEvent.Create(self.publish_event_handler)

    def __init__(self):
        self.pre_actions()

        xaml_file_name = "publish_to_bimrunner_ModelessForm.xaml"
        WPFWindow.__init__(self, xaml_file_name)

        self.title_text.Text = "Publish to BimRunner"
        self.sub_text.Text = __doc__
        self.Title = self.title_text.Text

        logo_file = IMAGE.get_image_path_by_name("logo_vertical_light.png")
        self.set_image_source(self.logo_img, logo_file)

        self.model_guid = None
        self.project_guid = None
        self.job_id = None
        self.picked_sheets = []
        self.auth_listener_registered = False

        self._detect_model()

        self.Show()

    # --- status helpers ---------------------------------------------------

    def _log(self, line):
        existing = self.textblock_status.Text
        if existing in ("Ready.", ""):
            self.textblock_status.Text = line
        else:
            self.textblock_status.Text = existing + "\n" + line

    # --- model detection ----------------------------------------------

    @ERROR_HANDLE.try_catch_error()
    def _detect_model(self):
        self.model_guid, self.project_guid = get_cloud_model_identity(doc)

        if not self.model_guid:
            self.textblock_model_display.Text = (
                "This document is not a cloud (ACC/BIM 360) model. "
                "Publishing to BimRunner needs a cloud model.")
            self.button_publish.IsEnabled = False
            return

        self.textblock_model_display.Text = (
            "Looking up this model on BimRunner...")

        try:
            self.job_id = WEB_REVIT.resolve_job_id(self.model_guid, self.project_guid)
        except WEB_REVIT.WebRevitError as e:
            self.textblock_model_display.Text = (
                "Could not reach BimRunner: {}".format(e))
            self.button_publish.IsEnabled = False
            return

        if not self.job_id:
            self.textblock_model_display.Text = (
                "This model has not been extracted by BimRunner yet. "
                "Run the model health extraction first, then publish.")
            self.button_publish.IsEnabled = False
            return

        self.textblock_model_display.Text = (
            "Model: {}\nModel GUID: {}\nCurrent job: {}".format(
                doc.Title, self.model_guid, self.job_id))
        self._update_publish_enabled()

    def _update_publish_enabled(self):
        self.button_publish.IsEnabled = bool(self.job_id and self.picked_sheets)

    # --- sheet picking (direct, read-only -- no ExternalEvent needed) -----

    @ERROR_HANDLE.try_catch_error()
    def pick_sheets_click(self, sender, e):
        all_sheets = get_publishable_sheets(doc)
        if not all_sheets:
            self.textblock_sheets_display.Text = "No sheets found in this document."
            return

        picked = forms.SelectFromList.show(
            [SheetPickerOption(s) for s in all_sheets],
            title="Pick sheets to publish",
            multiselect=True,
            button_name="Select Sheets")

        if not picked:
            self.picked_sheets = []
            self.textblock_sheets_display.Text = "No sheets picked yet."
            self._update_publish_enabled()
            return

        self.picked_sheets = picked
        names = "\n".join(
            "{} - {}".format(s.SheetNumber, s.Name) for s in picked)
        self.textblock_sheets_display.Text = "{} sheet(s) picked:\n{}".format(
            len(picked), names)
        self._update_publish_enabled()

    # --- auth --------------------------------------------------------------

    def _get_token_or_start_auth(self):
        """Non-blocking, per AUTH.py's own rule: get_token_blocking() must
        never be called from a Revit UI thread. Matches the pattern already
        proven in Tools.panel/ai_render.pushbutton."""
        token = AUTH.get_token()
        if token:
            return token

        if not AUTH.is_auth_in_progress():
            AUTH.request_auth()
        return None

    # --- publish (ExternalEvent-driven, sequential, resilient) -------------

    @ERROR_HANDLE.try_catch_error()
    def publish_click(self, sender, e):
        if not self.job_id:
            self._log("No BimRunner job to publish against.")
            return
        if not self.picked_sheets:
            self._log("No sheets picked.")
            return

        token = self._get_token_or_start_auth()
        if not token:
            self._log(
                "Not signed in yet -- a browser window should have opened. "
                "Sign in, then click Publish again.")
            return

        self.button_publish.IsEnabled = False
        self.button_pick_sheets.IsEnabled = False

        dest_folder = get_export_temp_folder()
        total = len(self.picked_sheets)
        succeeded = 0
        failed = []

        for index, sheet in enumerate(self.picked_sheets, 1):
            label = "{} - {}".format(sheet.SheetNumber, sheet.Name)
            self._log("[{}/{}] Exporting {}...".format(index, total, label))

            self.publish_event_handler.kwargs = (
                sheet, dest_folder, self.job_id, token)
            self.ext_event_publish.Raise()

            # ExternalEvent.Raise() is fire-and-forget; give Revit's API
            # context a moment to run the handler before reading OUT. This
            # mirrors the "give it a beat" idiom other modeless forms in
            # this repo use around ExternalEvent -- NOT a substitute for a
            # real completion signal, which pyRevit's ExternalEvent does
            # not expose.
            #
            # This modeless form shares Revit's own UI thread (Show(), not a
            # separate STA thread), and Revit only services a raised
            # ExternalEvent during its Idling loop, which requires this same
            # thread to return to its message pump. A bare time.sleep() here
            # blocks that pump completely, so the very message that would end
            # the wait can never be processed -- the loop is then guaranteed
            # to ride out its full per-sheet timeout, and Revit's main window
            # reports Not Responding for the whole wait (confirmed live
            # incident #6396, 2026-09-21: Revit hung with near-zero CPU for
            # 9+ minutes and had to be force-killed). WinFormsApplication.
            # DoEvents() pumps the message queue each tick so the Idling
            # callback -- and the rest of the UI -- can actually run while we
            # wait.
            waited = 0.0
            while self.publish_event_handler.OUT is None and waited < 300.0:
                WinFormsApplication.DoEvents()
                time.sleep(0.25)
                waited += 0.25

            result = self.publish_event_handler.OUT
            self.publish_event_handler.OUT = None

            if isinstance(result, tuple) and result and result[0] == "__EXCEPTION__":
                failed.append((label, result[1].strip().splitlines()[-1] if result[1] else "unknown error"))
                self._log("  FAILED: {}".format(failed[-1][1]))
                continue

            if result is None:
                failed.append((label, "timed out waiting for Revit"))
                self._log("  FAILED: timed out")
                continue

            succeeded += 1
            self._log("  OK")

        self._log("")
        self._log("Done: {}/{} succeeded.".format(succeeded, total))
        if failed:
            self._log("Failures:")
            for label, reason in failed:
                self._log("  - {}: {}".format(label, reason))

        NOTIFICATION.messenger(
            main_text="Publish to BimRunner: {}/{} sheets succeeded.".format(
                succeeded, total))

        self.button_publish.IsEnabled = True
        self.button_pick_sheets.IsEnabled = True

    def _publish_one_sheet(self, sheet, dest_folder, job_id, token):
        """Runs inside the ExternalEvent's Revit API context: export, then
        upload. Returns True on success; raises on any failure (caught by
        SimpleEventHandler.Execute and surfaced as an __EXCEPTION__ tuple)."""
        pdf_path = export_sheet_to_pdf(doc, sheet, dest_folder)

        unique_id = sheet.UniqueId
        category = WEB_REVIT.classify_sheet_number(sheet.SheetNumber)

        WEB_REVIT.publish_sheet(
            job_id, pdf_path, unique_id, category, token,
            file_name=os.path.basename(pdf_path))

        try:
            os.remove(pdf_path)
        except Exception:
            pass

        return True

    # --- window chrome -------------------------------------------------

    def close_Click(self, sender, e):
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        sender.DragMove()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    publish_to_bimrunner_ModelessForm()


################## main code below #####################
output = script.get_output()
output.close_others()


if __name__ == "__main__":
    main()
