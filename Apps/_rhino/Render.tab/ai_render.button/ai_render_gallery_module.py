# -*- coding: utf-8 -*-
"""Eto.Drawing bitmap loaders + GalleryRow view-model for the Rhino dialog.

All cloud fetch / cache / filter / sort / format logic lives in
EnneadTab.AI.AI_RENDER (shared with the Revit dialog). This file only owns
parts that touch Eto types: Eto.Drawing.Bitmap, Eto.Drawing.Color hex strings.

The Rhino UI uses Scrollable + StackLayout of custom row panels rather than
Eto.GridView (per Review #1) because Eto's GridView has variable-row-height
and per-cell-button limitations on IronPython. Rows are read directly from
field accessors — no WPF-style binding.

IronPython 2.7 — no f-strings, type hints, pathlib.
"""

import os
import base64
import time
import tempfile

import Eto # pyright: ignore

# 2026-04-28 — sibling-import baseline trace. If view2render_left.py logs
# this on dialog-open, sibling-module imports from .button/ are working.
# That isolates the viewer-import question: if THIS line shows up but
# the viewer's "loaded OK" line doesn't, the viewer file specifically
# has a problem (typo, syntax, missing class), not the import system.
try:
    import Rhino  # pyright: ignore
    Rhino.RhinoApp.WriteLine("[ai_render] gallery module loaded OK")
except Exception:
    pass

# Re-export shared helpers so the main script can stay terse.
from EnneadTab.AI.AI_RENDER import ( # noqa: F401
    DATE_FILTERS,
    DEFAULT_DATE_FILTER,
    cache_dir,
    item_cache_dir,
    cache_size_bytes,
    clear_cache,
    write_data_url_to_file,
    filter_rows,
    fetch_gallery_index_async as _shared_fetch_index_async,
    fetch_full_item_async as _shared_fetch_full_async,
    fmt_bytes,
    fmt_elapsed,
    truncate_str as truncate,
)


# ---------- Eto bitmap loaders ----------

# (2026-04-21) The previous implementation cached Eto.Drawing.Bitmap instances
# keyed on (path, mtime, max_w, max_h) and returned the SAME instance to
# multiple ImageViews across rebuilds. When `_rebuild_rows()` clears the
# StackLayout, the Eto WinForms backend disposes child ImageViews, which on
# some platforms releases the underlying GDI+ Bitmap handle. The next rebuild
# then assigns the SAME (now-disposed) Bitmap to a fresh ImageView, and the
# next paint pass crashes Rhino with a native AccessViolation. The Round 3
# perf rationale (avoid disk re-read on 1 Hz tick rebuilds) is preserved by
# constructing a fresh Bitmap each call — Eto.Drawing.Bitmap(path) for a
# small thumbnail is cheap (sub-millisecond from OS file cache after first
# load). If perf becomes a problem again, cache the RAW BYTES, not the
# Bitmap, and reconstruct per call.
def _thumb_trace(msg):
    # 2026-04-21 — trace why thumbnails come back None. Same target file
    # as view2render_left's _trace so the breadcrumb is unified.
    try:
        import os as _os
        from datetime import datetime as _dt
        base = _os.environ.get("APPDATA") or _os.path.expanduser("~")
        d = _os.path.join(base, "EnneadTab")
        if not _os.path.isdir(d):
            try: _os.makedirs(d)
            except Exception: pass
        p = _os.path.join(d, "ai_render_trace.log")
        f = open(p, "a")
        try:
            f.write("{}  thumb.{}\n".format(
                _dt.now().strftime("%H:%M:%S.%f")[:-3], msg))
            f.flush()
        finally:
            f.close()
    except Exception:
        pass


def bitmap_from_path(path, max_w=None, max_h=None):
    """Load a fresh Eto.Drawing.Bitmap from a file path. Never shares
    instances across callers — sharing causes GDI+ AccessViolation on
    rebuild because Eto disposes the bitmap when its owning ImageView is
    removed from the StackLayout."""
    if not path:
        _thumb_trace("MISS no_path")
        return None
    if not os.path.exists(path):
        _thumb_trace("MISS not_exist {}".format(path))
        return None
    try:
        bmp = Eto.Drawing.Bitmap(path)
        if max_w and max_h:
            try:
                bmp = bmp.WithSize(max_w, max_h)
            except Exception as ex:
                _thumb_trace("WITHSIZE_FAIL {} {}".format(path, ex))
                # Return the un-resized bitmap rather than nothing
        return bmp
    except Exception as ex:
        _thumb_trace("CTOR_FAIL {} {}".format(path, ex))
        return None


def bitmap_from_data_url(data_url, max_w=None, max_h=None):
    """Load Eto.Drawing.Bitmap from a base64 data URL.

    Eto's stream-based constructor is unreliable on IronPython; we round-trip
    via a temp file (cheap, only used for ~50 thumbnails on dialog open).
    """
    if not data_url:
        return None
    try:
        if "," in data_url:
            b64 = data_url.split(",", 1)[1]
        else:
            b64 = data_url
        buf = base64.b64decode(b64)
        fd, tmp = tempfile.mkstemp(suffix=".webp")
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(buf)
            bmp = Eto.Drawing.Bitmap(tmp)
            if max_w and max_h:
                bmp = bmp.WithSize(max_w, max_h)
            return bmp
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception:
        return None


# ---------- GalleryRow ----------

# Default (large) thumb size. Can be overridden at runtime by the dialog
# via set_thumb_size() — toggling between large (240x160, default) and
# small (84x60) preview modes. Default flipped to large 2026-04-22 because
# small thumbs hid composition details that users needed to verify the
# AI render matched their intent before downloading.
THUMB_W_SMALL, THUMB_H_SMALL = 84, 60
THUMB_W_LARGE, THUMB_H_LARGE = 240, 160
THUMB_W, THUMB_H = THUMB_W_LARGE, THUMB_H_LARGE


def set_thumb_size(w, h):
    """Set the thumb size used by row_from_job / row_from_cloud_item. The
    dialog calls this before _rebuild_rows when the user toggles preview
    size; subsequent row construction reads the new globals."""
    global THUMB_W, THUMB_H
    THUMB_W, THUMB_H = int(w), int(h)


class GalleryRow(object):
    """One row in the Rhino gallery panel. Same shape as the Revit version
    so the main scripts share field names — only the visibility/color types
    differ (bool here vs WPF Visibility strings)."""

    __slots__ = (
        "id", "kind", "created_at",
        "OriginalThumb", "ResultThumb", "KindIcon",
        "StyleName", "PromptPreview", "Subtitle",
        "StatusText", "StatusColor", "ProgressPct", "ProgressVisibility",
        "ProgressIndeterminate", "SaveVisibility",
        "original_path", "result_path", "full_prompt",
        "view_name", "host", "job_ref", "cloud_item",
    )

    def __init__(self):
        self.id = None
        self.kind = "image"
        self.created_at = 0
        self.OriginalThumb = None
        self.ResultThumb = None
        self.KindIcon = ""
        self.StyleName = ""
        self.PromptPreview = ""
        self.Subtitle = ""
        self.StatusText = ""
        self.StatusColor = "#FFFFFF"
        self.ProgressPct = 0
        self.ProgressVisibility = False
        self.ProgressIndeterminate = False
        self.SaveVisibility = False
        self.original_path = None
        self.result_path = None
        self.full_prompt = ""
        self.view_name = ""
        self.host = ""
        self.job_ref = None
        self.cloud_item = None


def row_from_job(job):
    r = GalleryRow()
    r.id = job.job_id
    r.kind = job.kind
    r.created_at = job.created_at
    r.KindIcon = "🎬" if job.kind == "video" else ""
    r.StyleName = job.style_preset or "Custom"
    # PromptPreview now carries the full text; the row label uses WrapMode.Word.
    r.PromptPreview = job.prompt
    # full_prompt is what the row label actually renders (with WrapMode.Word).
    # PromptPreview is kept on the type for any callers that still want the
    # truncated form, but the Rhino UI uses full_prompt for wrap-display.
    r.full_prompt = job.prompt
    r.view_name = job.view_name
    r.host = job.host
    r.original_path = job.original_path
    r.result_path = job.result_path
    r.OriginalThumb = bitmap_from_path(job.original_path, THUMB_W, THUMB_H)
    r.ResultThumb = bitmap_from_path(job.result_path, THUMB_W, THUMB_H) if job.result_path else None
    r.job_ref = job

    st = job.status
    elapsed = fmt_elapsed(job.elapsed_sec())
    if st == "pending":
        r.StatusText = "⏳ waiting"
        r.StatusColor = "#9A9A9A"
    elif st == "active":
        r.StatusText = "⚡ {}".format(elapsed) if elapsed else "⚡ 0:00"
        r.StatusColor = "#FFE59C"
        r.ProgressVisibility = True
        r.ProgressPct = job.progress_pct
        r.ProgressIndeterminate = (job.progress_pct == 0)
    elif st == "done":
        r.StatusText = "✓ {}".format(elapsed)
        r.StatusColor = "#88DD88"
        r.SaveVisibility = True
    elif st == "failed":
        r.StatusText = "✗ {}".format(elapsed or "")
        r.StatusColor = "#FF8888"

    style_ref = ""
    if job.style_ref_path:
        style_ref = " · ref: " + os.path.basename(job.style_ref_path)
    r.Subtitle = "{} · {} · {}px{}".format(
        job.host, job.aspect_ratio, job.long_edge, style_ref)
    return r


def row_from_cloud_item(item):
    # 2026-04-28 — Subtitle enriched to match the local-job row format
    # (host / aspect / longEdge / duration / style-ref / interior). All
    # values come from `item.metadata` populated by the new client
    # save_to_gallery_with_token() call. Old items where these were
    # never sent fall back gracefully to date-only.
    r = GalleryRow()
    r.id = item.get("id")
    meta = item.get("metadata") or {}
    r.kind = meta.get("type") or "image"
    created_ms = item.get("createdAt") or 0
    r.created_at = float(created_ms) / 1000.0 if created_ms else 0
    r.KindIcon = "🎬" if r.kind == "video" else ""
    r.full_prompt = item.get("promptPreview") or ""
    r.PromptPreview = r.full_prompt  # full text — Rhino label wraps
    # Prefer the user's saved-prompt title over the raw prompt-preset
    # name when both exist; "My Tower Night v2" is more meaningful than
    # "Night View" for a row the user authored themselves.
    r.StyleName = (meta.get("promptTitle")
                   or meta.get("styleName") or "—")
    r.view_name = meta.get("viewName") or ""
    r.host = meta.get("host") or "web"
    thumb_data = item.get("thumbnailData") or item.get("thumbnailVideo")
    orig_thumb_data = (
        item.get("originalThumbnailData") or meta.get("originalThumbnailData")
    )
    r.OriginalThumb = (
        bitmap_from_data_url(orig_thumb_data, THUMB_W, THUMB_H)
        if orig_thumb_data else None
    )
    r.ResultThumb = bitmap_from_data_url(thumb_data, THUMB_W, THUMB_H)
    r.StatusText = "✓"
    if meta.get("durationMs"):
        try:
            secs = int(meta["durationMs"]) // 1000
            r.StatusText = "✓ {}:{:02d}".format(secs // 60, secs % 60)
        except Exception:
            pass
    r.StatusColor = "#88DD88"
    r.SaveVisibility = True

    # Build the rich subtitle. Falls back to date-only if no metadata.
    parts = []
    if r.view_name:
        parts.append(r.view_name)
    if meta.get("aspectRatio"):
        parts.append(str(meta["aspectRatio"]))
    if meta.get("longEdge"):
        parts.append("{}px".format(meta["longEdge"]))
    if r.host and r.host != "web":
        parts.append(r.host)
    if meta.get("isInterior"):
        parts.append("interior")
    if meta.get("usedStyleRef"):
        parts.append("ref")
    ts = time.localtime(r.created_at) if r.created_at else None
    date_str = time.strftime("%Y-%m-%d %H:%M", ts) if ts else ""
    if parts:
        r.Subtitle = " · ".join(parts) + ("  ·  " + date_str if date_str else "")
    else:
        r.Subtitle = date_str
    r.cloud_item = item
    return r


def fetch_gallery_index_async(token, on_done, limit=200, offset=0):
    def shim(items):
        if items is None:
            on_done(None)
            return
        on_done([row_from_cloud_item(i) for i in items])
    _shared_fetch_index_async(token, shim, limit=limit, offset=offset)


def fetch_full_item_async(token, item_id, on_done):
    def shim(path):
        bmp = bitmap_from_path(path) if path else None
        on_done(bmp, path)
    _shared_fetch_full_async(token, item_id, shim)
