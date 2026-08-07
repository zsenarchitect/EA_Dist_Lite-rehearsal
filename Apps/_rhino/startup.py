__title__ = "EnneadTab_Startup"
__doc__ = """Get EnneadTab ready the moment a new Rhino session opens.

Runs by itself in the background, so every tool, command alias and shortcut is in place
before you start modeling and you never have to load anything by hand.

Features:
- Registers the EnneadTab command aliases you can type on the command line
- Checks whether a newer EnneadTab is available
- Wires up the background helpers the tools rely on"""
import os
import sys

_app_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lib_path = os.path.join(_app_folder, "lib" )
sys.path.append(_lib_path)

# Announce which source tree this session booted from. Helps developers verify
# dev-mode is active (RHINO_ALIAS._prefer_dev_path should have flipped the alias
# before this startup ran). End users see the same line with EA_Dist path.
print("[EnneadTab] Startup loaded from: {}".format(_app_folder))

# print ("\n".join(sys.path))
from EnneadTab import ERROR_HANDLE, NOTIFICATION, ENVIRONMENT
from EnneadTab import VERSION_CONTROL, USER, EXE, CONFIG, DOCUMENTATION, HOLIDAY
from EnneadTab.RHINO import RHINO_ALIAS


import rhinoscriptsyntax as rs
import Rhino # pyright: ignore
rs.AddSearchPath(_lib_path)

sys.path.append(ENVIRONMENT.RHINO_FOLDER + "\\{}.menu\\get_latest.button".format(ENVIRONMENT.PLUGIN_NAME))
import get_latest_left # pyright: ignore


@ERROR_HANDLE.try_catch_error(is_silent=True)
def main():


    get_latest_left.get_latest(is_silient = True)
    RHINO_ALIAS.register_alias_set()
    add_hook()
    auto_start_mcp_server()

    # InfraWatch fleet bootstrap. Mirrors plugin_startup.py call. Wrapped in
    # broad except -- Rhino startup must never fail because of telemetry setup.
    try:
        from EnneadTab import INFRAWATCH
        INFRAWATCH.register_if_needed()
    except:
        pass

    rs.Command("{}_Activate{}".format(ENVIRONMENT.PLUGIN_ABBR, ENVIRONMENT.PLUGIN_NAME))
    RHINO_ALIAS.register_shortcut("F12", "{}_SearchCommand".format(ENVIRONMENT.PLUGIN_ABBR))
    
    if NOTIFICATION is not None:
        NOTIFICATION.messenger(main_text = "Startup Script Completed")

    DOCUMENTATION.tip_of_day()

    # Weekly usage digest. Reads a handoff file the scheduled CPython producer
    # wrote; computes nothing here, so this cannot slow down startup. Mirrored
    # verbatim in Apps/_revit/EnneaDuck.extension/plugin_startup.py -- both
    # hosts call the same function, which is what keeps them from drifting.
    try:
        from EnneadTab import RECAP
        RECAP.show_pending_digest()
    except:
        pass

    # Save-time session card. Everything expensive it needs is prepared HERE,
    # where latency is free, so the save path itself stays a pure local read:
    #   - stamp the session clock
    #   - drain the Bank outbox and warm the wallet/leaderboard caches
    #   - pick the "not tried yet" tool (this one walks the knowledge database)
    # Mirrored in Apps/_revit/EnneaDuck.extension/plugin_startup.py -- both hosts
    # call the same functions, which is what keeps them from drifting. The one
    # Revit-only line there is the ViewActivated counter; Rhino samples its
    # active viewport on save instead (see event_func_session_card_start).
    try:
        from EnneadTab import SESSION_STATS, SYNC_SUMMARY, LEADER_BOARD
        SESSION_STATS.mark_session_start()
        LEADER_BOARD.refresh_async()
        SYNC_SUMMARY.refresh_recommendation()
    except:
        pass

    HOLIDAY.festival_greeting()



    
@ERROR_HANDLE.try_catch_error(is_silent=True, is_pass=True)
def add_hook(): 

        
    # then add hook for future file in this session
    Rhino.RhinoDoc.CloseDocument += event_func_timesheet
    Rhino.RhinoDoc.EndOpenDocumentInitialViewUpdate  += event_func_handle_auto_start_command
    Rhino.RhinoDoc.EndOpenDocumentInitialViewUpdate  += event_func_timesheet


    Rhino.RhinoDoc.BeginSaveDocument += event_func_update_dist_repo

    # The session card, mirroring the Revit doc-syncing / doc-synced pair. A save
    # is the Rhino equivalent of the sync wait: begin shows the card, end does the
    # Bank bookkeeping. Both call the same EnneadTab.SYNC_SUMMARY functions Revit
    # does, so the two hosts cannot drift.
    Rhino.RhinoDoc.BeginSaveDocument += event_func_session_card_start
    Rhino.RhinoDoc.EndSaveDocument += event_func_session_card_end

    # A big document open can freeze Rhino as long as a Revit open can. The arcade
    # was Revit-only until now purely because nobody wired the Rhino side; the
    # flag-file contract in EnneadTab/ARCADE.py is host-agnostic.
    Rhino.RhinoDoc.BeginOpenDocument += event_func_arcade_start
    Rhino.RhinoDoc.EndOpenDocumentInitialViewUpdate += event_func_arcade_end

    Rhino.RhinoApp.Closing += event_func_update_r8_rui


@ERROR_HANDLE.try_catch_error(is_silent=True, is_pass=True)
def auto_start_mcp_server():
    """Start the in-Rhino MCP/RPC bridge automatically on session open.

    The bridge (rhino_rpc_server) is an in-process System.Net.HttpListener that
    lets the desktop RhinoAssistant / an AI assistant read and edit THIS Rhino
    session. Until now it was only reachable by clicking the MCP Server button;
    this wires it into the startup path so it is up before the user asks for it.

    Parity with Revit: the Revit side (plugin_startup._auto_start_mcp_server)
    only RE-starts its bridge if it was running last session, because that bridge
    is an external CPython process that dies with Revit and has to be respawned.
    The Rhino bridge lives inside Rhino and also dies with it, so there is nothing
    to "restore" -- we start it fresh every session. To switch to the conditional,
    Revit-style behavior, gate the body of this function on a persisted flag
    (e.g. CONFIG.get_setting) that the MCP Server button writes on start/stop.

    Non-blocking: the bind runs on a background thread so a slow or blocked
    HttpListener.Start() can never freeze Rhino startup. Idempotent: start_server()
    returns early when already running and binds the FIRST FREE port in its window
    (48900..48915), so re-entry and a 2nd/3rd Rhino are both harmless.
    """
    import scriptcontext as sc  # pyright: ignore
    from System.Threading import Thread, ThreadStart  # pyright: ignore

    # rhino_rpc_server lives next to its button; put that dir on sys.path so the
    # module resolves to the SAME object the button imports (shared via
    # sys.modules), which is what lets a later button click stop this server.
    button_dir = ENVIRONMENT.RHINO_FOLDER + "\\{}.menu\\mcp_server.button".format(ENVIRONMENT.PLUGIN_NAME)
    if button_dir not in sys.path:
        sys.path.append(button_dir)

    import rhino_rpc_server  # pyright: ignore

    def _start():
        rhino_rpc_server.start_server()

    thread = Thread(ThreadStart(_start))
    thread.IsBackground = True
    thread.Start()

    # Keep the MCP Server toggle button in sync. The button decides start-vs-stop
    # from sc.sticky["mcp_rpc_running"]; set it here on the UI thread so the first
    # click after autostart correctly STOPS the bridge instead of no-opping.
    # Optimistic: start_server() runs async, but its own re-entry guard makes a
    # rare bind failure harmless (a later click just calls stop_server(), a no-op).
    sc.sticky["mcp_rpc_running"] = True


###################################################
def action_update_timesheet(doc):
    if doc.Path:
        try:
            from EnneadTab import TIMESHEET
            TIMESHEET.update_timesheet(doc.Path)
        except:
            print ("Error updating timesheet")
            if USER.IS_DEVELOPER:
                print (ERROR_HANDLE.get_alternative_traceback())


##################################################

def event_func_handle_auto_start_command(sender, e):
    file_name = e.FileName
    if not file_name:        
        return


    if "{}_Revit2Rhino".format(ENVIRONMENT.PLUGIN_ABBR) in rs.DocumentName():
        rs.Command("!Zoom Extents")
        rs.Command("!- _Select None")


        
def event_func_timesheet(sender, e):
    action_update_timesheet(e.Document)

def event_func_update_dist_repo(sender, e):
    if CONFIG.get_setting("is_update_dist_repo_enabled", True):
        VERSION_CONTROL.update_dist_repo()

def event_func_update_r8_rui():
    EXE.try_open_app("Rhino8RuiUpdater", safe_open=True)


@ERROR_HANDLE.try_catch_error(is_pass=True)
def event_func_session_card_start(sender, e):
    """Show the session card as a save begins. Rhino half of doc-syncing.

    The active viewport is sampled here rather than tracked continuously: Rhino
    has no cheap ViewActivated equivalent worth hooking for this, and sampling on
    save still answers "which views did you work in" across a session.
    """
    from EnneadTab import SESSION_STATS, SYNC_SUMMARY
    try:
        SESSION_STATS.note_view(sender.Views.ActiveView.ActiveViewport.Name)
    except Exception:
        pass
    doc_name = None
    try:
        doc_name = e.FileName
    except Exception:
        pass
    SYNC_SUMMARY.show_session_card(doc_name)


@ERROR_HANDLE.try_catch_error(is_pass=True)
def event_func_session_card_end(sender, e):
    """End-of-save bookkeeping. Rhino half of doc-synced.

    No document is passed: warning counts are a Revit concept, and
    on_sync_finished skips that metric when doc is None rather than inventing a
    Rhino analogue that would mean something different.
    """
    from EnneadTab import SYNC_SUMMARY
    doc_name = None
    try:
        doc_name = e.FileName
    except Exception:
        pass
    SYNC_SUMMARY.on_sync_finished(None, doc_name)


@ERROR_HANDLE.try_catch_error(is_pass=True)
def event_func_arcade_start(sender, e):
    from EnneadTab import ARCADE
    doc_name = None
    try:
        doc_name = e.FileName
    except Exception:
        pass
    ARCADE.start_wait_watch("open", doc_name)


@ERROR_HANDLE.try_catch_error(is_pass=True)
def event_func_arcade_end(sender, e):
    from EnneadTab import ARCADE
    ARCADE.end_wait_watch()


if __name__ == "__main__":
    main()