#!/usr/bin/python
# -*- coding: utf-8 -*-
"""EnneadCity data layer.

Rewritten 2026-08-21: the office L: shared drive is confirmed gone (not just
offline) -- there is no shared JSON file or shared .3dm folder to fall back to
anymore. This module's ENTIRE job now is: be an HTTP client to the
EnneadTab-EnneadCity cloud API, download/cache files locally, and otherwise
look EXACTLY like the old file to its callers (ennead_city_gui.py,
export_from_masterplan.py).

Every public function below keeps the SAME return shape the old local-file
version had: a local filesystem path (or list of paths) whose basename minus
".3dm" IS the plot id. Callers do sc.doc.Open(...)/-WorkSession Attach "..."
against that local path unchanged; all cloud complexity (API calls, auth,
caching, staleness checks) lives in here.
"""

import os
import sys
import json
import time

# Get the correct path to the lib folder
current_dir = os.path.dirname(os.path.realpath(__file__))
lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))), "lib")
sys.path.append(lib_path)

from EnneadTab import ENVIRONMENT, USER, NOTIFICATION, ERROR_HANDLE, AUTH
from EnneadTab.DEPOT import _transport


API_BASE = "https://enneadtab.com/ennead-city/api"

# api routes return proxy paths like "/api/plots/:id/file" that are relative to
# the APP ROOT (which itself sits behind Home's "/ennead-city" basePath, see
# EnneadTab-EnneadCity/web/next.config.ts), NOT relative to API_BASE (which
# already ends in "/api"). Concatenating API_BASE + fileUrl would double the
# "/api" segment -- verified against the literal string
# web/app/api/plots/[id]/download/route.ts returns. APP_ROOT strips the
# trailing "/api" so APP_ROOT + fileUrl reconstructs the correct absolute URL.
if API_BASE.endswith("/api"):
    APP_ROOT = API_BASE[:-len("/api")]
else:
    APP_ROOT = API_BASE

# Reuse the existing local-scratch convention (the old offline-L:-fallback
# sandbox) rather than inventing a new one -- per
# EnneadTab-EnneadCity/docs/plans/cloud-to-local-bridge.md.
MAIN_FOLDER = os.path.join(ENVIRONMENT.DUMP_FOLDER, "EnneadCity")
PLOT_FILES_FOLDER = os.path.join(MAIN_FOLDER, "plots")
CITY_BACKGROUND_FILES = [os.path.join(MAIN_FOLDER, "City_Background_Road.3dm")]

# Sentinel id the web app uses for the shared background/master file row (see
# web/app/api/background/route.ts's own comment -- there is no dedicated
# background table, it reuses the plots table under this well-known id).
# GET /api/background returns a proxy path (fileUrl), same shape as
# GET /api/plots/:id/download -- no special-casing needed here, the ordinary
# _download_to_cache path handles it like any other id.
_BACKGROUND_PLOT_ID = "__background__"

# Cached files are scratch, not authoritative -- mirror the existing DEBUG/
# 7-day age-based cleanup convention used elsewhere in EnneadTab-OS.
_CACHE_MAX_AGE_DAYS = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _auth_token():
    """Return a valid Bearer token, or None.

    On None, kicks off the non-blocking browser sign-in flow and tells the
    user to retry -- mirrors the AUTH.get_token()/AUTH.request_auth() pattern
    used by every other Rhino/Revit AI dialog in this codebase.
    """
    token = AUTH.get_token()
    if token:
        return token
    try:
        AUTH.request_auth()
    except Exception:
        pass
    try:
        NOTIFICATION.messenger(
            main_text="Please sign in to EnneadTab (a browser window just "
                      "opened). Try the action again after sign-in completes."
        )
    except Exception:
        pass
    return None


def _report_error(message, func_name):
    """The ONE place all API/network failures get surfaced. Every public
    function below routes failures through this rather than printing or
    swallowing, so city_utility.py has already reported the real cause to
    ErrorDump before the caller's generic except Exception as e: even sees it.
    """
    try:
        ERROR_HANDLE.send_error_to_error_dump(message, func_name, USER.USER_NAME)
    except Exception:
        pass
    try:
        NOTIFICATION.messenger(main_text=message)
    except Exception:
        pass


def _decode_token_email(token):
    """Best-effort decode of the 'email' field from a desktop token payload.

    Token format: base64url(JSON {email,name,iat,exp}).base64url(sig) -- same
    shape AUTH.py's _decode_token_expiry decodes for "exp". The server derives
    the ACTUAL claim owner from this same field, so comparing by it (rather
    than USER.USER_NAME) matches the server's notion of identity.

    Returns None if the token cannot be decoded. Known limitation: callers
    then fall back to comparing by USER.USER_NAME, which is a Windows display
    name and is NOT guaranteed to match the email string the server stores as
    claimed_by.
    """
    try:
        import base64
        payload_b64 = token.split(".")[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_str = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_str)
        return payload.get("email")
    except Exception:
        return None


def _body_to_text(body):
    if body is None:
        return None
    if hasattr(body, "decode"):
        try:
            return body.decode("utf-8")
        except Exception:
            return body
    return body


def _fetch_plots_list_or_fail(token):
    """GET /api/plots -> (plots, ok). ok=False lets a caller (e.g.
    download_all_required_files) tell a genuinely-empty plot list apart from a
    failed fetch -- an empty list on a failed fetch must NOT read as "nothing
    to attach", it must read as "the whole all-or-nothing action can't proceed".
    Routes the real failure cause through _report_error either way."""
    url = API_BASE + "/plots"
    result = _transport.get(url, token=token)
    if result.transport_failed:
        _report_error("Cannot reach EnneadCity server (offline?): {}".format(result.error),
                       "_fetch_plots_list_or_fail")
        return [], False
    if not result.ok():
        _report_error("Failed to list plots (HTTP {}): {}".format(result.status, result.error),
                       "_fetch_plots_list_or_fail")
        return [], False
    try:
        data = json.loads(_body_to_text(result.body))
    except Exception as e:
        _report_error("Failed to parse plots list response: {}".format(e), "_fetch_plots_list_or_fail")
        return [], False
    return data.get("plots", []), True


def _fetch_plots_list(token):
    """GET /api/plots -> list of plot dicts (each has at least id, status,
    claimed_by, blob_url). Returns [] on any failure, after routing the real
    cause through _report_error. Callers that need to distinguish "genuinely
    empty" from "fetch failed" should use _fetch_plots_list_or_fail instead."""
    plots, _ok = _fetch_plots_list_or_fail(token)
    return plots


def _ensure_cache_dirs():
    for folder in (MAIN_FOLDER, PLOT_FILES_FOLDER):
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except OSError:
                pass  # already exists / permission race


def _plot_cache_path(plot_id):
    return os.path.join(PLOT_FILES_FOLDER, "{}.3dm".format(plot_id))


def _download_to_cache_detailed(meta_url, cache_path, func_name, token):
    """Download-before-open bridge (cloud-to-local-bridge.md).

    Fetches {fileUrl, contentHash} from meta_url (both /api/plots/:id/download
    and /api/background return this same shape -- no per-route special-casing
    needed here), compares against a local <cache_path>.hash sidecar, and only
    downloads when missing/mismatched.

    Returns (cache_path, "ok") on success. On failure returns (None, reason)
    where reason is "not_found" (server genuinely has nothing uploaded for
    this id -- not a transport/auth error) or a short string describing what
    actually went wrong (network/auth/http/parse), for callers that need to
    report the real cause (download_all_required_files' all-or-nothing check).
    Every failure path also routes through _report_error so it reaches
    ErrorDump regardless of whether the caller inspects the reason.
    """
    result = _transport.get(meta_url, token=token)
    if result.transport_failed:
        reason = "network error: {}".format(result.error)
        _report_error("Cannot reach EnneadCity server for {}: {}".format(
            os.path.basename(cache_path), result.error), func_name)
        return None, reason
    if result.status == 404:
        # Nothing uploaded yet for this id -- not a transport/auth error, just
        # nothing to fetch. Whether that's fatal for the CALLER's purpose is
        # the caller's call (e.g. all-or-nothing WorkSession attach treats it
        # as fatal; a single "is anything claimed" check might not).
        return None, "not_found"
    if not result.ok():
        reason = "HTTP {}".format(result.status)
        _report_error("Failed to fetch download metadata for {} ({})".format(
            os.path.basename(cache_path), reason), func_name)
        return None, reason

    try:
        meta = json.loads(_body_to_text(result.body))
    except Exception as e:
        reason = "could not parse server response: {}".format(e)
        _report_error("Failed to parse download metadata for {}: {}".format(
            os.path.basename(cache_path), e), func_name)
        return None, reason

    content_hash = meta.get("contentHash")
    file_url = meta.get("fileUrl")
    if not file_url:
        # Same "nothing uploaded yet" case as a 404 -- GET /api/background
        # returns exactly this shape (200 + fileUrl: null), never a 404, when
        # the background row doesn't exist. That IS today's real live state
        # (no background file has been migrated in yet), so this must read as
        # "not_found" (not an error) rather than a generic server-shape
        # complaint -- otherwise download_all_required_files reports a
        # confusing "server has no file reference" instead of the accurate
        # "not yet uploaded to the server" for the one case guaranteed to
        # happen right now. Not an error, so no _report_error call here,
        # matching the 404 branch above.
        return None, "not_found"

    hash_sidecar = cache_path + ".hash"
    cached_hash = None
    if os.path.exists(hash_sidecar):
        try:
            with open(hash_sidecar, "r") as f:
                cached_hash = f.read().strip()
        except Exception:
            cached_hash = None

    if os.path.exists(cache_path) and content_hash and cached_hash == content_hash:
        return cache_path, "ok"  # already up to date

    _ensure_cache_dirs()
    full_url = APP_ROOT + file_url
    dl_result = _transport.download(full_url, cache_path, token=token)
    if not dl_result.ok():
        reason = "HTTP {}".format(dl_result.status)
        _report_error("Failed to download {} ({}): {}".format(
            os.path.basename(cache_path), reason, dl_result.error), func_name)
        return None, reason

    if content_hash:
        try:
            with open(hash_sidecar, "w") as f:
                f.write(content_hash)
        except Exception:
            pass

    return cache_path, "ok"


def _download_to_cache(meta_url, cache_path, func_name, token):
    """Thin wrapper over _download_to_cache_detailed for callers that only
    need the path/None shape (e.g. _download_plot) and don't need to
    distinguish WHY a download didn't happen."""
    path, _reason = _download_to_cache_detailed(meta_url, cache_path, func_name, token)
    return path


def _download_plot(plot_id, token):
    meta_url = API_BASE + "/plots/{}/download".format(plot_id)
    return _download_to_cache(meta_url, _plot_cache_path(plot_id), "_download_plot", token)


# ---------------------------------------------------------------------------
# Public API -- SAME shapes as the old local-file version
# ---------------------------------------------------------------------------

def cleanup_stale_cache():
    """Sweep PLOT_FILES_FOLDER + MAIN_FOLDER for cache files older than
    _CACHE_MAX_AGE_DAYS. Best-effort, never raises -- call once per GUI launch.
    Cached files are scratch; they simply re-download on next use if still
    needed."""
    try:
        cutoff = time.time() - _CACHE_MAX_AGE_DAYS * 24 * 3600
        for folder in (MAIN_FOLDER, PLOT_FILES_FOLDER):
            if not os.path.exists(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except Exception:
                    pass
    except Exception:
        pass


def download_background_files():
    """Ensure every path in CITY_BACKGROUND_FILES is present locally.

    New helper (not in the original file, but needed): call this before
    iterating CITY_BACKGROUND_FILES so the background file actually gets
    downloaded first -- today (before this fix) the caller just silently
    skipped a missing file via os.path.exists(). Returns True only if every
    background file downloaded successfully.

    NOTE: OnLoadAllPlots itself no longer calls this -- it uses
    download_all_required_files() instead, which folds the background files
    and every uploaded plot into a single all-or-nothing pass with per-file
    failure reasons. This function is kept for any other/future caller that
    only cares about the background files.
    """
    token = _auth_token()
    if not token:
        return False

    ok = True
    meta_url = API_BASE + "/background"
    for cache_path in CITY_BACKGROUND_FILES:
        result = _download_to_cache(meta_url, cache_path, "download_background_files", token)
        if result is None:
            ok = False
    return ok


def download_all_required_files():
    """Attempt to download EVERY file `-WorkSession Attach` needs: every plot
    that has an uploaded .3dm (matches the original get_all_plot_files()
    semantics -- regardless of claim status), plus every shared background
    file. Per docs/plans/cloud-to-local-bridge.md's all-or-nothing invariant,
    this function only COLLECTS outcomes -- it never decides what to do about
    a partial result. The caller (OnLoadAllPlots) MUST abort the whole action
    if `failures` is non-empty, rather than attaching whatever subset
    succeeded.

    Returns (plot_paths, background_paths, failures):
      - plot_paths / background_paths: local cache paths that downloaded
        successfully.
      - failures: list of (label, reason) tuples for anything that did NOT
        download, so the caller can report exactly what failed and why
        (network vs. auth vs. 404-not-uploaded vs. server HTTP error).
    """
    token = _auth_token()
    if not token:
        return [], [], [("sign-in", "Not signed in to EnneadTab (a browser sign-in window should have opened -- retry after signing in)")]

    failures = []

    background_paths = []
    for cache_path in CITY_BACKGROUND_FILES:
        path, status = _download_to_cache_detailed(
            API_BASE + "/background", cache_path, "download_all_required_files", token)
        if path:
            background_paths.append(path)
        elif status == "not_found":
            failures.append((os.path.basename(cache_path), "not yet uploaded to the server"))
        else:
            failures.append((os.path.basename(cache_path), status))

    plots, plots_ok = _fetch_plots_list_or_fail(token)
    if not plots_ok:
        failures.append(("plot list", "could not fetch the plot list from the server"))

    plot_paths = []
    for p in plots:
        if p.get("id") == _BACKGROUND_PLOT_ID:
            continue  # sentinel row for the shared background file, not a plot
        if not p.get("blob_url"):
            continue  # nothing uploaded for this plot yet -- not required
        meta_url = API_BASE + "/plots/{}/download".format(p["id"])
        path, status = _download_to_cache_detailed(
            meta_url, _plot_cache_path(p["id"]), "download_all_required_files", token)
        if path:
            plot_paths.append(path)
        elif status == "not_found":
            # blob_url was set moments ago but the server now says otherwise
            # (race with a concurrent release/re-upload) -- still a hard
            # failure for an all-or-nothing attach.
            failures.append((p["id"], "server reports no file (race with a concurrent change?)"))
        else:
            failures.append((p["id"], status))

    return plot_paths, background_paths, failures


def get_current_user_plot_file():
    """Return the local cache path of the plot claimed by the current user, or
    False if none / on failure."""
    token = _auth_token()
    if not token:
        return False

    plots = _fetch_plots_list(token)
    my_email = _decode_token_email(token)

    my_plot = None
    for p in plots:
        claimed_by = p.get("claimed_by")
        if not claimed_by:
            continue
        if my_email:
            if claimed_by == my_email:
                my_plot = p
                break
        else:
            # Known limitation: USER.USER_NAME is a Windows display name, not
            # guaranteed to match the email string the server stores.
            if claimed_by == USER.USER_NAME:
                my_plot = p
                break

    if not my_plot:
        return False

    cache_path = _download_plot(my_plot["id"], token)
    if not cache_path:
        return False
    return cache_path


def set_current_user_plot_file(plot_file):
    """Claim the plot whose id is plot_file's basename (minus .3dm), then
    ensure it is downloaded to the local cache path plot_file. Returns True on
    success, False on failure (after _report_error)."""
    plot_id = os.path.splitext(os.path.basename(plot_file))[0]
    token = _auth_token()
    if not token:
        return False

    url = API_BASE + "/plots/{}/claim".format(plot_id)
    result = _transport.post_json(url, "{}", token=token)
    if result.transport_failed:
        _report_error("Cannot reach EnneadCity server to claim plot {}: {}".format(
            plot_id, result.error), "set_current_user_plot_file")
        return False
    if result.status == 409:
        _report_error("Plot {} was already claimed by someone else. Refresh and try a different plot.".format(
            plot_id), "set_current_user_plot_file")
        return False
    if not result.ok():
        _report_error("Failed to claim plot {} (HTTP {})".format(plot_id, result.status),
                       "set_current_user_plot_file")
        return False

    cache_path = _download_plot(plot_id, token)
    if not cache_path:
        return False
    return True


def release_current_user_plot_file(plot_id):
    """New: release the calling identity's claim on plot_id. Did not exist in
    the original file -- the API supports release but the old local-JSON GUI
    never had a corresponding action (there was no Release button either).
    Returns True on success, False on failure (after _report_error)."""
    token = _auth_token()
    if not token:
        return False

    url = API_BASE + "/plots/{}/release".format(plot_id)
    result = _transport.post_json(url, "{}", token=token)
    if result.transport_failed:
        _report_error("Cannot reach EnneadCity server to release plot {}: {}".format(
            plot_id, result.error), "release_current_user_plot_file")
        return False
    if result.status == 403:
        _report_error("Cannot release plot {} -- it is not claimed by you.".format(plot_id),
                       "release_current_user_plot_file")
        return False
    if not result.ok():
        _report_error("Failed to release plot {} (HTTP {})".format(plot_id, result.status),
                       "release_current_user_plot_file")
        return False
    return True


def get_all_plot_files():
    """List every plot that has an uploaded file, ensure each is downloaded to
    the local cache, and return the list of local cache paths. Only plots with
    blob_url set server-side are downloaded -- a plot with nothing uploaded
    yet is skipped, not treated as an error."""
    token = _auth_token()
    if not token:
        return []

    plots = _fetch_plots_list(token)
    paths = []
    for p in plots:
        if p.get("id") == _BACKGROUND_PLOT_ID:
            continue  # sentinel row for the shared background file, not a plot
        if not p.get("blob_url"):
            continue
        cache_path = _download_plot(p["id"], token)
        if cache_path:
            paths.append(cache_path)
    return paths


def get_empty_plot_files():
    """Same shape as the original: list of local cache paths for plots that
    are NOT currently claimed."""
    token = _auth_token()
    if not token:
        return []

    plots = _fetch_plots_list(token)
    paths = []
    for p in plots:
        if p.get("id") == _BACKGROUND_PLOT_ID:
            continue
        if p.get("status") == "claimed":
            continue
        if not p.get("blob_url"):
            continue
        cache_path = _download_plot(p["id"], token)
        if cache_path:
            paths.append(cache_path)
    return paths


def get_occupied_plot_files():
    """Same shape as the original: list of local cache paths for plots that
    ARE currently claimed."""
    token = _auth_token()
    if not token:
        return []

    plots = _fetch_plots_list(token)
    paths = []
    for p in plots:
        if p.get("id") == _BACKGROUND_PLOT_ID:
            continue
        if p.get("status") != "claimed":
            continue
        if not p.get("blob_url"):
            continue
        cache_path = _download_plot(p["id"], token)
        if cache_path:
            paths.append(cache_path)
    return paths


def get_occupied_plot_names():
    """Used only by export_from_masterplan.py -- plain plot-name strings (no
    path, no extension), no local file/download needed."""
    token = _auth_token()
    if not token:
        return []

    plots = _fetch_plots_list(token)
    return [p["id"] for p in plots if p.get("status") == "claimed"]
