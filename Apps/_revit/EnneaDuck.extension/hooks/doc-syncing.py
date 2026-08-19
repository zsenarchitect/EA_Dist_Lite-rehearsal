from pyrevit import EXEC_PARAMS
from Autodesk.Revit import DB # pyright: ignore
import os

# pyRevit hook engines do not inherit the .lib search path that button scripts get,
# so put KingDuck.lib on sys.path before importing proDUCKtion (the EnneadTab bootstrap).
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "KingDuck.lib")))
import proDUCKtion # pyright: ignore 
proDUCKtion.validify()
from EnneadTab import VERSION_CONTROL, ERROR_HANDLE, LOG, USER, DUCK, CONFIG, TIMESHEET, ARCADE, SYNC_SUMMARY, LEADER_BOARD
from EnneadTab.REVIT import REVIT_FORMS, REVIT_SELECTION, REVIT_EVENT, REVIT_SYNC

__title__ = "Doc Syncing Hook"
DOC = EXEC_PARAMS.event_args.Document

# Sync queue configuration
SYNC_QUEUE_IGNORE_LIST = [
    "SPARC_A_EA_CUNY_Building",
]

QUEUE_DIALOG_FOOTER = "\n\nWhen There are no other people on the list, or you are the first on the wait list you can sync normally.\nRecord older than 30mins will be removed from the queue to avoid holding line too long."

# Reminder shown next to the "open dashboard" verification checkbox. Kept ASCII
# only (IronPython 2.7 runtime hazard on non-ASCII).
DASHBOARD_SSO_REMINDER = "\n\nTip: check the box below to open the live sync queue dashboard in your browser.\nThe dashboard lives at enneadtab.com and needs Microsoft sign-in (SSO). If your browser is not already signed in you will be asked to log in first -- the queue keeps working either way."


def _open_sync_dashboard(doc):
    """Open the live sync queue dashboard in the default browser.

    The URL is always built locally from the known-good template plus the model
    guid. The server-provided dashboard_url is intentionally NOT used as the
    open target: os.startfile() will "run" whatever string it is handed (a
    file:// path, a UNC path like \\\\host\\share\\x.exe, a local .bat), so a
    crafted or compromised API response must never be able to route it. The
    model guid is alphanumeric/underscore/dash only (see REVIT_SYNC.get_model_guid),
    so it cannot inject a scheme or path. Best-effort: any failure is logged and
    swallowed so it never blocks the sync-queue flow.

    Args:
        doc: Revit Document object
    """
    try:
        url = "https://enneadtab.com/sync/queue/{}".format(REVIT_SYNC.get_model_guid(doc))
    except Exception as e:
        ERROR_HANDLE.print_note("Could not build sync dashboard URL: {}".format(str(e)))
        return
    try:
        os.startfile(url)
    except Exception as e:
        ERROR_HANDLE.print_note("Could not open sync dashboard '{}': {}".format(url, str(e)))


def _watch_sync_turn(doc, dashboard_url=None):
    try:
        from EnneadTab import SYNC_TURN_WATCH, USER
        from EnneadTab.REVIT import REVIT_SYNC
        guid = REVIT_SYNC.get_model_guid(doc)
        SYNC_TURN_WATCH.add_watch(
            guid, doc.Title, USER.USER_NAME, dashboard_url)
    except Exception as err:
        ERROR_HANDLE.print_note("sync-turn watch add failed: {}".format(err))


# Helper functions for sync queue management

def _is_project_ignored(doc_title, ignore_list):
    """Check if project should bypass sync queue checking.
    
    Args:
        doc_title: Document title to check
        ignore_list: List of project names/patterns to ignore
        
    Returns:
        bool: True if project should bypass queue, False otherwise
    """
    if not doc_title:
        return False
        
    doc_title_lower = doc_title.lower()
    for ignored_project in ignore_list:
        if ignored_project.lower() in doc_title_lower:
            ERROR_HANDLE.print_note("Project '{}' is in sync queue ignore list, bypassing queue check.".format(doc_title))
            return True
    return False


def check_sync_queue(doc):
    """Check if document sync should proceed based on queue status.

    The office L: drive is retired. enneadtab.com/sync is the only queue.
    If the API is unreachable, allow the sync rather than writing a dead share.

    Args:
        doc: Revit Document object to check sync status for

    Returns:
        bool: True if sync can proceed, False if cancelled
    """
    if not doc:
        ERROR_HANDLE.print_note("Error: check_sync_queue received None document")
        return True

    if _is_project_ignored(doc.Title, SYNC_QUEUE_IGNORE_LIST):
        return True

    if REVIT_EVENT.is_sync_queue_disabled():
        return True

    user_name = USER.USER_NAME

    api_result = None
    try:
        api_result = REVIT_SYNC.api_request_sync(doc)
    except Exception as e:
        ERROR_HANDLE.print_note("Sync queue API request failed: {}".format(e))

    if api_result is not None:
        ERROR_HANDLE.print_note("Sync queue API responded: allowed={}".format(api_result.get("allowed")))
        return _check_sync_queue_api_based(doc, user_name, api_result)

    ERROR_HANDLE.print_note(
        "Sync queue API unreachable; L: fallback is retired. Allowing sync.")
    try:
        ERROR_HANDLE.report_infra_warning_to_error_dump_async(
            "revit-sync /request unreachable; file-based L: fallback is retired",
            "doc-syncing.check_sync_queue",
            throttle_key="sync_queue_api_request_unreachable")
    except Exception:
        pass
    return True


def _check_sync_queue_api_based(doc, user_name, api_result):
    """Handle sync queue decision using EnneadTab-DB API response.

    Args:
        doc: Revit Document object
        user_name: Current username
        api_result: Dict with "allowed", "queue", "dashboard_url"

    Returns:
        bool: True if sync can proceed, False if cancelled
    """
    if api_result.get("allowed", True):
        return True

    queue = api_result.get("queue", [])

    queue_lines = []
    for entry in queue:
        queue_lines.append("\n  - {}".format(entry.get("username", "unknown")))
    current_queue = "Current Sync Queue:" + "".join(queue_lines)
    current_queue += QUEUE_DIALOG_FOOTER + DASHBOARD_SSO_REMINDER

    opts = [
        ["I will join the waitlist and sync later.(Click 'Close' when you see Revit Sync Fail on next step, it just means the sync has been cancelled. You still hold position on the waitlist.)", "Resume working and try syncing later. (Earns EA Coins)"],
        ["I don't care! Sync me now!", "Jump in line will make other people who are syncing has to wait longer. (Costs EA Coins)"]
    ]
    dialog_result = REVIT_FORMS.dialogue(
        main_text="There are other people queuing before you, do you want to resume working and try sync later?\n\nYour name has been added to the wait list even if you cancel current sync.\n\n[You are also welcomed to save local while waiting.]",
        sub_text=current_queue,
        options=opts,
        verification_check_box_text="Open the live sync queue dashboard in my browser (needs enneadtab.com sign-in)"
    )
    # dialogue() returns (result, checkbox_state) when a checkbox is shown;
    # tolerate a bare result too in case the checkbox status is unavailable.
    if isinstance(dialog_result, tuple):
        res, open_dashboard = dialog_result[0], bool(dialog_result[1])
    else:
        res, open_dashboard = dialog_result, False

    if res == opts[1][0]:
        # Queued locally and posted at the next startup -- the Bank's rules engine
        # decides what cutting costs. We report the behaviour, never an amount.
        LEADER_BOARD.report_sync_queue_cut(doc.Title)
        REVIT_SYNC.api_prioritize_sync(doc)
        return True

    # Joining the waitlist (any choice other than cut-in-line, including closing
    # the dialog -- the name is already on the list). Honor the opt-in checkbox
    # to open the dashboard so the user can watch the queue while they wait.
    LEADER_BOARD.report_sync_queue_waited(doc.Title)
    _watch_sync_turn(doc, api_result.get("dashboard_url"))
    if open_dashboard:
        _open_sync_dashboard(doc)

    # Arm doc-synced's guard BEFORE cancelling: the doc-synced hook still fires
    # after this cancel, and without this flag its update_sync_queue() would drop
    # us from the queue (losing our waitlisted spot) and pop "[person ahead]
    # should sync next" -- the very thing the user chose to wait to avoid.
    REVIT_EVENT.set_sync_cancelled(True)
    EXEC_PARAMS.event_args.Cancel()
    if CONFIG.get_setting("toggle_bt_is_duck_allowed", False):
        DUCK.quack()
    try:
        doc.Save()
    except Exception as e:
        ERROR_HANDLE.print_note("Warning: Could not save local copy: {}".format(str(e)))
    return False


@ERROR_HANDLE.try_catch_error(is_pass=True)
def fill_drafter_info(doc):
    all_sheets = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).ToElements()
    free_sheets = REVIT_SELECTION.filter_elements_changable(all_sheets)
    
    t = DB.Transaction(doc, "Fill Drafter Info")
    t.Start()
    is_sparc_project = False
    if doc and doc.Title:
        is_sparc_project = doc.Title.strip().lower() == "sparc_a_ea_cuny_building"
    for sheet in free_sheets:
        tooltip_info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, sheet.Id)
        sheet.LookupParameter("Drawn By").Set(tooltip_info.Creator)
        designed_by_value = tooltip_info.LastChangedBy
        if is_sparc_project:
            designed_by_value = "Ennead Architects"
        sheet.LookupParameter("Designed By").Set(designed_by_value)
    t.Commit()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error(is_silent=True)
def doc_syncing(doc):
    VERSION_CONTROL.update_dist_repo()

    # A new sync cycle is starting -- clear any stale "cancelled" flag left by a
    # previous wait-in-line cancel, so a genuine completion this time is not
    # mistaken for a cancel by doc-synced's is_sync_cancelled() guard.
    REVIT_EVENT.set_sync_cancelled(False)

    can_sync = check_sync_queue(doc)
    if can_sync:
        # LEGACY_LOG.update_account_by_local_warning_diff(doc)
        pass

    if REVIT_EVENT.is_all_sync_closing():
        return

    # do this after checking queue so the primary EXE_PARAM is same as before
    fill_drafter_info(doc)

    TIMESHEET.update_timesheet(doc.Title)

    # OS: Snapshot in doc-syncing for model change log
    try:
        from pyrevit.coreutils import envvars
        from EnneadTab.SESSION_STATS import count_warnings
        # Snapshot warning count
        warn_count = count_warnings(doc)
        if warn_count is not None:
            envvars.set_pyrevit_env_var("EA_SYNC_WARNINGS_BEFORE", str(warn_count))
        # Snapshot document version (Revit 2023+)
        if hasattr(DB.Document, "GetDocumentVersion"):
            version_guid = DB.Document.GetDocumentVersion(doc).VersionGUID
            envvars.set_pyrevit_env_var("EA_SYNC_START_VERSION_GUID", str(version_guid))
    except Exception as e:
        ERROR_HANDLE.print_note("Could not take sync snapshot: {}".format(e))

    # Everything below runs microseconds before the UI thread freezes, so it must stay
    # local-only: no network, no element collection, no filesystem walk.

    # The session card. Renders out of process (NotificationHost), so the freeze does not
    # affect it, and its lifetime is pinned to the arcade threshold below so the two
    # surfaces hand over rather than stack. See EnneadTab/SYNC_SUMMARY.py.
    SYNC_SUMMARY.show_session_card(doc.Title, doc)

    # Sync is about to freeze the UI thread. Arm the arcade wait-watcher LAST, so its 60s
    # clock measures the sync itself, not the queue/dialog steps above. If the sync ends in
    # time, doc-synced deletes the flag and nothing happens. See EnneadTab/ARCADE.py for the
    # full flag-file contract (installed-app-only, per-user opt-out, age-checked).
    ARCADE.start_wait_watch("sync", doc.Title)


    

#################################################################

if __name__ == "__main__":
    doc_syncing(DOC)