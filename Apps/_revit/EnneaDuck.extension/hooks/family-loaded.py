"""
store session script data to a temp file
https://pyrevit.readthedocs.io/en/latest/pyrevit/coreutils/appdata.html


share parameter between script
https://pyrevit.readthedocs.io/en/latest/pyrevit/coreutils/envvars.html
"""
from pyrevit import script
from pyrevit import EXEC_PARAMS
import io

import json
import time
from pyrevit.coreutils import envvars
try:
    unicode
except NameError:
    unicode = str
# pyRevit hook engines do not inherit the .lib search path that button scripts get,
# so put KingDuck.lib on sys.path before importing proDUCKtion (the EnneadTab bootstrap).
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "KingDuck.lib")))
import proDUCKtion # pyright: ignore 
proDUCKtion.validify()
from Autodesk.Revit import DB # pyright: ignore
from EnneadTab import ERROR_HANDLE, SOUND, NOTIFICATION, TIME, OUTPUT, DATA_CONVERSION, DATA_FILE, USER
from EnneadTab.REVIT import REVIT_FORMS, REVIT_EVENT, REVIT_CATEGORY


def _cleanup_datafile(datafile):
    """Safely remove the baseline temp file so it cannot leak to subsequent loads."""
    try:
        if datafile and os.path.exists(datafile):
            os.remove(datafile)
    except Exception:
        pass


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

    Duplicated verbatim in the sibling hook family-loading.py. That duplication is
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
            "Please re-run the EnneadTab installer.")

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

    event_args = EXEC_PARAMS.event_args
    doc = getattr(event_args, "Document", None)
    if not doc or not doc.IsValidObject:
        return

    if doc.IsFamilyDocument:
        return

    datafile = script.get_instance_data_file("sub_c_list")

    # If the family load was cancelled or failed, discard the baseline and return early
    if hasattr(event_args, "Status"):
        try:
            if hasattr(DB, "Events") and hasattr(DB.Events, "RevitAPIEventStatus"):
                if event_args.Status != DB.Events.RevitAPIEventStatus.Succeeded:
                    _cleanup_datafile(datafile)
                    return
        except Exception:
            pass

    SOUND.play_sound("sound_effect_mario_coin.wav")

    start_time = envvars.get_pyrevit_env_var("FAMILY_LOAD_BEGIN")
    if start_time:
        time_pass = time.time() - start_time
        NOTIFICATION.messenger("Family load finished!!\n<{}> Uses {}".format(
            event_args.FamilyName, TIME.get_readable_time(time_pass)))

    # Read and immediately consume / remove the baseline file so it can NEVER leak to a subsequent load
    baseline_data = None
    try:
        if os.path.exists(datafile):
            with io.open(datafile, 'r', encoding="utf-8") as f:
                baseline_data = json.load(f)
    except Exception:
        baseline_data = None
    finally:
        _cleanup_datafile(datafile)

    if not baseline_data:
        # No usable before-snapshot from the pre-load hook (missing / empty /
        # corrupt file, or the pre-hook failed to write one). Without a baseline
        # we CANNOT compute which subcategories are new -- skip diff instead of dumping whole OST.
        NOTIFICATION.messenger("Subcategory diff unavailable for <{}>: no baseline snapshot from the pre-load hook. Reload pyRevit if this repeats.".format(event_args.FamilyName))
        ERROR_HANDLE.print_note("family-loaded hook: empty/missing baseline for {}; skipped whole-OST dump.".format(event_args.FamilyName))
        return

    # Parse baseline with document & family identity validation
    old_sub_c_list = None
    if isinstance(baseline_data, dict):
        base_doc_title = baseline_data.get("doc_title")
        base_doc_hash = baseline_data.get("doc_hash")
        base_family_name = baseline_data.get("family_name")
        base_timestamp = baseline_data.get("timestamp", 0)

        # Document title check
        if base_doc_title and base_doc_title != doc.Title:
            ERROR_HANDLE.print_note(
                "family-loaded hook: baseline document mismatch ('{}' vs '{}'); skipped diff.".format(
                    base_doc_title, doc.Title))
            return

        # Document hash check
        if base_doc_hash is not None:
            try:
                if int(base_doc_hash) != doc.GetHashCode():
                    ERROR_HANDLE.print_note(
                        "family-loaded hook: baseline document hash mismatch; skipped diff.")
                    return
            except (ValueError, TypeError):
                pass

        # Family name check (only if both non-empty)
        curr_family_name = getattr(event_args, "FamilyName", "")
        if base_family_name and curr_family_name and base_family_name != curr_family_name:
            ERROR_HANDLE.print_note(
                "family-loaded hook: baseline family mismatch ('{}' vs '{}'); skipped diff.".format(
                    base_family_name, curr_family_name))
            return

        # Expiration check: baseline must not be older than 120 seconds
        if base_timestamp and (time.time() - base_timestamp) > 120.0:
            ERROR_HANDLE.print_note(
                "family-loaded hook: baseline snapshot expired ({:.1f}s old); skipped diff.".format(
                    time.time() - base_timestamp))
            return

        old_sub_c_list = baseline_data.get("signatures")
    elif isinstance(baseline_data, list):
        # Legacy list fallback
        old_sub_c_list = baseline_data

    if not old_sub_c_list:
        NOTIFICATION.messenger(
            "Subcategory diff unavailable for <{}>: empty baseline snapshot from the pre-load hook.".format(
                event_args.FamilyName))
        ERROR_HANDLE.print_note(
            "family-loaded hook: empty baseline signatures for {}; skipped diff.".format(
                event_args.FamilyName))
        return

    current_sub_c_list = REVIT_CATEGORY.get_subcategory_signatures(doc)

    # Directional diff: only subcategories present NOW but not before are "new".
    # (The old symmetric difference also reported REMOVED subcategories as
    # "brought to the project", which is wrong.) compare_list returns
    # (only_in_A, only_in_B, shared); only_in_A == current - old == the new ones.
    new_sub_c_list, _removed, _shared = DATA_CONVERSION.compare_list(current_sub_c_list, old_sub_c_list)

    if len(new_sub_c_list) == 0:
        return

    # Plausibility / sanity guard:
    # A single family load introduces at most a handful of subcategories under a few parent categories.
    # An OST dump / invalid baseline shows dozens of parent categories and huge lists.
    root_categories = set()
    for sig in new_sub_c_list:
        if sig.startswith(u"[") and u"]--->[" in sig:
            root_categories.add(sig[1:sig.index(u"]--->[")])

    if len(root_categories) > 5 or len(new_sub_c_list) > 30:
        ERROR_HANDLE.print_note(
            "family-loaded hook: suspicious diff ({} subcategories across {} root categories) for <{}>; suppressed whole-OST dump.".format(
                len(new_sub_c_list), len(root_categories), event_args.FamilyName))
        NOTIFICATION.messenger(
            "Subcategory check: <{}> loaded, but diff was unusually large ({} items across {} categories). Output suppressed to prevent OST dump.".format(
                event_args.FamilyName, len(new_sub_c_list), len(root_categories)))
        return

    output = OUTPUT.get_output()
 
    output.insert_divider()
    output.write("The following new subCategory(s) are brought to the project [{}] while loading the family [{}]".format(doc.Title, event_args.FamilyName), OUTPUT.Style.Subtitle)
    output.write("<{}>".format(event_args.FamilyName), OUTPUT.Style.Title)
    output.write(new_sub_c_list)
    
    
    sub_display_text = "\n".join([
        "It happens when new sub-category is created intentionally, but also when you load a family:",
        "",
        "--from other project;",
        "--from manufacture website;",
        "--with a typo to an existing sub-category name.",
        "",
        "If this is unintensional, please take notes and use Ideate 'StyleManager' tool to manage object style later."
        ])
    output.write(sub_display_text, OUTPUT.Style.Footnote)

    output.plot()
    return
    REVIT_FORMS.notification(main_text = display_text,
                            sub_text = sub_display_text,
                            self_destruct = 5,
                            window_width = 650)

#############  main    ###########
if __name__ == "__main__":

    main()
