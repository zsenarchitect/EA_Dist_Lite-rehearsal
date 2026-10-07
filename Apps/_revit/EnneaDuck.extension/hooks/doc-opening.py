from pyrevit import EXEC_PARAMS
from pyrevit.coreutils import envvars
# pyRevit hook engines do not inherit the .lib search path that button scripts get,
# so put KingDuck.lib on sys.path before importing proDUCKtion (the EnneadTab bootstrap).
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "KingDuck.lib")))
import proDUCKtion # pyright: ignore 
proDUCKtion.validify()
from EnneadTab import ERROR_HANDLE, FOLDER, ARCADE, ENVIRONMENT
from EnneadTab.REVIT import REVIT_FORMS





def check_is_template_folder():
    path = EXEC_PARAMS.event_args.PathName
    extension = FOLDER.get_file_extension_from_path(path)
    #print extension
    if extension not in [".rft", ".rfa"]:
        return
    template_root = os.path.join(ENVIRONMENT.L_DRIVE_HOST_FOLDER, "01_Revit", "02_Template")
    library_root = os.path.join(ENVIRONMENT.L_DRIVE_HOST_FOLDER, "01_Revit", "03_Library")
    if path.startswith(template_root) or path.startswith(library_root):
        REVIT_FORMS.notification(
            self_destruct=5,
            main_text="This family is currently saved in the shared network library/template folder\nRepath to your project folder to avoid affecting the original.",
            sub_text=path
        )

@ERROR_HANDLE.try_catch_error(is_silent=True)
def main():
    check_is_template_folder()
    # A document open can freeze Revit as long as a sync does. Arm the arcade wait-watcher;
    # doc-opened deletes the flag when the open resolves. Contract: EnneadTab/ARCADE.py.
    doc_name = ""
    try:
        doc_name = os.path.basename(EXEC_PARAMS.event_args.PathName or "")
    except Exception:
        pass
    ARCADE.start_wait_watch("open", doc_name)

##########################################

if __name__ == '__main__':
    main()