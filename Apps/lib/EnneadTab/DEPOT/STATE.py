# -*- coding: utf-8 -*-
"""Depot shared state -- read/write/update JSON docs with rev checks and an
offline outbox.

Replaces the read-modify-write-a-file pattern the retired shared dump used
(plan 4, the 22 FOLDER.get_shared_dump_folder_file sites and the two DATA_FILE
shared-dump bodies). State loss is always loud: an offline write queues to an
outbox and returns False, and the alarm fires (plan 5.3).

Degradation (plan 5.3):
    online       -> GET refreshes the cache; PUT bumps rev
    offline read -> cached data with "_depot_stale": True, or default + alarm
    offline write-> outbox + alarm -> return False

C15: a 404 on a SINGLE state key is a real not-found (return default), NOT
offline -- only a transport failure (refused/DNS/timeout) is offline here.

Rev conflicts: PUT sends the last-known rev; a 409 returns the winning document,
so update_state re-applies its mutator to that document and PUTs once more
without a second GET (plan 6).

Fully-qualified imports; IronPython 2.7 + CPython safe. STATE keeps its own tiny
doc cache under the depot cache dir (state files are small; no LRU needed).
"""

import os
import json
import time

from EnneadTab import ENVIRONMENT
from EnneadTab.DEPOT import ROUTES
from EnneadTab.DEPOT import _transport
from EnneadTab.DEPOT import _cache
from EnneadTab.DEPOT import _alarm


def _get_token():
    try:
        from EnneadTab import AUTH
        return AUTH.get_token()
    except Exception:
        return None


# --- local doc cache --------------------------------------------------------

def _doc_path(key):
    return _cache.local_path("state/" + key + ".json")


def _read_cached_doc(key):
    """Return the cached {rev, data} doc for a key, or None."""
    path = _doc_path(key)
    if not os.path.exists(path):
        return None
    try:
        f = open(path, "r")
        try:
            data = json.load(f)
        finally:
            f.close()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_cached_doc(key, doc):
    path = _doc_path(key)
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    tmp = path + ".part"
    try:
        f = open(tmp, "w")
        try:
            json.dump(doc, f)
        finally:
            f.close()
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _cached_rev(key):
    doc = _read_cached_doc(key)
    if doc:
        return doc.get("rev")
    return None


def _parse(body):
    if body is None:
        return None
    try:
        text = body.decode("utf-8") if hasattr(body, "decode") else body
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _mark_stale(data):
    """Return data annotated as stale, without mutating the caller's object."""
    if isinstance(data, dict):
        out = dict(data)
        out["_depot_stale"] = True
        return out
    return data


def _inm(rev):
    """If-None-Match header value: the rev, quoted per the contract."""
    if not rev:
        return None
    return '"' + str(rev) + '"'


def _error_code(result):
    """Extract the server's {"error": "<code>"} (see ROUTES.ERR_*) from a
    rejected response body, e.g. ROUTES.ERR_UNAUTHORIZED. None when the body
    doesn't parse or there is none (as for a transport failure) -- callers
    thread this into _alarm.announce_depot_unreachable so an expired sign-in
    doesn't get reported as a depot outage (#5013)."""
    doc = _parse(result.body)
    if isinstance(doc, dict):
        return doc.get("error")
    return None


# --- read -------------------------------------------------------------------

def read_state(key, default=None, token=None):
    """Return the `data` for a state key. On a fresh 304 or a 200, returns the
    server copy (and refreshes the cache). Offline: returns the cached copy
    annotated with "_depot_stale": True, or `default` (and alarms once) if there
    is no cache. A 404 (key genuinely absent) returns `default`."""
    if token is None:
        token = _get_token()
    cached = _read_cached_doc(key)
    result = _transport.get(ROUTES.state_url(key), token=token, if_none_match=_inm(_cached_rev(key)))

    if result.not_modified() and cached is not None:
        return cached.get("data", default)
    if result.ok():
        doc = _parse(result.body)
        if doc is not None:
            _write_cached_doc(key, {"rev": doc.get("rev"), "data": doc.get("data")})
            return doc.get("data", default)
    if result.status == 404:
        return default   # C15: single-key 404 is not-found, not offline
    if result.transport_failed:
        if cached is not None:
            return _mark_stale(cached.get("data", default))
        _alarm.announce_depot_unreachable("state read:{0}".format(key))
        return default
    # Other HTTP error (401/5xx): serve cache if present, else default.
    if cached is not None:
        return cached.get("data", default)
    return default


def list_state(prefix="", token=None):
    """List state keys under a prefix (replaces os.listdir(SHARED_DUMP_FOLDER),
    e.g. REVIT_PROJ_DATA's project-data enumeration). Returns a list of keys, or
    [] when offline or on error -- the caller degrades to "no shared entries"."""
    if token is None:
        token = _get_token()
    result = _transport.get(ROUTES.state_list_url(prefix), token=token)
    if result.ok():
        obj = _parse(result.body) or {}
        keys = obj.get("keys")
        if isinstance(keys, list):
            return keys
        items = obj.get("items")
        if isinstance(items, list):
            return [it.get("key") for it in items if isinstance(it, dict) and it.get("key")]
    return []


# --- write ------------------------------------------------------------------

def write_state(key, data, token=None):
    """Overwrite a state key (last-writer-wins). Returns True on success. Offline
    -> queue to the outbox, alarm, return False. A 409 rev conflict retries once
    against the winning rev."""
    if token is None:
        token = _get_token()
    body = json.dumps({"rev": _cached_rev(key), "data": data})
    result = _transport.put_json(ROUTES.state_url(key), body, token=token)

    if result.ok():
        _cache_new_rev(key, result.body, data)
        return True
    if result.status == 409:
        winning = _parse(result.body)
        winrev = (winning or {}).get("rev")
        body2 = json.dumps({"rev": winrev, "data": data})
        r2 = _transport.put_json(ROUTES.state_url(key), body2, token=token)
        if r2.ok():
            _cache_new_rev(key, r2.body, data)
            return True
    if result.transport_failed:
        _queue_outbox(key, data)
        _alarm.announce_depot_unreachable("state write:{0}".format(key))
        return False
    # Server rejected the write (auth / 5xx): loud, but do NOT outbox-loop a
    # request the server actively refused. Thread the error code through so an
    # expired token (401) gets "please sign in again" instead of the generic
    # "could not reach the shared depot" text (#5013).
    _alarm.announce_depot_unreachable(
        "state write failed:{0}".format(key), error_code=_error_code(result))
    return False


def update_state(key, mutator, default=None, token=None):
    """Read-modify-write: apply mutator(data) -> new_data and PUT with a rev
    check. On a 409, re-apply the mutator to the winning document and PUT once
    more (no second GET). Returns True on success, False (queued) when offline."""
    if token is None:
        token = _get_token()
    doc, fetch_error_code = _fetch_doc(key, token)
    if doc is None:
        # Offline with no cache: apply to default, queue, alarm. fetch_error_code
        # is set instead of None when the GET was actually rejected (e.g. an
        # expired token) rather than genuinely offline (#5013).
        new_data = mutator(default)
        _queue_outbox(key, new_data)
        _alarm.announce_depot_unreachable(
            "state update:{0}".format(key), error_code=fetch_error_code)
        return False
    new_data = mutator(doc.get("data"))
    body = json.dumps({"rev": doc.get("rev"), "data": new_data})
    result = _transport.put_json(ROUTES.state_url(key), body, token=token)
    if result.ok():
        _cache_new_rev(key, result.body, new_data)
        return True
    if result.status == 409:
        winning = _parse(result.body) or {}
        new_data2 = mutator(winning.get("data"))
        body2 = json.dumps({"rev": winning.get("rev"), "data": new_data2})
        r2 = _transport.put_json(ROUTES.state_url(key), body2, token=token)
        if r2.ok():
            _cache_new_rev(key, r2.body, new_data2)
            return True
    if result.transport_failed:
        _queue_outbox(key, new_data)
        _alarm.announce_depot_unreachable("state update:{0}".format(key))
        return False
    _alarm.announce_depot_unreachable(
        "state update failed:{0}".format(key), error_code=_error_code(result))
    return False


def _fetch_doc(key, token):
    """Get the current {rev, data} for a key: server truth if reachable, else the
    cached doc, else None. Returns (doc, error_code): error_code is the
    server's rejection code (e.g. ROUTES.ERR_UNAUTHORIZED) when doc is None
    because the GET was rejected rather than genuinely offline, else None."""
    result = _transport.get(ROUTES.state_url(key), token=token)
    if result.ok():
        doc = _parse(result.body)
        if doc is not None:
            out = {"rev": doc.get("rev"), "data": doc.get("data")}
            _write_cached_doc(key, out)
            return out, None
    if result.status == 404:
        return {"rev": None, "data": None}, None   # exists to be created
    cached = _read_cached_doc(key)
    if cached is not None:
        return cached, None
    return None, _error_code(result)


def _cache_new_rev(key, resp_body, data_written):
    """After a successful PUT, cache the new rev the server returned (if any)."""
    newdoc = _parse(resp_body) or {}
    _write_cached_doc(key, {"rev": newdoc.get("rev"), "data": data_written})


# --- offline outbox ---------------------------------------------------------

def _outbox_dir():
    d = ENVIRONMENT.DEPOT_OUTBOX_FOLDER
    if not os.path.exists(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    return d


def _queue_outbox(key, data):
    """Persist an unsent write. Filename is time-ordered so flush replays in
    order. Never raises."""
    try:
        # Monotonic-ish, collision-resistant name; keys can contain '/'.
        safe = key.replace("/", "__").replace("\\", "__")
        name = "{0:.6f}_{1}.json".format(time.time(), safe)
        path = os.path.join(_outbox_dir(), name)
        tmp = path + ".part"
        f = open(tmp, "w")
        try:
            json.dump({"key": key, "data": data, "queued_at": time.time()}, f)
        finally:
            f.close()
        os.rename(tmp, path)
    except Exception:
        pass


def flush_outbox(token=None):
    """Replay queued writes oldest-first with an unconditional PUT (rev: null).
    Removes each file on success. Returns (flushed, remaining)."""
    if token is None:
        token = _get_token()
    d = _outbox_dir()
    try:
        files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    except Exception:
        return (0, 0)
    flushed = 0
    for name in files:
        path = os.path.join(d, name)
        try:
            f = open(path, "r")
            try:
                item = json.load(f)
            finally:
                f.close()
        except Exception:
            continue
        key = item.get("key")
        data = item.get("data")
        if not key:
            _safe_remove(path)
            continue
        # rev: null = unconditional overwrite (outbox flush only).
        body = json.dumps({"rev": None, "data": data})
        result = _transport.put_json(ROUTES.state_url(key), body, token=token)
        if result.ok():
            _cache_new_rev(key, result.body, data)
            _safe_remove(path)
            flushed += 1
        elif result.transport_failed:
            break   # still offline; stop and keep the rest queued
        else:
            # Server rejected -> drop it (a poison message would block the queue).
            _safe_remove(path)
    remaining = _outbox_count()
    return (flushed, remaining)


def _outbox_count():
    try:
        return len([f for f in os.listdir(ENVIRONMENT.DEPOT_OUTBOX_FOLDER) if f.endswith(".json")])
    except Exception:
        return 0


def _safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
