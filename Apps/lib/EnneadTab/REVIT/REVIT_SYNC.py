#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import sys

# Ensure parent lib/EnneadTab is on sys.path for sibling imports
_root = os.path.abspath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.append(_root)

import ERROR_HANDLE
import REVIT_APPLICATION
try:

    from Autodesk.Revit import DB # pyright: ignore
    from Autodesk.Revit import UI # pyright: ignore
    UIDOC = REVIT_APPLICATION.get_uidoc() 
    DOC = REVIT_APPLICATION.get_doc()
    from pyrevit import script #
    
except:
    globals()["UIDOC"] = object()
    globals()["DOC"] = object()
    ERROR_HANDLE.print_note("REVIT_SYNC.py: Error importing Revit modules")



import REVIT_FORMS, REVIT_VIEW, REVIT_EVENT
from EnneadTab import CONFIG, EXE, DATA_FILE, NOTIFICATION, SPEAK

import time
import json

# Sync Queue API configuration
# 2026-07-06 (#1435): primary base flipped to the /sync proxy path. The old
# /db path is kept as a transparent fallback base so the fleet transition is
# zero-risk. Both paths are permanent proxies to the SAME backend and are
# live-verified working -- the fallback is only reached when the primary edge
# is unreachable at the transport level (not on an HTTP error response, which
# would be byte-identical from either base).
SYNC_QUEUE_API_BASE = "https://enneadtab.com/sync/api/revit-sync"
SYNC_QUEUE_API_BASE_FALLBACK = "https://enneadtab.com/db/api/revit-sync"
SYNC_QUEUE_API_TIMEOUT_MS = 5000
SYNC_QUEUE_API_MAX_RETRIES = 2


def _is_transport_failure(error):
    """Decide whether a failed request should be retried against the fallback base.

    Only a transport/connection-level failure (host unreachable, DNS failure,
    connection refused, timeout) means the primary base itself is unreachable
    and the fallback base is worth trying. A ProtocolError -- the server
    returned an HTTP status such as 400/404/500 -- means the primary base IS
    reachable and answering; since both bases proxy to the same backend, the
    fallback would return the same response, so we do NOT fall back.

    Args:
        error: The exception caught from a failed request, or None

    Returns:
        bool: True if the primary base appears unreachable (fallback eligible)
    """
    if error is None:
        return False
    try:
        import clr
        clr.AddReference("System")
        from System.Net import WebException, WebExceptionStatus
        if isinstance(error, WebException):
            return error.Status != WebExceptionStatus.ProtocolError
    except Exception:
        # If we cannot classify the error, do not fall back -- preserve the
        # pre-fallback behavior of returning None on an unclassified failure.
        pass
    return False


def _create_web_request(url, method="GET"):
    """Create a WebRequest with timeout configured.

    System.Net.WebClient does not expose a timeout property,
    so we use HttpWebRequest directly for proper timeout control.

    Args:
        url: Full URL string
        method: HTTP method (GET or POST)

    Returns:
        System.Net.HttpWebRequest with timeout set
    """
    import clr
    clr.AddReference("System")
    from System.Net import WebRequest

    request = WebRequest.Create(url)
    request.Method = method
    request.Timeout = SYNC_QUEUE_API_TIMEOUT_MS
    return request


def _do_api_post(base, endpoint, data):
    """POST JSON to a single sync queue API base, with per-base retry.

    Uses System.Net.HttpWebRequest for IronPython 2.7 compatibility with proper
    timeout. Retries on transient failure (500, timeout) within this base only.

    Args:
        base: API base URL, e.g. "https://enneadtab.com/sync/api/revit-sync"
        endpoint: API path, e.g. "/request"
        data: Dict to serialize as JSON body

    Returns:
        tuple: (result, last_error). On success, (parsed_dict, None); on
        failure, (None, exception). The caller inspects last_error to decide
        whether to retry against the fallback base.
    """
    import clr
    clr.AddReference("System")
    from System.Text import Encoding
    from System.IO import StreamReader

    url = "{}{}".format(base, endpoint)
    body = json.dumps(data)
    body_bytes = Encoding.UTF8.GetBytes(body)

    last_error = None
    for attempt in range(SYNC_QUEUE_API_MAX_RETRIES):
        try:
            request = _create_web_request(url, "POST")
            request.ContentType = "application/json"
            request.ContentLength = len(body_bytes)

            stream = request.GetRequestStream()
            stream.Write(body_bytes, 0, len(body_bytes))
            stream.Close()

            response = request.GetResponse()
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            text = reader.ReadToEnd()
            reader.Close()
            response.Close()
            return (json.loads(text), None)
        except Exception as e:
            last_error = e
            error_str = str(e)
            is_retryable = "(500)" in error_str or "timed out" in error_str.lower() or "timeout" in error_str.lower()
            if not is_retryable or attempt == SYNC_QUEUE_API_MAX_RETRIES - 1:
                break
            time.sleep(1)

    return (None, last_error)


def _api_post(endpoint, data):
    """POST JSON to the sync queue API, with transparent fallback base.

    Tries the primary base (SYNC_QUEUE_API_BASE, the /sync proxy) first. If the
    primary base is unreachable at the transport level (connection refused, DNS
    failure, timeout) -- and NOT when it returns an HTTP error response -- the
    same call is retried once against the fallback base
    (SYNC_QUEUE_API_BASE_FALLBACK, the legacy /db proxy). Both proxy to the same
    backend; the fallback exists to make the /db -> /sync fleet transition
    zero-risk. Per-base retry-on-transient (500, timeout) is preserved.

    Args:
        endpoint: API path, e.g. "/request"
        data: Dict to serialize as JSON body

    Returns:
        dict or None: Parsed response, or None on any failure
    """
    result, last_error = _do_api_post(SYNC_QUEUE_API_BASE, endpoint, data)
    if last_error is None:
        return result

    if _is_transport_failure(last_error):
        ERROR_HANDLE.print_note("Sync queue primary base unreachable ({}), retrying fallback base: {}".format(endpoint, last_error))
        fb_result, fb_error = _do_api_post(SYNC_QUEUE_API_BASE_FALLBACK, endpoint, data)
        if fb_error is None:
            return fb_result
        last_error = fb_error

    ERROR_HANDLE.print_note("Sync queue API call failed ({}): {}".format(endpoint, last_error))
    return None


def _do_api_get(base, endpoint, params=None):
    """GET from a single sync queue API base, with per-base retry.

    Args:
        base: API base URL, e.g. "https://enneadtab.com/sync/api/revit-sync"
        endpoint: API path, e.g. "/status"
        params: Dict of query parameters

    Returns:
        tuple: (result, last_error). On success, (parsed_dict, None); on
        failure, (None, exception).
    """
    import clr
    clr.AddReference("System")
    from System.Text import Encoding
    from System.IO import StreamReader

    url = "{}{}".format(base, endpoint)
    if params:
        query_parts = ["{}={}".format(k, v) for k, v in params.items()]
        url = "{}?{}".format(url, "&".join(query_parts))

    last_error = None
    for attempt in range(SYNC_QUEUE_API_MAX_RETRIES):
        try:
            request = _create_web_request(url, "GET")
            response = request.GetResponse()
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            text = reader.ReadToEnd()
            reader.Close()
            response.Close()
            return (json.loads(text), None)
        except Exception as e:
            last_error = e
            error_str = str(e)
            is_retryable = "(500)" in error_str or "timed out" in error_str.lower() or "timeout" in error_str.lower()
            if not is_retryable or attempt == SYNC_QUEUE_API_MAX_RETRIES - 1:
                break
            time.sleep(1)

    return (None, last_error)


def _api_get(endpoint, params=None):
    """GET from the sync queue API, with transparent fallback base.

    Tries the primary base (SYNC_QUEUE_API_BASE, the /sync proxy) first. On a
    transport-level failure of the primary base (not on an HTTP error response),
    retries once against the fallback base (SYNC_QUEUE_API_BASE_FALLBACK, the
    legacy /db proxy). See _api_post for the full rationale.

    Args:
        endpoint: API path, e.g. "/status"
        params: Dict of query parameters

    Returns:
        dict or None: Parsed response, or None on any failure
    """
    result, last_error = _do_api_get(SYNC_QUEUE_API_BASE, endpoint, params)
    if last_error is None:
        return result

    if _is_transport_failure(last_error):
        ERROR_HANDLE.print_note("Sync queue primary base unreachable ({}), retrying fallback base: {}".format(endpoint, last_error))
        fb_result, fb_error = _do_api_get(SYNC_QUEUE_API_BASE_FALLBACK, endpoint, params)
        if fb_error is None:
            return fb_result
        last_error = fb_error

    ERROR_HANDLE.print_note("Sync queue API GET failed ({}): {}".format(endpoint, last_error))
    return None


def _hash_path_to_guid(path):
    """Hash a file path into a deterministic GUID-like string.

    Uses djb2 algorithm matching server-side normalizeModelGuid() in EnneadTab-DB
    so that hashed IDs are consistent across client and server.

    Args:
        path: File path string to hash

    Returns:
        str: Deterministic ID in format "path-{hash}-{clean_name}"
    """
    # 2026-04-01: Must use ADD variant (h * 33 + ord) to match server-side
    # normalizeModelGuid() in EnneadTab-DB/schemas.ts. XOR variant produces
    # different hashes for the same input.
    h = 5381
    for ch in path:
        h = ((h * 33) + ord(ch)) & 0xFFFFFFFF
    hex_str = format(h, '08x')
    # Clean filename for readability
    name = os.path.splitext(os.path.basename(path))[0]
    clean = ''.join(c if c.isalnum() else '_' for c in name)
    clean = '_'.join(p for p in clean.split('_') if p)[:50]
    return "path-{}-{}".format(hex_str, clean)


# 2026-04-01: Fixed to return actual GUID instead of model path.
# Previously returned user-visible central model path (e.g. "Autodesk Docs://..."),
# which is not a stable identifier. Now returns a real GUID for both cloud-based
# (BIM 360/ACC) and server-based (Revit Server) central models, falling back to
# a deterministic djb2 hash of the path for local workshared or non-workshared models.
def get_model_guid(doc):
    """Extract a stable identifier for the Revit central model.

    Priority:
        1. Cloud model GUID via GetCloudModelPath (BIM 360/ACC/Autodesk Docs)
        2. Server-based GUID via WorksharingCentralGUID (Revit Server)
        3. Deterministic hash of the central model path
        4. Deterministic hash of doc.Title

    Args:
        doc: Revit Document object

    Returns:
        str: A GUID string or deterministic hash ID
    """
    # 1. Cloud-based models (BIM 360 / ACC / Autodesk Docs) -- Revit 2019+
    try:
        if hasattr(doc, 'IsModelInCloud') and doc.IsModelInCloud:
            cloud_path = doc.GetCloudModelPath()
            if cloud_path:
                model_guid = str(cloud_path.GetModelGUID())
                if model_guid and model_guid != "00000000-0000-0000-0000-000000000000":
                    return model_guid
    except Exception:
        pass  # Older Revit versions without cloud support

    # 2. Server-based central models (Revit Server)
    try:
        guid = doc.WorksharingCentralGUID
        if guid and str(guid) != "00000000-0000-0000-0000-000000000000":
            return str(guid)
    except Exception:
        pass  # Older Revit versions or non-workshared models

    # 3. Fall back to hashing the central model path (local workshared)
    try:
        central_path = doc.GetWorksharingCentralModelPath()
        if central_path:
            from Autodesk.Revit.DB import ModelPathUtils
            path_str = ModelPathUtils.ConvertModelPathToUserVisiblePath(central_path)
            if path_str:
                return _hash_path_to_guid(path_str)
    except Exception as e:
        ERROR_HANDLE.print_note("Could not get central model path: {}".format(e))

    # 4. Last resort: hash the document title (non-workshared)
    return _hash_path_to_guid(doc.Title)


def api_request_sync(doc):
    """Request sync permission from EnneadTab-DB API.

    Joins the queue or refreshes heartbeat. Returns API response
    with allowed status, or None if API is unreachable.

    Args:
        doc: Revit Document object

    Returns:
        dict or None: {"allowed": bool, "queue": [...], "dashboard_url": str}
    """
    from EnneadTab import USER, ENVIRONMENT
    model_guid = get_model_guid(doc)
    data = {
        "model_guid": model_guid,
        "model_name": doc.Title,
        "username": USER.USER_NAME,
        "machine_name": ENVIRONMENT.get_computer_name()
    }
    return _api_post("/request", data)


def api_complete_sync(doc, changes=None):
    """Notify EnneadTab-DB that sync is complete. Remove from queue.

    Args:
        doc: Revit Document object
        changes: Array or object representing model changes

    Returns:
        dict or None: {"success": bool, "found": bool, "queue": [...]}
    """
    from EnneadTab import USER
    model_guid = get_model_guid(doc)
    data = {
        "model_guid": model_guid,
        "username": USER.USER_NAME
    }
    if changes:
        data["changes"] = changes
    return _api_post("/complete", data)


def api_get_status(model_guid):
    """Read-only queue snapshot. Does not join or heartbeat.

    Args:
        model_guid: Central model identifier

    Returns:
        dict or None: {"queue": [...], "dashboard_url": str}
    """
    if not model_guid:
        return None
    return _api_get("/status", {"model_guid": model_guid})


def api_prioritize_sync(doc):
    """Move current user to front of queue (cut in line).

    Args:
        doc: Revit Document object

    Returns:
        dict or None: {"success": bool, "queue": [...]}
    """
    from EnneadTab import USER
    model_guid = get_model_guid(doc)
    data = {
        "model_guid": model_guid,
        "username": USER.USER_NAME
    }
    return _api_post("/prioritize", data)


SYNC_MONITOR_FILE = "last_sync_record_data"




@ERROR_HANDLE.try_catch_error()
def kill_record():
    from pyrevit import forms

    with DATA_FILE.update_data(SYNC_MONITOR_FILE) as data:
        if not data:
            NOTIFICATION.messenger(main_text = "No Active Record Found!!!")
            return

        """
        class MyOption(forms.TemplateListItem):
            @property
            def name(self):
                return "{} :Last Record {}".format(self.item)

        ops = [MyOption(key, value) for key, value in data]
        """
        selected_keys = forms.SelectFromList.show(data.keys(),
                                                multiselect = True,
                                                title = "Want to kill curtain record from last sync monitor?",
                                                button_name = 'Kill Selected Record(s)')
        if not selected_keys:
            return

        for key in selected_keys:
            del data[key]




@ERROR_HANDLE.try_catch_error(is_silent=True)
def update_last_sync_data_file(doc):

    if "detach" in doc.Title.lower():
        return

    # old_data = DATA_FILE.get_data(SYNC_MONITOR_FILE)
    # if old_data:
    #     for key, value in old_data.items():
    #         if time.time() - value  > 60*60*24:#record older than 24 hour should be removed
    #             print ("deleting key", key)
    #             del old_data[key]
    # else:
    #     old_data = dict()

    # old_data[doc.Title] = time.time()
    # DATA_FILE.set_data(old_data, SYNC_MONITOR_FILE)
    # return 



    with DATA_FILE.update_data(SYNC_MONITOR_FILE, keep_holder_key=time.time()) as data:
        if data:

            for key, value in data.items():
                if key == "key_holder":
                    continue
                if time.time() - value  > 60*60*24:#record older than 24 hour should be removed
                    print ("This project is no longer being monitored for sync due to long inactivity: {}".format(key))
                    del data[key]
        else:
  
            data = dict()
        

        if doc.IsModified:
            punish_long_gap_time(data)


   
        data[doc.Title] = time.time()



    


@ERROR_HANDLE.try_catch_error(is_silent=True)
def remove_last_sync_data_file(doc):

    with DATA_FILE.update_data(SYNC_MONITOR_FILE) as data:
        if not data:
            return

        if doc.Title in data.keys():
            del data[doc.Title]


@ERROR_HANDLE.try_catch_error()
def punish_long_gap_time(data):

    now = time.time()
    min_max = 90
    for key, value in data.items():
        if now - value  > 60 * min_max:
            
            #print int( (now - value - 60 * min_max) / 60)
            try:
                pass
                # LEGACY_LOG.sync_gap_too_long(mins_exceeded = int( (now - value - 60 * min_max) / 60), doc_name = key )
            except:
                pass
                # ENNEAD_LOG.sync_gap_too_long(mins_exceeded = int( (now - value - 60 * min_max) / 60) )





@ERROR_HANDLE.try_catch_error()
def is_doc_opened(doc):
    data = DATA_FILE.get_data(SYNC_MONITOR_FILE)
    if not data:
        return False

    if doc.Title in data.keys():
        NOTIFICATION.messenger(main_text = "Wait a minutes...\nThis document seems to be opened already.")
        SPEAK.speak("Unless you recently crashed Revit, this document seems to be opened already. You should prevent opening same file on same machine, because this will confuse central model which local version to allow sync.")
        REVIT_FORMS.notification(main_text = "This document seems to be opened already in other session.\nOr maybe recently crashed.\nAnyway, I have detected the record already existing.",
                                        sub_text = "Double check if this double opening is intentional.\nThere is another possibility that your last session crashed and the exit is not logged. In that case, please ignore this message box.",
                                        self_destruct = 20)
        return True
    return False

@ERROR_HANDLE.try_catch_error()
def is_hate_sync_monitor():
    return CONFIG.get_setting("radio_bt_sync_monitor_never", False)

@ERROR_HANDLE.try_catch_error()
def start_monitor():

    if is_hate_sync_monitor():
        return

    if EXE is not None:
        EXE.try_open_app("LastSyncMonitor")





def do_you_want_to_sync_and_close_after_done():
    will_sync_and_close = False
    res = REVIT_FORMS.dialogue(main_text = "Sync and Close after done?", options = ["Yes", "No"])
    if res == "Yes":
        will_sync_and_close = True

    return will_sync_and_close



def sync_and_close(close_others = True, disable_sync_queue = True):
    """Synchronizes current document and optionally closes other documents.
    
    Performs a safe sync operation with error handling and optional cleanup:
    1. Attempts to sync current document
    2. Optionally closes other open documents
    3. Handles various edge cases (links, read-only, etc.)
    
    Args:
        close_others (bool): Close other open documents. Defaults to True
        disable_sync_queue (bool): Bypass sync queue system. Defaults to True
        
    Note:
        - Will attempt to close documents even if sync fails
        - Skips linked documents and read-only files
        - Logs operations to error handler
    """
    from pyrevit import script
    from pyrevit.coreutils import envvars
    output = script.get_output()
    killtime = 30
    output.self_destruct(killtime)

    
    REVIT_EVENT.set_sync_queue_enable_stage(disable_sync_queue)
    if close_others:
        envvars.set_pyrevit_env_var("IS_AFTER_SYNC_WARNING_DISABLED", True)
        # if you descide to close others, they should be no further warning. Only recover that warning behavir in DOC OPENED event


    def get_docs():
        try:
            doc = __revit__.ActiveUIDocument.Document # pyright: ignore
            docs = doc.Application.Documents
            ERROR_HANDLE.print_note("get docs using using method 1")
        except:
            docs = __revit__.Documents #pyright: ignore
            ERROR_HANDLE.print_note("get docs using using method 2")
        ERROR_HANDLE.print_note( "Get all docs, inlcuding links and family doc = {}".format(str([x.Title for x in docs])))
        return docs

    ERROR_HANDLE.print_note("getting docs before sync")
    docs = get_docs()
    logs = []

    for doc in docs:

        if doc.IsLinked or doc.IsFamilyDocument:
            continue

        try:
            REVIT_VIEW.switch_to_sync_draft_view(doc)
        except Exception as e:
            ERROR_HANDLE.print_note("Error switching to sync draft view: {}".format(e))
            pass
        # print "#####"
        # print ("# {}".format( doc.Title) )
        #with revit.Transaction("Sync {}".format(doc.Title)):
        t_opts = DB.TransactWithCentralOptions()
        #t_opts.SetLockCallback(SynchLockCallBack())
        s_opts = DB.SynchronizeWithCentralOptions()
        s_opts.SetRelinquishOptions(DB.RelinquishOptions(True))

        s_opts.SaveLocalAfter = True
        s_opts.SaveLocalBefore = True
        s_opts.Comment = "EnneadTab Batch Sync"
        s_opts.Compact = True


        try:
            doc.SynchronizeWithCentral(t_opts,s_opts)
            logs.append( "\tSync [{}] Success.".format(doc.Title))
            import SPEAK
            SPEAK.speak("Document {} has finished syncing.".format(doc.Title))
        except Exception as e:
            logs.append( "\tSync [{}] Failed.\n{}\t".format(doc.Title, e))

        REVIT_VIEW.switch_from_sync_draft_view()
    
    envvars.set_pyrevit_env_var("IS_SYNC_QUEUE_DISABLED", not(disable_sync_queue))
    for log in logs:
        ERROR_HANDLE.print_note( log)
    if not close_others:
        return

    ERROR_HANDLE.print_note("getting docs before active safty doc")
    docs = get_docs()
    REVIT_APPLICATION.open_safety_doc_family()
    ERROR_HANDLE.print_note("active doc set as safety doc")
    for doc in docs:
        if doc is None:
            ERROR_HANDLE.print_note("doc is None, skip")
            continue
        try:
            if doc.IsLinked:
                ERROR_HANDLE.print_note("doc {} is a link doc, skip".format(doc.Title))
                continue
        except Exception as e:
            ERROR_HANDLE.print_note ("Sync&Close Info:")
            ERROR_HANDLE.print_note (e)
            ERROR_HANDLE.print_note(str(doc))
            continue

        title = doc.Title
        try:
            ERROR_HANDLE.print_note ("Trying to close [{}]".format(title))
            doc.Close(False)
            doc.Dispose()
        except Exception as e:
            ERROR_HANDLE.print_note (e)
            try:
                ERROR_HANDLE.print_note ("skip closing [{}]".format(title))
            except:
                ERROR_HANDLE.print_note ("skip closing some doc")
        """
        try to open a dummy family rvt file in the buldle folder and switch to that as active doc then close original active doc
        """


################## main code below #####################
if __name__== "__main__":
    output = script.get_output()
    output.close_others()
    


