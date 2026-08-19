
__title__ = "ChinaCodeRef"
__doc__ = """Open a China building code reference PDF without leaving Rhino.

Pick a document from the list and it opens straight away, or jump to the folder to drop in
codes that are not there yet. The folder is created for you the first time you run it.

Usage:
1. Run the button and pick a code document from the list
2. Choose to open the folder instead if you want to add more PDFs"""
import os
import subprocess
from EnneadTab import EXE, FOLDER, ENVIRONMENT, NOTIFICATION
from EnneadTab.RHINO import RHINO_FORMS

from EnneadTab import LOG, ERROR_HANDLE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def china_code_ref():
    # Use local folder instead of network drive
    folder = os.path.join(ENVIRONMENT.DOCUMENT_FOLDER, "BuildingCode")
    
    # Check if folder exists, if not create it
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
            NOTIFICATION.messenger("Created BuildingCode folder. Please add your code reference files there.", sticky=True)
            return
        except Exception as e:
            NOTIFICATION.messenger("Failed to create BuildingCode folder: {}".format(str(e)))
            return
    
    try:
        files = os.listdir(folder)
    except Exception as e:
        NOTIFICATION.messenger("Failed to access BuildingCode folder: {}".format(str(e)))
        return
    
    # Filter out non-PDF files and special folders
    pdf_files = [f for f in files if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        NOTIFICATION.messenger("No PDF files found in BuildingCode folder. Please add your code reference PDFs there.")
        return

    keyword = "<Open BuildingCode Folder...>"
    pdf_files.insert(0, keyword)

    selected_opt = RHINO_FORMS.select_from_list(pdf_files, multi_select = False, message = "Select a code reference document:")

    if not selected_opt:
        return

    if keyword == selected_opt:
        subprocess.Popen('explorer /select, {}'.format(folder))
        return

    filepath = os.path.join(folder, str(selected_opt))
    EXE.try_open_app(filepath)


if __name__ == "__main__":
    china_code_ref()