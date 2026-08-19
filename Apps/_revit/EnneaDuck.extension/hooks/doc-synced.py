import os
import random
import io
import imp
import time
from pyrevit import EXEC_PARAMS
from Autodesk.Revit import DB  # pyright: ignore
from pyrevit.coreutils import envvars

DOC = EXEC_PARAMS.event_args.Document

# pyRevit hook engines do not inherit the .lib search path that button scripts get,
# so put KingDuck.lib on sys.path before importing proDUCKtion (the EnneadTab bootstrap).
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "KingDuck.lib")))
import proDUCKtion  # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import (
    ERROR_HANDLE, FOLDER, SOUND, LOG, NOTIFICATION, SPEAK,
    MODULE_HELPER, ENVIRONMENT, USER,
    TIME, SYNC_TURN_EMAIL
)
from EnneadTab.REVIT import (
    REVIT_SYNC, REVIT_FORMS, REVIT_EVENT, 
    REVIT_SPATIAL_ELEMENT, REVIT_PROJ_DATA,
    REVIT_SELECTION
)

__title__ = "Doc Synced Hook"


# =============================================================================
# CONSTANTS
# =============================================================================

REGISTERED_AUTO_PROJS = [
    "1643_lhh bod-a_new",
    "1643_lhh_bod-a_existing",
    "2151_a_ea_nyuli_cup_ext",
    "2151_a_ea_nyuli_hospital_ext",
    "2151_A_EAEC_NYULI_Hospital_INT",
    "2151_a_ea_nyuli_parking east",
    "2151_a_ea_nyuli_parking west",
    "2151_a_ea_nyuli_site",
    "2151_A_EA_NYU Melville_Site",
    "2151_A_EA_NYU Melville_Hospital Existing",
    "2151_A_EA_NYU Melville_Hospital New",
    "2151_A_EA_NYU Melville_Garage North",
    "2151_A_EA_NYU Melville_Garage South",
    "2151_A_EA_NYU Melville_CUP",
    "2148_textile museum",
    "2419_Xiong An SinoChem",
    "Facade System"
]

REGISTERED_AUTO_PROJS = [x.lower() for x in REGISTERED_AUTO_PROJS]

SPARC_RELOAD_COOLDOWN_SECONDS = 60 * 60  # 1 hour
SPARC_RELOAD_MARKER_FILE = "sparc_exterior_reload_marker.txt"
SPARC_TARGET_LINK_NAME = "sparc_a_ea_exterior"


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def validate_document(doc, operation_name="operation"):
    """
    Centralized document validation function.
    
    Args:
        doc: Revit document to validate
        operation_name: Name of the operation for logging purposes
    
    Returns:
        bool: True if document is valid, False otherwise
    """
    if doc is None:
        print("Error: Cannot perform {} - document is None".format(operation_name))
        return False
    
    try:
        # Test document validity by accessing basic properties
        doc_title = doc.Title
        if not doc_title:
            print("Error: Cannot perform {} - document title is empty".format(operation_name))
            return False
        
        # Additional validation to ensure document methods are available
        if not hasattr(doc, "GetElement"):
            print("Error: Cannot perform {} - invalid document object".format(operation_name))
            return False
            
        return True
            
    except Exception as e:
        print("Error: Cannot perform {} - document validation failed: {}".format(operation_name, str(e)))
        return False


def warn_non_enclosed_area(doc):
    # Validate document before proceeding
    if doc is None:
        print("Warning: Cannot check areas - document is None")
        return
    
    try:
        areas = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).ToElements()
        non_closed, non_placed = REVIT_SPATIAL_ELEMENT.filter_bad_elements(areas)
        note = ""
        if len(non_closed) > 0:
            note += "There are {} non-enclosed areas in need of attention.\n".format(len(non_closed))
        if len(non_placed) > 0:
            note += "There are {} non-placed areas in need of attention.".format(len(non_placed))
        if note:
            NOTIFICATION.messenger(note)
    except Exception as e:
        print("Error checking non-enclosed areas: {}".format(str(e)))


def warn_non_enclosed_room(doc):
    # Validate document before proceeding
    if doc is None:
        print("Warning: Cannot check rooms - document is None")
        return
    
    try:
        rooms = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).ToElements()
        non_closed, non_placed = REVIT_SPATIAL_ELEMENT.filter_bad_elements(rooms)
        note = ""
        if len(non_closed) > 0:
            note += "There are {} non-enclosed rooms in need of attention.\n".format(len(non_closed))
        if len(non_placed) > 0:
            note += "There are {} non-placed rooms in need of attention.".format(len(non_placed))
        if note:
            NOTIFICATION.messenger(note)
    except Exception as e:
        print("Error checking non-enclosed rooms: {}".format(str(e)))


def warn_revit_session_too_long():
    uptime = TIME.get_revit_uptime(return_number=True)
    if uptime > 3 * 24 * 60 * 60:
        NOTIFICATION.messenger("Revit has been open for {}. Please consider restarting your computer.".format(TIME.get_revit_uptime()))
        return
    if uptime > 5 * 24 * 60 * 60:
        NOTIFICATION.messenger("Ahhhh! Revit has been open for {}. Please consider restarting your computer soon.".format(TIME.get_revit_uptime()))
        return
    if uptime > 10 * 24 * 60 * 60:
        NOTIFICATION.messenger("This is ridiculous! Revit has been open for {}. Please consider restarting your computer.".format(TIME.get_revit_uptime()))
        return
    if uptime > 15 * 24 * 60 * 60:
        NOTIFICATION.messenger("I am begging you! please restart your computer. Revit has been open for {}. ".format(TIME.get_revit_uptime()))
        return


def play_success_sound():
    file = 'sound_effect_mario_1up.wav'
    SOUND.play_sound(file)


def _get_sparc_reload_marker_path():
    return FOLDER.get_local_dump_folder_file(SPARC_RELOAD_MARKER_FILE)



def _has_recent_sparc_reload():
    marker_path = _get_sparc_reload_marker_path()
    if not marker_path or not os.path.exists(marker_path):
        return False
    try:
        with io.open(marker_path, "r", encoding="utf-8") as marker_file:
            content = marker_file.read().strip()
            if not content:
                return False
            last_timestamp = float(content)
    except Exception as e:
        print("Failed to read Sparc reload marker: {}".format(str(e)))
        return False
    
    elapsed = time.time() - last_timestamp
    return elapsed < SPARC_RELOAD_COOLDOWN_SECONDS


def _record_sparc_reload_timestamp():
    marker_path = _get_sparc_reload_marker_path()
    if not marker_path:
        return
    try:
        with io.open(marker_path, "w", encoding="utf-8") as marker_file:
            marker_file.write(str(time.time()))
    except Exception as e:
        print("Failed to write Sparc reload marker: {}".format(str(e)))


# =============================================================================
# PROJECT-SPECIFIC UPDATE FUNCTIONS
# =============================================================================

def update_project_1643(doc):
    update_new(doc)
    update_existing(doc)


def update_new(doc):
    if "1643_lhh bod-a_new" not in doc.Title.lower():
        return

    folder = "EnneadTab Tailor.tab\\Proj. Lenox Hill.panel\\Lenox Hill.pulldown"
    func_name = "update_level_relative_value"
    MODULE_HELPER.run_revit_script(folder, func_name, doc)

    folder = "EnneadTab Tailor.tab\\Proj. Lenox Hill.panel\\Lenox Hill.pulldown"
    func_name = "update_keyplan"
    MODULE_HELPER.run_revit_script(folder, func_name, doc)


def update_existing(doc):
    if "1643_lhh bod-a_existing" not in doc.Title.lower():
        return

    folder = "EnneadTab Tailor.tab\\Proj. Lenox Hill.panel\\Lenox Hill.pulldown"
    func_name = "update_grid_bldgId"
    MODULE_HELPER.run_revit_script(folder, func_name, doc)

    folder = "EnneadTab Tailor.tab\\Proj. Lenox Hill.panel\\Lenox Hill.pulldown"
    func_name = "update_level_relative_value"
    MODULE_HELPER.run_revit_script(folder, func_name, doc)

    folder = "EnneadTab Tailor.tab\\Proj. Lenox Hill.panel\\Lenox Hill.pulldown"
    func_name = "update_keyplan"
    MODULE_HELPER.run_revit_script(folder, func_name, doc)


def update_project_2314(doc):
    if "2314_a-455 1st ave" not in doc.Title.lower():
        return
    
    folder = "EnneadTab Tailor.tab\\Proj. 2314.panel\\First Ave.pulldown"
    func_name = "all_in_one_checker"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False)
    
    return


def update_project_2306(doc):
    if "universal hydrogen" not in doc.Title.lower():
        return
    # if not USER.IS_DEVELOPER:
    #     return

    folder = "EnneadTab Tailor.tab\\Proj. 2306.panel\\Universal Hydro.pulldown"
    func_name = "factory_internal_check"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False)


# =============================================================================
# LEGACY UPDATE FUNCTIONS
# =============================================================================

def LEGACY_update_project_2151(doc):
    if not doc.Title.lower().startswith("2151_"):
        return

    folder = "EnneadTab Tailor.tab\\Proj. 2151.panel\\LI_NYU.pulldown"
    func_name = "update_parking_data"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False, is_from_sync_hook=True)

    return
    
    if USER.USER_NAME not in ["sha.li", "szhang"]:
        return
    
    folder = "EnneadTab Tailor.tab\\Proj. 2151.panel\\LI_NYU.pulldown"
    func_name = "color_pills"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False)
    
    folder = "EnneadTab Tailor.tab\\Proj. 2151.panel\\LI_NYU.pulldown"
    func_name = "all_in_one_checker"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False)

    folder = "EnneadTab Tailor.tab\\Proj. 2151.panel\\LI_NYU.pulldown"
    func_name = "confirm_RGB"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False)


def LEGACY_update_DOB_numbering(doc):
    folder = "EnneadTab.tab\\ACE.panel"
    func_name = "update_DOB_page"
    MODULE_HELPER.run_revit_script(folder, func_name, doc, show_log=False)


def LEGACY_update_sheet_name(doc):
    try:
        doc.Title
    except Exception as e:
        if USER.USER_NAME == "szhang":
            print(str(e))
        return

    # Additional document validation
    if doc is None:
        print("Warning: Cannot update sheet names - document is None")
        return

    if doc.Title.lower() not in REGISTERED_AUTO_PROJS:
        return

    try:
        script = "EnneadTab.tab\\Tools.panel\\general_renamer.pushbutton\\general_renamer_script.py"
        func_name = "rename_views"
        sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).WhereElementIsNotElementType().ToElements()
        is_default_format = True
        show_log = False
        MODULE_HELPER.run_revit_script(script, func_name, doc, sheets, is_default_format, show_log)
    except Exception as e:
        print("Error updating sheet names: {}".format(str(e)))


def LEGACY_update_working_view_name(doc):
    try:
        doc.Title
    except:
        return

    # Additional document validation
    if doc is None:
        print("Warning: Cannot update working view names - document is None")
        return

    if doc.Title.lower() not in REGISTERED_AUTO_PROJS:
        return

    try:
        script = "EnneadTab.tab\\Manage.panel\\working_view_cleanup.pushbutton\\manage_working_view_script.py"
        func_name = "modify_creator_in_view_name"

        fullpath = "{}\\{}".format(ENVIRONMENT.REVIT_PRIMARY_EXTENSION, script)
        import imp
        ref_module = imp.load_source("manage_working_view_script", fullpath)

        views = DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType().ToElements()
        no_sheet_views = filter(ref_module.is_no_sheet, views)
        is_adding_creator = True
        MODULE_HELPER.run_revit_script(script, func_name, no_sheet_views, is_adding_creator)
    except Exception as e:
        print("Error updating working view names: {}".format(str(e)))


def run_legacy_updates(doc):
    """Run all the deprecated update functions - they're old but gold!"""
    if MODULE_HELPER is None:
        print("Warning: MODULE_HELPER not available, skipping legacy updates")
        return
    LEGACY_update_DOB_numbering(doc)
    LEGACY_update_sheet_name(doc)
    LEGACY_update_working_view_name(doc)
    LEGACY_update_project_2151(doc)


# =============================================================================
# MODERN UPDATE FUNCTIONS
# =============================================================================

def update_view_names(doc):
    """Update view names - because nobody likes unnamed views wandering around!"""
    # Validate document before proceeding
    if doc is None:
        print("Error: Cannot update view names - document is None")
        return
    
    try:
        # Test document validity by accessing a basic property
        doc_title = doc.Title
        if not doc_title:
            print("Error: Cannot update view names - document title is empty")
            return
    except Exception as e:
        print("Error: Cannot update view names - document validation failed: {}".format(str(e)))
        return
    
    try:
        # Update sheet views
        script = "EnneadTab.tab\\Tools.panel\\general_renamer.pushbutton\\general_renamer_script.py"
        sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).WhereElementIsNotElementType().ToElements()
        MODULE_HELPER.run_revit_script(script, "rename_views", doc, sheets, True, False)


        # Update working views
        script = "EnneadTab.tab\\Manage.panel\\working_view_cleanup.pushbutton\\manage_working_view_script.py"
        fullpath = "{}\\{}".format(ENVIRONMENT.REVIT_PRIMARY_EXTENSION, script)
        ref_module = imp.load_source("manage_working_view_script", fullpath)
        
        views = DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType().ToElements()
        no_sheet_views = filter(ref_module.is_no_sheet, views)
        MODULE_HELPER.run_revit_script(script, "modify_creator_in_view_name", no_sheet_views, True)


    except Exception as e:
        print("Error during view names update: {}".format(str(e)))
        ERROR_HANDLE.print_note("View names update failed: {}".format(str(e)))


def update_area_tracking(doc):
    """Update area tracking - keeping those square feet in check!"""
    # Validate document before proceeding
    if doc is None:
        print("Error: Cannot update area tracking - document is None")
        return
    
    try:
        # Test document validity by accessing a basic property
        doc_title = doc.Title
        if not doc_title:
            print("Error: Cannot update area tracking - document title is empty")
            return
    except Exception as e:
        print("Error: Cannot update area tracking - document validation failed: {}".format(str(e)))
        return
    
    try:
        fullpath = "{}\\EnneadTab.tab\\Tools.panel\\generic_healthcare_tool.pushbutton\\dgsf_chart.py".format(
            ENVIRONMENT.REVIT_PRIMARY_EXTENSION)
        ref_module = imp.load_source("dgsf_chart", fullpath)
        ref_module.dgsf_chart_update(doc, show_log=False)
    except:
        try:
            import traceback
            msg = traceback.format_exc()
        except:
            msg = "unknown error"
        print("Error during area tracking update: {}".format(msg))
        ERROR_HANDLE.print_note("Area tracking update failed: {}".format(msg))


# =============================================================================
# SYNC QUEUE MANAGEMENT
# =============================================================================

def _gather_sync_changes(doc):
    changes = []
    try:
        from pyrevit.coreutils import envvars
        import System
        
        # 1. Warning delta
        before_str = envvars.get_pyrevit_env_var("EA_SYNC_WARNINGS_BEFORE")
        if before_str is not None:
            before = int(before_str)
            from EnneadTab.SESSION_STATS import count_warnings
            after = count_warnings(doc)
            if after is not None:
                delta = after - before
                if delta < 0:
                    changes.append("Cleared {} warning{}".format(abs(delta), "" if abs(delta) == 1 else "s"))
                elif delta > 0:
                    changes.append("Added {} warning{}".format(delta, "" if delta == 1 else "s"))

        # 2. GetChangedElements (Revit 2023+)
        if hasattr(doc, "GetChangedElements"):
            guid_str = envvars.get_pyrevit_env_var("EA_SYNC_START_VERSION_GUID")
            if guid_str:
                guid = System.Guid(guid_str)
                diff = doc.GetChangedElements(guid)
                
                created = diff.GetCreatedElementIds()
                modified = diff.GetModifiedElementIds()
                deleted = diff.GetDeletedElementIds()
                
                c_count = len(created) if created else 0
                m_count = len(modified) if modified else 0
                d_count = len(deleted) if deleted else 0
                
                if c_count > 0:
                    changes.append("Created {} element{}".format(c_count, "" if c_count == 1 else "s"))
                if m_count > 0:
                    changes.append("Modified {} element{}".format(m_count, "" if m_count == 1 else "s"))
                if d_count > 0:
                    changes.append("Deleted {} element{}".format(d_count, "" if d_count == 1 else "s"))
                    
    except Exception as e:
        from EnneadTab import ERROR_HANDLE
        ERROR_HANDLE.print_note("Could not gather sync changes: {}".format(e))
        
    return changes

def update_sync_queue(doc):
    """Remove current user from sync queue after successful sync.

    The office L: drive is retired. enneadtab.com/sync is the only queue.
    If the API is unreachable, skip cleanup -- do not write a dead share.
    """
    if REVIT_EVENT.is_sync_cancelled():
        return

    try:
        from EnneadTab import SYNC_TURN_WATCH
        SYNC_TURN_WATCH.remove_watch(REVIT_SYNC.get_model_guid(doc))
    except Exception as err:
        ERROR_HANDLE.print_note("sync-turn watch remove failed: {}".format(err))

    api_result = None
    if hasattr(REVIT_SYNC, "api_complete_sync"):
        try:
            changes = _gather_sync_changes(doc)
            # Compatibility guard if api_complete_sync signature changes or doesn't support changes keyword
            import inspect
            sig = inspect.getargspec(REVIT_SYNC.api_complete_sync)
            if "changes" in sig.args:
                api_result = REVIT_SYNC.api_complete_sync(doc, changes=changes)
            else:
                api_result = REVIT_SYNC.api_complete_sync(doc)
        except Exception as e:
            ERROR_HANDLE.print_note("Sync queue API complete failed: {}".format(e))

    if api_result is None:
        ERROR_HANDLE.print_note(
            "Sync queue API unreachable for completion; L: fallback is retired, skipping.")
        try:
            ERROR_HANDLE.report_infra_warning_to_error_dump_async(
                "revit-sync /complete unreachable; file-based L: fallback is retired",
                "doc-synced.update_sync_queue",
                throttle_key="sync_queue_api_complete_unreachable")
        except Exception:
            pass
        return

    ERROR_HANDLE.print_note("Sync queue API: complete sync reported success={}".format(
        api_result.get("success")))
    _notify_next_user_from_api(doc, api_result)


def _usernames_from_api_queue(queue):
    names = []
    for entry in queue or []:
        name = (entry.get("username") or "").strip()
        if name:
            names.append(name)
    return names


def _send_turn_email(doc, next_user, remaining_after):
    """Notify the next waiter via the email gateway. No Outlook fallback."""
    next_user = (next_user or "").strip()
    if not next_user:
        ERROR_HANDLE.print_note("Sync queue notification skipped: empty next_user.")
        return

    model_guid = None
    try:
        model_guid = REVIT_SYNC.get_model_guid(doc)
    except Exception as err:
        ERROR_HANDLE.print_note("Could not resolve model guid for sync-turn mail: {}".format(err))

    result = SYNC_TURN_EMAIL.send(
        model_title=doc.Title,
        just_finished=USER.USER_NAME,
        next_user=next_user,
        remaining_after=remaining_after or [],
        model_guid=model_guid,
    )
    ERROR_HANDLE.print_note("Sync-turn email status={} reason={}".format(
        result.get("status"), result.get("reason")))


def _notify_next_user_from_api(doc, api_result):
    """Notify the next user in queue based on API response.

    Args:
        doc: Revit Document object
        api_result: Dict with "success", "queue" from API
    """
    if REVIT_EVENT.is_sync_queue_disabled():
        return

    queue = api_result.get("queue", [])
    if not queue:
        return

    # Defensively drop ourselves before picking the head. The /complete
    # endpoint is documented to remove the caller server-side, but a server
    # race / eventual-consistency window can still return a queue that still
    # contains us at index 0. Without this filter we would email ourselves
    # "your turn to sync" and show our own name in the popup.
    remaining = [entry for entry in queue
                 if entry.get("username", "") != USER.USER_NAME]
    if not remaining:
        return

    try:
        next_user = remaining[0].get("username", "")
        if not next_user:
            return
    except Exception:
        return

    after = _usernames_from_api_queue(remaining[1:])
    _send_turn_email(doc, next_user, after)

    REVIT_FORMS.notification(
        main_text="[{}]\nshould sync next.".format(next_user),
        sub_text="Queue managed by EnneadTab-DB.",
        window_width=500,
        window_height=400,
        self_destruct=15
    )


# =============================================================================
# MAIN DOCUMENT SYNC FUNCTION
# =============================================================================

@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error(is_silent=True)
def doc_synced(doc):
    # Comprehensive document validation at the start
    if doc is None:
        print("Error: doc_synced received None document, skipping sync operations")
        return
    
    try:
        # Test document validity by accessing basic properties
        doc_title = doc.Title
        if not doc_title:
            print("Error: doc_synced received document with empty title, skipping sync operations")
            return
        
        # Additional validation to ensure document methods are available
        if not hasattr(doc, "GetElement"):
            print("Error: doc_synced received invalid document object, skipping sync operations")
            return
            
    except Exception as e:
        print("Error: doc_synced document validation failed: {}, skipping sync operations".format(str(e)))
        return

    play_success_sound()
    # The wait is over -- pull the arcade flag before anything slower runs, so a pending
    # watcher (armed in doc-syncing) sees the resolution and stands down. Import is local
    # + guarded: this late-add must never break the sync-complete path.
    try:
        from EnneadTab import ARCADE
        ARCADE.end_wait_watch()
    except Exception:
        pass

    # End-of-wait bookkeeping for the session card: report what this sync earned
    # to the Bank (queued locally, posted at the next startup -- never a network
    # call here). Gated on is_sync_cancelled for the same reason update_sync_queue
    # is: this hook ALSO fires when the user chose to wait in the queue, and no
    # sync actually happened, so there is nothing to credit.
    if not REVIT_EVENT.is_sync_cancelled():
        try:
            from EnneadTab import SYNC_SUMMARY
            SYNC_SUMMARY.on_sync_finished(doc, doc_title)
        except Exception:
            pass

    REVIT_SYNC.update_last_sync_data_file(doc)

    update_sync_queue(doc)

    if random.random() < 0.1:
        warn_non_enclosed_area(doc)
    if random.random() < 0.1:
        warn_non_enclosed_room(doc)

    if REVIT_EVENT.is_all_sync_closing():
        return

    if not REVIT_PROJ_DATA.is_setup_project_data_para_exist(doc):
        run_legacy_updates(doc)
    else:
        proj_data = REVIT_PROJ_DATA.get_revit_project_data(doc)
        if proj_data:
            if proj_data.get("area_tracking", {}).get("auto_update_enabled", False):
                update_area_tracking(doc)
            if proj_data.get("is_update_view_name_format", False):
                update_view_names(doc)

    if USER.IS_DEVELOPER:
        SPEAK.speak("Document {} has finished syncing.".format(doc.Title))
        NOTIFICATION.messenger("Document {} has finished syncing.".format(doc.Title))

    warn_revit_session_too_long()
    reload_sparc_exterior(doc)

    return

    update_project_2314(doc)
    update_project_2306(doc)
    update_project_1643(doc)

    LEGACY_LOG.warn_revit_session_too_long(non_interuptive=False)

    if LEGACY_LOG.is_money_negative():
        print("Your Current balance is {}".format(LEGACY_LOG.get_current_money()))

    LEGACY_LOG.update_local_warning(doc)

    envvars.set_pyrevit_env_var("IS_DOC_CHANGE_HOOK_ENABLED", True)


# =============================================================================
# MAIN EXECUTION
# =============================================================================



def reload_sparc_exterior(doc):
    if doc.Title.lower() != "sparc_a_ea_cuny_building":
        return
    if _has_recent_sparc_reload():
        msg = "Skipping Sparc exterior reload - last successful reload occurred within the past hour."

        NOTIFICATION.messenger(msg)
        return

    all_revit_link_types = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType).ToElements()
    if not all_revit_link_types:

        return
    exterior_link_type = None
    
    for revit_link_type in all_revit_link_types:
        param = revit_link_type.LookupParameter("Type Name")
        link_name = param.AsString() if param else None
        normalized_name = (link_name or "").strip().lower()
        if normalized_name.endswith(".rvt"):
            normalized_name = normalized_name[:-4]
        if not normalized_name:
            continue
        if normalized_name == SPARC_TARGET_LINK_NAME:
            exterior_link_type = revit_link_type
            break
    if not exterior_link_type:
        print("Sparc reload skipped: could not find link type named 'sparc_a_ea_exterior'.")
        return
    
    # Check if element is read-only
    if getattr(exterior_link_type, "IsReadOnly", False):
        msg = "Cannot reload Sparc exterior link - element is read-only (document may be read-only or element is in a read-only state)."
        print(msg)
        NOTIFICATION.messenger(msg)
        return
    
    # Check if document is read-only by checking if it's a linked document
    # Linked documents are typically read-only
    if doc.IsLinked:
        msg = "Cannot reload Sparc exterior link - current document is a linked document (read-only)."
        print(msg)
        NOTIFICATION.messenger(msg)
        return
    
    if not REVIT_SELECTION.is_changable(exterior_link_type):
        owner = REVIT_SELECTION.get_owner(exterior_link_type)
        msg = "Cannot reload Sparc exterior link - element is owned by '{}'".format(owner or "Unknown")
        print(msg)
        NOTIFICATION.messenger(msg)
        return

    def _try_local_reload(link_type):
        try:
            # Check if element is read-only before attempting reload
            if getattr(link_type, "IsReadOnly", False):
                print("Local reload skipped: link type is read-only.")
                return False
            if hasattr(link_type, "LocallyUnloaded") and not link_type.LocallyUnloaded:
                link_type.UnloadLocally(None)
            if hasattr(link_type, "RevertLocalUnloadStatus"):
                link_type.RevertLocalUnloadStatus()
                print("Sparc exterior link local reload succeeded.")
                return True
        except Exception as local_error:
            error_msg = str(local_error)
            if "read-only" in error_msg.lower() or "readonly" in error_msg.lower():
                print("Local reload failed: The element is in a read-only document.")
            else:
                print("Local reload failed: {}".format(local_error))
        return False
    
    def _try_global_reload(link_type):
        try:
            # Check if element is read-only before attempting reload
            if getattr(link_type, "IsReadOnly", False):
                print("Global reload skipped: link type is read-only.")
                return False
            link_type.Reload()
            print("Sparc exterior link global reload succeeded.")
            return True
        except Exception as global_error:
            error_msg = str(global_error)
            if "read-only" in error_msg.lower() or "readonly" in error_msg.lower():
                print("Error reloading sparc exterior globally: The element is in a read-only document.")
            else:
                try:
                    import traceback
                    tb = traceback.format_exc()
                except Exception:
                    tb = None
                print("Error reloading sparc exterior globally: {}".format(global_error))
                if tb:
                    print(tb)
        return False
    
    reloaded = False
    if REVIT_SELECTION.is_changable(exterior_link_type):
        reloaded = _try_local_reload(exterior_link_type)
        if not reloaded:
            reloaded = _try_global_reload(exterior_link_type)
    else:
        reloaded = _try_global_reload(exterior_link_type)
    
    if reloaded:
        _record_sparc_reload_timestamp()
    else:
        print("Sparc exterior link reload failed after local and global attempts.")

    


if __name__ == "__main__":
    doc_synced(DOC)

