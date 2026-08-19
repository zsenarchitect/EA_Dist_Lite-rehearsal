#!/usr/bin/python
# -*- coding: utf-8 -*-


import shutil
import os
import sys
import time
import datetime
import subprocess


def _bootstrap_module_path():
    """Ensure bundled runtime can import shared utilities."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_root = os.path.dirname(script_dir)

    if getattr(sys, "frozen", False):
        frozen_root = getattr(sys, "_MEIPASS", source_root)
        # Add the PyInstaller extraction root first so bundled helpers are importable.
        if frozen_root not in sys.path:
            sys.path.insert(0, frozen_root)
        # Also add the script directory in case helper modules live alongside the entry point.
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
    else:
        if source_root not in sys.path:
            sys.path.insert(0, source_root)


_bootstrap_module_path()
import _Exe_Util
import _GUI_Util
import pygame

TITLE = u"EnneadTab Revit Schedule Opener."
DATA_FILE = "schedule_opener_data"


def start_revit(revit_version):
    revit_path = "C:\\Program Files\\Autodesk\\Revit {}\\Revit.exe".format(revit_version)
    subprocess.Popen(revit_path)


    
class ScheduleOpener(_GUI_Util.BasePyGameGUI):
    def __init__(self):

        self.app_title = TITLE
        self.SCREEN_WIDTH = 700
        self.SCREEN_HEIGHT = 500
        self.content_folder = os.path.dirname(__file__)

        self.life_max = _GUI_Util.BasePyGameGUI.MAX_LIFE
        self.life_count = self.life_max

        self.taskbar_icon = "{}\\images\\icon.png".format(self.content_folder)

    

        self.setup_GUI()
        self.set_RIR_clicker()


    def set_RIR_clicker(self):
        data = _Exe_Util.get_data("auto_click_data")
        if "ref_images" not in data or data["ref_images"] is None:
            data["ref_images"] = []
        data["ref_images"].append("{}\\images\\search_RIR_7.png".format(_Exe_Util.CORE_LIB_FOLDER))
        _Exe_Util.set_data(data, "auto_click_data")
        _Exe_Util.try_open_app("AutoClicker")


    

    def display_data(self, data):
        self.POINTER_Y = 150
        
        self.draw_text("Below are docs that will be opened:", self.FONT_SUBTITLE, self.TEXT_COLOR_FADE)
        
        target_time = data["open_time"]
        
        try:
            # Try parsing the ISO format timestamp
            target_time = datetime.datetime.strptime(target_time, "%Y-%m-%dT%H:%M:%S.%f")
        except:
            try:
                # Fallback for whole clock time
                target_time = datetime.datetime.strptime(target_time, "%Y-%m-%dT%H:%M:%S")
            except:
                # Ultimate fallback - Rick Roll time! 🎵
                target_time = datetime.datetime.now() + datetime.timedelta(seconds=10)
                self.draw_text("Never gonna give you up...", self.FONT_BODY, self.TEXT_COLOR_WARNING)
        
        time_diff = target_time - datetime.datetime.now()
        self.draw_text("Time Till Scheduled Open Time: {}".format(time_diff), 
                      self.FONT_BODY, self.TEXT_COLOR_FADE)
        
        # Convert timedelta to seconds for life_count
        self.life_count = int(time_diff.total_seconds())
        
        for i, doc in enumerate(data["docs"]):
            self.draw_text("    [{}]".format(doc), self.FONT_BODY, self.TEXT_COLOR_WARNING)
        
        if datetime.datetime.now() > target_time:
            revit_version = data['revit_version']
            start_revit(revit_version)
            data_file = _Exe_Util.get_file_in_dump_folder(DATA_FILE)
            marker_file = os.path.join(os.path.dirname(data_file), "action_" + DATA_FILE + _Exe_Util.PLUGIN_EXTENSION)
            if os.path.exists(marker_file):
                os.remove(marker_file)
            shutil.copyfile(data_file, marker_file)
            os.remove(data_file)
            return True

        

    @_Exe_Util.try_catch_error
    def main(self):

        while self.run:
            self.reset_pointer()# move pointer to initial position
            self.screen.fill(self.BACKGROUND_COLOR)# fill background color before drawing anything elese
            
            self.update_logo_angle()# update animated logo
            self.update_title()
            self.update_footnote()


            
            data = _Exe_Util.get_data(DATA_FILE)
            if not data:# no data
                self.run = False
                return False
            res = self.display_data(data)
            if res:
                data = None#clear data to prevent repeat open revit
            
            self.check_exit()

            # refresh all drawing by order
            self.clock.tick(self.FPS)
            pygame.display.update()

        pygame.quit()



if __name__ == "__main__":
    monitor = ScheduleOpener()
    monitor.main()