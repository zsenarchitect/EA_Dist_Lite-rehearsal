#!/usr/bin/python
# -*- coding: utf-8 -*-



__doc__ = """Open the Project Config window and pick the project setup task you want to run.

One modeless window gathers the healthcare project tools (design outline, project
initialization, DGSF chart, color palette) together with the generic project-data
setup/edit actions, so you do not have to hunt for separate buttons. The window stays
open after you trigger an action, so you can run several in a row.

Features:
- Read the Ennead healthcare design outline
- Initialize a new healthcare project
- Edit or open the project data setup
- Update the detailed DGSF chart
- Refresh the department color palette from an Excel file"""
__title__ = "Project\nConfig"
__tip__ = True
__is_popular__ = True

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent # pyright: ignore
from Autodesk.Revit.Exceptions import InvalidOperationException # pyright: ignore
from pyrevit.forms import WPFWindow
from pyrevit import forms #
from pyrevit import script #

import proDUCKtion # pyright: ignore
proDUCKtion.validify()
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_PROJ_DATA
from EnneadTab import IMAGE, USER, NOTIFICATION, ERROR_HANDLE, LOG
import traceback
from Autodesk.Revit import DB # pyright: ignore

import design_guideline
import dgsf_chart
import color_pallete

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()
__persistentengine__ = True
# __persistentengine__ keeps this module (and the handler/event instances pre_actions
# creates) alive after main() returns, which a modeless window needs -- a normal
# pyRevit engine gets torn down as soon as the script call returns, which would
# orphan the window's event handlers. Only a full Revit restart clears a persistent
# engine, so `pyrevit reload` will NOT pick up edits to this file; a BUILD_TAG is
# shown in the window so you can confirm which build is actually loaded before
# trusting a test result.
BUILD_TAG = "build-2026-09-02-a"


# Create a subclass of IExternalEventHandler
class SimpleEventHandler(IExternalEventHandler):
    """
    Simple IExternalEventHandler sample
    """

    # __init__ is used to make function from outside of the class to be executed by the handler. \
    # Instructions could be simply written under Execute method only
    def __init__(self, do_this):
        self.do_this = do_this
        self.kwargs = None
        self.OUT = None


    # Execute method run in Revit API environment.
    def Execute(self,  uiapp):
        try:
            try:
                self.OUT = self.do_this(*self.kwargs)
            except:
                print ("failed")
                print (traceback.format_exc())
        except InvalidOperationException:
            # If you don't catch this exeption Revit may crash.
            print ("InvalidOperationException catched")

    def GetName(self):
        return "simple function executed by an IExternalEventHandler in a Form"


# A simple WPF form used to call the ExternalEvent
class ProjectConfig(WPFWindow):
    """
    Modeless launcher for the project config actions. Every action below runs on
    the Revit API thread via its own ExternalEvent -- never directly from a WPF
    click callback -- because several of them (setup_healthcare_project,
    dgsf_chart_update, update_color_pallete) start their own DB.Transaction.
    Buttons are plain static actions (no DataGrid, no bound Revit elements), so
    the DataGrid-row-selection crash class documented in this repo's CLAUDE.md
    does not apply here.
    """

    def pre_actions(self):
        self.show_design_outline_handler = SimpleEventHandler(design_guideline.show_design_outline)
        self.ext_event_show_design_outline = ExternalEvent.Create(self.show_design_outline_handler)

        self.setup_healthcare_project_handler = SimpleEventHandler(REVIT_PROJ_DATA.setup_healthcare_project)
        self.ext_event_setup_healthcare_project = ExternalEvent.Create(self.setup_healthcare_project_handler)

        self.edit_project_data_file_handler = SimpleEventHandler(REVIT_PROJ_DATA.edit_project_data_file)
        self.ext_event_edit_project_data_file = ExternalEvent.Create(self.edit_project_data_file_handler)

        self.open_project_data_file_handler = SimpleEventHandler(REVIT_PROJ_DATA.open_project_data_file)
        self.ext_event_open_project_data_file = ExternalEvent.Create(self.open_project_data_file_handler)

        self.dgsf_chart_update_handler = SimpleEventHandler(dgsf_chart.dgsf_chart_update)
        self.ext_event_dgsf_chart_update = ExternalEvent.Create(self.dgsf_chart_update_handler)

        self.update_color_pallete_handler = SimpleEventHandler(color_pallete.update_color_pallete)
        self.ext_event_update_color_pallete = ExternalEvent.Create(self.update_color_pallete_handler)
        return

    def __init__(self):
        self.pre_actions()

        xaml_file_name = "ProjectConfig.xaml"
        WPFWindow.__init__(self, xaml_file_name)

        self.title_text.Text = "EnneadTab Project Config"
        self.sub_text.Text = "Healthcare project setup and general project-data tools."
        self.build_tag_text.Text = BUILD_TAG

        self.Title = "EnneadTab Project Config"

        logo_file = IMAGE.get_image_path_by_name("logo_vertical_light.png")
        self.set_image_source(self.logo_img, logo_file)

        self.debug_textbox.Text = "Debug Output:"

        self.Show()

    def _run(self, handler, event):
        event.Raise()
        res = handler.OUT
        if res:
            self.debug_textbox.Text = res
        else:
            self.debug_textbox.Text = "Debug Output:"

    @ERROR_HANDLE.try_catch_error()
    def show_design_outline_Click(self, sender, e):
        self.show_design_outline_handler.kwargs = (DOC,)
        self._run(self.show_design_outline_handler, self.ext_event_show_design_outline)

    @ERROR_HANDLE.try_catch_error()
    def setup_healthcare_project_Click(self, sender, e):
        self.setup_healthcare_project_handler.kwargs = (DOC,)
        self._run(self.setup_healthcare_project_handler, self.ext_event_setup_healthcare_project)

    @ERROR_HANDLE.try_catch_error()
    def edit_project_data_file_Click(self, sender, e):
        self.edit_project_data_file_handler.kwargs = (DOC,)
        self._run(self.edit_project_data_file_handler, self.ext_event_edit_project_data_file)

    @ERROR_HANDLE.try_catch_error()
    def open_project_data_file_Click(self, sender, e):
        self.open_project_data_file_handler.kwargs = (DOC,)
        self._run(self.open_project_data_file_handler, self.ext_event_open_project_data_file)

    @ERROR_HANDLE.try_catch_error()
    def dgsf_chart_update_Click(self, sender, e):
        self.dgsf_chart_update_handler.kwargs = (DOC,)
        self._run(self.dgsf_chart_update_handler, self.ext_event_dgsf_chart_update)

    @ERROR_HANDLE.try_catch_error()
    def update_color_pallete_Click(self, sender, e):
        self.update_color_pallete_handler.kwargs = (DOC,)
        self._run(self.update_color_pallete_handler, self.ext_event_update_color_pallete)

    def close_Click(self, sender, e):
        # This Raise() method launch a signal to Revit to tell him you want to do something in the API context
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        sender.DragMove()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    ProjectConfig()


################## main code below #####################
output = script.get_output()
output.close_others()


if __name__ == "__main__":

    main()
