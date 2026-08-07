# -*- coding: utf-8 -*-
"""What the user has actually done in THIS host session.

Feeds the sync-time card (SYNC_SUMMARY). Shared verbatim by Revit and Rhino, so
there is no per-framework copy that could drift -- the same rule that keeps
RECAP.py honest.

TWO CONSTRAINTS SHAPE EVERY FUNCTION HERE
-----------------------------------------
1. **Nothing expensive on the UI thread.** The card is built microseconds before
   Revit freezes for a sync. The log read is scoped to today's keys; there is no
   full-history parse, no element collection, no network.

2. **A metric we cannot compute returns None, never 0.** Zero is a claim ("you
   touched no views"); None is an absence, and SYNC_SUMMARY omits the line
   entirely. Silently rendering a failed lookup as 0 would put a false, mildly
   insulting number in front of the user -- the exact failure the recap package
   was built to avoid.

WHERE THE COUNTERS LIVE
-----------------------
pyRevit runs each hook in its OWN IronPython engine, so a module-level set
populated by the startup script is simply not there when the sync hook reads it.
Counters therefore go in a process-scoped store: pyRevit env vars in Revit (the
mechanism TIME.get_revit_uptime's APP_UPTIME and REVIT_VIEW's
LAST_VIEW_BEFORE_SYNC already rely on), scriptcontext.sticky in Rhino, and a
plain dict elsewhere. `store_get`/`store_set` are the only host-aware code in
this file; every other function is identical for both hosts. They are public
because SYNC_SUMMARY needs the same process-scoped store for its own keys.

IronPython 2.7 SAFE. No f-strings, no type hints, no pathlib.
"""

import time

try:
    from EnneadTab import ENVIRONMENT, ERROR_HANDLE, TIME, USER
except Exception:  # pragma: no cover - bare-import fallback for older loaders
    import ENVIRONMENT  # pyright: ignore
    import ERROR_HANDLE  # pyright: ignore
    import TIME  # pyright: ignore
    import USER  # pyright: ignore


LOG_KEY_FORMAT = "%Y-%m-%d_%H-%M-%S"

KEY_VIEWS = "EA_SESSION_VIEWS"
KEY_SESSION_START = "EA_SESSION_START"

# Fallback store for CPython / unit tests, where neither host store exists.
_MEMORY_STORE = {}

# Views are held as a comma-joined id string rather than a list: pyRevit env vars
# round-trip scalars reliably across engines, and a 200-view session is still a
# short string.
_VIEW_SEPARATOR = ","


# --------------------------------------------------------------- host store

def store_set(key, value):
    try:
        if ENVIRONMENT.IS_REVIT_ENVIRONMENT:
            from pyrevit.coreutils import envvars
            envvars.set_pyrevit_env_var(key, value)
            return True
        if ENVIRONMENT.IS_RHINO_ENVIRONMENT:
            import scriptcontext  # pyright: ignore
            scriptcontext.sticky[key] = value
            return True
    except Exception:
        pass
    _MEMORY_STORE[key] = value
    return True


def store_get(key, default=None):
    try:
        if ENVIRONMENT.IS_REVIT_ENVIRONMENT:
            from pyrevit.coreutils import envvars
            value = envvars.get_pyrevit_env_var(key)
            return default if value is None else value
        if ENVIRONMENT.IS_RHINO_ENVIRONMENT:
            import scriptcontext  # pyright: ignore
            return scriptcontext.sticky.get(key, default)
    except Exception:
        pass
    return _MEMORY_STORE.get(key, default)


# --------------------------------------------------------------- session clock

def mark_session_start():
    """Stamp the session's start. Idempotent -- a second call is ignored.

    Called from startup. Revit also has TIME.get_revit_uptime, but Rhino has no
    equivalent, so both hosts stamp this and `get_session_seconds` prefers it.
    """
    if store_get(KEY_SESSION_START) is None:
        store_set(KEY_SESSION_START, time.time())
    return True


def get_session_seconds():
    """How long this host session has been open, or None."""
    started = store_get(KEY_SESSION_START)
    if started is not None:
        try:
            elapsed = time.time() - float(started)
            if elapsed >= 0:
                return elapsed
        except Exception:
            pass
    # Revit fallback: pyRevit stamps APP_UPTIME even if our startup never ran.
    try:
        if ENVIRONMENT.IS_REVIT_ENVIRONMENT:
            uptime = TIME.get_revit_uptime(return_number=True)
            if isinstance(uptime, (int, float)) and uptime >= 0:
                return uptime
    except Exception:
        pass
    return None


# --------------------------------------------------------------- views

def note_view(view_id):
    """Record one view as touched. Cheap enough for a ViewActivated handler.

    Deduped by id, so flipping back and forth between two views counts two, not
    twenty.
    """
    if view_id is None:
        return False
    token = str(view_id)
    if _VIEW_SEPARATOR in token:
        return False
    raw = store_get(KEY_VIEWS, "")
    seen = str(raw).split(_VIEW_SEPARATOR) if raw else []
    if token in seen:
        return False
    seen.append(token)
    store_set(KEY_VIEWS, _VIEW_SEPARATOR.join(seen))
    return True


def get_views_touched():
    """Distinct views touched this session, or None if nothing was recorded.

    None rather than 0 when the counter was never armed: an unregistered handler
    and a genuinely idle session are different facts, and only the second one
    deserves to be shown.
    """
    raw = store_get(KEY_VIEWS)
    if raw is None:
        return None
    text = str(raw)
    if not text:
        return None
    return len([x for x in text.split(_VIEW_SEPARATOR) if x])


# --------------------------------------------------------------- tools

def _parse_log_key(key):
    try:
        return time.mktime(time.strptime(str(key), LOG_KEY_FORMAT))
    except Exception:
        return None


def get_tools_used(since_seconds=None):
    """(total_runs, distinct_names) for this session, or (None, None).

    Reads the same `log_<user>` file LOG.log writes on every instrumented button
    and parses keys with the same format recap_stats.parse_records uses. Records
    older than the session start are skipped, so a long-running machine does not
    inflate today's number with yesterday's work.
    """
    try:
        from EnneadTab import DATA_FILE, LOG
        data = DATA_FILE.get_data(LOG.LOG_FILE_NAME)
    except Exception:
        return None, None
    if not isinstance(data, dict) or not data:
        return None, None

    if since_seconds is None:
        since_seconds = get_session_seconds()
    cutoff = None
    if since_seconds is not None:
        cutoff = time.time() - since_seconds

    total = 0
    names = set()
    for key, record in data.items():
        if not isinstance(record, dict):
            continue
        if cutoff is not None:
            stamp = _parse_log_key(key)
            if stamp is None or stamp < cutoff:
                continue
        total += 1
        name = record.get("function_name")
        if name:
            names.add(name)

    if total == 0:
        return None, None
    return total, len(names)


# --------------------------------------------------------------- warnings

def count_warnings(doc):
    """How many warnings this document currently has, or None.

    A plain document query, not an element collection -- cheap enough for the
    doc-opened hook, which already runs REVIT_HISTORY.record_warning right
    beside it (that one walks the same warnings AND does a worksharing-tooltip
    lookup per failing element, so it costs far more than this).

    Deliberately not derived from REVIT_HISTORY's stored per-day counts: those
    ACCUMULATE across repeated opens on the same day, so reopening a model would
    read back double.
    """
    if doc is None:
        return None
    try:
        return len(list(doc.GetWarnings()))
    except Exception:
        return None


def note_warning_baseline(doc, count=None):
    """Record the current warning count as the baseline to measure against.

    Called from doc-opened so the FIRST sync of a session can report cleared
    warnings. Without it the baseline is only ever written by
    get_warnings_cleared itself, which means the first sync has nothing to
    compare against and always returns None.
    """
    if doc is None:
        return False
    if count is None:
        count = count_warnings(doc)
    if count is None:
        return False
    _set_warning_baseline(doc, count)
    return True


def get_warnings_cleared(doc):
    """How many warnings this doc lost since we last looked, or None.

    Only a REDUCTION is ever returned. An increase resolves to None so the card
    physically cannot scold anyone -- the positivity rule is enforced at the
    source, not left to the copy layer to remember.

    The current count is read from the live document; the baseline comes from
    the process-scoped store (see the module docstring), written either by
    note_warning_baseline at document-open or by the previous call to this
    function.
    """
    if doc is None:
        return None
    current = count_warnings(doc)
    if current is None:
        return None

    previous = _get_warning_baseline(doc)
    _set_warning_baseline(doc, current)

    if previous is None:
        return None
    cleared = previous - current
    return cleared if cleared > 0 else None


def _baseline_key(doc):
    try:
        return "EA_WARNING_BASELINE_{}".format(doc.Title)
    except Exception:
        return None


def _get_warning_baseline(doc):
    key = _baseline_key(doc)
    if key is None:
        return None
    value = store_get(key)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _set_warning_baseline(doc, count):
    key = _baseline_key(doc)
    if key is not None:
        store_set(key, int(count))


# --------------------------------------------------------------- snapshot

@ERROR_HANDLE.try_catch_error(is_pass=True)
def snapshot(doc=None):
    """Everything the card might want, gathered once.

    Each metric is collected independently so one failure cannot blank the rest.
    Keys whose value is None are still present -- SYNC_SUMMARY drops them, and
    keeping them here makes `peek()` show which lookup came back empty.
    """
    total_runs, distinct_tools = get_tools_used()
    return {
        "session_seconds": get_session_seconds(),
        "views_touched": get_views_touched(),
        "tool_runs": total_runs,
        "distinct_tools": distinct_tools,
        "warnings_cleared": get_warnings_cleared(doc),
        "user": _safe_user(),
    }


def _safe_user():
    try:
        return USER.USER_NAME
    except Exception:
        return None


def peek():
    """Diagnostic: the raw counters, with no document involved."""
    total_runs, distinct_tools = get_tools_used()
    return {
        "session_seconds": get_session_seconds(),
        "views_touched": get_views_touched(),
        "tool_runs": total_runs,
        "distinct_tools": distinct_tools,
    }


def unit_test():
    mark_session_start()
    note_view("101")
    note_view("102")
    note_view("101")
    assert get_views_touched() == 2, "duplicate view ids must not double count"
    print("SESSION_STATS peek: {}".format(peek()))


if __name__ == "__main__":
    unit_test()
