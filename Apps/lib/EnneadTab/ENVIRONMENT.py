#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Environment configuration and detection module for EnneadTab.

This module handles environment setup, path configurations, and runtime environment detection
for the EnneadTab ecosystem. It supports multiple applications including Revit, Rhino,
and terminal environments.

Key Features:
- Path configuration for development and production environments
- Application environment detection (Revit, Rhino, Grasshopper)
- System environment checks (AVD, Python version)
- Filesystem management for temp and dump folders
- Network drive availability monitoring

Note:
    Network drive connectivity is managed through GitHub distribution rather than 
    direct network mapping to optimize IT infrastructure costs.



Unfortunately IT department cannot make L drive and other drive to be connnected by default ever since the Azure dirve migration.
There are money to be saved to disconnect the drive, so we need to use github to push update to all users.

Dont tell me it is a security risk, it is NOT.



"""

import os
import sys
from datetime import datetime
import json
import getpass

current_user_name = getpass.getuser()


PLUGIN_NAME = "EnneadTab"
PLUGIN_ABBR = "EA"
PLUGIN_EXTENSION = ".sexyDuck"

IS_PY3 = sys.version.startswith("3")
IS_PY2 = not IS_PY3
IS_IRONPYTHON = sys.platform == "cli"


# this is the repo folder if you are a developer, or EA_dist if you are a normal user
ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

USER_PROFILE_FOLDER = os.environ["USERPROFILE"]
USER_DOCUMENT_FOLDER = os.path.join(USER_PROFILE_FOLDER, "Documents")
USER_DOWNLOAD_FOLDER = os.path.join(USER_PROFILE_FOLDER, "downloads")

USER_DESKTOP_FOLDER = os.path.join(USER_PROFILE_FOLDER, "Desktop")


def _find_onedrive_folders():
    """Every '<profile>/OneDrive*' sibling, tenant-agnostic (Ennead, CannonDesign,
    or any future tenant). OneDrive Known-Folder-Move creates one of these and can
    redirect Desktop/Documents into it. We intentionally do NOT resolve the shell
    known folder anywhere in EnneadTab: the ecosystem always uses the literal
    USER_PROFILE_FOLDER paths so it stays OUT of OneDrive (see ECO_SYS_FOLDER)."""
    result = []
    try:
        for _name in os.listdir(USER_PROFILE_FOLDER):
            if _name.lower().startswith("onedrive"):
                _full = os.path.join(USER_PROFILE_FOLDER, _name)
                if os.path.isdir(_full):
                    result.append(_full)
    except Exception:
        pass
    return result


# Prefer a real OneDrive Desktop if one exists (any tenant); else the literal Desktop.
ONE_DRIVE_DESKTOP_FOLDER = USER_DESKTOP_FOLDER
for _od_folder in _find_onedrive_folders():
    _od_desktop = os.path.join(_od_folder, "Desktop")
    if os.path.exists(_od_desktop):
        ONE_DRIVE_DESKTOP_FOLDER = _od_desktop
        break
USER_APPDATA_FOLDER = os.path.join(USER_PROFILE_FOLDER, "AppData")
ECO_SYS_FOLDER = os.path.join(USER_DOCUMENT_FOLDER, 
                            "{} Ecosystem".format(PLUGIN_NAME))
DUMP_FOLDER = os.path.join(ECO_SYS_FOLDER, "Dump")
INSTALLATION_FOLDER = os.path.join(ROOT, "Installation")

def _secure_folder(folder):
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception as e:
            print("Cannot secure folder [{}] becasue {}".format(folder, e))

def _secure_folder_safe(folder):
    """Safely create folder with better error handling for network drives.

    A missing shared-network folder is NOT reported here on purpose: a stray
    print at import time is noise, not a signal, and it fires on every single
    button press. The real alarm for "the shared root vanished" is
    announce_shared_root_status() below, which is rate-limited and reaches
    ErrorDump.
    """
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception as e:
            # Don't print error for network locations that might not be available
            if not _is_under_shared_root(folder):
                print("Cannot secure folder [{}] becasue {}".format(folder, e))

def _execute_map_compatible(func, iterable, *args):
    """Execute a function on each item in an iterable, compatible with both IronPython 2.7 and Python 3.
    
    Args:
        func: Function to execute
        iterable: Iterable of items to process
        *args: Additional arguments to pass to func
    
    Returns:
        List of results (for compatibility)
    """
    results = []
    for item in iterable:
        if args:
            result = func(item, *args)
        else:
            result = func(item)
        results.append(result)
    return results

# Fix: Use compatible approach for both IronPython 2.7 and Python 3
_execute_map_compatible(_secure_folder, [ECO_SYS_FOLDER, DUMP_FOLDER])




APP_FOLDER = os.path.join(ROOT, "Apps")


LIB_FOLDER = os.path.join(APP_FOLDER, "lib")
CORE_FOLDER = os.path.join(LIB_FOLDER, PLUGIN_NAME)
IMAGE_FOLDER = os.path.join(CORE_FOLDER, "images")
AUDIO_FOLDER = os.path.join(CORE_FOLDER, "audios")
DOCUMENT_FOLDER = os.path.join(CORE_FOLDER, "documents")
SCRIPT_FOLDER = os.path.join(CORE_FOLDER, "scripts")

DIST_VERSION_FILE = os.path.join(CORE_FOLDER, "DIST_VERSION.json")

_DIST_VERSION_CACHE = [None]

def get_dist_version():
    """Version stamp of the installed EA_Dist publish, or "dev".

    DarkSide/publish/________publish.py writes DIST_VERSION.json next to the
    lib on every publish run; a source/dev tree has no such file. Lazy and
    cached so a truncated or corrupt file (partial installer extract) can
    never break importers -- every failure collapses to "dev".
    """
    if _DIST_VERSION_CACHE[0] is None:
        version = "dev"
        try:
            if os.path.exists(DIST_VERSION_FILE):
                with open(DIST_VERSION_FILE, "r") as f:
                    version = str(json.load(f).get("version", "dev"))
        except Exception:
            version = "dev"
        _DIST_VERSION_CACHE[0] = version
    return _DIST_VERSION_CACHE[0]


EXE_PRODUCT_FOLDER = os.path.join(LIB_FOLDER, "ExeProducts")
WINDOW_TEMP_FOLDER = os.path.join("C:\\", "temp", "{}_Dump".format(PLUGIN_NAME))
_secure_folder(WINDOW_TEMP_FOLDER)

DEPENDENCY_FOLDER = os.path.join(LIB_FOLDER, "dependency")
if IS_PY2:
    DEPENDENCY_FOLDER = os.path.join(DEPENDENCY_FOLDER, "py2")
else:
    DEPENDENCY_FOLDER = os.path.join(DEPENDENCY_FOLDER, "py3")
PY3_DEPENDENCY_FOLDER = os.path.join(LIB_FOLDER, "dependency", "py3")




REVIT_FOLDER_KEYNAME = "_revit"
REVIT_FOLDER = os.path.join(APP_FOLDER, REVIT_FOLDER_KEYNAME)

################# rhino extension ####################
RHINO_FOLDER_KEYNAME = "_rhino"
RHINO_FOLDER = os.path.join(APP_FOLDER, RHINO_FOLDER_KEYNAME)
DIST_RUI_CLASSIC = os.path.join(RHINO_FOLDER, "{}_For_Rhino_Classic.rui".format(PLUGIN_NAME))
DIST_RUI_MODERN = os.path.join(RHINO_FOLDER, "{}_For_Rhino_Modern.rui".format(PLUGIN_NAME))
ACTIVE_MODERN_RUI = os.path.join(DUMP_FOLDER, "{}_For_Rhino_Modern.rui".format(PLUGIN_NAME))
INSTALLATION_RUI = os.path.join(INSTALLATION_FOLDER, "{}_For_Rhino_Installer.rui".format(PLUGIN_NAME))
RHINO_INSTALLER_SETUP_FOLDER = os.path.join(LIB_FOLDER, PLUGIN_NAME, "RHINO")

################# indesign extension ####################
INDESIGN_FOLDER_KEYNAME = "_indesign"
INDESIGN_FOLDER = os.path.join(APP_FOLDER, INDESIGN_FOLDER_KEYNAME)

################### knowledge database ####################
KNOWLEDGE_RHINO_FILE = "{}\\knowledge_rhino_database{}".format(RHINO_FOLDER, PLUGIN_EXTENSION)
KNOWLEDGE_REVIT_FILE = "{}\\knowledge_revit_database{}".format(REVIT_FOLDER, PLUGIN_EXTENSION)
for _ in [KNOWLEDGE_RHINO_FILE, KNOWLEDGE_REVIT_FILE]:
    if not os.path.exists(_):
        import json
        try:
            with open(_, "w") as f:
                json.dump({}, f, indent=4)
        except Exception as e:
            print("Cannot create file [{}] becasue {}".format(_, e))

################### revit extension ####################
PRIMARY_EXTENSION_NAME = "EnneaDuck"
REVIT_PRIMARY_EXTENSION = os.path.join(
    REVIT_FOLDER, "{}.extension".format(PRIMARY_EXTENSION_NAME)
)
REVIT_PRIMARY_TAB = os.path.join(REVIT_PRIMARY_EXTENSION, "{}.tab".format(PLUGIN_NAME))
REVIT_LIBRARY_TAB = os.path.join(REVIT_PRIMARY_EXTENSION, "{} Library.tab".format(PLUGIN_NAME))
REVIT_TAILOR_TAB = os.path.join(REVIT_PRIMARY_EXTENSION, "{} Tailor.tab".format(PLUGIN_NAME))



#################### shared network root (formerly the L: drive) ####################
#
# The office L: drive is RETIRED. Nothing below may resolve to L:. Shared data
# lives in the enneadtab.com depot (DEPOT.STATE / DEPOT.ASSET). A machine with
# no replacement share is deliberately offline: local dump only, no L: probe.
#
# Precedence, first hit wins:
#   1. EA_SHARED_ROOT environment variable.
#      "OFFLINE" (or any L: path) -> local dump, deliberately offline.
#      Any other path is a real replacement share.
#   2. <ECO_SYS_FOLDER>/shared_root.json      -- per-user / per-machine override
#   3. <CORE_FOLDER>/shared_root.json         -- SHIPPED WITH EA_DIST
#   4. No share configured -> local dump, deliberately offline.
#
# An L: path in env or json is treated as "not configured". Never last-resort
# to L:\4b_Design Technology -- that share is gone and a mapped ghost letter
# produces Access Denied (the 2026-08-03 cn-myruan silent crash).

DB_FOLDER_NAME = "05_EnneadTab-DB"

SHARED_ROOT_ENV_VAR = "EA_SHARED_ROOT"
SHARED_ROOT_CONFIG_NAME = "shared_root.json"
_OFFLINE_SENTINEL = "OFFLINE"

USER_SHARED_ROOT_CONFIG = os.path.join(ECO_SYS_FOLDER, SHARED_ROOT_CONFIG_NAME)
DIST_SHARED_ROOT_CONFIG = os.path.join(CORE_FOLDER, SHARED_ROOT_CONFIG_NAME)


def _is_retired_l_drive_path(path):
    """True if path is the retired office L: drive (any spelling)."""
    if not path:
        return False
    try:
        text = str(path).strip().replace("/", "\\")
    except Exception:
        return False
    if not text:
        return False
    upper = text.upper()
    if upper == "L:" or upper.startswith("L:\\"):
        return True
    if upper.startswith("\\\\TSCLIENT\\L\\"):
        return True
    return False


def _retired_offline_root(source):
    """Local-only root. Sentinel is never created, so exists() is False and
    IS_OFFLINE_MODE trips without probing a hanging UNC or a ghost L: letter."""
    sentinel = os.path.join(DUMP_FOLDER, "_no_shared_network_root")
    return (sentinel,
            os.path.join(sentinel, DB_FOLDER_NAME),
            source,
            True)


def _load_shared_root_config(config_path):
    """Read one shared_root.json.

    Returns {} on any problem (missing, unreadable, truncated, not a dict).
    Never raises: a corrupt config must degrade to the next precedence level,
    not break every import of EnneadTab.

    Args:
        config_path (str): Path to a shared_root.json candidate.

    Returns:
        dict: Parsed config, or {} if unusable.
    """
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _resolve_shared_root():
    """Resolve the shared network root at runtime.

    Returns:
        tuple: (shared_root, db_folder, source, is_deliberately_offline)
            shared_root (str): Root folder of the office shared data.
            db_folder (str): EnneadTab-DB folder inside it.
            source (str): Human-readable provenance, for diagnostics and for
                the ErrorDump payload -- when the fleet goes dark we need to
                know WHICH lever fed it the dead path.
            is_deliberately_offline (bool): True when no live share is configured
                (L: retired, offline flag, or explicit OFFLINE).
    """
    env_value = os.environ.get(SHARED_ROOT_ENV_VAR)
    if env_value:
        env_value = env_value.strip()
    if env_value:
        if env_value.upper() == _OFFLINE_SENTINEL or _is_retired_l_drive_path(env_value):
            return _retired_offline_root("env:{}=OFFLINE".format(SHARED_ROOT_ENV_VAR))
        return (env_value,
                os.path.join(env_value, DB_FOLDER_NAME),
                "env:{}".format(SHARED_ROOT_ENV_VAR),
                False)

    for config_path in [USER_SHARED_ROOT_CONFIG, DIST_SHARED_ROOT_CONFIG]:
        config = _load_shared_root_config(config_path)
        if not config:
            continue
        if config.get("offline") is True:
            return _retired_offline_root("config:{} (offline=true)".format(config_path))
        root = config.get("shared_root")
        if root and _is_retired_l_drive_path(root):
            return _retired_offline_root("config:{} (retired L: ignored)".format(config_path))
        if root:
            db_folder = config.get("db_folder") or os.path.join(root, DB_FOLDER_NAME)
            if _is_retired_l_drive_path(db_folder):
                return _retired_offline_root("config:{} (retired L: db ignored)".format(config_path))
            return (root, db_folder, "config:{}".format(config_path), False)

    return _retired_offline_root("retired-no-shared-root")


SHARED_ROOT, DB_FOLDER, SHARED_ROOT_SOURCE, IS_DELIBERATELY_OFFLINE = _resolve_shared_root()

# Back-compat alias. ~20 call sites across Revit/Rhino/DarkSide still say
# L_DRIVE_HOST_FOLDER; every one of them means "the shared network root".
# Keep the name working, drop the L: assumption. New code should use SHARED_ROOT.
L_DRIVE_HOST_FOLDER = SHARED_ROOT

SHARED_DUMP_FOLDER = os.path.join(DB_FOLDER, "Shared Data Dump")

# Public temp folder for shared temporary files
PUBLIC_TEMP_FOLDER = os.path.join(DB_FOLDER, "temp")

STAND_ALONE_FOLDER = os.path.join(DB_FOLDER, "Stand Alone Tools")

# Where the shared dump / public temp are SUPPOSED to be. Both get rewritten to
# the local dump below when the shared root is unreachable, so the expected paths
# have to be captured now -- they are what the user and ErrorDump need to see.
SHARED_DUMP_FOLDER_EXPECTED = SHARED_DUMP_FOLDER
PUBLIC_TEMP_FOLDER_EXPECTED = PUBLIC_TEMP_FOLDER


# ---------------------------------------------------------------------------
# DEPOT constants -- ADDITIVE (2026-07-29, PR #77 / office network-drive
# retirement, Commit 1). The office drives (L:/J:/I:/W:) are retired; shared
# data moves to the enneadtab.com depot over HTTPS. This block is pure strings
# and os.path.join ONLY -- no network, no file I/O, and no import of the depot
# client. ENVIRONMENT is imported by everything, so any HTTP or disk touch here
# would become a fleet-wide Revit-startup stall. The depot client lives in the
# EnneadTab/DEPOT/ subpackage; the endpoint/URL contract lives in DEPOT/ROUTES.
# Nothing imports these names yet -- Commit 1 is additive and the repo must
# still import cleanly. The old shared-root block above is untouched; it is
# deleted only in Commit 5 once every consumer has moved. See
# docs/plans/2026-07-29-network-drive-retirement-epic.md.
# ---------------------------------------------------------------------------

# Local cache root for depot assets and shared state, under the existing
# ecosystem folder (a stale cached copy beats a dead button when offline).
DEPOT_CACHE_FOLDER = os.path.join(ECO_SYS_FOLDER, "DepotCache")
# Queued writes that could not reach the server (offline) wait here for flush.
DEPOT_OUTBOX_FOLDER = os.path.join(DEPOT_CACHE_FOLDER, "outbox")
# Cache index (etag/sha256/last-checked per key); self-healing if corrupt.
DEPOT_CACHE_INDEX_FILE = os.path.join(DEPOT_CACHE_FOLDER, "cache_index.sexyDuck")

# Namespaces (plan 5.1). Names only -- routing and URLs live in DEPOT/ROUTES.
DEPOT_NS_ASSET = "asset"   # read-only, cacheable (a stale copy beats a dead button)
DEPOT_NS_STATE = "state"   # read-write, rev-checked (loss is always loud)
DEPOT_NS_BLOB = "blob"     # large binary via signed URLs

# Manifest refresh cadence. Steady state must issue zero requests, so the
# client trusts a cached manifest for this long before re-checking (plan R5).
DEPOT_MANIFEST_TTL_SEC = 4 * 60 * 60  # 4 hours

# Per-machine escape hatch (plan R10): point the client at a different depot
# (or a local stub) without a code change. Read by DEPOT/ROUTES, not here.
EA_DEPOT_URL_ENV_VAR = "EA_DEPOT_URL"

# Per-user SharePoint sync root for the retired project drives (J:/I:/W:,
# plan 5.5 / D4). The project files moved to a SharePoint library each user
# syncs to a different local path, so the root is user-configured. Config path
# only here; the resolver and first-use folder-picker prompt land in a later
# commit. NOT a depot concern -- plain local filesystem, no HTTP.
SHAREPOINT_ROOT_CONFIG_NAME = "sharepoint_root.json"
USER_SHAREPOINT_ROOT_CONFIG = os.path.join(ECO_SYS_FOLDER, SHAREPOINT_ROOT_CONFIG_NAME)


def _is_under_shared_root(folder):
    """True if a folder lives on the shared network root (used to mute noise)."""
    try:
        return folder.lower().startswith(SHARED_ROOT.lower())
    except Exception:
        return False


############# engine ####################
ENGINE_FOLDER = os.path.join(APP_FOLDER, "_engine")
SITE_PACKAGES_FOLDER = os.path.join(ENGINE_FOLDER, "Lib")
# Fix: Use compatible approach for both IronPython 2.7 and Python 3
_execute_map_compatible(_secure_folder, [ECO_SYS_FOLDER, DUMP_FOLDER])

# Never mkdir the retired sentinel (that would make exists() True and hide
# IS_OFFLINE_MODE). Engine folders are always local.
_local_only = [ENGINE_FOLDER, SITE_PACKAGES_FOLDER]
if IS_DELIBERATELY_OFFLINE:
    _execute_map_compatible(_secure_folder_safe, _local_only)
else:
    _execute_map_compatible(_secure_folder_safe, [SHARED_ROOT, DB_FOLDER, SHARED_DUMP_FOLDER,
                         PUBLIC_TEMP_FOLDER, STAND_ALONE_FOLDER] + _local_only)

IS_SHARED_ROOT_REACHABLE = os.path.exists(SHARED_DUMP_FOLDER_EXPECTED)

# UNCHANGED SEMANTICS. IS_OFFLINE_MODE has always meant "the shared dump is not
# reachable, we are working against the local dump". Six call sites depend on
# exactly that meaning (SECRET x3, DOCUMENTATION, doc-syncing, doc-synced) and
# they all still behave correctly. Do not repurpose this flag.
IS_OFFLINE_MODE = not IS_SHARED_ROOT_REACHABLE

# THE NEW DISTINCTION, and the whole point of this module's rewrite.
#
# "Deliberately offline" (laptop on a plane, EA_SHARED_ROOT=OFFLINE) is a
# legitimate degraded mode: the user knows, and degradation-to-local is the
# desired behaviour. Stay quiet.
#
# A shared root we were TOLD to use that is simply GONE is a data-loss event.
# Every write below silently lands in a private local sandbox; the user sees no
# error, keeps working, and nothing they produce ever reaches anybody. That is
# the failure mode the L-drive cutover will produce fleet-wide. It stays loud to
# ErrorDump; the on-screen alarm (console + popup) is developer-only as of
# 2026-07-29 (per request). See announce_shared_root_status().
IS_SHARED_DATA_LOST = IS_OFFLINE_MODE and not IS_DELIBERATELY_OFFLINE

if IS_OFFLINE_MODE:
    SHARED_DUMP_FOLDER = DUMP_FOLDER
    PUBLIC_TEMP_FOLDER = os.path.join(DUMP_FOLDER, "temp")
    _secure_folder(PUBLIC_TEMP_FOLDER)


SHARED_ROOT_ALARM_TEMPLATE = (
    "EnneadTab: THE SHARED NETWORK DRIVE IS NOT REACHABLE.\n"
    "\n"
    "Expected shared folder: {}\n"
    "That path came from   : {}\n"
    "\n"
    "Your work is now being saved ONLY on this computer.\n"
    "It is NOT being shared with the office, and other people's shared data is\n"
    "NOT reaching you. Anything that looks like it saved 'to the server' did not.\n"
    "\n"
    "Contact Design Technology before you rely on any shared data."
)

_SHARED_ROOT_ALARM_FIRED = [False]


def get_shared_root_alarm_message():
    """User-facing text for the "shared drive vanished" state.

    Returns:
        str: Plain-language explanation that data is NOT being shared.
    """
    return SHARED_ROOT_ALARM_TEMPLATE.format(SHARED_DUMP_FOLDER_EXPECTED,
                                             SHARED_ROOT_SOURCE)


def _should_report_shared_root_alarm():
    """Rate-limit the ErrorDump report to once per machine per 24 hours.

    Without this, a fleet-wide outage turns into an ErrorDump flood (every user
    x every button press) and the signal drowns in its own alarm.

    Returns:
        bool: True if this machine has not reported in the last 24 hours.
    """
    import time

    marker = os.path.join(DUMP_FOLDER, "shared_root_alarm.DuckLock")
    try:
        if os.path.exists(marker):
            if os.path.getmtime(marker) > (time.time() - 24 * 60 * 60):
                return False
    except Exception:
        pass
    try:
        with open(marker, "w") as f:
            f.write(SHARED_ROOT_SOURCE)
    except Exception:
        pass
    return True


def announce_shared_root_status():
    """Report the vanished-shared-drive failure -- loud to ErrorDump, dev-only on-screen.

    Called from FOLDER.get_shared_dump_folder_file() -- i.e. at the exact moment
    a caller believes it is sharing data and is not. Not called at import: a 5s
    HTTP timeout on every Revit/Rhino startup is not acceptable.

    Behaviour:
      - No-op unless IS_SHARED_DATA_LOST (deliberate offline stays quiet).
      - At most once per process, and at most once per 24h per machine.
      - Reports to ErrorDump so Design Technology sees the fleet-wide blast
        radius instead of learning about it weeks later.
      - Shows DEVELOPERS an on-screen message that data is NOT being shared
        (console + popup, gated on USER.IS_DEVELOPER as of 2026-07-29 per
        request). Average users see nothing on-screen; ErrorDump above still
        fires for everyone.
      - Never raises. ERROR_HANDLE and NOTIFICATION are imported lazily inside
        this function because both import ENVIRONMENT at module load; a
        top-level import here would be a cycle.

    Returns:
        bool: True if the alarm was raised on this call.
    """
    if not IS_SHARED_DATA_LOST:
        return False
    if _SHARED_ROOT_ALARM_FIRED[0]:
        return False
    _SHARED_ROOT_ALARM_FIRED[0] = True

    message = get_shared_root_alarm_message()

    # 2026-07-29 (per request): this alarm is now developer-only on BOTH
    # user-facing channels -- the console echo AND the messenger popup. Average
    # (non-developer) users no longer see it at all. The ErrorDump report below
    # is NOT user-facing (it is the silent signal to Design Technology) and
    # still fires unconditionally, so the fleet-wide blast radius is still
    # captured. All imports are lazy for the same cycle reason noted above.
    try:
        import USER
        _is_developer = USER.IS_DEVELOPER
    except Exception:
        _is_developer = False

    if _is_developer:
        try:
            import ERROR_HANDLE
            ERROR_HANDLE.print_note(message)
        except Exception:
            pass

        try:
            import NOTIFICATION
            NOTIFICATION.messenger(main_text=message)
        except Exception:
            pass

    if not _should_report_shared_root_alarm():
        return True

    try:
        import ERROR_HANDLE
        ERROR_HANDLE.send_error_to_error_dump(
            message,
            "ENVIRONMENT.announce_shared_root_status",
            current_user_name,
            is_silent=True)  # 2026-07-29: on-screen alarm is now dev-only, so this is a silent report
    except Exception:
        pass

    return True


# Error-log submit form retired 2026-06-10 (replaced by ErrorDump API);
# the result URL stays for the legacy sheet-viewer buttons.
ERROR_LOG_GOOGLE_FORM_RESULT = "https://docs.google.com/forms/d/1nEbgC-Nbaiwrr5FFVfVgqc_hUqzBrtvus8aHY6aL4lE/edit?pli=1#responses"


USAGE_LOG_GOOGLE_FORM_SUBMIT = "https://docs.google.com/forms/d/e/1FAIpQLSc2Ruskj8BQYYA91vOaXqg_mOk0l67ca_ZGXpS-e-LwfU9bVA/formResponse"
USAGE_LOG_GOOGLE_FORM_RESULT = "https://docs.google.com/forms/d/12Ew3_3Mmrl4P-grEnVkK8cIuLQzDAEm0ECqBmJI_7oA/edit#responses"

####################################


# Global cache for deletion counter to reduce file I/O
_DELETION_COUNTER_CACHE = None

def _delete_folder_or_file_after_date(path, date_YYMMDD_tuple, max_delete_per_day = 200):
    """Delete a folder if current date is past the specified date.
    
    Args:
        path (str): Path to the folder or file to be deleted
        date_YYMMDD_tuple (tuple): Date tuple in format (year, month, day)
        max_delete_per_day (int): Maximum number of deletions allowed per day (default: 200)
    """
    global _DELETION_COUNTER_CACHE
    
    if not os.path.exists(path):
        return
        
    delete_after = datetime(*date_YYMMDD_tuple)
    if datetime.now() >= delete_after:
        # Check daily deletion limit
        import time
        import json
        
        deletion_counter_file = os.path.join(DUMP_FOLDER, "daily_deletion_counter.DuckLock")
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Use cache or load from file
        if _DELETION_COUNTER_CACHE is None or _DELETION_COUNTER_CACHE.get("date") != current_date:
            deletion_data = {"date": current_date, "count": 0}
            if os.path.exists(deletion_counter_file):
                try:
                    with open(deletion_counter_file, "r") as f:
                        deletion_data = json.load(f)
                except:
                    pass
            
            # Reset counter if it's a new day
            if deletion_data.get("date") != current_date:
                deletion_data = {"date": current_date, "count": 0}
            
            _DELETION_COUNTER_CACHE = deletion_data
        else:
            deletion_data = _DELETION_COUNTER_CACHE
        
        # Check if we've reached the daily limit
        if deletion_data["count"] >= max_delete_per_day:
            return
        
        # Perform deletion
        import shutil
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            
            # Increment deletion counter
            deletion_data["count"] += 1
            _DELETION_COUNTER_CACHE = deletion_data
            
            # Only save to file when reaching the max delete count
            if deletion_data["count"] >= max_delete_per_day:
                try:
                    with open(deletion_counter_file, "w") as f:
                        json.dump(deletion_data, f)
                except:
                    pass
                
        except Exception as e:
            pass



# Remove stale OneDrive "<PLUGIN> Ecosystem" copies left behind by OneDrive
# Known-Folder-Move (any tenant: Ennead, CannonDesign, ...). The LIVE install
# always lives at the literal USER_DOCUMENT_FOLDER path (ECO_SYS_FOLDER); these
# OneDrive copies are never read by EnneadTab and only confuse users who open
# "Documents" in Explorer and find a stale, dehydrated copy.
def _find_stale_onedrive_ecosystem_folders():
    stale = []
    live = os.path.normcase(os.path.abspath(ECO_SYS_FOLDER))
    for _od_folder in _find_onedrive_folders():
        # SAFETY: if the live install itself sits inside a OneDrive tree (a fully
        # KFM-redirected machine), never touch anything under that tree -- we could
        # otherwise delete the live install.
        if live.startswith(os.path.normcase(os.path.abspath(_od_folder))):
            continue
        for _variant in ("{} Ecosystem".format(PLUGIN_NAME), "{}-Ecosystem".format(PLUGIN_NAME)):
            _candidate = os.path.join(_od_folder, "Documents", _variant)
            if os.path.exists(_candidate) and os.path.normcase(os.path.abspath(_candidate)) != live:
                stale.append(_candidate)
    return stale

# no longer plan to have both folder, so delete the modern one and keep using the old one. i have resolved this by rerouting rvb file for rhino.
depreciated_ECO_SYS_FOLDER_MODERN = os.path.join(USER_DOCUMENT_FOLDER, 
                                     "{}-Ecosystem".format(PLUGIN_NAME))

depreciated_dist_lite_folder = os.path.join(ECO_SYS_FOLDER, "EA_Dist_Lite")
depreciated_enneadPLUS_menu = os.path.join(RHINO_FOLDER, "Ennead+.menu")


depreciated_log = os.path.join(os.path.expanduser("~"), "Desktop", "I just blue myself.log")

# Tenant-agnostic OneDrive "Ecosystem" cleanup. Delete-after-date so it is
# reversible until the cutoff and rolls out gradually. The finder already refuses
# to return the live install (see safety guard above).
for _stale_od in _find_stale_onedrive_ecosystem_folders():
    _delete_folder_or_file_after_date(_stale_od, (2026, 9, 1))

_delete_folder_or_file_after_date(depreciated_enneadPLUS_menu, (2025, 4, 1))
_delete_folder_or_file_after_date(depreciated_dist_lite_folder, (2025, 5, 1))
_delete_folder_or_file_after_date(depreciated_ECO_SYS_FOLDER_MODERN, (2025, 5, 1))

_delete_folder_or_file_after_date(depreciated_log, (2025, 5, 1))

####################################
def cleanup_dump_folder():
    """Clean up temporary files from the dump folder.

    Removes files older than 3 days from the DUMP_FOLDER, excluding protected file types:
    .json, PLUGIN_EXTENSION, .txt, .DuckLock, and .rui files.
    
    This function runs silently and handles file deletion errors gracefully.
    """
    import os
    import time

    cutoff_time = time.time() - (3 * 24 * 60 * 60)  # 3 days
    protected_extensions = {'.json', PLUGIN_EXTENSION, ".txt", ".lock", ".DuckLock", ".rui"}

    for filename in os.listdir(DUMP_FOLDER):
        file_path = os.path.join(DUMP_FOLDER, filename)
        if not os.path.isfile(file_path):
            continue
            
        file_ext = os.path.splitext(filename)[1].lower()

        if file_ext in protected_extensions:
            continue
            
        if os.path.getmtime(file_path) < cutoff_time:
            try:
                os.remove(file_path)
            except:
                pass


def should_check_l_drive():
    """Determine if L drive should be checked based on time elapsed since last check.
    
    Ensures check happens at most once per hour.
    
    Returns:
        bool: True if an hour has passed since last check, False otherwise.
    """
    import time
    import os.path
    
    timestamp_file = os.path.join(DUMP_FOLDER, "l_drive_check.DuckLock")
    current_time = time.time()
    cutoff_time = current_time - (60 * 60)  # 1 hour
    
    # If lock file exists and is less than an hour old, don't check
    if os.path.exists(timestamp_file):
        if os.path.getmtime(timestamp_file) > cutoff_time:
            return False
    
    # Update timestamp by touching the file
    try:
        with open(timestamp_file, "w") as f:
            f.write("")
    except:
        pass
        
    return True

def should_cleanup_dump_folder():
    """Determine if dump folder should be cleaned up based on time elapsed since last cleanup.
    
    Ensures cleanup happens at most once per day.
    
    Returns:
        bool: True if a day has passed since last cleanup, False otherwise.
    """
    import time
    import os.path
    
    timestamp_file = os.path.join(DUMP_FOLDER, "dump_cleanup.DuckLock")
    current_time = time.time()
    cutoff_time = current_time - (24 * 60 * 60)  # 24 hours
    
    # If lock file exists and is less than a day old, don't cleanup
    if os.path.exists(timestamp_file):
        if os.path.getmtime(timestamp_file) > cutoff_time:
            return False
    
    # Update timestamp by touching the file
    try:
        with open(timestamp_file, "w") as f:
            f.write("")
    except:
        pass
        
    return True

def is_avd():
    """Detect if running in Azure Virtual Desktop environment.

    Returns:
        bool: True if running in AVD or GPU-PD environment, False otherwise
    """
    computer_name = get_computer_name()
  
    return "avd" in computer_name.lower() or "gpupd" in computer_name.lower()

def get_computer_name():
    """Get the computer name.

    Returns:
        str: Computer name

    """
    try:
        import clr  # pyright:ignore
        from System.Net import Dns  # pyright:ignore

        computer_name = Dns.GetHostName()
    except:
        try:
            import socket
            computer_name = socket.gethostname()
        except:
            # Final fallback for environments without socket module (embedded Python, etc.)
            import os
            computer_name = os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'unknown'))

    return computer_name


def is_Rhino_8():
    """Check if current environment is Rhino 8.

    Returns:
        bool: True if running in Rhino 8, False otherwise
    """

    return str(get_rhino_version()) == "8"

def is_Rhino_7():
    """Check if current environment is Rhino 7.

    Returns:
        bool: True if running in Rhino 7, False otherwise
    """

    return str(get_rhino_version()) == "7"

def get_rhino_version(main_version_only=True):
    """Retrieve the current Rhino version.

    Args:
        main_version_only (bool, optional): If True, returns only the major version number.
            Defaults to True.

    Returns:
        str or None: Rhino version number if in Rhino environment, None otherwise
    """
    if not IS_RHINO_ENVIRONMENT:
        return None
    import Rhino  # pyright: ignore

    return Rhino.RhinoApp.ExeVersion  if main_version_only else Rhino.RhinoApp.Version

def is_Rhino_environment():
    """Check if the current environment is Rhino.

    Returns:
        bool: True if running in Rhino environment, False otherwise
    """
    try:
        import rhinoscriptsyntax  # pyright: ignore

        return True
    except:
        return False


def is_Grasshopper_environment():
    """Check if current environment is Grasshopper.

    Returns:
        bool: True if running in Grasshopper environment, False otherwise
    """
    try:
        import Grasshopper  # pyright: ignore

        return True
    except:
        return False


def is_Revit_environment():
    """Check if the current environment is Revit.

    Returns:
        bool: True if current environment is Revit.
    """
    try:
        from Autodesk.Revit import DB  # pyright: ignore

        return True
    except:
        return False


def is_RhinoInsideRevit_environment():
    """Check if the current environment is RhinoInsideRevit.

    Returns:
        bool: True if current environment is RhinoInsideRevit
    """
    try:
        import clr  # pyright: ignore

        clr.AddReference("RhinoCommon")
        clr.AddReference("RhinoInside.Revit")
        return True
    except:
        return False


def is_terminal_environment():
    """Check if the current environment is within the terminal.

    Returns:
        bool: True if current environment is a terminal.
    """
    return not is_Rhino_environment() and not is_Revit_environment()


def unit_test():
    import inspect
    # get all the global varibales in the current script

    for i, var_name in enumerate(sorted(globals())):
        var_value = globals()[var_name]

        if inspect.ismodule(var_value):
            continue

        if not var_name.startswith("_") and not callable(var_value):
            print(var_name, " = ", var_value)

            if isinstance(var_value, bool):
                continue

            if not isinstance(var_value, list):
                var_value = [var_value]

            for item in var_value:
                if "\\" in item:
                    is_ok = os.path.exists(item) or os.path.isdir(item)

                    # Check old paths that should be deleted
                    if "depreciated_" in var_name:
                        if is_ok:
                            print("!!!!!!!!!!!!!!!!!!WARNING: depreciated folder still exists and should be deleted: {}".format(item))
                        continue
                    else:
                        # Check required paths that should exist
                        if not is_ok:
                            print("!!!!!!!!!!!!!!ERROR: Required path does not exist: {}".format(item))
                        # assert is_ok


IS_AVD = is_avd()
IS_RHINO_ENVIRONMENT = is_Rhino_environment()
IS_RHINO_7 = is_Rhino_7()
IS_RHINO_8 = is_Rhino_8()
IS_GRASSHOPPER_ENVIRONMENT = is_Grasshopper_environment()
IS_REVIT_ENVIRONMENT = is_Revit_environment()
IS_RHINOINSIDEREVIT_ENVIRONMENT = is_RhinoInsideRevit_environment()

def get_app_name():
    """Determine the current application environment.

    Returns:
        str: Application identifier - 'revit', 'rhino', or 'terminal'.
    """
    app_name = "terminal"
    if IS_REVIT_ENVIRONMENT:
        app_name = "revit"
    elif IS_RHINO_ENVIRONMENT:
        app_name = "rhino"
    return app_name

def is_shared_root_available():
    """Return whether the resolved shared network root is reachable right now.

    Live check, not the import-time snapshot: a drive can come back (VPN
    reconnect) inside a long Revit session.

    Returns:
        bool: True if SHARED_ROOT exists, False otherwise.
    """
    return os.path.exists(SHARED_ROOT)


def require_shared_root(feature_label=None):
    """Gate features that need the office shared network folder.

    Returns True when the shared root is reachable. When it is not, fires
    announce_shared_root_status() and shows a user messenger (if a feature
    label is provided), then returns False. Callers that need library content
    (assets, family browser, tutorials) should abort on False -- do not invent
    a fake local library.

    Args:
        feature_label (str or None): Short name for the messenger, e.g.
            "Place Asset". When None, only the ErrorDump announce fires.

    Returns:
        bool: True if shared root is available, False otherwise.
    """
    if is_shared_root_available():
        return True
    announce_shared_root_status()
    if feature_label:
        try:
            import NOTIFICATION
            NOTIFICATION.messenger(
                main_text="Shared network folder is offline. Cannot run: {}".format(
                    feature_label
                )
            )
        except Exception:
            pass
    return False


def alert_l_drive_not_available(play_sound=False):
    """Deprecated alias of is_shared_root_available().

    Kept because REVIT_PROJ_DATA still calls it as a True/False gate at three
    sites. Silent by design -- the loud path is announce_shared_root_status().

    Args:
        play_sound (bool): Ignored; retained for call-site compatibility.

    Returns:
        bool: True if the shared root exists, False otherwise.
    """
    return is_shared_root_available()


# Run maintenance operations
if should_cleanup_dump_folder():
    cleanup_dump_folder()

# 2026-08-18: office L: is retired. shared_root.json ships with offline:true.
# Do not put an L: path in that file. Shared data is the enneadtab.com depot.
# alert_l_drive_not_available() is a silent existence check of SHARED_ROOT
# (a local sentinel when offline). Loud alarm is announce_shared_root_status().
###############
if __name__ == "__main__":
    unit_test()

