# -*- coding: utf-8 -*-
"""Depot asset layer -- read-only, cacheable files resolved to a local path.

Assets resolve to a real filesystem path, not bytes (plan 5.2): sys.path.append
needs a directory, the Revit API wants a path for SharedParametersFilename, and
an .exe cannot launch from a URL. So get_asset_path downloads to the cache and
returns the cached path.

Degradation (plan 5.3), deterministic in both runtimes:
    online fresh   -> serve cache after a 304, or download+replace on change
    offline cached -> serve the cached copy, silently
    offline none   -> return None (or raise if required=True), alarm once

Manifest TTL keeps steady state at zero requests (plan R5): a cached manifest is
trusted for DEPOT_MANIFEST_TTL_SEC before the client re-checks with If-None-Match.

Fully-qualified imports; IronPython 2.7 + CPython safe.
"""

import os
import json
import time

from EnneadTab import ENVIRONMENT
from EnneadTab import INTEGRITY
from EnneadTab.DEPOT import ROUTES
from EnneadTab.DEPOT import _transport
from EnneadTab.DEPOT import _cache
from EnneadTab.DEPOT import _alarm

# Client-side policy budgets (not server contract, so not in ENVIRONMENT).
DEFAULT_CACHE_BUDGET_BYTES = 2 * 1024 * 1024 * 1024      # 2 GB total cache
DEFAULT_FOLDER_BUDGET_BYTES = 1 * 1024 * 1024 * 1024      # refuse a folder over 1 GB (R2)

_MANIFEST_KEY = "__manifest__"
_MANIFEST_FILE = "__manifest__.json"


class DepotAssetError(Exception):
    pass


def _get_token():
    """Best-effort desktop Bearer token. Never blocks (get_token, not
    get_token_blocking -- banned on Revit UI threads, plan 5.4), never raises."""
    try:
        from EnneadTab import AUTH
        return AUTH.get_token()
    except Exception:
        return None


# --- Manifest ---------------------------------------------------------------

def _manifest_path():
    return _cache.local_path(_MANIFEST_FILE)


def _read_cached_manifest():
    path = _manifest_path()
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


def get_manifest(channel="prod", token=None, force=False):
    """Return the asset manifest dict, or None when offline with no cached copy.
    Honors the TTL: a fresh cached manifest is returned with zero network."""
    rec = _cache.entry(_MANIFEST_KEY) or {}
    cached = _read_cached_manifest()
    last_checked = rec.get("last_checked", 0)
    fresh = cached is not None and (time.time() - last_checked) < ENVIRONMENT.DEPOT_MANIFEST_TTL_SEC
    if fresh and not force:
        return cached

    if token is None:
        token = _get_token()
    result = _transport.get(ROUTES.manifest_url(channel), token=token,
                            if_none_match=rec.get("etag"))
    if result.not_modified() and cached is not None:
        _cache.record(_MANIFEST_KEY, etag=rec.get("etag"))  # refresh last_checked
        return cached
    if result.ok() and result.body is not None:
        try:
            text = result.body.decode("utf-8") if hasattr(result.body, "decode") else result.body
            manifest = json.loads(text)
        except Exception:
            manifest = None
        if isinstance(manifest, dict):
            _write_manifest(manifest)
            _cache.record(_MANIFEST_KEY, etag=result.etag)
            return manifest
    # Offline or an error: fall back to the cached manifest if we have one.
    if _transport.is_route_offline(result) and cached is None:
        _alarm.announce_depot_unreachable("manifest")
    return cached


def _write_manifest(manifest):
    path = _manifest_path()
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
            json.dump(manifest, f)
        finally:
            f.close()
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
    except Exception:
        _cache_safe_remove(tmp)


def _cache_safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _asset_meta(manifest, key):
    if not manifest:
        return None
    assets = manifest.get("assets")
    if isinstance(assets, dict):
        return assets.get(key)
    return None


# --- The main API -----------------------------------------------------------

def get_asset_path(key, required=False, channel="prod", token=None):
    """Resolve an asset key to a local cached path.

    Returns the path on success, or None when the asset is unavailable and
    required=False. Raises DepotAssetError only when required=True and the asset
    cannot be produced. Serves a stale cached copy silently when offline.
    """
    if token is None:
        token = _get_token()

    manifest = get_manifest(channel=channel, token=token)
    meta = _asset_meta(manifest, key)
    want_sha = (meta or {}).get("sha256")

    cached_ok = _cache.has_valid_file(key)
    cached_rec = _cache.entry(key) or {}

    # Fast path: cache present and (no manifest opinion OR manifest agrees).
    if cached_ok and (want_sha is None or cached_rec.get("sha256") == want_sha):
        _cache.touch(key)
        return _cache.local_path(key)

    # Manifest reached us and does not list the key -> asset not found.
    if manifest is not None and meta is None:
        if cached_ok:
            _cache.touch(key)
            return _cache.local_path(key)   # unknown to manifest but we have a copy
        return _missing(key, required, "asset_not_found")

    # Need to (re)download.
    dest = _cache.local_path(key)
    _ensure_parent(dest)
    result = _transport.download(ROUTES.asset_url(key), dest, token=token)

    if result.ok():
        _cache.strip_zone_identifier(dest)
        got_sha = INTEGRITY.hash_file(dest)
        if want_sha and got_sha != want_sha:
            # Corrupt / truncated download -> drop it, do not serve garbage.
            _cache_safe_remove(dest)
            if cached_ok:
                return _cache.local_path(key)
            return _missing(key, required, "sha256_mismatch")
        size = None
        try:
            size = os.path.getsize(dest)
        except Exception:
            pass
        _cache.record(key, etag=result.etag, sha256=got_sha, size=size)
        _cache.prune_to(DEFAULT_CACHE_BUDGET_BYTES)
        return dest

    # Download failed. Offline + cached -> serve stale silently.
    if _transport.is_route_offline(result):
        if cached_ok:
            _cache.touch(key)
            return _cache.local_path(key)
        _alarm.announce_depot_unreachable("asset:{0}".format(key))
        return _missing(key, required, "offline")

    # A real HTTP error (401/403/5xx). Serve cache if we have it.
    if cached_ok:
        _cache.touch(key)
        return _cache.local_path(key)
    return _missing(key, required, result.error or "http_error")


def _missing(key, required, reason):
    if required:
        raise DepotAssetError("depot asset unavailable: {0} ({1})".format(key, reason))
    return None


def _ensure_parent(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d)
        except Exception:
            pass


def get_asset_folder(prefix, channel="prod", token=None, budget_bytes=None):
    """Materialize every asset under a key prefix into the cache and return the
    local folder path. Refuses a folder whose manifest total_size exceeds the
    budget (plan R2 -- never bulk-materialize the multi-GB Rhino library blindly).
    Returns None on refusal or when offline with nothing cached."""
    if budget_bytes is None:
        budget_bytes = DEFAULT_FOLDER_BUDGET_BYTES
    if token is None:
        token = _get_token()
    manifest = get_manifest(channel=channel, token=token)
    if manifest is None:
        # Offline: return the cached folder if it exists, else None.
        folder = _cache.local_path(prefix)
        return folder if os.path.exists(folder) else None

    folders = manifest.get("folders") or {}
    finfo = folders.get(prefix) or {}
    total = finfo.get("total_size")
    if total is not None and int(total) > budget_bytes:
        # Local policy refusal, not a depot-reachability problem -- error_code
        # picks the distinguishing "folder too large" message instead of the
        # generic "could not reach the shared depot" text (#5013).
        _alarm.announce_depot_unreachable(
            "folder {0} is {1} bytes > budget {2}".format(prefix, total, budget_bytes),
            error_code="budget_exceeded")
        return None

    assets = manifest.get("assets") or {}
    keys = [k for k in assets.keys() if k == prefix or k.startswith(prefix + "/")]
    for k in keys:
        get_asset_path(k, required=False, channel=channel, token=token)
    return _cache.local_path(prefix)
