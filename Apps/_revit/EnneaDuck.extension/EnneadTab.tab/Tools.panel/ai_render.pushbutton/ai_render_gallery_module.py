# -*- coding: utf-8 -*-
"""WPF-side bitmap loaders + GalleryRow view-model for the Revit dialog.

All cloud fetch / cache / filter / sort / format logic lives in
EnneadTab.AI.AI_RENDER (shared with the Rhino dialog). This file only owns
the parts that touch WPF types: BitmapImage, Visibility strings, color
strings used by DataTemplate bindings.

IronPython 2.7 — no f-strings, type hints, pathlib.
"""

import os
import base64
import time

import clr # pyright: ignore
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System # pyright: ignore
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption # pyright: ignore

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


# ---------- WPF bitmap loaders ----------

# 2026-05-12: High-frequency refresh optimization. Re-loading bitmaps for
# every row on every second's tick was tanking Revit performance.
_BITMAP_CACHE = {}


def bitmap_from_path(path):
    """Frozen WPF BitmapImage from local disk path. Cached to prevent
    redundant I/O on UI refresh ticks. Thread-safe (Freeze()).
    """
    if not path or not os.path.exists(path):
        return None

    # Key by path + mtime so if the file changes (e.g. render completes)
    # the cache is busted automatically.
    try:
        mtime = os.path.getmtime(path)
        cache_key = (path, mtime)
        if cache_key in _BITMAP_CACHE:
            return _BITMAP_CACHE[cache_key]

        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.UriSource = System.Uri(os.path.abspath(path))
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()

        # Keep cache size manageable — this module is short-lived anyway.
        if len(_BITMAP_CACHE) > 200:
            _BITMAP_CACHE.clear()
        _BITMAP_CACHE[cache_key] = bmp
        return bmp
    except Exception:
        return None


def bitmap_from_data_url(data_url):
    """Frozen WPF BitmapImage from base64 data URL (gallery/index thumbs).
    Cached by string content.
    """
    if not data_url:
        return None

    # Key by full string — base64 thumbs are small (~5-10KB).
    if data_url in _BITMAP_CACHE:
        return _BITMAP_CACHE[data_url]

    try:
        if "," in data_url:
            b64 = data_url.split(",", 1)[1]
        else:
            b64 = data_url
        buf = base64.b64decode(b64)
        ms = System.IO.MemoryStream(System.Array[System.Byte](bytearray(buf)))
        try:
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.StreamSource = ms
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.EndInit()
            bmp.Freeze()
            
            if len(_BITMAP_CACHE) > 200:
                _BITMAP_CACHE.clear()
            _BITMAP_CACHE[data_url] = bmp
            return bmp
        finally:
            ms.Close()
    except Exception:
        return None


# ---------- GalleryRow view-model bound to ListView DataTemplate ----------

class GalleryRow(object):
    """One ListView row. Wholesale-rebuild ItemsSource on update (Review #1).

    IronPython classes don't auto-implement INotifyPropertyChanged; replacing
    the items list is simpler and performs fine for <5k rows.
    """

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
        self.StatusColor = "#FFFFFFFF"
        self.ProgressPct = 0
        self.ProgressVisibility = "Collapsed"
        self.ProgressIndeterminate = False
        self.SaveVisibility = "Collapsed"
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
    # Don't truncate — the row TextBlock now uses TextWrapping="Wrap" so
    # the full prompt is visible. PromptPreview kept as the binding name for
    # historical reasons; it now carries the full text.
    r.PromptPreview = job.prompt
    r.full_prompt = job.prompt
    r.view_name = job.view_name
    r.host = job.host
    r.original_path = job.original_path
    r.result_path = job.result_path
    r.OriginalThumb = bitmap_from_path(job.original_path)
    r.ResultThumb = bitmap_from_path(job.result_path) if job.result_path else None
    r.job_ref = job

    st = job.status
    elapsed = fmt_elapsed(job.elapsed_sec())
    if st == "pending":
        r.StatusText = "⏳ waiting"
        r.StatusColor = "#FF9A9A9A"
        r.ProgressVisibility = "Collapsed"
    elif st == "active":
        r.StatusText = "⚡ {}".format(elapsed) if elapsed else "⚡ 0:00"
        r.StatusColor = "#FFFFE59C"
        r.ProgressVisibility = "Visible"
        r.ProgressPct = job.progress_pct
        r.ProgressIndeterminate = (job.progress_pct == 0)
    elif st == "done":
        r.StatusText = "✓ {}".format(elapsed)
        r.StatusColor = "#FF88DD88"
        r.ProgressVisibility = "Collapsed"
        r.SaveVisibility = "Visible"
    elif st == "failed":
        r.StatusText = "✗ {}".format(elapsed or "")
        r.StatusColor = "#FFFF8888"
        r.ProgressVisibility = "Collapsed"

    style_ref = ""
    if job.style_ref_path:
        style_ref = " · ref: " + os.path.basename(job.style_ref_path)
    r.Subtitle = "{} · {} · {}px{}".format(
        job.host, job.aspect_ratio, job.long_edge, style_ref)
    return r


def row_from_cloud_item(item):
    r = GalleryRow()
    r.id = item.get("id")
    r.kind = (item.get("metadata") or {}).get("type") or "image"
    created_ms = item.get("createdAt") or 0
    r.created_at = float(created_ms) / 1000.0 if created_ms else 0
    r.KindIcon = "🎬" if r.kind == "video" else ""
    r.full_prompt = item.get("promptPreview") or ""
    r.PromptPreview = r.full_prompt  # full text — TextBlock wraps
    r.StyleName = (item.get("metadata") or {}).get("styleName") or "—"
    r.view_name = (item.get("metadata") or {}).get("viewName") or ""
    r.host = (item.get("metadata") or {}).get("host") or "web"
    thumb_data = item.get("thumbnailData") or item.get("thumbnailVideo")
    meta = item.get("metadata") or {}
    orig_thumb_data = (
        item.get("originalThumbnailData") or meta.get("originalThumbnailData")
    )
    r.OriginalThumb = (
        bitmap_from_data_url(orig_thumb_data) if orig_thumb_data else None
    )
    r.ResultThumb = bitmap_from_data_url(thumb_data)
    r.StatusText = "✓"
    r.StatusColor = "#FF88DD88"
    r.ProgressVisibility = "Collapsed"
    r.SaveVisibility = "Visible"
    ts = time.localtime(r.created_at) if r.created_at else None
    r.Subtitle = time.strftime("%Y-%m-%d %H:%M", ts) if ts else ""
    r.cloud_item = item
    return r


# ---------- Async fetchers (wrap shared helpers, return platform rows) ----------

def fetch_gallery_index_async(token, on_done, limit=200, offset=0):
    """Wrap shared fetch — turn raw items into platform-specific rows."""
    def shim(items):
        if items is None:
            on_done(None)
            return
        on_done([row_from_cloud_item(i) for i in items])
    _shared_fetch_index_async(token, shim, limit=limit, offset=offset)


def fetch_full_item_async(token, item_id, on_done):
    """Wrap shared fetch — load WPF BitmapImage for the downloaded path."""
    def shim(path):
        bmp = bitmap_from_path(path) if path else None
        on_done(bmp, path)
    _shared_fetch_full_async(token, item_id, shim)
