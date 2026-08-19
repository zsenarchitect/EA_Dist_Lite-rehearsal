
"""
store session script data to a temp file
https://pyrevit.readthedocs.io/en/latest/pyrevit/coreutils/appdata.html


share parameter between script
https://pyrevit.readthedocs.io/en/latest/pyrevit/coreutils/envvars.html
"""

import io
from pyrevit import script
from pyrevit import EXEC_PARAMS
# from pyrevit.coreutils import appdata
from pyrevit.coreutils import envvars
import time
import json
# pyRevit hook engines do not inherit the .lib search path that button scripts get,
# so put KingDuck.lib on sys.path before importing proDUCKtion (the EnneadTab bootstrap).
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "KingDuck.lib")))
import proDUCKtion # pyright: ignore
proDUCKtion.validify()
from EnneadTab import ERROR_HANDLE, NOTIFICATION, DATA_FILE, USER
from EnneadTab.REVIT import REVIT_EVENT, REVIT_CATEGORY
envvars.set_pyrevit_env_var("FAMILY_LOAD_BEGIN", time.time())
datafile = script.get_instance_data_file("sub_c_list")

# print datafile


def has_required_lib(module, attr_name):
    """Guard against a TORN INSTALL: this hook file is newer than the lib it calls.

    An EnneadTab update copies file-by-file straight into the live EA_Dist folder.
    If it dies partway (Revit holding a file open, network blip), the machine is
    left with the NEW hooks and the OLD lib. The hook then calls a helper that does
    not exist yet and every single family load explodes with a raw

        AttributeError: 'module' object has no attribute 'get_subcategory_signatures'

    which is 94 of the last 100 EnneadTab-OS production ErrorDump events.

    This check is deliberately SELF-CONTAINED -- no new lib helper, no new lib
    import. On a torn install the LIB is the stale half, so anything we factored
    out into a fresh lib module would itself be the thing that is missing, and the
    guard would fail with ImportError instead of AttributeError: same crash, new
    spelling. Only long-standing, always-present APIs are safe to lean on here.

    Duplicated verbatim in the sibling hook family-loaded.py. That duplication is
    the feature, not an oversight: these two are the only callers, and the whole
    point is that neither may depend on a shared home a torn update can delete out
    from under it. Edit both or neither.

    Args:
        module: The lib module the hook depends on.
        attr_name (str): The helper the hook is about to call.

    Returns:
        bool: True when the lib is complete and the hook may proceed.
    """
    if hasattr(module, attr_name):
        return True

    message = "EnneadTab install is INCOMPLETE: {}.{} is missing (hook is newer than lib).".format(
        getattr(module, "__name__", "?"), attr_name)
    try:
        ERROR_HANDLE.print_note(message)
        NOTIFICATION.messenger(
            "Your EnneadTab install is incomplete or out of date.\n"
            "Please re-run the EnneadTab installer.", sticky=True)

        # Once per day per missing symbol. Without this gate a torn machine would
        # fire one ErrorDump event per family load -- the exact flood we are here
        # to stop -- just with a friendlier message.
        gate = DATA_FILE.get_data("integrity_report_gate") or {}
        gate_key = "stale_lib_{}".format(attr_name)
        if (time.time() - gate.get(gate_key, 0)) >= 86400.0:
            gate[gate_key] = time.time()
            DATA_FILE.set_data(gate, "integrity_report_gate")
            ERROR_HANDLE.send_error_to_error_dump(
                error_message=message,
                func_name="integrity_torn_install:hook_guard",
                user_name=USER.USER_NAME,
                is_silent=False)
    except Exception:
        # The guard must never become a second source of crashes on a broken install.
        pass
    return False


@ERROR_HANDLE.try_catch_error(is_silent=True)
def main():
    if not REVIT_EVENT.is_family_load_hook_enabled():
        return

    if not has_required_lib(REVIT_CATEGORY, "get_subcategory_signatures"):
        return

    doc = EXEC_PARAMS.event_args.Document

    # Shared snapshot helper (unicode-coerced signatures) -- kept in one place so
    # the pre (writer) and post (reader) hooks can never drift on the format.
    data = REVIT_CATEGORY.get_subcategory_signatures(doc)

    # json, not pickle: IronPython's protocol-0 pickle emits raw high bytes
    # for non-ASCII category names (0xC3...), corrupting text-mode files and
    # crashing the reader hook (family-loaded.py) with UnicodeDecodeError.
    # ensure_ascii keeps the payload pure ASCII so utf-8 text mode is safe.
    #
    # Serialize BEFORE opening the file: io.open('w') truncates the target the
    # instant it opens, so if json.dumps raised AFTER the open (the old non-ASCII
    # crash) the file was left at 0 bytes -- wiping a previously-good baseline and
    # making the reader dump the whole OST. Building the payload first keeps the
    # write-in-place safe: if dumps ever raises again, the old baseline survives.
    payload = unicode(json.dumps(data, ensure_ascii=True))
    with io.open(datafile, 'w', encoding="utf-8") as f:
        f.write(payload)
############### main ###################
if __name__ == "__main__":
    main()


