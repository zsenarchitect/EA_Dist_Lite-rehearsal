

#!/usr/bin/python
# -*- coding: utf-8 -*-


import rhinoscriptsyntax as rs
import scriptcontext as sc

import os
import sys

# get current script file directory
my_directory = os.path.dirname(os.path.realpath(__file__))

sys.path.append(my_directory)
import city_utility # pyright: ignore

from EnneadTab import ERROR_HANDLE, NOTIFICATION, AUTH
from EnneadTab.DEPOT import _transport


def _upload_plot_file(filepath, plot_name):
    """Upload the freshly-exported .3dm to the cloud API.

    Per-plot failure is reported individually (ErrorDump + NOTIFICATION) --
    the top-level @ERROR_HANDLE.try_catch_error() decorator on
    export_from_masterplan() only tells you the whole function threw
    somewhere, not which specific plot's upload failed. Returns True on
    success, False otherwise (after reporting)."""
    try:
        token = AUTH.get_token()
        if not token:
            NOTIFICATION.messenger(
                main_text="Not signed in -- plot {} exported locally but NOT "
                         "uploaded to the cloud. Sign in and re-run.".format(plot_name)
            )
            return False

        if not os.path.exists(filepath):
            message = "Export produced no local file for plot {} at {}".format(plot_name, filepath)
            try:
                ERROR_HANDLE.send_error_to_error_dump(message, "_upload_plot_file", city_utility.USER.USER_NAME)
            except Exception:
                pass
            NOTIFICATION.messenger(main_text=message)
            return False

        with open(filepath, "rb") as f:
            data_bytes = f.read()

        url = "{}/plots/{}/upload".format(city_utility.API_BASE, plot_name)
        result = _transport.upload_bytes(url, data_bytes, token=token)

        if result.transport_failed or not result.ok():
            message = "Upload failed for plot {} (HTTP {}): {}".format(
                plot_name, result.status, result.error)
            try:
                ERROR_HANDLE.send_error_to_error_dump(message, "_upload_plot_file", city_utility.USER.USER_NAME)
            except Exception:
                pass
            NOTIFICATION.messenger(main_text=message)
            return False

        return True
    except Exception as e:
        message = "Unexpected error uploading plot {}: {}".format(plot_name, str(e))
        try:
            ERROR_HANDLE.send_error_to_error_dump(message, "_upload_plot_file", city_utility.USER.USER_NAME)
        except Exception:
            pass
        NOTIFICATION.messenger(main_text=message)
        return False


@ERROR_HANDLE.try_catch_error()
def export_from_masterplan():
    used_plots = city_utility.get_occupied_plot_names()
    print("Used plots = " + str(used_plots))
    
    # get groups that is currently visible in view
    for group in rs.GroupNames():


        contents = rs.ObjectsByGroup(group)
        if not contents:
            continue
        is_group_hidden = False
        for content in contents:
            if not rs.IsVisibleInView(content):
                is_group_hidden = True
                
                break
            if rs.IsTextDot(content):
                break
        if is_group_hidden:
            continue
        plot_name = rs.TextDotText(content)#.zfill(3)
        #print plot_name

        rs.UnselectAllObjects()
        rs.SelectObjects(contents)

        if plot_name in used_plots:
            NOTIFICATION.messenger(main_text = "Skipping plot {}. File already been claimmed.".format(plot_name))
            print(plot_name)
            continue
        """
        if os.path.exists(filepath):
            NOTIFICATION.messenger(main_text = "Skipping plot {}. File already exists".format(plot_name))
            continue
        """
        filepath = "{}\{}.3dm".format(city_utility.PLOT_FILES_FOLDER, plot_name)
        #print filepath
        rs.Command("!_-Export \"{}\" -Enter -Enter".format(filepath))
        _upload_plot_file(filepath, plot_name)


    rs.UnselectAllObjects()



   
   
    pass




      




######################  main code below   #########
if __name__ == "__main__":

    export_from_masterplan()


