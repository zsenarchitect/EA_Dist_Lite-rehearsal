"""
Delta wiki ingest client — shared by ________publish.py and EnneadTabWiki/scripts/ingest.py.

Two-phase protocol:
  1. POST /wiki/api/ingest/manifest  — compare hashes, get need_data / need_icons
  2. POST /wiki/api/ingest/          — send manifest + partial data + only required icons

Hash algorithm must stay in sync with EnneadTabWiki/lib/tool-hash.ts.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None  # type: ignore


def _normalize_alias(alias: Any) -> str:
    if isinstance(alias, str) and alias:
        return alias
    if isinstance(alias, list):
        parts = [a for a in alias if isinstance(a, str) and a]
        if parts:
            return " / ".join(parts)
    return ""


def compute_tool_content_hash(entry: dict) -> str:
    """Must match lib/tool-hash.ts computeToolContentHash."""
    payload = {
        "alias": _normalize_alias(entry.get("alias")),
        "doc": entry.get("doc") or "",
        "tab": entry.get("tab") or "Other",
        "script": entry.get("script") or "",
        "is_popular": bool(entry.get("is_popular")),
        "icon": entry.get("icon") or "",
        "tab_icon": entry.get("tab_icon") or "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_digest(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_icon_path(icon_relative: str, icons_dir: str, platform: str) -> Optional[str]:
    normalized = icon_relative.replace("\\", os.sep)
    full_path = os.path.join(icons_dir, normalized)
    if os.path.isfile(full_path):
        return full_path
    if platform == "revit":
        alt = os.path.join(icons_dir, "EnneaDuck.extension", normalized)
        if os.path.isfile(alt):
            return alt
    return None


# The wiki server rejects any single icon over this size with HTTP 413, which
# aborts the ENTIRE platform batch. One oversized icon must never freeze a whole
# platform (this silently froze rhino for ~3 months, see fix d569dee20). Skip the
# offending icon and keep going; the tool ships without its icon, not never.
MAX_ICON_BYTES = 262144


def _resolve_sendable_icon(icon_rel: str, icons_dir: str, platform: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve an icon only if it exists AND is within the server size cap.

    Returns (abs_path_or_None, reason) where reason is None when sendable,
    else "missing" (unresolvable) or "oversized" (over MAX_ICON_BYTES).
    """
    icon_abs = resolve_icon_path(icon_rel, icons_dir, platform)
    if not icon_abs:
        return None, "missing"
    try:
        if os.path.getsize(icon_abs) > MAX_ICON_BYTES:
            return None, "oversized"
    except OSError:
        return None, "missing"
    return icon_abs, None


def build_manifest(
    data: dict,
    icons_dir: str,
    platform: str,
) -> Tuple[dict, int, int]:
    """Build server manifest; returns (manifest, icons_found, icons_missing)."""
    manifest = {}
    icons_found = 0
    icons_missing = 0

    for tool_path, tool_info in data.items():
        if not isinstance(tool_info, dict):
            continue
        entry = dict(tool_info)
        if not _normalize_alias(entry.get("alias")):
            continue

        icons: Dict[str, str] = {}
        icon_paths: Dict[str, str] = {}

        for icon_field in ("icon", "tab_icon"):
            icon_rel = entry.get(icon_field)
            if not icon_rel:
                continue
            # Oversized icons are treated as absent: they can't be sent (the
            # server 413s), so the manifest must not claim to carry them.
            icon_abs, _reason = _resolve_sendable_icon(icon_rel, icons_dir, platform)
            if icon_abs:
                icons[icon_field] = compute_file_hash(icon_abs)
                icon_paths[icon_field] = icon_rel
                icons_found += 1
            else:
                icons_missing += 1

        manifest[tool_path] = {
            "content_hash": compute_tool_content_hash(entry),
            "icons": icons,
            "icon_paths": icon_paths,
        }

    return manifest, icons_found, icons_missing


def _manifest_api_url(ingest_api_url: str) -> str:
    base = ingest_api_url.rstrip("/")
    if base.endswith("/ingest"):
        return base + "/manifest"
    return base + "/manifest/"


def _load_local_cache(cache_path: str) -> dict:
    if not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_local_cache(cache_path: str, cache: dict) -> None:
    parent = os.path.dirname(cache_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _ingest_platform_full(
    platform: str,
    data: dict,
    icons_dir: str,
    api_url: str,
    api_key: str,
    cache_path: Optional[str],
    log,
) -> Tuple[bool, Optional[str], Optional[dict]]:
    """Legacy full payload when manifest API is unavailable."""
    manifest, icons_found, icons_missing = build_manifest(data, icons_dir, platform)
    digest = manifest_digest(manifest)
    log("    {}: full ingest {} tools, {} icons ({} missing)".format(
        platform, len(data), icons_found, icons_missing
    ))

    fields = {
        "platform": (None, platform),
        "data": (None, json.dumps(data)),
    }
    files_to_close = []
    for tool_path, tool_info in data.items():
        if not isinstance(tool_info, dict):
            continue
        for icon_field in ("icon", "tab_icon"):
            icon_rel = tool_info.get(icon_field)
            if not icon_rel:
                continue
            icon_abs, reason = _resolve_sendable_icon(icon_rel, icons_dir, platform)
            if reason == "oversized":
                log("    {}: WARNING skipping oversized icon (> {}KB), tool ships without it: {}".format(
                    platform, MAX_ICON_BYTES // 1024, icon_rel
                ))
            if icon_abs:
                fh = open(icon_abs, "rb")
                files_to_close.append(fh)
                fields["icon:{}".format(icon_rel)] = (
                    os.path.basename(icon_abs), fh, "image/png"
                )

    result = None
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(
                api_url, files=fields, headers={"x-api-key": api_key}, timeout=120
            )
            if resp.ok:
                result = resp.json()
                break
            if resp.status_code in (429,) or resp.status_code >= 500:
                last_error = resp.text[:200]
                if attempt < 2:
                    for fh in files_to_close:
                        try:
                            fh.seek(0)
                        except Exception:
                            pass
                    time.sleep(2 ** attempt)
                    continue
            return False, "full ingest {}: {}".format(resp.status_code, resp.text[:200]), None
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return False, str(e), None

    for fh in files_to_close:
        fh.close()

    if result is None:
        return False, last_error or "full ingest failed", None

    if cache_path:
        cache = _load_local_cache(cache_path)
        cache[platform] = {
            "manifest_digest": digest,
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_local_cache(cache_path, cache)

    return True, None, result


def ingest_platform_delta(
    platform: str,
    data: dict,
    icons_dir: str,
    api_url: str,
    api_key: str,
    cache_path: Optional[str] = None,
    dry_run: bool = False,
    log_fn=None,
) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Run two-phase delta ingest for one platform.

    Returns (success, error_message, result_json).
    """
    if requests is None:
        return False, "requests package not installed", None

    log = log_fn or print
    manifest, icons_found, icons_missing = build_manifest(data, icons_dir, platform)
    digest = manifest_digest(manifest)

    log("    {}: manifest {} tools, {} icon hashes ({} missing paths)".format(
        platform, len(manifest), icons_found, icons_missing
    ))

    if cache_path:
        cache = _load_local_cache(cache_path)
        prev = cache.get(platform, {})
        if prev.get("manifest_digest") == digest:
            log("    {}: local cache hit — nothing changed since last ingest, skipping".format(platform))
            return True, None, {
                "status": "skipped",
                "reason": "local_cache",
                "tools_unchanged": len(manifest),
            }

    manifest_url = _manifest_api_url(api_url)
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    plan = None
    last_error = None
    for attempt in range(3):
        try:
            log("    {}: manifest check (attempt {}/3)...".format(platform, attempt + 1))
            resp = requests.post(
                manifest_url,
                json={"platform": platform, "manifest": manifest},
                headers=headers,
                timeout=120,
            )
            if resp.ok:
                plan = resp.json()
                last_error = None
                break
            if resp.status_code == 404:
                log("    {}: manifest API not available — falling back to full ingest".format(platform))
                return _ingest_platform_full(
                    platform, data, icons_dir, api_url, api_key, cache_path, log
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = "{}: {}".format(resp.status_code, resp.text[:200])
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            return False, "manifest API {}: {}".format(resp.status_code, resp.text[:200]), None
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return False, "manifest request failed: {}".format(e), None

    if plan is None:
        return False, last_error or "manifest failed", None

    if plan.get("skip_entirely"):
        log("    {}: server skip_entirely — no changes".format(platform))
        if cache_path:
            cache = _load_local_cache(cache_path)
            cache[platform] = {
                "manifest_digest": digest,
                "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _save_local_cache(cache_path, cache)
        return True, None, plan

    need_data = plan.get("need_data") or []
    need_icons = set(plan.get("need_icons") or [])
    log("    {}: delta need_data={}, need_icons={}, unchanged={}".format(
        platform,
        len(need_data),
        len(need_icons),
        plan.get("tools_unchanged", 0),
    ))

    partial_data = {k: data[k] for k in need_data if k in data}

    fields = {
        "platform": (None, platform),
        "manifest": (None, json.dumps(manifest)),
        "data": (None, json.dumps(partial_data)),
    }

    files_to_close = []

    for tool_path in need_data:
        tool_info = data.get(tool_path)
        if not isinstance(tool_info, dict):
            continue
        manifest_entry = manifest.get(tool_path, {})
        icon_paths = manifest_entry.get("icon_paths") or {}
        icon_hash_map = manifest_entry.get("icons") or {}

        for icon_field in ("icon", "tab_icon"):
            icon_rel = tool_info.get(icon_field)
            if not icon_rel:
                continue
            icon_hash = icon_hash_map.get(icon_field)
            if icon_rel in need_icons:
                icon_abs, reason = _resolve_sendable_icon(icon_rel, icons_dir, platform)
                if reason == "oversized":
                    log("    {}: WARNING skipping oversized icon (> {}KB), tool ships without it: {}".format(
                        platform, MAX_ICON_BYTES // 1024, icon_rel
                    ))
                if icon_abs:
                    fh = open(icon_abs, "rb")
                    files_to_close.append(fh)
                    fields["icon:{}".format(icon_rel)] = (
                        os.path.basename(icon_abs),
                        fh,
                        "image/png",
                    )
            elif icon_hash:
                fields["icon_hash:{}".format(icon_rel)] = (None, icon_hash)

    if dry_run:
        for fh in files_to_close:
            fh.close()
        log("    {}: dry run — would post {} tools, {} icon files".format(
            platform, len(partial_data), sum(1 for k in fields if k.startswith("icon:"))
        ))
        return True, None, plan

    result = None
    last_error = None
    for attempt in range(3):
        try:
            log("    {}: posting delta ingest (attempt {}/3)...".format(platform, attempt + 1))
            resp = requests.post(
                api_url,
                files=fields,
                headers={"x-api-key": api_key},
                timeout=120,
            )
            if resp.ok:
                try:
                    result = resp.json()
                except ValueError:
                    return False, "non-JSON 200 response: {}".format(resp.text[:200]), None
                last_error = None
                break
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = "{}: {}".format(resp.status_code, resp.text[:200])
                if attempt < 2:
                    for fh in files_to_close:
                        try:
                            fh.seek(0)
                        except Exception:
                            pass
                    time.sleep(2 ** attempt)
                    continue
            return False, "ingest API {}: {}".format(resp.status_code, resp.text[:200]), None
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                for fh in files_to_close:
                    try:
                        fh.seek(0)
                    except Exception:
                        pass
                time.sleep(2 ** attempt)
            else:
                return False, "ingest request failed: {}".format(e), None
        finally:
            pass

    for fh in files_to_close:
        fh.close()

    if result is None:
        return False, last_error or "ingest failed", None

    if cache_path:
        cache = _load_local_cache(cache_path)
        cache[platform] = {
            "manifest_digest": digest,
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_local_cache(cache_path, cache)

    return True, None, result
