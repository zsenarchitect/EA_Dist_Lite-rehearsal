# -*- coding: utf-8 -*-
"""Depot-unreachable alarm -- loud once, then quiet.

A straight port of ENVIRONMENT.announce_shared_root_status (plan 5.3): fire at
most once per process, and at most once per 24h per machine (a marker file under
the cache dir plays the DuckLock role). Lazy, guarded imports of NOTIFICATION so
this never drags a UI dependency into ENVIRONMENT's import graph, and it NEVER
raises -- an alarm that crashes the button is worse than no alarm.

Both ASSET (offline read) and STATE (offline write, Commit 3) call this.

Every call also posts a silent, throttled ErrorDump report (via
ERROR_HANDLE.report_infra_warning_to_error_dump_async) so a fleet-wide depot
outage is visible to developers even though the popup itself is deliberately
quiet after the first hit (#5013). The existing per-process / 24h gate above
already caps how often that report fires, so no separate throttle_key is
needed on the ErrorDump call.
"""

import os
import time

from EnneadTab import ENVIRONMENT

_ANNOUNCED_THIS_PROCESS = False
_MARKER_NAME = ".depot_unreachable_alarm"
_QUIET_SECONDS = 24 * 60 * 60

# Server error codes (DEPOT.ROUTES.ERR_UNAUTHORIZED / ERR_FORBIDDEN) that mean
# "your sign-in expired", not "the depot is down". Token expiry on the ~30-day
# AUTH.get_token() cache is routine (every user hits it roughly monthly) and
# needs its own message rather than the generic outage text (#5013).
_AUTH_ERROR_CODES = ("unauthorized", "forbidden")


def _marker_path():
    return os.path.join(ENVIRONMENT.DEPOT_CACHE_FOLDER, _MARKER_NAME)


def _within_quiet_window():
    """True if the 24h marker exists and is fresh (so we should stay quiet)."""
    path = _marker_path()
    try:
        if not os.path.exists(path):
            return False
        return (time.time() - os.path.getmtime(path)) < _QUIET_SECONDS
    except Exception:
        return False


def _touch_marker():
    path = _marker_path()
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d)
        f = open(path, "w")
        try:
            f.write(str(time.time()))
        finally:
            f.close()
    except Exception:
        pass


def announce_depot_unreachable(context="", error_code=None):
    """Notify the user once that the depot is unreachable and work is offline.

    Pass error_code with the server's {"error": "<code>"} value (see
    DEPOT.ROUTES.ERR_*) when the caller has one, so an expired sign-in
    (unauthorized/forbidden) gets its own message instead of the generic
    "could not reach the shared depot" text -- the two conditions look
    identical to a non-technical user but have completely different fixes
    ("sign in again" vs. "wait for the network").

    Idempotent per process and rate-limited to once per 24h per machine.
    Returns True if it actually announced this call, else False. Never
    raises."""
    global _ANNOUNCED_THIS_PROCESS
    if _ANNOUNCED_THIS_PROCESS:
        return False
    _ANNOUNCED_THIS_PROCESS = True
    if _within_quiet_window():
        return False
    _touch_marker()
    if error_code in _AUTH_ERROR_CODES:
        msg = ("EnneadTab's sign-in with the shared depot (enneadtab.com) has "
               "expired. Please sign in again.")
    elif error_code == "budget_exceeded":
        msg = ("EnneadTab did not download a shared asset folder because it is "
               "larger than the local size budget allows.")
    else:
        msg = ("EnneadTab could not reach the shared depot (enneadtab.com). "
               "Working from the local cache; new shared data may be unavailable "
               "until the connection returns.")
    if context:
        msg = msg + " [" + str(context) + "]"
    try:
        from EnneadTab import NOTIFICATION
        NOTIFICATION.messenger(msg)
    except Exception:
        pass
    try:
        from EnneadTab import ERROR_HANDLE
        ERROR_HANDLE.print_note(msg)
        ERROR_HANDLE.report_infra_warning_to_error_dump_async(
            msg, "DEPOT._alarm.announce_depot_unreachable")
    except Exception:
        pass
    return True
