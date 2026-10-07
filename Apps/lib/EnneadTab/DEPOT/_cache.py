# -*- coding: utf-8 -*-
"""Depot local cache -- index, atomic replace, sha256 verify, LRU prune, MOTW strip.

A stale cached copy beats a dead button (plan 5.3), so the asset layer serves
from here whenever the network is unreachable. This module owns only the local
store; it does no HTTP.

Design points:
  * Index is a single JSON at ENVIRONMENT.DEPOT_CACHE_INDEX_FILE mapping
    key -> {etag, sha256, size, last_checked, last_access}. Corrupt index
    self-heals to empty (a lost index costs a re-download, never a crash).
  * sha256 is REUSED from INTEGRITY.hash_file (C18) -- one hashing path.
  * Downloaded files get their Windows Mark-of-the-Web (:Zone.Identifier ADS)
    stripped (plan R8) so a cached .exe launches without a SmartScreen block.
  * IronPython 2.7 + CPython safe: no f-strings, no type hints, no pathlib.

Fully-qualified imports only.
"""

import os
import json
import time

from EnneadTab import ENVIRONMENT
from EnneadTab import INTEGRITY


def cache_dir():
    """Absolute cache root; created on first use."""
    d = ENVIRONMENT.DEPOT_CACHE_FOLDER
    if not os.path.exists(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    return d


def local_path(key):
    """Filesystem path for a depot key. Keys use '/' as the separator; map them
    to nested folders under the cache root. '..' segments are rejected so a
    malicious manifest cannot escape the cache dir."""
    parts = [p for p in key.split("/") if p not in ("", ".", "..")]
    return os.path.join(cache_dir(), *parts)


# --- Index ------------------------------------------------------------------

def read_index():
    """Load the cache index, self-healing to {} if missing or corrupt."""
    path = ENVIRONMENT.DEPOT_CACHE_INDEX_FILE
    if not os.path.exists(path):
        return {}
    try:
        f = open(path, "r")
        try:
            data = json.load(f)
        finally:
            f.close()
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        # Corrupt index -> discard it. A re-download is cheaper than a crash.
        return {}


def write_index(index):
    """Persist the index via temp file + rename.

    NOT atomic: the existing index is removed BEFORE the rename, so there is
    a window where the index file does not exist. Do not build on an
    atomicity guarantee here. senzhang-todo #3896.
    """
    path = ENVIRONMENT.DEPOT_CACHE_INDEX_FILE
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
            json.dump(index, f)
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


def entry(key):
    """Index record for a key, or None."""
    return read_index().get(key)


def record(key, etag=None, sha256=None, size=None):
    """Upsert the index record for a key and stamp last_checked/last_access."""
    index = read_index()
    now = time.time()
    rec = index.get(key, {})
    if etag is not None:
        rec["etag"] = etag
    if sha256 is not None:
        rec["sha256"] = sha256
    if size is not None:
        rec["size"] = size
    rec["last_checked"] = now
    rec["last_access"] = now
    index[key] = rec
    write_index(index)
    return rec


def touch(key):
    """Bump last_access for LRU. No-op if the key is unknown."""
    index = read_index()
    if key in index:
        index[key]["last_access"] = time.time()
        write_index(index)


def has_valid_file(key):
    """True if the key's file exists AND its sha256 matches the index (C18 via
    INTEGRITY.hash_file). A mismatch means a corrupt/partial cache entry -> the
    caller should re-download."""
    rec = entry(key)
    if not rec:
        return False
    path = local_path(key)
    if not os.path.exists(path):
        return False
    expected = rec.get("sha256")
    if not expected:
        return True  # no recorded hash to check against; trust presence
    return INTEGRITY.hash_file(path) == expected


# --- Mark-of-the-Web (Windows) ----------------------------------------------

def strip_zone_identifier(path):
    """Remove the :Zone.Identifier alternate data stream a downloaded file gets
    on Windows (plan R8), so a cached .exe is not SmartScreen-blocked. No-op on
    non-Windows or if the stream is absent."""
    if os.name != "nt":
        return
    ads = path + ":Zone.Identifier"
    try:
        if os.path.exists(ads):
            os.remove(ads)
    except Exception:
        pass


# --- LRU prune --------------------------------------------------------------

def total_size():
    """Sum of recorded sizes in the index (bytes)."""
    total = 0
    for rec in read_index().values():
        try:
            total += int(rec.get("size") or 0)
        except Exception:
            pass
    return total


def prune_to(budget_bytes):
    """Evict least-recently-accessed entries until total recorded size is within
    budget. Returns the list of evicted keys. Deletes both the file and the
    index record."""
    index = read_index()
    # Oldest access first.
    ordered = sorted(index.items(), key=lambda kv: kv[1].get("last_access", 0))
    total = 0
    for _, rec in ordered:
        try:
            total += int(rec.get("size") or 0)
        except Exception:
            pass
    evicted = []
    i = 0
    while total > budget_bytes and i < len(ordered):
        key, rec = ordered[i]
        i += 1
        path = local_path(key)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        try:
            total -= int(rec.get("size") or 0)
        except Exception:
            pass
        index.pop(key, None)
        evicted.append(key)
    if evicted:
        write_index(index)
    return evicted
