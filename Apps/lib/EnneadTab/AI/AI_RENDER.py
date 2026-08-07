#!/usr/bin/python
# -*- coding: utf-8 -*-
"""AI image/video render -- wrappers, queue, and gallery cache.

Single module owning the complete render concern:

  Section A -- Style preset library      (get_render_presets)
  Section B -- Image render API          (render_image_with_token, render_image)
  Section C -- Video render API          (render_video_with_token)
  Section D -- Style-reference library   (get_demo_style_images, cache helpers)
  Section E -- User saved prompts        (list_prompts_with_token, save_prompt_with_token)
  Section F -- Quota                     (get_quota_with_token)
  Section G -- Cloud Gallery API         (list/items/save/community/delete)
  Section H -- Local gallery cache       (cache_dir, fetch_*_async, filter_rows)
  Section I -- Render job model + worker (RenderJob, QueueWorker, ACTIVE_CAP)

All HTTP transports come from EnneadTab.AI._common. All the desktop UIs in
Revit and Rhino import from this module -- there is no per-platform copy of
the queue or gallery logic.

IronPython 2.7 + CPython 3.x compatible.
"""

import base64
import io
import json
import os
import time
import shutil
import uuid

# Optional .NET imports -- only present in IronPython hosts (Revit/Rhino).
# Pure-CPython callers (e.g. ENGINE.py background tasks that only need
# AI.chat or AI.translate via the back-compat re-exports) must still be
# able to import this module without crashing on `import clr`.
try:
    import clr # pyright: ignore
    clr.AddReference("System")
    import System # pyright: ignore
    from System.Threading import Thread, ThreadStart, AutoResetEvent, Monitor # pyright: ignore
    _HAS_DOTNET = True
except ImportError:
    _HAS_DOTNET = False
    System = None
    Thread = ThreadStart = AutoResetEvent = Monitor = None

from EnneadTab import AUTH
from EnneadTab import SOUND, FOLDER  # noqa: F401 -- kept for callers
from EnneadTab.AI._common import (
    RENDER_URL, AIRequestError,
    post_json, get_json, post_multipart, post_multipart_raw,
    download_url_to_file,
)


_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


# =====================================================================
# Auth panel canonical copy (2026-04-30, Item A)
#
# Both the Rhino and Revit dialogs import these strings so first-time-user
# auth UX cannot drift between the two surfaces. If you change copy here,
# both dialogs reflect it on next reload.
#
# WHY EnneaDuck not Microsoft: per memory feedback_enneaduck_branding.md,
# every AI-facing UI uses the EnneaDuck identity. The IdP is Microsoft
# under the hood (Entra ID via enneadtab.com SSO), but the user-visible
# surface is "EnneaDuck."
# =====================================================================

AUTH_PANEL_HEADING = "Sign in to EnneaDuck"
AUTH_PANEL_BODY = (
    "AI Render uses your Ennead account. Click below -- your browser will "
    "open enneadtab.com to sign in. After you sign in, this dialog will "
    "refresh automatically (no Rhino/Revit restart needed)."
)
AUTH_PANEL_BUTTON = "Sign in"
AUTH_PANEL_WAITING = "Waiting for sign-in... complete the flow in your browser."
AUTH_PANEL_TIMEOUT = "Sign-in timed out. Click Sign in to try again."
AUTH_PANEL_EXPIRED_HEADING = "Session expired"
AUTH_PANEL_EXPIRED_BODY = "Sign in again to continue using AI Render."

QUOTA_PANEL_HEADING = "Daily render quota reached"
QUOTA_PANEL_BODY = (
    "You've used your daily render allowance. Try again tomorrow, or "
    "contact design-tech if this is unexpected (Ennead is on a paid tier)."
)


def _mime_for_path(path):
    """Pick correct MIME from file extension. Defaults to image/jpeg.
    Round 3 P2-5 -- was hardcoded `png else jpeg` so .webp uploaded as jpeg."""
    return _MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "image/jpeg")


# =====================================================================
# Section A -- Style preset library
# =====================================================================

def get_render_presets(token=None):
    """Fetch rendering style presets from /api/create/image (GET).

    Returns list of {name, prompt, category, description}. Empty on failure.
    """
    url = "{}/api/create/image".format(RENDER_URL)
    try:
        data = get_json(url, token=token, timeout_ms=10000)
        if data.get("ok") and isinstance(data.get("prompts"), list):
            return data["prompts"]
    except Exception:
        pass
    return []


# =====================================================================
# Section B -- Image render API
# =====================================================================

def render_image_with_token(token, image_path, prompt, aspect_ratio="16:9",
                            style_image_path=None, progress_callback=None):
    """Render an architectural image via /api/create/image (SSE streaming).

    Returns: list of {b64, mime} dicts (one per generated image).
    Raises: AIRequestError. Check status_code == 401 for expired token.
    """
    if not token:
        raise AIRequestError("No auth token provided. Please sign in first.")
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    mime = _mime_for_path(image_path)
    filename = os.path.basename(image_path)

    url = "{}/api/create/image?generationMode=image-to-image&countFactor=1&aspectRatio={}&temperature=1.0&stream=true".format(
        RENDER_URL, aspect_ratio or "16:9")

    fields = {"inSessionPrompt": prompt}
    files = [("mainImages", filename, image_bytes, mime)]

    if style_image_path and os.path.exists(style_image_path):
        with open(style_image_path, "rb") as sf:
            style_bytes = sf.read()
        s_mime = _mime_for_path(style_image_path)
        files.append(("styleImages", os.path.basename(style_image_path), style_bytes, s_mime))

    raw = post_multipart_raw(url, fields, files, token, timeout_ms=180000,
                             progress_callback=progress_callback)
    if progress_callback:
        progress_callback("Processing response...")

    # SSE parser: normalize CRLF->LF first (some CDNs use \r\n\r\n separators),
    # then split by blank lines and collect lines starting with "data:".
    # Tolerates "event: <name>" prefix lines (multi-line SSE events).
    images = []
    event_count = 0
    raw_normalized = raw.replace("\r\n", "\n")
    for chunk in raw_normalized.split("\n\n"):
        chunk = chunk.strip("\r\n")
        if not chunk:
            continue
        data_lines = []
        for line in chunk.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
        if not data_lines:
            continue
        event_count += 1
        try:
            event = json.loads("\n".join(data_lines))
        except ValueError:
            continue
        etype = event.get("type")
        if etype == "image":
            result = event.get("result", {})
            if result.get("b64"):
                images.append(result)
        elif etype == "error":
            raise AIRequestError(event.get("error", "Generation failed"))
        elif etype == "progress" and progress_callback:
            try:
                cur = int(event.get("current") or 0)
                tot = int(event.get("total") or 1)
            except (TypeError, ValueError):
                cur, tot = 0, 1
            if tot < 1:
                tot = 1
            progress_callback("AI is generating... {}%".format(int(100 * cur / tot)))

    if not images:
        preview = raw[:500].replace("\n", "\\n") if raw else "(empty)"
        raise AIRequestError(
            "No images in response. {} bytes, {} SSE events parsed. Response start: {}".format(
                len(raw), event_count, preview))
    return images


def render_image(image_path, prompt, aspect_ratio="16:9"):
    """Convenience wrapper with blocking auth. Empty list on failure."""
    token = AUTH.get_token_blocking()
    if not token:
        return []
    try:
        return render_image_with_token(token, image_path, prompt, aspect_ratio)
    except AIRequestError as e:
        if e.status_code == 401:
            AUTH.clear_token()
            token = AUTH.get_token_blocking()
            if not token:
                return []
            return render_image_with_token(token, image_path, prompt, aspect_ratio)
        print("Render failed: {}".format(e))
        return []


# =====================================================================
# Section C -- Video render API
# =====================================================================

def render_video_with_token(token, image_path, prompt, duration_sec=4,
                            resolution="720p", last_frame_path=None,
                            timeout_ms=300000, progress_callback=None):
    """Image-to-video via /api/create/video (long-poll JSON, NOT SSE).

    Vercel route maxDuration=300; can run 60-180s typical. Returns the parsed
    JSON response -- caller downloads the videoUrl + posterUrl (if present).
    """
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    if not os.path.exists(image_path):
        raise AIRequestError("First-frame image not found: {}".format(image_path))
    if duration_sec not in (4, 6, 8):
        raise AIRequestError("duration_sec must be 4, 6, or 8")
    if resolution not in ("720p", "1080p"):
        raise AIRequestError("resolution must be '720p' or '1080p'")

    with open(image_path, "rb") as f:
        first_bytes = f.read()
    mime = _mime_for_path(image_path)
    files = [("firstFrame", os.path.basename(image_path), first_bytes, mime)]
    if last_frame_path and os.path.exists(last_frame_path):
        with open(last_frame_path, "rb") as f:
            last_bytes = f.read()
        l_mime = _mime_for_path(last_frame_path)
        files.append(("lastFrame", os.path.basename(last_frame_path), last_bytes, l_mime))

    fields = {
        "prompt": prompt,
        "duration": str(duration_sec),
        "resolution": resolution,
    }
    if progress_callback:
        progress_callback("Generating video... (this can take 1-3 minutes)")
    url = "{}/api/create/video".format(RENDER_URL)
    data = post_multipart(url, fields, files, token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        raise AIRequestError(data.get("error") or "create/video failed")
    return data


# =====================================================================
# Section D -- Style-reference library + per-image cache
# =====================================================================

def _style_cache_dir():
    appdata = os.environ.get("APPDATA") or os.environ.get("USERPROFILE") or os.path.expanduser("~")
    folder = os.path.join(appdata, "EnneadTab", "ai_style_cache")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def get_demo_style_images(token, timeout_ms=10000):
    """List the 60+ curated Ennead style references via /api/demo-images.

    Returns: [{url, filename}, ...]. Image URLs are public (no auth on fetch).
    """
    url = "{}/api/demo-images".format(RENDER_URL)
    try:
        data = get_json(url, token=token, timeout_ms=timeout_ms)
    except AIRequestError:
        return []
    out = []
    for rel in (data.get("images") or []):
        if not rel:
            continue
        absolute = rel if rel.startswith("http") else "{}{}".format(RENDER_URL, rel)
        out.append({"url": absolute, "filename": rel.rsplit("/", 1)[-1]})
    return out


def get_or_cache_demo_style_image(url, filename=None, max_age_days=30):
    """Cache hit returns local path instantly. Miss downloads, then returns path.
    Stale-on-network-error fallback so flaky connections don't break the picker.
    """
    if not filename:
        filename = url.rsplit("/", 1)[-1] or "style_ref.jpg"
    safe_name = "".join(c if (c.isalnum() or c in "._-()") else "_" for c in filename)
    cache_path = os.path.join(_style_cache_dir(), safe_name)
    if os.path.exists(cache_path):
        try:
            age_sec = time.time() - os.path.getmtime(cache_path)
            if age_sec < max_age_days * 86400 and os.path.getsize(cache_path) > 0:
                return cache_path
        except Exception:
            pass
    try:
        download_url_to_file(url, cache_path)
        return cache_path
    except AIRequestError:
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return cache_path
        raise


def prefetch_demo_style_images(token, max_count=None, progress_callback=None):
    """Background-warm the local style cache. Call on dialog open."""
    items = get_demo_style_images(token)
    if max_count:
        items = items[:max_count]
    total = len(items)
    out = []
    for i, item in enumerate(items, 1):
        try:
            item["cached_path"] = get_or_cache_demo_style_image(item["url"], item.get("filename"))
        except Exception:
            item["cached_path"] = None
        out.append(item)
        if progress_callback:
            try:
                progress_callback(i, total)
            except Exception:
                pass
    return out


# =====================================================================
# Section E -- User saved prompts
# =====================================================================

def list_prompts_with_token(token, timeout_ms=10000):
    """Returns the user's saved prompts via /api/prompts/list. Empty on failure."""
    if not token:
        return []
    url = "{}/api/prompts/list".format(RENDER_URL)
    try:
        data = get_json(url, token=token, timeout_ms=timeout_ms)
    except AIRequestError:
        return []
    if not data.get("ok"):
        return []
    return data.get("prompts") or []


def save_prompt_with_token(token, name, prompt, category=None, tags=None, timeout_ms=15000):
    """Persist a custom prompt for this user via /api/prompts/save."""
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    url = "{}/api/prompts/save".format(RENDER_URL)
    body = {"name": name, "prompt": prompt}
    if category:
        body["category"] = category
    if tags:
        body["tags"] = list(tags)
    data = post_json(url, json.dumps(body, ensure_ascii=True), token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        raise AIRequestError(data.get("error") or "prompts/save failed")
    return data


# =====================================================================
# Section F -- Quota
# =====================================================================

def get_quota_with_token(token, timeout_ms=10000):
    """Returns office-wide tracked quota dict, or None on failure."""
    if not token:
        return None
    url = "{}/api/quota".format(RENDER_URL)
    try:
        data = get_json(url, token=token, timeout_ms=timeout_ms)
    except AIRequestError:
        return None
    if not data.get("ok"):
        return None
    return data.get("trackedQuota") or {}


# =====================================================================
# Section G -- Cloud Gallery API (list / items / save / community / delete)
# =====================================================================

def _lib_trace(msg):
    """2026-06-04 diagnostic: the gallery dialogs' own trace can't see inside
    this lib, so an empty fetch is indistinguishable from no-token / request
    error / server ok=False. Append a line to a dedicated lib log so we can
    tell exactly why the cloud gallery came back empty. Cheap; remove once the
    history-loading root cause is confirmed."""
    try:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(appdata, "EnneadTab")
        if not os.path.exists(d):
            os.makedirs(d)
        f = open(os.path.join(d, "ai_render_lib_trace.log"), "a")
        try:
            f.write("{}  {}\n".format(
                time.strftime("%H:%M:%S"), msg))
        finally:
            f.close()
    except Exception:
        pass


def list_gallery_index_with_token(token, limit=200, offset=0, timeout_ms=15000):
    """Lightweight index -- items have inline thumbnailData (data URL). Empty on failure.

    NOTE: the server hard-caps a single request at 200 items
    (RenderPolisher app/api/gallery/index/route.ts:104, `Math.min(200, limit)`),
    so this returns AT MOST 200 regardless of `limit`. To fetch a full history
    longer than 200 items, call list_gallery_index_paged() which loops offset.
    """
    if not token:
        _lib_trace("with_token: NO TOKEN")
        return []
    url = "{}/api/gallery/index?limit={}&offset={}".format(RENDER_URL, int(limit), int(offset))
    try:
        data = get_json(url, token=token, timeout_ms=timeout_ms)
    except AIRequestError as e:
        _lib_trace("with_token: AIRequestError offset={} {}".format(offset, str(e)[:160]))
        return []
    except Exception as e:
        _lib_trace("with_token: OTHER-EXC offset={} {}: {}".format(
            offset, type(e).__name__, str(e)[:160]))
        raise
    if not data.get("ok"):
        _lib_trace("with_token: ok=False offset={} keys={} err={}".format(
            offset, list(data.keys()), str(data.get("error"))[:120]))
        return []
    items = data.get("items") or []
    _lib_trace("with_token: OK offset={} limit={} got={}".format(offset, limit, len(items)))
    return items


# Server page-size cap for /api/gallery/index (see route.ts Math.min(200, limit)).
# A single request silently truncates any history longer than this, so callers
# that want the full gallery MUST paginate.
_SERVER_INDEX_PAGE_CAP = 200


def list_gallery_index_paged(token, total=500, start_offset=0, timeout_ms=15000):
    """Fetch up to `total` index items, paginating past the server's 200/page cap.

    Root cause (2026-06-04): both the Revit and Rhino gallery dialogs requested
    limit=500 in a single call, but the server clamps each request to 200 and the
    clients never advanced the offset -- so any user with >200 renders only ever
    saw their newest 200. This loops offset in <=200 chunks until `total` items
    are collected or the server runs out (a short page == last page). The `total`
    ceiling is the runaway guard. Empty list on failure / no token.
    """
    if not token:
        _lib_trace("paged: NO TOKEN")
        return []
    _lib_trace("paged: START total={} start_offset={}".format(total, start_offset))
    out = []
    offset = int(start_offset)
    total = int(total)
    while len(out) < total:
        want = min(_SERVER_INDEX_PAGE_CAP, total - len(out))
        # 2026-06-04 robustness fix: a LATER page (offset > 0) is a request
        # the old single-fetch code never made. If any one page throws an
        # exception that list_gallery_index_with_token doesn't wrap as
        # AIRequestError (timeout subclass, transport error, JSON decode),
        # it must NOT kill the whole load -- otherwise pagination is strictly
        # more failure-prone than the old single fetch and regresses history
        # loading. Catch per-page and return what we already have; worst case
        # this degrades to exactly the old "newest page only" behavior.
        try:
            items = list_gallery_index_with_token(
                token, limit=want, offset=offset, timeout_ms=timeout_ms)
        except Exception:
            break  # keep pages collected so far; never fail the whole load
        if not items:
            break  # failure or exhausted
        out.extend(items)
        if len(items) < want:
            break  # short page -> server has no more
        offset += len(items)
    _lib_trace("paged: END total_out={}".format(len(out)))
    return out


def get_gallery_items_with_token(token, ids, timeout_ms=30000):
    """Fetch full items (with original imageData) by ID list. Server caps at 200 IDs."""
    if not token or not ids:
        return []
    try:
        from urllib.parse import quote as _q
    except ImportError:
        from urllib import quote as _q  # IronPython 2.7 / Py2
    if isinstance(ids, str):
        ids_param = _q(ids, safe=",")
    else:
        ids_param = ",".join(_q(str(x), safe="") for x in ids[:200])
    url = "{}/api/gallery/items?ids={}".format(RENDER_URL, ids_param)
    try:
        data = get_json(url, token=token, timeout_ms=timeout_ms)
    except AIRequestError:
        return []
    if not data.get("ok"):
        return []
    return data.get("items") or []


def save_to_gallery_with_token(token, image_path, prompt, mode="image",
                               style_name=None, view_name=None, original_path=None,
                               aspect_ratio=None, long_edge=None, host=None,
                               is_interior=None, duration_ms=None,
                               prompt_title=None, used_style_ref=None,
                               timeout_ms=60000):
    """Save a generated image to the user's cloud Gallery. Visible on every device.

    If `original_path` is provided, the source capture is uploaded alongside the
    result as a second multipart file. The server derives a small thumbnail and
    stores it on the gallery item so the History panel can show both thumbs.
    Old clients omit the field; server treats that case as result-only.

    2026-04-28 -- extended kwargs (aspect_ratio, long_edge, host, is_interior,
    duration_ms, prompt_title, used_style_ref) are bundled into a `metadata`
    JSON form field so the server `/api/gallery/save` (saveToStorage util)
    persists them on the gallery item. Without these the History panel shows
    only prompt + date because the server's saveToStorage IGNORES flat
    styleName/viewName fields and only reads the metadata JSON.
    """
    import json
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    if not os.path.exists(image_path):
        raise AIRequestError("Image not found: {}".format(image_path))
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    fields = {"prompt": prompt, "mode": mode}
    # Flat fields kept for back-compat with any older server build that
    # might read them. Newer server reads only the metadata JSON.
    if style_name:
        fields["styleName"] = style_name
    if view_name:
        fields["viewName"] = view_name
    # Build the rich metadata blob the History panel needs to surface
    # style/view/resolution/duration/etc. Keys match what
    # ai_render_gallery_module.row_from_cloud_item() reads.
    meta = {}
    if style_name:
        meta["styleName"] = style_name
    if view_name:
        meta["viewName"] = view_name
    if aspect_ratio:
        meta["aspectRatio"] = aspect_ratio
    if long_edge:
        meta["longEdge"] = int(long_edge)
    if host:
        meta["host"] = host
    if is_interior is not None:
        meta["isInterior"] = bool(is_interior)
    if duration_ms is not None:
        meta["durationMs"] = int(duration_ms)
    if prompt_title:
        meta["promptTitle"] = prompt_title
    if used_style_ref is not None:
        meta["usedStyleRef"] = bool(used_style_ref)
    meta["type"] = mode  # row builder reads metadata.type for video icon
    fields["metadata"] = json.dumps(meta)
    files = [("file", os.path.basename(image_path), image_bytes, mime)]
    if original_path and os.path.exists(original_path):
        try:
            with open(original_path, "rb") as f:
                orig_bytes = f.read()
            o_ext = os.path.splitext(original_path)[1].lower()
            o_mime = "image/png" if o_ext == ".png" else "image/jpeg"
            files.append(
                ("originalFile", os.path.basename(original_path), orig_bytes, o_mime)
            )
        except Exception:
            # Non-fatal: if the original can't be read, still save the result.
            pass
    url = "{}/api/gallery/save".format(RENDER_URL)
    data = post_multipart(url, fields, files, token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        raise AIRequestError(data.get("error") or "gallery/save failed")
    return data


def save_to_community_with_token(token, image_path, prompt, mode="image",
                                 style_name=None, view_name=None, timeout_ms=60000):
    """Publish to the public community Museum. Caller MUST gate on confirmation."""
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    if not os.path.exists(image_path):
        raise AIRequestError("Image not found: {}".format(image_path))
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    fields = {"prompt": prompt, "mode": mode}
    if style_name:
        fields["styleName"] = style_name
    if view_name:
        fields["viewName"] = view_name
    files = [("file", os.path.basename(image_path), image_bytes, mime)]
    url = "{}/api/community/save".format(RENDER_URL)
    data = post_multipart(url, fields, files, token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        raise AIRequestError(data.get("error") or "community/save failed")
    return data


def delete_gallery_item_with_token(token, item_id, timeout_ms=15000):
    """Delete an item -- affects every device the user is signed in on."""
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    if not item_id:
        raise AIRequestError("item_id required")
    url = "{}/api/gallery/delete".format(RENDER_URL)
    payload = json.dumps({"id": str(item_id)}, ensure_ascii=True)
    data = post_json(url, payload, token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        raise AIRequestError(data.get("error") or "gallery/delete failed")
    return data


# =====================================================================
# Section H -- Local gallery cache + fetch helpers (framework-agnostic)
# =====================================================================
#
# These run on a ThreadPool so the UI stays responsive. The platform-specific
# UI module is responsible for marshalling on_done callbacks back onto its UI
# thread (Dispatcher.Invoke for WPF, Eto.Application.Instance.Invoke for Eto).

DATE_FILTERS = [
    ("Today", 86400),
    ("Last 7 days", 7 * 86400),
    ("Last 30 days", 30 * 86400),
    ("This year", 365 * 86400),
    ("All time", None),
]
DEFAULT_DATE_FILTER = "All time"


def cache_dir():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(appdata, "EnneadTab", "ai_gallery_cache")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def item_cache_dir(item_id):
    folder = os.path.join(cache_dir(), str(item_id))
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def cache_size_bytes():
    total = 0
    base = cache_dir()
    for root, _dirs, files in os.walk(base):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except Exception:
                pass
    return total


def clear_cache():
    """Wipe local cache. Cloud is canonical so this is non-destructive.

    Per-entry try/except so a single locked file (Windows: another process
    has it open) doesn't abort the whole sweep -- Round 3 P3-4.
    """
    base = cache_dir()
    if not os.path.exists(base):
        return
    for entry in os.listdir(base):
        p = os.path.join(base, entry)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except (OSError, IOError):
                    # File locked by another process (Windows). Skip this one,
                    # continue cleanup. Will be retried next time.
                    continue
        except Exception:
            continue


def write_data_url_to_file(data_url, dest_path):
    if not data_url:
        return None
    try:
        if "," in data_url:
            b64 = data_url.split(",", 1)[1]
        else:
            b64 = data_url
        with open(dest_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return dest_path
    except Exception:
        return None


def filter_rows(rows, seconds_back=None, query=""):
    """Date window + text search; active jobs pinned to top, then date-desc.

    Each row is duck-typed: needs .created_at, .full_prompt, .view_name,
    .StyleName, optional .job_ref whose status pins to top.
    """
    query = (query or "").strip().lower()
    now = time.time()
    out = []
    for r in rows:
        if seconds_back is not None and r.created_at and (now - r.created_at) > seconds_back:
            continue
        if query:
            hay = "{} {} {}".format(
                (r.full_prompt or "").lower(),
                (r.view_name or "").lower(),
                (r.StyleName or "").lower())
            if query not in hay:
                continue
        out.append(r)
    def sort_key(rr):
        if rr.job_ref and rr.job_ref.status in ("pending", "active"):
            return (0, -rr.created_at)
        return (1, -rr.created_at)
    out.sort(key=sort_key)
    return out


def fetch_gallery_index_async(token, on_done, limit=200, offset=0):
    """Background fetch of /api/gallery/index. on_done(items_or_None) on ThreadPool.

    `limit` is the TOTAL number of items wanted, not a single-request size. The
    server caps each request at 200, so we paginate internally (see
    list_gallery_index_paged) to honor the requested total. Both the Revit and
    Rhino dialogs pass limit=500, so this now returns their full history up to
    500 items instead of a silently-truncated first 200.
    """
    def worker(state):
        try:
            items = list_gallery_index_paged(token, total=limit, start_offset=offset)
            on_done(items)
        except Exception:
            on_done(None)
    System.Threading.ThreadPool.QueueUserWorkItem(System.Threading.WaitCallback(worker))


def fetch_full_item_async(token, item_id, on_done):
    """Background fetch of /api/gallery/items?ids=<id>; writes imageData to local cache.
    on_done(local_path_or_None) on ThreadPool.
    """
    def worker(state):
        try:
            items = get_gallery_items_with_token(token, [item_id])
            if not items:
                on_done(None)
                return
            it = items[0]
            data_url = it.get("imageData") or ""
            # Parse mime explicitly -- substring match treats webp as jpg.
            ext = ".jpg"
            if data_url.startswith("data:"):
                mime_part = data_url.split(";", 1)[0].split(":", 1)[-1].lower()
                if "png" in mime_part:
                    ext = ".png"
                elif "webp" in mime_part:
                    ext = ".webp"
                elif "gif" in mime_part:
                    ext = ".gif"
            dest = os.path.join(item_cache_dir(item_id), "result" + ext)
            path = write_data_url_to_file(data_url, dest)
            on_done(path)
        except Exception:
            on_done(None)
    System.Threading.ThreadPool.QueueUserWorkItem(System.Threading.WaitCallback(worker))


def fmt_bytes(n):
    if n < 1024:
        return "{}B".format(n)
    if n < 1024 * 1024:
        return "{:.1f}KB".format(n / 1024.0)
    if n < 1024 * 1024 * 1024:
        return "{:.1f}MB".format(n / (1024.0 * 1024))
    return "{:.2f}GB".format(n / (1024.0 * 1024 * 1024))


def fmt_elapsed(sec):
    if not sec or sec < 0:
        return ""
    m = int(sec // 60)
    s = int(sec - 60 * m)
    return "{}:{:02d}".format(m, s)


def truncate_str(s, n):
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n - 1] + "..."


# =====================================================================
# Section I -- Render job model + FIFO worker thread
# =====================================================================

KIND_IMAGE = "image"
KIND_VIDEO = "video"

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 50-cap applies only to in-flight jobs (defensive against runaway).
ACTIVE_CAP = 50


def _resolve_video_url(url):
    """Convert relative API URLs to absolute. Returns (absolute_url, needs_auth).

    Today video URLs come back as public Vercel Blob URLs (no auth needed).
    If the web team ever returns /api/-relative URLs for signed downloads,
    needs_auth=True signals the download helper to attach the bearer token --
    when the helper grows that capability. Currently this is informational only.
    """
    if not url:
        return url, False
    needs_auth = url.startswith(RENDER_URL) or url.startswith("/api/")
    if url.startswith("/"):
        url = "{}{}".format(RENDER_URL, url)
    return url, needs_auth


def cleanup_old_captures(dump_root, max_age_days=7):
    """Delete capture_* folders older than max_age_days from the dump root.

    Each Update Capture writes a fresh `capture_<ts>/` folder; over months of
    daily use this becomes unbounded disk growth (Round 2 P1 -- capture folder
    leak). Call on dialog open. Safe -- only removes capture_* folders.
    """
    base = os.path.join(dump_root, "EnneadTab_Ai_Rendering")
    if not os.path.exists(base):
        return 0
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for entry in os.listdir(base):
        if not entry.startswith("capture_"):
            continue
        path = os.path.join(base, entry)
        try:
            if os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                deleted += 1
        except Exception:
            continue
    return deleted


def _inflight_dir():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(appdata, "EnneadTab", "ai_inflight")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def _local_only_dir():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(appdata, "EnneadTab", "ai_renders_local_only")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


class RenderJob(object):
    """One render request. Status fields mutate; rest is immutable post-construction."""

    __slots__ = (
        "job_id", "kind", "host",
        "original_path", "prompt", "style_preset", "style_ref_path",
        "aspect_ratio", "long_edge", "view_name", "is_interior",
        "video_duration", "video_resolution",
        "status", "progress_pct", "started_at", "finished_at",
        "error_msg", "result_path", "poster_path", "gallery_id",
        "auto_save_gallery", "job_folder", "created_at",
    )

    def __init__(self, original_path, prompt, style_preset=None,
                 style_ref_path=None, aspect_ratio="16:9", long_edge=1500,
                 view_name="", is_interior=False, kind=KIND_IMAGE, host="revit",
                 video_duration=4, video_resolution="720p",
                 auto_save_gallery=True):
        self.job_id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.host = host
        self.original_path = original_path
        self.prompt = prompt or ""
        self.style_preset = style_preset or ""
        self.style_ref_path = style_ref_path
        self.aspect_ratio = aspect_ratio
        self.long_edge = int(long_edge or 1500)
        self.view_name = view_name or ""
        self.is_interior = bool(is_interior)
        self.video_duration = int(video_duration or 4)
        self.video_resolution = video_resolution or "720p"
        self.status = STATUS_PENDING
        self.progress_pct = 0
        self.started_at = None
        self.finished_at = None
        self.error_msg = None
        self.result_path = None
        self.poster_path = None
        self.gallery_id = None
        self.auto_save_gallery = bool(auto_save_gallery)
        self.created_at = time.time()
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.job_folder = os.path.join(_inflight_dir(), "{}_{}".format(ts, self.job_id))
        if not os.path.exists(self.job_folder):
            try:
                os.makedirs(self.job_folder)
            except Exception:
                pass

    def elapsed_sec(self):
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at else time.time()
        return max(0.0, end - self.started_at)

    _sidecar_lock = None  # class attr -- created lazily, shared across instances

    def write_sidecar(self):
        """Write prompt.json next to result. Lock-guarded so the worker, the
        upload_worker success branch, and the upload_worker failure branch
        can't race (Round 3 P2-1 -- three concurrent writers caused silent
        IOException + missing gallery_id in some sidecars)."""
        # Lazy class-level lock so we don't change __init__ signature.
        if RenderJob._sidecar_lock is None:
            RenderJob._sidecar_lock = System.Object() if System is not None else object()
        side = os.path.join(self.job_folder, "result.prompt.json")
        if Monitor is not None:
            Monitor.Enter(RenderJob._sidecar_lock)
        try:
            with io.open(side, "w", encoding="utf-8") as f:
                json.dump({
                    "job_id": self.job_id, "kind": self.kind, "host": self.host,
                    "prompt": self.prompt, "style_preset": self.style_preset,
                    "style_ref_path": self.style_ref_path or "",
                    "aspect_ratio": self.aspect_ratio, "long_edge": self.long_edge,
                    "view_name": self.view_name, "is_interior": self.is_interior,
                    "video_duration": self.video_duration,
                    "video_resolution": self.video_resolution,
                    "created_at": self.created_at, "started_at": self.started_at,
                    "finished_at": self.finished_at, "elapsed_sec": self.elapsed_sec(),
                    "status": self.status,
                    "result_path": self.result_path or "",
                    "poster_path": self.poster_path or "",
                    "gallery_id": self.gallery_id or "",
                }, f, indent=2, ensure_ascii=True)
        except Exception:
            pass
        finally:
            if Monitor is not None:
                try:
                    Monitor.Exit(RenderJob._sidecar_lock)
                except Exception:
                    pass


class QueueWorker(object):
    """Background FIFO worker. Construct one per kind (image / video) so a
    long video doesn't block a short image (Review #2 design tradeoff A).
    Uses System.Threading.Lock for queue mutation, AutoResetEvent for wake/pause,
    and asks the caller to handle UI marshalling.
    """

    def __init__(self, kind_filter, jobs_list, lock_obj,
                 invoke_ui, job_update_callback,
                 is_form_closed_fn, auto_save_enabled_fn=None,
                 on_completion=None):
        # auto_save_enabled_fn is kept as a backward-compat stub so existing
        # AiRenderForm.__init__ calls don't have to change. The worker never
        # reads it -- auto-save is locked at queue time on `job.auto_save_gallery`
        # (Round 3 audit P2-4 noted the parameter was dead).
        self._kind_filter = kind_filter
        self._jobs = jobs_list
        self._lock = lock_obj
        self._invoke_ui = invoke_ui  # not currently used here -- callers marshal in callbacks
        self._on_job_update = job_update_callback
        self._is_form_closed = is_form_closed_fn
        self._auto_save_enabled = auto_save_enabled_fn  # kept for caller back-compat; never read
        self._on_completion = on_completion
        self._wake = AutoResetEvent(False)
        self._paused = [False]
        self._stop_flag = [False]
        self._thread = None
        self._last_progress_ms = [0]

    def start(self):
        if self._thread is not None:
            return
        self._thread = Thread(ThreadStart(self._run))
        self._thread.IsBackground = True
        self._thread.Start()

    def wake(self):
        try:
            self._wake.Set()
        except Exception:
            pass

    def pause(self):
        self._paused[0] = True

    def resume(self):
        self._paused[0] = False
        self.wake()

    def stop(self):
        self._stop_flag[0] = True
        self.wake()

    def _next_pending(self):
        Monitor.Enter(self._lock)
        try:
            for j in self._jobs:
                if j.kind == self._kind_filter and j.status == STATUS_PENDING:
                    return j
            return None
        finally:
            Monitor.Exit(self._lock)

    def _set_status(self, job, status, **fields):
        Monitor.Enter(self._lock)
        try:
            job.status = status
            for k, v in fields.items():
                setattr(job, k, v)
        finally:
            Monitor.Exit(self._lock)
        try:
            self._on_job_update(job)
        except Exception:
            pass

    def _throttled_progress(self, job, pct, text=None):
        """Coalesce to ~100ms updates so the UI thread doesn't get hammered."""
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_progress_ms[0] < 100:
            return
        self._last_progress_ms[0] = now_ms
        Monitor.Enter(self._lock)
        try:
            job.progress_pct = int(max(0, min(100, pct)))
        finally:
            Monitor.Exit(self._lock)
        try:
            self._on_job_update(job)
        except Exception:
            pass

    def _run_one_image(self, job, token):
        def progress_callback(msg):
            if self._is_form_closed():
                return
            pct = job.progress_pct
            if "%" in msg:
                try:
                    pct = int(msg.split()[-1].rstrip("%"))
                except Exception:
                    pass
            self._throttled_progress(job, pct)

        try:
            images = render_image_with_token(
                token, job.original_path, job.prompt,
                aspect_ratio=job.aspect_ratio,
                style_image_path=job.style_ref_path,
                progress_callback=progress_callback)
        except AIRequestError as e:
            if e.status_code == 401:
                AUTH.clear_token()
                self.pause()
                self._set_status(job, STATUS_PENDING,
                                 error_msg="Auth expired. Queue paused -- sign in and resume.")
                return False
            self._set_status(job, STATUS_FAILED, error_msg=str(e)[:500])
            return False

        if not images:
            self._set_status(job, STATUS_FAILED, error_msg="No images returned from server")
            return False

        img = images[0]
        ext = ".png" if "png" in (img.get("mime") or "image/png") else ".jpg"
        result_path = os.path.join(job.job_folder, "result" + ext)
        try:
            with open(result_path, "wb") as f:
                f.write(base64.b64decode(img.get("b64", "")))
        except Exception as e:
            self._set_status(job, STATUS_FAILED,
                             error_msg="Failed to write result: {}".format(e))
            return False

        job.result_path = result_path
        self._set_status(job, STATUS_DONE,
                         finished_at=time.time(), progress_pct=100)

        # Always write the local sidecar -- gives every render full
        # reproducibility metadata regardless of cloud save (Audit P1 -- NDA
        # mode previously had BETTER metadata than the default cloud path).
        try:
            job.write_sidecar()
        except Exception:
            pass

        # Lock the auto-save decision at queue time (job.auto_save_gallery is
        # captured in __init__). Don't read the live callable here -- that would
        # let mid-batch toggle changes silently flip already-queued jobs
        # (Audit P0 -- auto-save toggle had asymmetric mid-batch semantics).
        if job.auto_save_gallery:
            # Off-worker upload so the next queued render starts immediately.
            def upload_worker(state):
                try:
                    # 2026-04-28 -- pass full job context so the History
                    # row can render style/view/resolution/duration etc.
                    # Without these the cloud row shows only prompt + date.
                    duration_ms = None
                    try:
                        if getattr(job, "started_at", None):
                            duration_ms = int(
                                (time.time() - float(job.started_at)) * 1000)
                    except Exception:
                        duration_ms = None
                    resp = save_to_gallery_with_token(
                        token, result_path, job.prompt,
                        mode="image", style_name=job.style_preset,
                        view_name=job.view_name,
                        original_path=job.original_path,
                        aspect_ratio=getattr(job, "aspect_ratio", None),
                        long_edge=getattr(job, "long_edge", None),
                        host=getattr(job, "host", None),
                        is_interior=getattr(job, "is_interior", None),
                        duration_ms=duration_ms,
                        used_style_ref=bool(getattr(job, "style_ref_path", None)))
                    gid = (resp.get("item") or {}).get("id") or resp.get("id")
                    if gid:
                        Monitor.Enter(self._lock)
                        try:
                            job.gallery_id = gid
                        finally:
                            Monitor.Exit(self._lock)
                        # Re-write sidecar now that gallery_id is known --
                        # otherwise sidecar always has gallery_id="" on the
                        # success path (Round 2 P1-state-6).
                        try:
                            job.write_sidecar()
                        except Exception:
                            pass
                        try:
                            self._on_job_update(job)
                        except Exception:
                            pass
                except Exception as e:
                    Monitor.Enter(self._lock)
                    try:
                        job.error_msg = "Gallery save failed: {}".format(str(e)[:200])
                    finally:
                        Monitor.Exit(self._lock)
                    # Split sidecar + UI callback into separate try blocks so a
                    # WPF/Eto Dispatcher exception in _on_job_update can't kill
                    # the sidecar write. _on_job_update on Revit hits Monitor +
                    # multiple _invoke_ui calls; any unhandled exception there
                    # propagates to the .NET ThreadPool and crashes Revit with
                    # 0xE0434352 (Mac/Eto is more forgiving). Belt and braces.
                    try:
                        job.write_sidecar()
                    except Exception:
                        pass
                    try:
                        self._on_job_update(job)
                    except Exception:
                        pass
            System.Threading.ThreadPool.QueueUserWorkItem(
                System.Threading.WaitCallback(upload_worker))
        else:
            # Local-only path (NDA mode) -- copy + sidecar.
            try:
                local_only = _local_only_dir()
                ts = time.strftime("%Y%m%d-%H%M%S")
                dest_dir = os.path.join(local_only, "{}_{}".format(ts, job.job_id))
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                shutil.copy2(job.original_path,
                             os.path.join(dest_dir, os.path.basename(job.original_path)))
                shutil.copy2(result_path,
                             os.path.join(dest_dir, os.path.basename(result_path)))
                job.job_folder = dest_dir
                job.result_path = os.path.join(dest_dir, os.path.basename(result_path))
                job.write_sidecar()
            except Exception:
                pass
        return True

    def _run_one_video(self, job, token):
        try:
            resp = render_video_with_token(
                token, job.original_path, job.prompt,
                duration_sec=job.video_duration,
                resolution=job.video_resolution,
                progress_callback=lambda msg: self._throttled_progress(job, job.progress_pct))
        except AIRequestError as e:
            if e.status_code == 401:
                AUTH.clear_token()
                self.pause()
                self._set_status(job, STATUS_PENDING,
                                 error_msg="Auth expired. Queue paused -- sign in and resume.")
                return False
            self._set_status(job, STATUS_FAILED, error_msg=str(e)[:500])
            return False

        video_url = (resp.get("item") or {}).get("videoUrl") or resp.get("videoUrl")
        poster_url = (resp.get("item") or {}).get("posterUrl") or resp.get("posterUrl")
        gallery_id = (resp.get("item") or {}).get("id") or resp.get("id")

        if video_url:
            video_path = os.path.join(job.job_folder, "result.mp4")
            try:
                resolved, _needs_auth = _resolve_video_url(video_url)
                download_url_to_file(resolved, video_path)
                job.result_path = video_path
            except Exception as ex:
                # Surface the failure rather than swallowing it; the cloud
                # copy still exists, but the user has no local file.
                Monitor.Enter(self._lock)
                try:
                    job.error_msg = "Video saved to Gallery but local download failed: {}".format(
                        str(ex)[:200])
                finally:
                    Monitor.Exit(self._lock)
        if poster_url:
            poster_path = os.path.join(job.job_folder, "poster.jpg")
            try:
                resolved, _needs_auth = _resolve_video_url(poster_url)
                download_url_to_file(resolved, poster_path)
                job.poster_path = poster_path
            except Exception:
                pass  # poster is non-critical, fall through to text-only row
        if gallery_id:
            job.gallery_id = gallery_id

        self._set_status(job, STATUS_DONE,
                         finished_at=time.time(), progress_pct=100)
        # Always write sidecar for video too (parity with image path --
        # Round 2 P1-state-6 noted videos had no sidecar).
        try:
            job.write_sidecar()
        except Exception:
            pass
        return True

    def _run(self):
        while not self._stop_flag[0]:
            if self._paused[0]:
                self._wake.WaitOne(1000)
                continue
            job = self._next_pending()
            if not job:
                self._wake.WaitOne(10000)
                continue
            self._set_status(job, STATUS_ACTIVE,
                             started_at=time.time(), progress_pct=0)
            token = AUTH.get_token()
            if not token:
                self.pause()
                self._set_status(job, STATUS_PENDING,
                                 error_msg="Not signed in. Sign in and click Resume.")
                continue
            if job.kind == KIND_IMAGE:
                success = self._run_one_image(job, token)
            elif job.kind == KIND_VIDEO:
                success = self._run_one_video(job, token)
            else:
                self._set_status(job, STATUS_FAILED,
                                 error_msg="Unknown job kind: {}".format(job.kind))
                success = False
            try:
                if success and self._on_completion:
                    self._on_completion(job)
            except Exception:
                pass


def count_inflight(jobs, lock_obj):
    Monitor.Enter(lock_obj)
    try:
        return sum(1 for j in jobs
                   if j.status in (STATUS_PENDING, STATUS_ACTIVE))
    finally:
        Monitor.Exit(lock_obj)


def can_enqueue(jobs, lock_obj):
    return count_inflight(jobs, lock_obj) < ACTIVE_CAP


def play_completion_sound():
    try:
        SOUND.play_sound("sound_effect_popup_msg3.wav")
    except Exception:
        pass
