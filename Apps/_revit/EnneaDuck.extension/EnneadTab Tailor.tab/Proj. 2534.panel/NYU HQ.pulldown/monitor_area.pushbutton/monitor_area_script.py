#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Check the designed areas against the program requirement and publish to the NYU HQ webapp.

Every area in the model is matched to its line in the program targets (fetched
from the webapp API -- Postgres is the system of record), so you can see at a
glance which departments are over, under, or on target. Color schemes and the
area parameters are refreshed from the match, and the report + geometry are
published to the webapp, which renders the dashboard in your browser.

Features:
- Areas that have no match in the program are called out
- Color schemes are rebuilt so over and under areas read by color in plan
- Report and geometry are published via the webapp API (service token auth)
- Department level summary spreadsheets can be exported to the file exchange folder"""
__title__ = "Monitor Area"


import os
import traceback
import time
import webbrowser

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, NOTIFICATION, EXE, USER, FOLDER

try:
    import pythoncom
    from win32com.client import DispatchEx, constants
    _HAS_EXCEL_AUTOMATION = True
except Exception:
    _HAS_EXCEL_AUTOMATION = False

from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_FORMS
from Autodesk.Revit import DB # pyright: ignore 

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


# Import consolidated modules
# NOTE: targets come from the NYU HQ webapp API (target_data.py -- Postgres is
# the system of record), NOT from the hand-crafted Excel drop. Excel drops are
# dirty inputs cleaned by AI agents via the webapp's MCP server, or fine-tuned
# by humans in targets.html. Revit only reads the clean data via the API.
from target_data import get_target_data
from revit_data import get_revit_area_data_by_scheme
from website_data_export import WebsiteDataExporter
from color_scheme_updater import update_all_color_schemes
from parameter_updater import update_area_parameters
import department_matrix
import config


def _get_matrix_export_directory():
    username = os.environ.get('USERNAME')
    if not username:
        try:
            username = USER.get_user_name()
        except Exception:
            username = None

    if not username:
        return None

    base_dir = os.path.join(
        "C:\\Users",
        username,
        "DC",
        "ACCDocs",
        "Ennead Architects LLP",
        "2534_NYUL Long Island HQ",
        "Project Files",
        "[EXTERNAL] File Exchange Hub",
        "B-10_Architecture_EA",
        "EA Linked Schedule"
    )

    if os.path.isdir(base_dir):
        return base_dir

    print("Matrix export skipped - directory not found: {}".format(base_dir))
    return None


def _force_excel_resave(filepath):
    if _HAS_EXCEL_AUTOMATION:
        pythoncom.CoInitialize()
        excel = DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        try:
            time.sleep(0.25)
            workbook = excel.Workbooks.Open(
                filepath,
                UpdateLinks=constants.xlUpdateLinksNever,
                ReadOnly=False,
                IgnoreReadOnlyRecommended=True
            )
            workbook.Save()
            workbook.Close(SaveChanges=True)
            return True
        except Exception:
            traceback.print_exc()
            return False
        finally:
            excel.Quit()
            pythoncom.CoUninitialize()

    try:
        import clr  # type: ignore
        clr.AddReference("Microsoft.Office.Interop.Excel")
        from Microsoft.Office.Interop import Excel  # type: ignore
        from System.Runtime.InteropServices import Marshal  # type: ignore
    except Exception:
        traceback.print_exc()
        return None

    excel = Excel.ApplicationClass()
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        time.sleep(0.25)
        workbook = excel.Workbooks.Open(filepath)
        workbook.Save()
        workbook.Close(True)
        return True
    except Exception:
        traceback.print_exc()
        return False
    finally:
        excel.Quit()
        Marshal.ReleaseComObject(excel)


@ERROR_HANDLE.try_catch_error()
def monitor_area(doc):
    """
    Main function to monitor areas and generate HTML report
    This function is designed to run in Revit environment
    """
    
    # Get CLEAN target data from the NYU HQ webapp API (Postgres is the system
    # of record). The hand-crafted Excel is a dirty drop only -- it is cleaned
    # by AI agents via the webapp MCP server or fine-tuned by humans in
    # targets.html.
    excel_data, color_hierarchy = get_target_data()

    # Update color schemes from the target color hierarchy
    update_all_color_schemes(doc, color_hierarchy)

    revit_data_by_scheme = get_revit_area_data_by_scheme()

    # Publish report + geometry to the webapp API (no HTML builder, no JSON
    # files: the NYU HQ repo owns all presentation and holds zero data).
    # Revit only syncs data.
    exporter = WebsiteDataExporter()
    sync_result, all_matches, all_unmatched = exporter.export_website_data(
        excel_data, revit_data_by_scheme, color_hierarchy)

    # Update Revit area parameters with suggestions
    param_stats = update_area_parameters(doc, all_matches, all_unmatched)

    # NOTE: the old "write DESIGN values back to Excel" step is retired.
    # Excel drops are dirty inputs, not the system of record -- writing Revit
    # actuals into them would corrupt the drop. Reality data lives in
    # Postgres behind the webapp API; planners who need a spreadsheet can
    # export from there.
    print("Reality data published to the NYU HQ webapp API.")

    # Open the published dashboard in the browser (the webapp owns presentation).
    webbrowser.open(config.NYU_HQ_WEBAPP_URL)
    
    excel_export_dir = _get_matrix_export_directory()
    matrix_exports = []
    matrix_failures = []

    if excel_export_dir:
        staging_dir = FOLDER.get_local_dump_folder_folder("MonitorAreaMatrix")
        FOLDER.secure_folder(staging_dir)
        for scheme_name, scheme_data in all_matches.items():
            matches = scheme_data.get('matches', [])
            scheme_areas = revit_data_by_scheme.get(scheme_name, [])
            matrix_data = department_matrix.build_matrix(matches, scheme_areas, color_hierarchy)
            staged_path = department_matrix.write_excel(matrix_data, scheme_name, staging_dir)
            if staged_path:
                wait_attempts = 0
                while not os.path.exists(staged_path) and wait_attempts < 50:
                    time.sleep(0.2)
                    wait_attempts += 1

                if not os.path.exists(staged_path):
                    print("WARNING: Staged matrix not created at {}".format(staged_path))
                    matrix_failures.append(scheme_name)
                    continue

                auto_resave = _force_excel_resave(staged_path)
                if auto_resave:
                    print("Excel auto-resaved: {}".format(staged_path))
                elif auto_resave is False:
                    print("WARNING: Excel auto-resave skipped or failed for {}".format(staged_path))

                final_filename = os.path.basename(staged_path)
                final_path = os.path.join(excel_export_dir, final_filename)
                if os.path.exists(staged_path):
                    try:
                        FOLDER.copy_file(staged_path, final_path)
                    except Exception:
                        print("WARNING: Failed to move staged matrix to {}".format(final_path))
                        final_path = staged_path
                else:
                    print("WARNING: Staged matrix missing at {}".format(staged_path))
                    final_path = staged_path
                matrix_exports.append(final_path)
                print("Department-level matrix exported: {}".format(final_path))
            else:
                matrix_failures.append(scheme_name)
    elif all_matches:
        matrix_failures = list(all_matches.keys())

    # Calculate total fulfilled across all schemes
    total_fulfilled = 0
    total_requirements = 0
    scheme_names = []
    for scheme_name, scheme_data in all_matches.items():
        matches = scheme_data.get('matches', [])
        total_requirements += len(matches)
        total_fulfilled += sum(1 for m in matches if m['status'] == 'Fulfilled')
        scheme_names.append(scheme_name)
    
    # Create notification message with parameter update stats
    param_summary = "\n\nParameter Updates:\n  Matched areas cleared: {}\n  Target DGSF set: {}\n  Unmatched areas updated: {}\n  Skipped: {}".format(
        param_stats['matched_cleared'],
        param_stats.get('target_dgsf_updated', 0),
        param_stats['unmatched_updated'],
        param_stats['matched_skipped'] + param_stats['unmatched_skipped']
    )
    
    if param_stats['errors']:
        param_summary += "\n  Errors: {}".format(len(param_stats['errors']))
    
    # Excel writeback retired: reality data lives in Postgres behind the webapp
    # API; the Excel drop is a dirty input, not the system of record.
    writeback_summary = ("\n\nWebapp Sync:\n  Published report + geometry to {}"
                         .format(config.NYU_HQ_API_URL))

    if excel_export_dir and matrix_exports:
        latest_path = matrix_exports[-1]
        matrix_summary = "\n\nLevel Matrix Export:\n  Saved {} file(s)\n  Latest: {}".format(len(matrix_exports), latest_path)
    elif excel_export_dir and matrix_failures:
        matrix_summary = "\n\nLevel Matrix Export:\n  WARNING: Failed to save for: {}".format(", ".join(matrix_failures))
    else:
        matrix_summary = "\n\nLevel Matrix Export:\n  Target folder unavailable. Skipped."
    
    # Create notification message
    schemes_text = ", ".join(scheme_names) if len(scheme_names) <= 3 else "{} schemes".format(len(scheme_names))
    msg = (
        "NYU HQ data published to the webapp!\n"
        "Dashboard: {dashboard}\n"
        "Schemes: {schemes}\n"
        "Fulfilled: {fulfilled}/{total}"
        "{param_summary}"
        "{writeback_summary}"
        "{matrix_summary}"
    ).format(
        dashboard=config.NYU_HQ_WEBAPP_URL,
        schemes=schemes_text,
        fulfilled=total_fulfilled,
        total=total_requirements,
        param_summary=param_summary,
        writeback_summary=writeback_summary,
        matrix_summary=matrix_summary
    )

    NOTIFICATION.messenger(main_text=msg)


    # Open NYU_HQ executable
    EXE.try_open_app("NYU_HQ")









################## main code below #####################
if __name__ == "__main__":
    monitor_area(DOC)







