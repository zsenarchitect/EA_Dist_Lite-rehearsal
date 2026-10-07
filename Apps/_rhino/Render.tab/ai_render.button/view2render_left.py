# -*- coding: utf-8 -*-
__title__ = "AiRenderingFromView"
__doc__ = """View rendering for Rhino through Ennead's in-house style library.

Capture the active viewport, queue prompts, and see your full cloud Gallery
across every device (Revit, Rhino, mobile web, desktop web - same items).

All features call the live ennead-ai.com web API. No local fallbacks: when
the web product improves, this dialog improves automatically.
"""

import time
import os
import shutil
import webbrowser

import Rhino # pyright: ignore
import scriptcontext as sc
import Eto # pyright: ignore
import System # pyright: ignore
from System.Threading import Monitor # pyright: ignore

from EnneadTab import FOLDER, IMAGE  # noqa: F401
from EnneadTab import LOG, ERROR_HANDLE, AUTH
from EnneadTab.AI import AI_CHAT, AI_RENDER
from EnneadTab.AI._common import AIRequestError  # noqa: F401
from EnneadTab.RHINO import RHINO_UI

import ai_render_gallery_module as G

# Native Eto image viewer (2026-04-28). Imported at script-load time so a
# missing/broken module surfaces immediately on the Rhino command line
# instead of silently falling through to os.startfile every time the
# user clicks a thumbnail. _SHOW_VIEWER stays None on import failure so
# callers know to use the legacy path.
#
# 2026-04-28 v3 — explicitly invalidate sys.modules entry FOR EVERY
# sibling module on each dialog open. Rhino's IronPython script engine
# holds onto previously-loaded modules even after _-RunPythonScript
# ResetEngine. v2 only invalidated the viewer; gallery_module changes
# (row metadata, materialize_thumb, etc.) were silently no-ops because
# the cached version kept loading.
# 2026-04-30 v4 — extended the invalidation list to cover the lib
# modules touched by Phase A: EnneadTab.COLOR (added hex_to_rgba) and
# EnneadTab.RHINO.RHINO_UI (added hex_to_eto_color). Without this, a
# stale-cache user picks up b9f22fc06's new lib symbols against the
# old in-memory module dict, raising AttributeError on first call OR
# silently routing to the old _hex_to_color path. Add new entries
# here whenever a lib module is touched by an AI Render iteration.
import sys as _sys
import time as _t_modload
_AI_RENDER_LOAD_TS = _t_modload.strftime("%H:%M:%S")
_STALE_MODULES = (
    "ai_render_image_viewer",
    "ai_render_gallery_module",
    "EnneadTab.COLOR",
    "EnneadTab.IMAGE",  # 2026-04-30: copy_image_to_clipboard added
    "EnneadTab.RHINO.RHINO_UI",
    "EnneadTab.RHINO",  # parent package - forces reimport of children
)
for _stale in _STALE_MODULES:
    if _stale in _sys.modules:
        try:
            del _sys.modules[_stale]
        except Exception:
            pass
_SHOW_VIEWER = None
try:
    from ai_render_image_viewer import show_viewer as _SHOW_VIEWER
    Rhino.RhinoApp.WriteLine(
        "[ai_render] view2render_left.py loaded {} (viewer OK)".format(
            _AI_RENDER_LOAD_TS))
except Exception as _viewer_import_ex:
    try:
        Rhino.RhinoApp.WriteLine(
            "[ai_render] native image viewer FAILED to import: {} - "
            "thumbnails will open in the OS default app instead".format(
                _viewer_import_ex))
    except Exception:
        pass


# 2026-04-21 — Crash tracer. Queue Render is currently crashing Rhino with
# no journal/log to point at. _trace() flushes a timestamped breadcrumb to
# disk so the next crash leaves a trail showing exactly where execution
# died (even if the failure is a native AccessViolation Python can't catch).
# Remove these calls once the crash class is identified and stable.
_TRACE_PATH = None
def _trace(msg):
    global _TRACE_PATH
    try:
        if _TRACE_PATH is None:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            d = os.path.join(base, "EnneadTab")
            try:
                if not os.path.isdir(d):
                    os.makedirs(d)
            except Exception:
                pass
            _TRACE_PATH = os.path.join(d, "ai_render_trace.log")
        f = open(_TRACE_PATH, "a")
        try:
            from datetime import datetime
            f.write("{}  {}\n".format(
                datetime.now().strftime("%H:%M:%S.%f")[:-3], msg))
            f.flush()
        finally:
            f.close()
    except Exception:
        pass


STUDIO_URL = "https://enneadtab.com/rendering"


# 2026-06-04: visible build stamp so we can tell at a glance whether the
# RUNNING code is fresh or a stale distributed copy (Rhino loads from
# EA_Dist, which can lag the dev repo by days). Derived from this file's
# own mtime at import -- no manual bumping, always truthful about the file
# actually loaded. Shown in the footer; if the date looks old, the copy is
# stale and needs re-deploying.
def _compute_build_tag():
    # Newest mtime across every dialog file in this folder (view2render, the
    # image viewer, the gallery module), not just this .py -- so a fix that
    # lands only in ai_render_image_viewer.py still bumps the visible stamp
    # (2026-06-04). Any file change in the button folder moves the stamp.
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        newest = 0
        for fn in os.listdir(d):
            if fn.lower().endswith(".py"):
                try:
                    mt = os.path.getmtime(os.path.join(d, fn))
                    if mt > newest:
                        newest = mt
                except Exception:
                    pass
        if newest <= 0:
            newest = os.path.getmtime(os.path.abspath(__file__))
        return time.strftime("%m-%d %H:%M", time.localtime(newest))
    except Exception:
        return "?"


_BUILD_TAG = _compute_build_tag()


# ----------------------------------------------------------------------
# Preference persistence (2026-04-28)
# ----------------------------------------------------------------------
# Small JSON file in %APPDATA%/EnneadTab/ remembers checkbox + dropdown
# state across sessions so the user only has to set their preferences once.
# Kept tiny and dependency-free; failures fall back to defaults silently.
_PREF_FILE = None
def _pref_path():
    global _PREF_FILE
    if _PREF_FILE is None:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "EnneadTab")
        try:
            if not os.path.isdir(d):
                os.makedirs(d)
        except Exception:
            pass
        _PREF_FILE = os.path.join(d, "ai_render_prefs.json")
    return _PREF_FILE

def _load_prefs():
    import json
    try:
        with open(_pref_path(), "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_prefs(prefs):
    import json
    try:
        with open(_pref_path(), "w") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        pass

RESOLUTION_OPTIONS = [
    ("Low (768 px)", 768),
    ("Medium (1024 px)", 1024),
    ("High (1500 px)", 1500),
    ("Ultra (2048 px)", 2048),
]
ASPECT_OPTIONS = ["16:9", "4:3", "3:2", "1:1", "9:16", "21:9"]
DEFAULT_RESOLUTION_LABEL = "High (1500 px)"
DEFAULT_ASPECT = "16:9"
PROMPT_UNDO_CAP = 10
ROW_HEIGHT = 72


def _compute_px(long_edge, aspect):
    try:
        wp, hp = aspect.split(":")
        w, h = float(wp), float(hp)
    except Exception:
        w, h = 16.0, 9.0
    if w >= h:
        return (int(long_edge), int(round(long_edge * h / w)))
    return (int(round(long_edge * w / h)), int(long_edge))


_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _safe_filename(s):
    out = []
    for c in (s or ""):
        if c in _INVALID_FILENAME_CHARS or ord(c) < 32:
            out.append("_")
        else:
            out.append(c)
    cleaned = "".join(out).strip("_ \t\r\n")
    return (cleaned or "untitled").replace(" ", "_")


def _items_text(dropdown, idx):
    """Defensive accessor for Eto.Forms.DropDown items.

    Some Rhino 7 Eto versions store strings directly when added via
    Items.Add(string); others wrap them in a ListItem with .Text.
    Also guards against -1 / out-of-range indices (Round 2 P2-edge-14).
    """
    if idx is None or idx < 0:
        return ""
    try:
        if idx >= dropdown.Items.Count:
            return ""
        item = dropdown.Items[idx]
    except Exception:
        # If Count or the indexer throws (stale/disposed control), treat as
        # no selection instead of letting the access crash outside the guard.
        return ""
    return getattr(item, "Text", item) if item is not None else ""


def _hex_to_color(hex_str):
    """Eto.Drawing.Color from #RRGGBB or #AARRGGBB hex string.

    Lifted to EnneadTab.RHINO.RHINO_UI.hex_to_eto_color (2026-04-30) so
    the parse logic lives in COLOR.py (framework-agnostic) and the Eto
    construction lives next to other Eto helpers. This local wrapper
    is kept as a thin alias to avoid a sweeping rename across ~40
    callsites in this file. New code should call
    RHINO_UI.hex_to_eto_color directly.
    """
    return RHINO_UI.hex_to_eto_color(hex_str)


class GalleryRowPanel(Eto.Forms.Panel):
    """Custom Eto Panel rendering one GalleryRow. Owns its own buttons + click
    handlers; main form attaches via per-instance lambdas.

    2026-04-21 — Factory pattern (per McNeel forum thread on Eto subclass
    init args, https://discourse.mcneel.com/t/eto-forms-class-inheritance-
    and-initialization-argument-issue/167981). IronPython 2.7's CLR-derived
    constructor binder runs the .NET base `Eto.Forms.Panel(content=None)`
    BEFORE the Python __init__, so any extra args fail with "takes at most
    2 arguments (N given)". Workaround is mandatory: __init__ takes ZERO
    args (matching the Panel(content=None) overload exactly), and a
    classmethod factory `create(...)` instantiates then calls `_initialize`.
    Confirmed by `ai_render_trace.log` 14:48 — every row failed with the
    arity error until we adopted this pattern; gallery panel rendered empty
    despite history count == 7.
    """

    @classmethod
    def create(cls, row, on_view_original, on_view_result, on_save, on_context, on_copy):
        inst = cls()  # zero-arg init goes through Panel(content=None) cleanly
        inst._initialize(row, on_view_original, on_view_result, on_save, on_context, on_copy)
        return inst

    def _initialize(self, row, on_view_original, on_view_result, on_save, on_context, on_copy):
        self._row = row
        self._on_view_original = on_view_original
        self._on_view_result = on_view_result
        self._on_save = on_save
        self._on_context = on_context
        self._on_copy = on_copy

        self.BackgroundColor = _hex_to_color("#FF333333")
        self.Padding = Eto.Drawing.Padding(4)
        # 2026-04-21 — thumb size driven by G.THUMB_W/H so the dialog's
        # "Large" toggle (set_thumb_size + rebuild) makes both data + view
        # scale together. Row height = thumb height + small chrome padding.
        tw, th = G.THUMB_W, G.THUMB_H
        self.Size = Eto.Drawing.Size(0, max(ROW_HEIGHT, th + 12))

        layout = Eto.Forms.DynamicLayout()
        layout.Spacing = Eto.Drawing.Size(6, 0)
        layout.BeginHorizontal()

        # Original thumb
        iv_orig = Eto.Forms.ImageView()
        iv_orig.Size = Eto.Drawing.Size(tw, th)
        if row.OriginalThumb is not None:
            iv_orig.Image = row.OriginalThumb
        iv_orig.MouseDown += self._handle_orig_click
        layout.Add(iv_orig)

        # Result thumb
        iv_res = Eto.Forms.ImageView()
        iv_res.Size = Eto.Drawing.Size(tw, th)
        if row.ResultThumb is not None:
            iv_res.Image = row.ResultThumb
        iv_res.MouseDown += self._handle_res_click
        layout.Add(iv_res)

        # Info column. Three stacked labels:
        #   - StyleName (bold, top)
        #   - full prompt (wraps to multiple lines, fills middle)
        #   - Subtitle (small grey, pinned to bottom by spacer)
        # The spacer (empty Add with yscale=True) pushes the subtitle to the
        # bottom of the row so it visually aligns with the status column's
        # bottom-aligned status text.
        info = Eto.Forms.DynamicLayout()
        info.Padding = Eto.Drawing.Padding(0)
        info.Spacing = Eto.Drawing.Size(0, 2)
        lbl_style = Eto.Forms.Label(Text=row.StyleName)
        lbl_style.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 11)
        info.Add(lbl_style)
        lbl_prompt = Eto.Forms.Label(Text=(row.full_prompt or row.PromptPreview))
        lbl_prompt.TextColor = _hex_to_color("#CBCBCB")
        try:
            lbl_prompt.Wrap = Eto.Forms.WrapMode.Word
        except Exception:
            pass  # older Eto builds may not expose Wrap
        info.Add(lbl_prompt, yscale=True)
        lbl_sub = Eto.Forms.Label(Text=row.Subtitle)
        lbl_sub.TextColor = _hex_to_color("#9A9A9A")
        info.Add(lbl_sub)
        layout.Add(info, xscale=True)

        # Status + progress column. Top spacer pushes content to the bottom
        # so the status text aligns with the Subtitle line in the info column.
        status_col = Eto.Forms.DynamicLayout()
        status_col.Spacing = Eto.Drawing.Size(0, 2)
        status_col.Add(None, yscale=True)  # bottom-align spacer
        lbl_st = Eto.Forms.Label(Text=row.StatusText)
        lbl_st.TextColor = _hex_to_color(row.StatusColor)
        lbl_st.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 11)
        status_col.Add(lbl_st)
        if row.ProgressVisibility:
            pb = Eto.Forms.ProgressBar()
            pb.Indeterminate = bool(row.ProgressIndeterminate)
            pb.Value = int(row.ProgressPct or 0)
            pb.MaxValue = 100
            pb.Height = 6
            status_col.Add(pb)
        layout.Add(status_col)

        # Inline save + copy buttons (only when SaveVisibility True). Wrapped
        # in their own bottom-aligned column so they sit on the same baseline
        # as the status text and Subtitle, not floating top.
        if row.SaveVisibility:
            save_col = Eto.Forms.DynamicLayout()
            save_col.Add(None, yscale=True)  # bottom-align spacer
            bt = Eto.Forms.Button(Text="💾")
            bt.Size = Eto.Drawing.Size(28, 28)
            bt.ToolTip = "Save result to disk"
            bt.Click += self._handle_save_click
            save_col.Add(bt)
            bt_copy = Eto.Forms.Button(Text="Copy")
            bt_copy.Size = Eto.Drawing.Size(48, 28)
            bt_copy.ToolTip = "Copy image to clipboard"
            bt_copy.Click += self._handle_copy_click
            save_col.Add(bt_copy)
            layout.Add(save_col)

        layout.EndHorizontal()
        self.Content = layout

        # Context-menu via right-click anywhere on the panel.
        self.MouseDown += self._handle_panel_mouse

    def _handle_orig_click(self, sender, e):
        if e.Buttons == Eto.Forms.MouseButtons.Primary:
            self._on_view_original(self._row)

    def _handle_res_click(self, sender, e):
        if e.Buttons == Eto.Forms.MouseButtons.Primary:
            self._on_view_result(self._row)

    def _handle_save_click(self, sender, e):
        self._on_save(self._row)

    def _handle_copy_click(self, sender, e):
        self._on_copy(self._row)

    def _handle_panel_mouse(self, sender, e):
        if e.Buttons == Eto.Forms.MouseButtons.Alternate:
            self._on_context(self._row, sender)


class AiRenderForm(Eto.Forms.Form):

    def __init__(self):
        # 2026-04-28 — load saved preferences (window size, checkboxes,
        # dropdown selections) before constructing widgets so they can be
        # applied during _build_ui rather than re-applied afterward.
        self._prefs = _load_prefs()
        win_w = int(self._prefs.get("window_w", 1180))
        win_h = int(self._prefs.get("window_h", 940))

        self.Title = "EnneaDuck: View Render"
        self.Padding = Eto.Drawing.Padding(8)
        self.Size = Eto.Drawing.Size(win_w, win_h)
        self.MinimumSize = Eto.Drawing.Size(900, 560)

        self._form_closed = False
        self._jobs = []
        self._jobs_lock = System.Object()
        self._all_rows = []  # cached cloud rows
        # 2026-04-28 — distinguishes "history hasn't loaded yet" from
        # "history loaded but empty" so the gallery can show skeleton
        # placeholder rows during the initial fetch instead of "0 items".
        self._history_loaded = False
        # 2026-06-10: seed the tick diff state to () so the FIRST 1Hz tick is a
        # no-op when no job is active. Previously it defaulted to None, so the
        # first idle tick (~1s after open) saw `() != None`, fired a rebuild
        # with empty _all_rows, and WIPED the just-rendered skeleton -- leaving
        # a confusing "0 items" gallery for the rest of the ~cloud-fetch window
        # before history finally appeared.
        self._last_tick_state = ()
        # 2026-06-10: derive the initial date-filter window from
        # DEFAULT_DATE_FILTER ("All time" -> None) so it MATCHES the dropdown's
        # initial selection. The dropdown is set to DEFAULT_DATE_FILTER but its
        # SelectionChanged handler is wired AFTER SelectedIndex is set, so it
        # never fires on init -- a hardcoded `7 * 86400` here meant the dropdown
        # read "All time" while the gallery silently filtered to the last 7 days.
        # That bug was invisible while the cloud index OOM'd (0 rows to filter);
        # once the OOM fix landed and 160 rows returned, "All time" was hiding
        # everything older than a week. Keep this in sync with the dropdown.
        self._filter_seconds = dict(G.DATE_FILTERS).get(G.DEFAULT_DATE_FILTER)
        self._filter_query = ""
        self._auto_save_enabled = bool(self._prefs.get("auto_save", True))
        self._last_tick_state = None  # explicit init (Round 3 P2-9)
        self._presets = []
        self._categories = []
        self._filtered_presets = []
        self._initial_prompt_for_reset = ""
        self._prompt_undo = []
        self._style_ref_path = None
        self._capture_path = None
        self._capture_view_name = ""
        self._last_save_folder = None
        self._my_prompts = []

        # Auto-capture state (2026-04-28). DisplayPipeline.PostDrawObjects
        # fires per redraw of any viewport — only when something changes,
        # so this is genuinely event-driven (not a 1Hz poll).
        self._auto_capture_enabled = bool(self._prefs.get("auto_capture", False))
        self._last_cam_signature = None
        self._auto_cap_timer = None
        self._draw_handler = None  # keep ref so .NET doesn't GC the delegate
        self._capturing = False    # in-flight guard so debounce-fire while a
                                    # capture is still saving/loading doesn't
                                    # stack a second one behind it (2026-04-28)

        self._build_ui()

        # 2026-04-30 (Item A): show auth banner if no token cached. The
        # timer drives auto-dismiss when the OAuth callback completes.
        try:
            self._refresh_auth_banner()
        except Exception:
            pass

        # Workers
        self._image_worker = AI_RENDER.QueueWorker(
            kind_filter=AI_RENDER.KIND_IMAGE,
            jobs_list=self._jobs,
            lock_obj=self._jobs_lock,
            invoke_ui=self._invoke_ui,
            job_update_callback=self._on_job_update,
            is_form_closed_fn=lambda: self._form_closed,
            auto_save_enabled_fn=lambda: self._auto_save_enabled,
            on_completion=self._on_any_job_complete)
        self._video_worker = AI_RENDER.QueueWorker(
            kind_filter=AI_RENDER.KIND_VIDEO,
            jobs_list=self._jobs,
            lock_obj=self._jobs_lock,
            invoke_ui=self._invoke_ui,
            job_update_callback=self._on_job_update,
            is_form_closed_fn=lambda: self._form_closed,
            auto_save_enabled_fn=lambda: self._auto_save_enabled,
            on_completion=self._on_any_job_complete)
        self._image_worker.start()
        self._video_worker.start()

        # Tick timer for live elapsed updates on active rows.
        self._tick_timer = Eto.Forms.UITimer()
        self._tick_timer.Interval = 1.0
        self._tick_timer.Elapsed += self._on_tick
        self._tick_timer.Start()

        # 2026-06-10: chunked-rebuild driver. Building 160 GalleryRowPanels into
        # the non-virtualized StackLayout in one synchronous pass froze the UI
        # thread (the Revit sibling's ListView is virtualized, so it never
        # froze). The rows are now built in time-boxed slices: _rebuild_rows
        # builds the first slice in-cycle, then this UITimer fills the rest,
        # yielding the message pump between slices so the dialog stays
        # responsive. UITimer (not AsyncInvoke) because AsyncInvoke posts at
        # Normal dispatcher priority and drains ahead of paint/input -- chained
        # AsyncInvoke batches would still freeze. State lives on self (single
        # source of truth); a new _rebuild_rows overwrites it and an in-flight
        # slice loop stops on the next tick.
        self._rebuild_merged = []
        self._rebuild_pos = 0
        self._rebuild_total = 0
        self._rebuild_timer = Eto.Forms.UITimer()
        self._rebuild_timer.Interval = 0.01
        self._rebuild_timer.Elapsed += self._on_rebuild_timer_tick

        self.Closed += self._on_closed
        self.Closing += self._on_closing
        try:
            self.SizeChanged += self._on_size_changed
        except Exception:
            pass

        # 2026-04-28 — Subscribe to DisplayPipeline so auto-capture is
        # event-driven. PostDrawObjects fires per viewport redraw, which
        # only happens when the camera/scene changes — when the dialog is
        # idle and Rhino isn't repainting, the handler costs nothing.
        try:
            self._draw_handler = self._on_post_draw
            Rhino.Display.DisplayPipeline.PostDrawObjects += self._draw_handler
        except Exception:
            self._draw_handler = None

        # Restore checkbox state from prefs now that widgets exist.
        # (cb_auto_capture is a styled Button, not a CheckBox — its visual
        # state is set by _apply_auto_capture_visual() during _build_ui.)
        try:
            self.cb_auto_save.Checked = self._auto_save_enabled
            self.cb_interior.Checked = bool(self._prefs.get("interior", False))
            self.cb_large_thumbs.Checked = bool(self._prefs.get("large_thumbs", True))
            res_idx = self._prefs.get("resolution_idx")
            if res_idx is not None and 0 <= int(res_idx) < self.cb_resolution.Items.Count:
                self.cb_resolution.SelectedIndex = int(res_idx)
            asp_idx = self._prefs.get("aspect_idx")
            if asp_idx is not None and 0 <= int(asp_idx) < self.cb_aspect.Items.Count:
                self.cb_aspect.SelectedIndex = int(asp_idx)
        except Exception:
            pass

        # Cleanup old capture_* folders (>7 days). Round 2 P1.
        try:
            AI_RENDER.cleanup_old_captures(FOLDER.DUMP_FOLDER, max_age_days=7)
        except Exception:
            pass

        # Render skeleton rows BEFORE kicking off the async cloud fetch
        # so the gallery doesn't read as "0 items" during the 0.5-3s
        # network round-trip. _apply_gallery_rows replaces them when
        # real data arrives.
        try:
            self._render_skeleton_rows()
        except Exception:
            pass

        # Async loads
        self._load_presets_async()
        self._open_browser_if_needed()
        self._refresh_gallery_async()
        self._refresh_quota_async()
        self._refresh_my_prompts_async()

        # 2026-05-14 — register auth-complete listener so the dialog auto-
        # refreshes the moment the OAuth callback writes a token. Without
        # this, the user clicks the sign-in button, completes auth in the
        # browser, comes back to Rhino, and the dialog STILL shows
        # "Sign in required" / empty preset+gallery state until they
        # click something. Now presets, gallery, quota, my-prompts, and
        # the auth banner all refresh themselves automatically.
        # Always defined as a bound method so _on_closed can unregister it.
        try:
            AUTH.register_auth_complete_listener(self._on_auth_complete)
        except Exception:
            pass

        # 2026-05-12: Show the dialog FIRST, then schedule the auto-capture 
        # asynchronously. ViewCapture blocks the UI thread for 2-5s — if 
        # we capture before Show(), the user clicks the button and sees 
        # nothing for seconds (port from Revit Round 3 P1-startup-3).
        Eto.Forms.Application.Instance.AsyncInvoke(self._capture_view)

        RHINO_UI.apply_dark_style(self)

    def _on_auth_complete(self):
        """Fires (on the AUTH worker thread) once the user finishes browser
        sign-in and the token lands on disk. Mirror of the Revit handler in
        ai_render_script.py::_on_auth_complete (per CLAUDE.md Rhino↔Revit
        parity rule).

        Marshals every refresh back to the Eto UI thread; the AUTH module
        invokes us from a .NET background thread that cannot touch Eto
        widgets directly.
        """
        if self._form_closed:
            return

        def _refresh_all():
            if self._form_closed:
                return
            try:
                self._refresh_auth_banner()
            except Exception:
                pass
            try:
                self._load_presets_async()
            except Exception:
                pass
            try:
                self._refresh_gallery_async()
            except Exception:
                pass
            try:
                self._refresh_quota_async()
            except Exception:
                pass
            try:
                self._refresh_my_prompts_async()
            except Exception:
                pass
            # Also wake the queue workers in case a paused job was waiting
            # for the user to sign in (see _on_resume — same pattern).
            try:
                self._image_worker.resume()
                self._video_worker.resume()
            except Exception:
                pass
            try:
                if hasattr(self, "bt_resume"):
                    self.bt_resume.Visible = False
            except Exception:
                pass
            try:
                self.status_label.Text = "Signed in. Dialog refreshed."
            except Exception:
                pass

        self._invoke_ui(_refresh_all)

    def _on_sign_out(self, sender, e):
        """Clear the cached desktop token and CLOSE the dialog (2026-06-04).

        Per user direction: signing out must close the modeless tool, not
        refresh it in place -- (1) it protects plugin/account info by tearing
        the window down, (2) it forces the user to reopen and re-auth cleanly,
        and (3) refreshing WPF/Eto state in place after clearing the token was
        crashing Revit. Keep this minimal: clear token, then close."""
        try:
            AUTH.clear_token()
        except Exception:
            pass
        try:
            self.Close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = Eto.Forms.DynamicLayout()
        root.Padding = Eto.Drawing.Padding(8)
        root.Spacing = Eto.Drawing.Size(6, 6)

        # --- Header row ---
        hdr = Eto.Forms.DynamicLayout()
        hdr.BeginHorizontal()
        hdr.Add(self._build_logo())
        hdr.Add(self._build_title_block(), xscale=True)
        bt_web = Eto.Forms.LinkButton(Text="Open ennead-ai.com >")
        bt_web.Click += lambda s, e: webbrowser.open(STUDIO_URL)
        hdr.Add(bt_web)
        # Sign out / switch account (2026-06-04): placed by the ennead-ai.com
        # link per user preference. The auth banner only shows when signed OUT,
        # so this is the only way to re-auth onto a different account (e.g. when
        # the gallery shows the wrong/empty history).
        self.bt_sign_out = Eto.Forms.LinkButton(Text="Sign out")
        self.bt_sign_out.ToolTip = (
            "Sign out and clear the cached login, then sign in again to switch "
            "account (e.g. if the gallery shows the wrong/empty history).")
        self.bt_sign_out.Click += self._on_sign_out
        hdr.Add(self.bt_sign_out)
        hdr.EndHorizontal()
        root.Add(hdr)

        # --- Auth banner (2026-04-30, Item A) ---
        # Shown when no token cached. Self-hides when token arrives. Stays
        # visible during browser sign-in via UITimer-driven polling.
        root.Add(self._build_auth_banner())

        # --- Controls (capture + prompt panels side by side) ---
        ctrl = Eto.Forms.DynamicLayout()
        ctrl.BeginHorizontal()
        ctrl.Add(self._build_capture_panel(), yscale=True)
        ctrl.Add(self._build_prompt_panel(), xscale=True, yscale=True)
        ctrl.EndHorizontal()
        root.Add(ctrl)

        # --- Primary CTA bar: status + Queue Render. 2026-04-28 — promoted
        # out of the prompt panel so it dominates over the chip toolbar. ---
        root.Add(self._build_cta_bar())

        # --- Filter bar + gallery ---
        root.Add(self._build_filter_bar())
        root.Add(self._build_gallery_panel(), yscale=True)

        # --- Footer ---
        root.Add(self._build_footer())

        self.Content = root

    def _build_auth_banner(self):
        """Auth state banner. Hidden by default; shown when no token cached.

        Self-driven via Eto UITimer (1s tick) so the banner auto-dismisses
        once the OAuth callback writes the token to disk and the next
        AUTH.get_token() returns non-None. No need for the user to click a
        retry button.

        Per memory feedback_evidence_before_hypothesis.md and reviewer #3
        roleplay findings: hardcoded enneadtab.com/auth URLs cannot work
        because the URL needs a `?port=NNNNN` query param tied to a
        per-call randomized localhost listener spun up by request_auth().
        Always go through request_auth(); never webbrowser.open() a static
        URL.
        """
        panel = Eto.Forms.Panel()
        panel.BackgroundColor = _hex_to_color("#FF3A2E14")
        panel.Padding = Eto.Drawing.Padding(12, 10)
        panel.Visible = False  # default hidden; shown only if not authed
        self._auth_banner = panel

        col = Eto.Forms.DynamicLayout()
        col.Spacing = Eto.Drawing.Size(0, 4)
        self._auth_heading = Eto.Forms.Label(Text=AI_RENDER.AUTH_PANEL_HEADING)
        self._auth_heading.Font = Eto.Drawing.Font(
            Eto.Drawing.SystemFont.Bold, 12)
        self._auth_heading.TextColor = _hex_to_color("#FFE0B070")
        col.Add(self._auth_heading)

        self._auth_body = Eto.Forms.Label(Text=AI_RENDER.AUTH_PANEL_BODY)
        self._auth_body.TextColor = _hex_to_color("#CBCBCB")
        try:
            self._auth_body.Wrap = Eto.Forms.WrapMode.Word
        except Exception:
            pass
        col.Add(self._auth_body)

        row = Eto.Forms.DynamicLayout()
        row.Spacing = Eto.Drawing.Size(8, 0)
        row.BeginHorizontal()
        self._auth_button = Eto.Forms.Button(Text=AI_RENDER.AUTH_PANEL_BUTTON)
        self._auth_button.Click += self._on_auth_button
        row.Add(self._auth_button)
        row.Add(None, xscale=True)
        row.EndHorizontal()
        col.Add(row)

        panel.Content = col

        # Polling timer (1s) so the banner auto-dismisses on token arrival.
        try:
            self._auth_timer = Eto.Forms.UITimer()
            self._auth_timer.Interval = 1.0
            self._auth_timer.Elapsed += self._on_auth_tick
            # Started lazily by _refresh_auth_banner when banner becomes visible.
        except Exception:
            self._auth_timer = None

        # Initial visibility check happens in __init__ after _build_ui.
        return panel

    def _refresh_auth_banner(self):
        """Update banner visibility based on current AUTH state. Called from
        __init__ after build, and after every auth event."""
        if not hasattr(self, "_auth_banner") or self._auth_banner is None:
            return
        try:
            has_token = bool(AUTH.get_token())
            in_progress = bool(AUTH.is_auth_in_progress())
        except Exception:
            has_token = False
            in_progress = False
        if has_token:
            self._auth_banner.Visible = False
            try:
                if self._auth_timer is not None:
                    self._auth_timer.Stop()
            except Exception:
                pass
            return
        # Not authed — show banner.
        self._auth_banner.Visible = True
        if in_progress:
            self._auth_heading.Text = AI_RENDER.AUTH_PANEL_HEADING
            self._auth_body.Text = AI_RENDER.AUTH_PANEL_WAITING
            self._auth_button.Enabled = False
        else:
            self._auth_heading.Text = AI_RENDER.AUTH_PANEL_HEADING
            self._auth_body.Text = AI_RENDER.AUTH_PANEL_BODY
            self._auth_button.Enabled = True
        try:
            if self._auth_timer is not None:
                self._auth_timer.Start()
        except Exception:
            pass

    def _on_auth_button(self, sender, e):
        try:
            AUTH.request_auth()
        except Exception as ex:
            self.status_label.Text = "Sign-in failed: {}".format(ex)
            return
        self._refresh_auth_banner()

    def _on_auth_tick(self, sender, e):
        self._refresh_auth_banner()

    def _build_logo(self):
        iv = Eto.Forms.ImageView()
        logo_path = IMAGE.get_image_path_by_name("logo_vertical_light.png")
        if logo_path and os.path.exists(logo_path):
            try:
                iv.Image = Eto.Drawing.Bitmap(logo_path).WithSize(40, 40)
            except Exception:
                pass
        iv.Size = Eto.Drawing.Size(40, 40)
        return iv

    def _build_title_block(self):
        col = Eto.Forms.DynamicLayout()
        title = Eto.Forms.Label(Text="EnneaDuck: View Render")
        title.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 14)
        title.TextColor = _hex_to_color("#FFFFE59C")
        col.Add(title)
        sub = Eto.Forms.Label(
            Text="Render Rhino views through Ennead's curated style library.")
        sub.TextColor = _hex_to_color("#CBCBCB")
        col.Add(sub)
        return col

    def _build_capture_panel(self):
        # 2026-04-28 redesign:
        #   - Bigger capture preview (264x168 -> 280x220) so composition is
        #     readable at a glance ("images all small" feedback).
        #   - preview_label moved BELOW the preview to act as a caption
        #     instead of a header, freeing vertical space.
        #   - Style Reference buttons collapse from 4 vertical to 1 horizontal
        #     row of chips next to a smaller (100x76) thumb.
        # 2026-04-30: capture preview enlarged 300x220 -> 420x300; user feedback
        # asked for the prompt to take less space and the preview to take more.
        col = Eto.Forms.DynamicLayout()
        col.Spacing = Eto.Drawing.Size(0, 4)
        col.Width = 440

        # STEP 1 eyebrow
        step1_lbl = Eto.Forms.Label(Text="STEP 1 / CAPTURE")
        step1_lbl.TextColor = _hex_to_color("#9A9A9A")
        step1_lbl.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 9)
        col.Add(step1_lbl)

        self.capture_preview = Eto.Forms.ImageView()
        self.capture_preview.Size = Eto.Drawing.Size(420, 300)
        col.Add(self.capture_preview)
        self.preview_label = Eto.Forms.Label(Text="Click Update Capture to begin")
        self.preview_label.TextColor = _hex_to_color("#CBCBCB")
        col.Add(self.preview_label)
        # 2026-04-28 — paired buttons. Update Capture is the primary
        # explicit action; the auto-toggle to its right is a related MODE
        # control (modifies the button's behavior). Styling them as two
        # buttons of similar weight reads as a logical pair, not as
        # disconnected siblings the way the old CheckBox did.
        cap_row = Eto.Forms.DynamicLayout()
        cap_row.Spacing = Eto.Drawing.Size(6, 0)
        cap_row.BeginHorizontal()
        bt_cap = Eto.Forms.Button(Text="Update Capture")
        bt_cap.Click += self._on_capture
        cap_row.Add(bt_cap, xscale=True)

        # Auto-capture mode toggle styled as a button (Eto's CheckBox is
        # too low-contrast to communicate "this is a live mode"). Text +
        # accent color flip on toggle so the state is visible at a glance.
        # Internal API surface stays as `cb_auto_capture` so existing
        # handlers + prefs code don't need to change.
        self.cb_auto_capture = Eto.Forms.Button(Text="Auto: OFF")
        self.cb_auto_capture.ToolTip = (
            "Auto-recapture the viewport ~0.3s after the camera stops "
            "moving. Useful while iterating on framing.")
        # Synthesize a `Checked` property so existing code that reads/sets
        # cb_auto_capture.Checked keeps working against the Button.
        self._auto_capture_btn_state = bool(self._auto_capture_enabled)
        self.cb_auto_capture.Click += self._on_auto_capture_btn_click
        try:
            self.cb_auto_capture.Size = Eto.Drawing.Size(110, -1)
        except Exception:
            pass
        cap_row.Add(self.cb_auto_capture)
        cap_row.EndHorizontal()
        col.Add(cap_row)
        # Apply initial visual state (color/text reflects loaded pref).
        self._apply_auto_capture_visual()

        # Resolution: inline "Size [res] [aspect]"
        col.Add(Eto.Forms.Label(Text="Capture Resolution",
                                TextColor=_hex_to_color("#CBCBCB")))
        res_row = Eto.Forms.DynamicLayout()
        res_row.BeginHorizontal()
        self.cb_resolution = Eto.Forms.DropDown()
        for label, _ in RESOLUTION_OPTIONS:
            self.cb_resolution.Items.Add(label)
        self.cb_resolution.SelectedIndex = [l for l, _ in RESOLUTION_OPTIONS].index(DEFAULT_RESOLUTION_LABEL)
        self.cb_resolution.SelectedIndexChanged += self._on_resolution_changed
        res_row.Add(self.cb_resolution, xscale=True)
        self.cb_aspect = Eto.Forms.DropDown()
        for a in ASPECT_OPTIONS:
            self.cb_aspect.Items.Add(a)
        self.cb_aspect.SelectedIndex = ASPECT_OPTIONS.index(DEFAULT_ASPECT)
        self.cb_aspect.SelectedIndexChanged += self._on_resolution_changed
        res_row.Add(self.cb_aspect, xscale=True)
        res_row.EndHorizontal()
        col.Add(res_row)
        self.resolution_hint = Eto.Forms.Label(Text="")
        self.resolution_hint.TextColor = _hex_to_color("#9A9A9A")
        col.Add(self.resolution_hint)
        self._update_resolution_hint()

        # Style reference: chip-row of buttons + smaller inline thumb.
        col.Add(Eto.Forms.Label(Text="Style Reference (optional)",
                                TextColor=_hex_to_color("#CBCBCB")))
        ref_row = Eto.Forms.DynamicLayout()
        ref_row.BeginHorizontal()
        ref_btns = Eto.Forms.DynamicLayout()
        ref_btns.Spacing = Eto.Drawing.Size(0, 3)
        bt_browse = Eto.Forms.Button(Text="Browse...")
        bt_browse.Click += self._on_browse_style
        ref_btns.Add(bt_browse)
        bt_paste = Eto.Forms.Button(Text="Paste Clipboard")
        bt_paste.Click += self._on_paste_style
        ref_btns.Add(bt_paste)
        bt_lib = Eto.Forms.Button(Text="Load from Library...")
        bt_lib.Click += self._on_library_style
        ref_btns.Add(bt_lib)
        self.bt_clear_style = Eto.Forms.Button(Text="Clear")
        self.bt_clear_style.Click += self._on_clear_style
        self.bt_clear_style.Visible = False
        ref_btns.Add(self.bt_clear_style)
        ref_row.Add(ref_btns, xscale=True)
        self.style_preview = Eto.Forms.ImageView()
        self.style_preview.Size = Eto.Drawing.Size(100, 76)
        ref_row.Add(self.style_preview)
        ref_row.EndHorizontal()
        col.Add(ref_row)
        return col

    def _build_prompt_panel(self):
        # 2026-04-28 redesign:
        #   - Prompt action buttons (Spell/Lengthen/Shorten/Reset/Undo) flipped
        #     from a vertical column on the right of the textbox into a
        #     horizontal chip toolbar ABOVE the textbox, alongside Interior.
        #   - TextArea height 120 -> 100 ("prompt uses too much space" feedback);
        #     scrollbar still handles long prompts.
        #   - Status label + Queue Render button removed from this panel; they
        #     now live in the dedicated CTA bar built by _build_cta_bar().
        col = Eto.Forms.DynamicLayout()
        col.Spacing = Eto.Drawing.Size(0, 4)

        # STEP 2 eyebrow
        step2_lbl = Eto.Forms.Label(Text="STEP 2 / STYLE + PROMPT")
        step2_lbl.TextColor = _hex_to_color("#9A9A9A")
        step2_lbl.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 9)
        col.Add(step2_lbl)

        col.Add(Eto.Forms.Label(Text="Rendering Style",
                                TextColor=_hex_to_color("#CBCBCB")))
        cat_row = Eto.Forms.DynamicLayout()
        cat_row.Spacing = Eto.Drawing.Size(6, 0)
        cat_row.BeginHorizontal()
        # 2026-04-21 — switched DropDown → ComboBox + AutoComplete so users
        # can type-to-filter the curated list (matches the WPF Revit dialog
        # IsEditable=True + IsTextSearchEnabled=True). AutoComplete attempted
        # on every selector; some Eto builds don't expose it on ComboBox so
        # we set it defensively via try/except.
        def _make_searchable_combo(width=None):
            cb = Eto.Forms.ComboBox()
            if width is not None:
                cb.Width = width
            try:
                cb.AutoComplete = True
            except Exception:
                pass
            return cb
        self.cb_category = _make_searchable_combo(width=150)
        self.cb_category.SelectedIndexChanged += self._on_category_changed
        cat_row.Add(self.cb_category)
        self.cb_style = _make_searchable_combo()
        self.cb_style.SelectedIndexChanged += self._on_style_changed
        cat_row.Add(self.cb_style, xscale=True)
        cat_row.EndHorizontal()
        col.Add(cat_row)

        # My Prompts row
        myp_row = Eto.Forms.DynamicLayout()
        myp_row.Spacing = Eto.Drawing.Size(6, 0)
        myp_row.BeginHorizontal()
        myp_row.Add(Eto.Forms.Label(Text="My Prompts:",
                                    TextColor=_hex_to_color("#CBCBCB")))
        self.cb_my_prompts = _make_searchable_combo()
        self.cb_my_prompts.SelectedIndexChanged += self._on_my_prompt_changed
        myp_row.Add(self.cb_my_prompts, xscale=True)
        # 2026-04-28 — modal browser. Eto's ComboBox.ToolTip is silently
        # ignored on this Rhino build, so the per-item preview tooltip
        # never appeared. The Browse button opens a proper picker with
        # a name list on the left and a live full-prompt preview pane
        # on the right.
        bt_browse_p = Eto.Forms.Button(Text="Browse...")
        bt_browse_p.ToolTip = "Open a picker with full-prompt previews"
        bt_browse_p.Click += self._on_browse_my_prompts
        myp_row.Add(bt_browse_p)
        bt_save_p = Eto.Forms.Button(Text="Save current...")
        bt_save_p.Click += self._on_save_prompt
        myp_row.Add(bt_save_p)
        myp_row.EndHorizontal()
        col.Add(myp_row)

        # Prompt header: label + horizontal action toolbar + Interior toggle.
        ptop = Eto.Forms.DynamicLayout()
        ptop.Spacing = Eto.Drawing.Size(4, 0)
        ptop.BeginHorizontal()
        ptop.Add(Eto.Forms.Label(Text="Prompt",
                                 TextColor=_hex_to_color("#CBCBCB")))
        self.bt_spell = Eto.Forms.Button(Text="Spell Check")
        self.bt_spell.ToolTip = "Check spelling and grammar"
        self.bt_spell.Click += self._on_spell
        ptop.Add(self.bt_spell)
        self.bt_lengthen = Eto.Forms.Button(Text="Improve Prompt")
        self.bt_lengthen.ToolTip = "Use AI to improve your prompt"
        self.bt_lengthen.Click += self._on_lengthen
        ptop.Add(self.bt_lengthen)
        self.bt_shorten = Eto.Forms.Button(Text="Summarize Prompt")
        self.bt_shorten.ToolTip = "Use AI to summarize and reduce prompt length (75% of original)"
        self.bt_shorten.Click += self._on_shorten
        ptop.Add(self.bt_shorten)
        self.bt_reset_prompt = Eto.Forms.Button(Text="Clear Prompt")
        self.bt_reset_prompt.ToolTip = "Clear the prompt textbox"
        self.bt_reset_prompt.Click += self._on_reset_prompt
        ptop.Add(self.bt_reset_prompt)
        self.bt_undo_prompt = Eto.Forms.Button(Text="Undo")
        self.bt_undo_prompt.ToolTip = "Undo the last AI change"
        self.bt_undo_prompt.Click += self._on_undo_prompt
        self.bt_undo_prompt.Enabled = False
        ptop.Add(self.bt_undo_prompt)
        ptop.Add(None, xscale=True)  # spacer pushes Interior to the right
        self.cb_interior = Eto.Forms.CheckBox(Text="Interior scene")
        self.cb_interior.CheckedChanged += self._on_interior_changed
        ptop.Add(self.cb_interior)
        ptop.EndHorizontal()
        col.Add(ptop)

        # Keep #459 -- suggested starter-prompt chips above the textbox.
        # Shared list lives in AI_RENDER.get_suggested_starter_prompts().
        col.Add(self._build_suggested_prompt_chips())

        self.tbox_prompt = Eto.Forms.TextArea()
        # 2026-04-30: shrunk 100 -> 80 (user feedback: prompt area too tall).
        # Still scrollable for long prompts via TextArea's intrinsic scrollbar.
        self.tbox_prompt.Size = Eto.Drawing.Size(0, 80)
        self.tbox_prompt.AcceptsReturn = True
        col.Add(self.tbox_prompt, yscale=True)

        return col

    def _build_suggested_prompt_chips(self):
        """Horizontal row of clickable starter-prompt bubbles.

        Click fills the prompt TextArea (undoable). Labels/prompts come from
        the shared AI_RENDER list so Revit and Rhino cannot drift.
        """
        row = Eto.Forms.DynamicLayout()
        row.Spacing = Eto.Drawing.Size(4, 2)
        row.BeginHorizontal()
        hint = Eto.Forms.Label(Text="Try:")
        hint.TextColor = _hex_to_color("#9A9A9A")
        try:
            hint.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Default, 9)
        except Exception:
            pass
        row.Add(hint)

        items = AI_RENDER.get_suggested_starter_prompts()
        for item in items:
            label = item.get("label") or ""
            prompt = item.get("prompt") or label
            if not label:
                continue
            btn = Eto.Forms.Button(Text=label)
            btn.ToolTip = "Fill prompt box with: {}".format(prompt)
            # Tag is not universally available on Eto Button across builds;
            # close over prompt via a factory (same pattern as viewer handlers).
            btn.Click += self._make_suggested_prompt_handler(prompt)
            try:
                btn.BackgroundColor = _hex_to_color("#FF3A3A3A")
                btn.TextColor = _hex_to_color("#CBCBCB")
            except Exception:
                pass
            row.Add(btn)
        row.Add(None, xscale=True)  # push chips left
        row.EndHorizontal()
        return row

    def _make_suggested_prompt_handler(self, prompt_text):
        def _on_chip(sender, e):
            self._on_suggested_prompt_chip(prompt_text)
        return _on_chip

    def _on_suggested_prompt_chip(self, prompt_text):
        if not prompt_text:
            return
        self._push_prompt_undo()
        self.tbox_prompt.Text = prompt_text
        try:
            self.status_label.Text = (
                "Starter prompt loaded -- edit or queue as-is.")
        except Exception:
            pass

    def _build_cta_bar(self):
        """Dedicated full-width band: status text on the left, Queue Render
        button on the right, accent-tinted background + larger button so the
        primary action stands out against every other button in the dialog.
        2026-04-28 — extracted from the old prompt-panel bottom row in
        response to feedback that Queue Render was hard to find among the
        Spell/Lengthen/Shorten/Reset/Undo button cluster."""
        panel = Eto.Forms.Panel()
        panel.BackgroundColor = _hex_to_color("#FF2E2E2E")
        panel.Padding = Eto.Drawing.Padding(14, 10)

        bar = Eto.Forms.DynamicLayout()
        bar.Spacing = Eto.Drawing.Size(12, 0)
        bar.BeginHorizontal()

        status_col = Eto.Forms.DynamicLayout()
        cta_eyebrow = Eto.Forms.Label(Text="READY TO RENDER")
        cta_eyebrow.TextColor = _hex_to_color("#9A9A9A")
        cta_eyebrow.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 9)
        status_col.Add(cta_eyebrow)
        self.status_label = Eto.Forms.Label(
            Text="Ready. Capture a view then queue a render.")
        self.status_label.TextColor = _hex_to_color("#DAE8FD")
        self.status_label.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Default, 11)
        status_col.Add(self.status_label)
        bar.Add(status_col, xscale=True)

        self.bt_render = Eto.Forms.Button(Text="Queue Render  >")
        self.bt_render.Size = Eto.Drawing.Size(220, 40)
        # Eto Button has limited theming support across builds; defensively
        # apply accent + bold font when the API is available.
        try:
            self.bt_render.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 12)
        except Exception:
            pass
        try:
            self.bt_render.BackgroundColor = _hex_to_color("#FFF39C12")
            self.bt_render.TextColor = _hex_to_color("#FFFFFFFF")
        except Exception:
            pass
        self.bt_render.Click += self._on_render
        bar.Add(self.bt_render)

        bar.EndHorizontal()
        panel.Content = bar
        return panel

    def _build_filter_bar(self):
        row = Eto.Forms.DynamicLayout()
        row.BeginHorizontal()
        self.gallery_header = Eto.Forms.Label(Text="Gallery")
        self.gallery_header.Font = Eto.Drawing.Font(Eto.Drawing.SystemFont.Bold, 12)
        row.Add(self.gallery_header)
        self.gallery_count = Eto.Forms.Label(Text="loading...")
        self.gallery_count.TextColor = _hex_to_color("#CBCBCB")
        row.Add(self.gallery_count, xscale=True)
        # 2026-04-21 — Large-thumb toggle. Calls G.set_thumb_size() then
        # rebuilds the gallery so existing rows reload at the new size.
        self.cb_large_thumbs = Eto.Forms.CheckBox(Text="Large")
        # Default ON (2026-04-22) — matches the new G.THUMB_W/H default in
        # ai_render_gallery_module.py. Users can uncheck for compact rows.
        self.cb_large_thumbs.Checked = True
        self.cb_large_thumbs.ToolTip = "Show larger preview thumbnails (240x160)"
        self.cb_large_thumbs.CheckedChanged += self._on_large_thumbs_changed
        row.Add(self.cb_large_thumbs)
        self.cb_date_filter = Eto.Forms.DropDown()
        for label, _ in G.DATE_FILTERS:
            self.cb_date_filter.Items.Add(label)
        self.cb_date_filter.SelectedIndex = [l for l, _ in G.DATE_FILTERS].index(G.DEFAULT_DATE_FILTER)
        self.cb_date_filter.SelectedIndexChanged += self._on_date_filter_changed
        row.Add(self.cb_date_filter)
        self.tbox_search = Eto.Forms.TextBox()
        self.tbox_search.PlaceholderText = "search prompt or view"
        self.tbox_search.Size = Eto.Drawing.Size(160, 22)
        self.tbox_search.TextChanged += self._on_search_changed
        row.Add(self.tbox_search)
        bt_refresh = Eto.Forms.Button(Text="⟳ Refresh")
        bt_refresh.Click += self._on_refresh_gallery
        row.Add(bt_refresh)
        self.bt_active_jobs = Eto.Forms.Button(Text="Active jobs (0)")
        self.bt_active_jobs.Click += self._on_scroll_to_active
        row.Add(self.bt_active_jobs)
        self.bt_resume = Eto.Forms.Button(Text="Resume (auth paused)")
        self.bt_resume.Click += self._on_resume
        self.bt_resume.Visible = False
        row.Add(self.bt_resume)
        row.EndHorizontal()
        return row

    def _build_gallery_panel(self):
        # Scrollable wrapping a vertical StackLayout of GalleryRowPanel widgets.
        # (Per Review #1 — Eto.GridView's per-row variable layout is awkward.)
        self._rows_layout = Eto.Forms.StackLayout()
        self._rows_layout.Orientation = Eto.Forms.Orientation.Vertical
        self._rows_layout.HorizontalContentAlignment = Eto.Forms.HorizontalAlignment.Stretch
        self._rows_layout.Spacing = 1
        self._rows_layout.Padding = Eto.Drawing.Padding(2)

        self._scroll = Eto.Forms.Scrollable()
        self._scroll.Content = self._rows_layout
        self._scroll.Border = Eto.Forms.BorderType.Line
        return self._scroll

    def _build_footer(self):
        row = Eto.Forms.DynamicLayout()
        # 2026-04-21 — gap between adjacent controls so labels don't abut
        # ("Auto-save to Gallery0B cached" / "Open Output FolderQuota:" was
        # unreadable in user screenshot).
        row.Spacing = Eto.Drawing.Size(10, 0)
        row.Padding = Eto.Drawing.Padding(2, 4, 2, 4)
        row.BeginHorizontal()
        self.cb_auto_save = Eto.Forms.CheckBox(Text="Auto-save to Cloud")
        self.cb_auto_save.Checked = True
        self.cb_auto_save.CheckedChanged += self._on_auto_save_changed
        self.cb_auto_save.ToolTip = (
            "Saves every new render to your cloud Gallery (visible from web "
            "Studio, Revit, Rhino, mobile). Applies to newly-queued renders "
            "only - in-flight jobs keep their setting. Turn OFF to keep this "
            "render local-only (won't appear on other devices).")
        row.Add(self.cb_auto_save)
        # Cache label is clickable — opens manage-cache modal (Round 3 P1-parity
        # with Revit fix #16; Rhino missed this in Round 2).
        self.cache_size_label = Eto.Forms.LinkButton(Text="—")
        self.cache_size_label.TextColor = _hex_to_color("#9A9A9A")
        self.cache_size_label.ToolTip = "Click to manage local gallery cache (clearing is safe — cloud copy is canonical)"
        self.cache_size_label.Click += self._on_manage_cache
        row.Add(self.cache_size_label, xscale=True)
        # Build stamp (2026-06-04): tiny dim label so a stale distributed copy
        # is obvious. Fresh deploy -> recent date; old date -> EA_Dist lagging.
        self.lbl_build = Eto.Forms.Label(Text="build {}".format(_BUILD_TAG))
        try:
            self.lbl_build.TextColor = _hex_to_color("#5A5A5A")
            self.lbl_build.Font = Eto.Drawing.Font(
                Eto.Drawing.SystemFont.Default, 8)
            self.lbl_build.ToolTip = (
                "Build timestamp of the running view2render_left.py. If this "
                "looks old, Rhino is loading a stale EA_Dist copy.")
        except Exception:
            pass
        row.Add(self.lbl_build)
        bt_open_folder = Eto.Forms.Button(Text="Open Output Folder")
        bt_open_folder.Click += self._on_open_folder
        row.Add(bt_open_folder)
        self.quota_label = Eto.Forms.Label(Text="Quota: -")
        self.quota_label.TextColor = _hex_to_color("#9A9A9A")
        row.Add(self.quota_label)
        row.EndHorizontal()
        return row

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_closing(self, sender, e):
        # If there are pending/active jobs, confirm.
        in_flight = AI_RENDER.count_inflight(self._jobs, self._jobs_lock)
        if in_flight > 0:
            res = Eto.Forms.MessageBox.Show(
                self,
                "{} render(s) still running or pending.\n\n"
                "Yes = finish them in the background (dialog closes).\n"
                "No  = drop pending jobs and close now.\n"
                "Cancel = keep the dialog open.".format(in_flight),
                "Closing render",
                Eto.Forms.MessageBoxButtons.YesNoCancel)
            if res == Eto.Forms.DialogResult.Cancel:
                e.Cancel = True
                return
            if res == Eto.Forms.DialogResult.No:
                # Mark all pending as failed so the worker exits promptly.
                Monitor.Enter(self._jobs_lock)
                try:
                    for j in self._jobs:
                        if j.status == AI_RENDER.STATUS_PENDING:
                            j.status = AI_RENDER.STATUS_FAILED
                            j.error_msg = "Cancelled on close"
                finally:
                    Monitor.Exit(self._jobs_lock)

    def _on_closed(self, sender, e):
        self._form_closed = True
        # 2026-05-14 — unregister auth-complete listener FIRST so a callback
        # racing the close path cannot fire against a half-torn-down form.
        try:
            AUTH.unregister_auth_complete_listener(self._on_auth_complete)
        except Exception:
            pass
        try:
            self._tick_timer.Stop()
        except Exception:
            pass
        try:
            if self._auto_cap_timer is not None:
                self._auto_cap_timer.Stop()
        except Exception:
            pass
        # Unsubscribe DisplayPipeline event so we don't leak a handler that
        # keeps firing after the form is gone (would call _capture_view
        # against a disposed Eto control and likely crash Rhino).
        try:
            if self._draw_handler is not None:
                Rhino.Display.DisplayPipeline.PostDrawObjects -= self._draw_handler
        except Exception:
            pass

        # 2026-05-12: Only stop workers if the user explicitly chose NOT to 
        # finish in background (handled by STATUS_FAILED marks above) or 
        # if no jobs remain.
        Monitor.Enter(self._jobs_lock)
        try:
            any_active = any(j.status in (AI_RENDER.STATUS_PENDING, AI_RENDER.STATUS_ACTIVE)
                            for j in self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        
        if not any_active:
            try:
                self._image_worker.stop()
                self._video_worker.stop()
            except Exception:
                pass

        # Identity check — only clear sticky if it still points to us
        # (prevents close+reopen race from clobbering a freshly-created form).
        if sc.sticky.has_key("EA_AI_RENDER_FORM") and sc.sticky["EA_AI_RENDER_FORM"] is self:
            sc.sticky.Remove("EA_AI_RENDER_FORM")

    # ------------------------------------------------------------------
    # Animate (Image → Video)
    # ------------------------------------------------------------------

    def _ctx_animate(self, row):
        # Need a local image to use as firstFrame.
        if row.result_path and os.path.exists(row.result_path):
            self._show_animate_dialog(row, row.result_path)
            return
        if row.cloud_item:
            self.status_label.Text = "Downloading image for animation..."
            token = AUTH.get_token()
            if not token:
                self.status_label.Text = "Sign in required."
                return
            def on_done(_bmp, path):
                if path:
                    self._invoke_ui(lambda: self._show_animate_dialog(row, path))
                else:
                    self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                    "Failed to fetch image."))
            G.fetch_full_item_async(token, row.id, on_done)

    def _show_animate_dialog(self, row, image_path):
        dlg = Eto.Forms.Dialog[bool]()
        dlg.Title = "Animate (Image → Video)"
        dlg.Padding = Eto.Drawing.Padding(12)
        dlg.Resizable = False
        dlg.BackgroundColor = _hex_to_color("#464646")

        layout = Eto.Forms.DynamicLayout()
        layout.Spacing = Eto.Drawing.Size(6, 6)

        def _lbl(txt):
            l = Eto.Forms.Label(Text=txt)
            l.TextColor = _hex_to_color("#DAE8FD")
            return l

        layout.Add(_lbl("Motion Prompt (describe movement):"))
        tb_prompt = Eto.Forms.TextBox()
        tb_prompt.Text = "Slow cinematic pan across the scene, realistic movement."
        layout.Add(tb_prompt)

        layout.BeginHorizontal()
        layout.BeginVertical(spacing=Eto.Drawing.Size(6, 6))
        layout.Add(_lbl("Duration:"))
        cb_dur = Eto.Forms.DropDown()
        cb_dur.Items.Add("4 seconds")
        cb_dur.Items.Add("6 seconds")
        cb_dur.Items.Add("8 seconds")
        cb_dur.SelectedIndex = 0
        layout.Add(cb_dur)
        layout.EndVertical()

        layout.BeginVertical(spacing=Eto.Drawing.Size(6, 6))
        layout.Add(_lbl("Resolution:"))
        cb_res = Eto.Forms.DropDown()
        cb_res.Items.Add("720p")
        cb_res.Items.Add("1080p")
        cb_res.SelectedIndex = 0
        layout.Add(cb_res)
        layout.EndVertical()
        layout.EndHorizontal()

        layout.AddSeparator()
        
        btn_row = Eto.Forms.DynamicLayout()
        btn_row.BeginHorizontal()
        btn_row.Add(None, xscale=True)
        ok = Eto.Forms.Button(Text="Queue Video")
        cancel = Eto.Forms.Button(Text="Cancel")
        def on_ok(s, a):
            duration = [4, 6, 8][cb_dur.SelectedIndex]
            resolution = ["720p", "1080p"][cb_res.SelectedIndex]
            self._enqueue_video(image_path, tb_prompt.Text, duration, resolution,
                                row.view_name or "", row.StyleName or "")
            dlg.Close(True)
        ok.Click += on_ok
        cancel.Click += lambda s, a: dlg.Close(False)
        btn_row.Add(ok)
        btn_row.Add(cancel)
        btn_row.EndHorizontal()
        layout.Add(btn_row)

        dlg.Content = layout
        RHINO_UI.apply_dark_style(dlg)
        dlg.ShowModal(self)

    def _enqueue_video(self, image_path, motion_prompt, duration, resolution,
                       view_name, style_name):
        if not AI_RENDER.can_enqueue(self._jobs, self._jobs_lock):
            self.status_label.Text = "Queue full."
            return
        job = AI_RENDER.RenderJob(
            original_path=image_path,
            prompt=motion_prompt,
            style_preset=style_name,
            view_name=view_name,
            kind=AI_RENDER.KIND_VIDEO,
            host="rhino",
            video_duration=duration,
            video_resolution=resolution,
            auto_save_gallery=self._auto_save_enabled)
        Monitor.Enter(self._jobs_lock)
        try:
            self._jobs.append(job)
        finally:
            Monitor.Exit(self._jobs_lock)
        self._video_worker.wake()
        self.status_label.Text = "Video queued (job #{}).".format(job.job_id[:6])
        self._rebuild_rows()
        self._update_active_jobs_label()

    # ------------------------------------------------------------------
    # Preferences (2026-04-28) — write-through helpers used by every
    # checkbox / dropdown handler so the next session restores state.
    # ------------------------------------------------------------------

    def _save_pref(self, key, value):
        try:
            self._prefs[key] = value
            _save_prefs(self._prefs)
        except Exception:
            pass

    def _on_size_changed(self, sender, e):
        # Persist last user-resized window so it reopens at their preferred
        # dimensions; gallery height was the chief complaint at 780px.
        if self._form_closed:
            return
        try:
            sz = self.Size
            self._save_pref("window_w", int(sz.Width))
            self._save_pref("window_h", int(sz.Height))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Auto-capture on camera change (2026-04-28)
    # ------------------------------------------------------------------

    def _on_auto_capture_btn_click(self, sender, e):
        # Toggle state, persist, repaint.
        self._auto_capture_enabled = not bool(self._auto_capture_enabled)
        self._auto_capture_btn_state = self._auto_capture_enabled
        self._save_pref("auto_capture", self._auto_capture_enabled)
        # Reset the camera baseline so toggling ON doesn't immediately fire
        # against a now-stale signature from before the user enabled it.
        self._last_cam_signature = self._cam_signature_for_active_view()
        self._apply_auto_capture_visual()

    def _apply_auto_capture_visual(self):
        """Paint the auto-capture button to make ON/OFF unmistakable.
        Text changes between 'Auto: ON' (with bullet) and 'Auto: OFF';
        background flips to accent orange when ON. Color setters are
        wrapped because some Eto builds don't honor them on Button."""
        on = bool(self._auto_capture_enabled)
        try:
            self.cb_auto_capture.Text = "● Auto: ON" if on else "Auto: OFF"
        except Exception:
            pass
        try:
            if on:
                self.cb_auto_capture.BackgroundColor = _hex_to_color("#FFF39C12")
                self.cb_auto_capture.TextColor = _hex_to_color("#FFFFFFFF")
            else:
                # Default-ish dark button look.
                self.cb_auto_capture.BackgroundColor = _hex_to_color("#FF3A3A3A")
                self.cb_auto_capture.TextColor = _hex_to_color("#FFCBCBCB")
        except Exception:
            pass

    def _cam_signature_for_active_view(self):
        try:
            view = sc.doc.Views.ActiveView
            if view is None:
                return None
            return self._cam_signature(view.ActiveViewport)
        except Exception:
            return None

    def _cam_signature(self, vp):
        # Round to 2 decimals — sub-millimeter jitter shouldn't trigger
        # captures, and floating-point noise would otherwise look like
        # constant motion to the diff check.
        try:
            loc = vp.CameraLocation
            tgt = vp.CameraTarget
            return "{:.2f},{:.2f},{:.2f}|{:.2f},{:.2f},{:.2f}".format(
                loc.X, loc.Y, loc.Z, tgt.X, tgt.Y, tgt.Z)
        except Exception:
            return None

    def _on_post_draw(self, sender, e):
        """Fires per viewport redraw. Cheap when nothing changes (Rhino only
        emits these during scene/view updates). Diffs camera signature, then
        debounces via a 1.2s one-shot Eto timer so a continuous spin produces
        ONE capture after the user lets go, not 60 per second."""
        if self._form_closed or not self._auto_capture_enabled:
            return
        try:
            view = sc.doc.Views.ActiveView
            if view is None:
                return
            # Filter to active viewport — we don't want every floating
            # detail view in the doc to retrigger.
            if e.Viewport.Id != view.ActiveViewport.Id:
                return
            sig = self._cam_signature(e.Viewport)
            if sig is None or sig == self._last_cam_signature:
                return
            self._last_cam_signature = sig
            # Marshal timer manipulation onto the UI thread; PostDrawObjects
            # runs on Rhino's display thread.
            self._invoke_ui(self._restart_auto_capture_timer)
        except Exception:
            pass

    def _restart_auto_capture_timer(self):
        if self._form_closed:
            return
        if self._auto_cap_timer is None:
            self._auto_cap_timer = Eto.Forms.UITimer()
            # 2026-04-28 — debounce 1.2s -> 0.3s after user reported the
            # auto-update felt laggy. Short enough that it fires almost
            # immediately when the user lets go of the camera, long enough
            # that a brief mid-orbit pause doesn't burn a capture.
            self._auto_cap_timer.Interval = 0.3
            self._auto_cap_timer.Elapsed += self._on_auto_capture_fire
        try:
            self._auto_cap_timer.Stop()
            self._auto_cap_timer.Start()
        except Exception:
            pass

    def _on_auto_capture_fire(self, sender, e):
        try:
            self._auto_cap_timer.Stop()
        except Exception:
            pass
        if self._form_closed or not self._auto_capture_enabled:
            return
        # In-flight guard: capture at high res (e.g. 2048 px) takes hundreds
        # of ms for ViewCapture + JPEG save + preview reload. If the timer
        # fires again while we're still mid-save, skip — the next camera
        # change will retrigger anyway and we won't fall behind.
        if self._capturing:
            return
        try:
            self._capture_view()
        except Exception:
            pass

    def _invoke_ui(self, fn):
        # Two race windows to guard:
        # 1. Form may close between this check and AsyncInvoke being scheduled.
        # 2. Form may close between scheduling and the dispatcher actually
        #    running our lambda — by which point Eto controls are disposed
        #    and `setattr(self.bt_X, 'Text', ...)` raises ObjectDisposedException
        #    inside the WndProc, which Rhino propagates as a hard crash.
        # Re-check inside the dispatched lambda AND swallow any exception so
        # post-close callbacks can never reach the native message loop.
        # (2026-04-21 audit P0-3.)
        if self._form_closed:
            return
        def _safe():
            if self._form_closed:
                return
            try:
                fn()
            except Exception:
                pass
        try:
            Eto.Forms.Application.Instance.AsyncInvoke(System.Action(_safe))
        except Exception:
            pass

    def _on_tick(self, sender, e):
        """Diff against last tick — only rebuild when (status, progress)
        actually changed. Mirrors the Revit fix from Round 1 to stop the
        1Hz full-rebuild perf hit on Rhino (Round 2 P0-perf-3).

        2026-06-10: dropped `int(j.elapsed_sec())` from the diff tuple. It
        changed every second while a job was ACTIVE, so the tick rebuilt the
        WHOLE gallery once per second. Harmless when the list was small, but
        with the chunked rebuild (large "All time" lists) it would clear and
        restart the build every second and the gallery would never finish
        painting. Progress is still reflected via `progress_pct`; the
        ProgressBar.Indeterminate animates itself without a rebuild. (Slice of
        the #1423 1Hz-rebuild-storm cleanup.)"""
        if self._form_closed:
            return
        Monitor.Enter(self._jobs_lock)
        try:
            current_state = tuple(
                (j.job_id, j.status, j.progress_pct)
                for j in self._jobs
                if j.status == AI_RENDER.STATUS_ACTIVE)
        finally:
            Monitor.Exit(self._jobs_lock)
        if current_state != getattr(self, "_last_tick_state", None):
            self._last_tick_state = current_state
            self._rebuild_rows()

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _on_capture(self, sender, e):
        self._capture_view()

    @ERROR_HANDLE.try_catch_error()
    def _capture_view(self):
        if self._capturing:
            return
        self._capturing = True
        try:
            self._capture_view_impl()
        finally:
            self._capturing = False

    def _capture_view_impl(self):
        view = sc.doc.Views.ActiveView
        if view is None:
            self.status_label.Text = "No active Rhino view to capture."
            return
        long_edge = self._current_long_edge()
        aspect = self._current_aspect()
        w, h = _compute_px(long_edge, aspect)

        # Capture at the requested resolution but NEVER mutate view.Size
        # (Bug-finder [P0-5-2] — old code stretched the actual viewport).
        capture = Rhino.Display.ViewCapture()
        capture.Width = w
        capture.Height = h
        capture.ScaleScreenItems = False
        capture.DrawAxes = False
        capture.DrawGrid = False
        capture.DrawGridAxes = False
        capture.TransparentBackground = False

        # Full ms — fixes folder collision on rapid double-click (Audit P1-runtime-2).
        session_ts = time.strftime("%Y%m%d-%H%M%S-") + str(int(time.time() * 1000))
        folder = os.path.join(FOLDER.DUMP_FOLDER, "EnneadTab_Ai_Rendering",
                              "capture_" + session_ts)
        if not os.path.exists(folder):
            os.makedirs(folder)
        target = os.path.join(folder, "Original.jpeg")

        try:
            bitmap = capture.CaptureToBitmap(view)
            try:
                bitmap.Save(target, System.Drawing.Imaging.ImageFormat.Jpeg)
            finally:
                bitmap.Dispose()
        except Exception as ex:
            self.status_label.Text = "Capture failed: {}".format(str(ex)[:150])
            return

        self._capture_path = target
        self._capture_view_name = view.ActiveViewport.Name

        bmp = G.bitmap_from_path(target, 300, 220)
        if bmp:
            self.capture_preview.Image = bmp
        self.preview_label.Text = "Captured: {}".format(self._capture_view_name)
        self.status_label.Text = "Ready. Click Queue Render to send."

    # ------------------------------------------------------------------
    # Resolution / aspect
    # ------------------------------------------------------------------

    def _on_resolution_changed(self, sender, e):
        self._update_resolution_hint()
        try:
            self._save_pref("resolution_idx", int(self.cb_resolution.SelectedIndex))
            self._save_pref("aspect_idx", int(self.cb_aspect.SelectedIndex))
        except Exception:
            pass

    def _update_resolution_hint(self):
        label = _items_text(self.cb_resolution, self.cb_resolution.SelectedIndex)
        asp = _items_text(self.cb_aspect, self.cb_aspect.SelectedIndex)
        long_edge = dict(RESOLUTION_OPTIONS)[label]
        w, h = _compute_px(long_edge, asp)
        self.resolution_hint.Text = "{} × {} ({} · {})".format(
            w, h, label.split(" ")[0], asp)

    def _current_long_edge(self):
        label = _items_text(self.cb_resolution, self.cb_resolution.SelectedIndex)
        return dict(RESOLUTION_OPTIONS)[label]

    def _current_aspect(self):
        return _items_text(self.cb_aspect, self.cb_aspect.SelectedIndex)

    # ------------------------------------------------------------------
    # Style preset dropdowns
    # ------------------------------------------------------------------

    def _load_presets_async(self):
        def worker(state):
            try:
                token = AUTH.get_token()
                presets = AI_RENDER.get_render_presets(token=token) or []
            except Exception:
                presets = []
            self._invoke_ui(lambda: self._apply_presets(presets))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _apply_presets(self, presets):
        self._presets = presets or []
        if not self._presets:
            self.cb_category.Items.Clear()
            self.cb_category.Items.Add("(Presets unavailable — check connection)")
            self.cb_category.SelectedIndex = 0
            self.cb_style.Items.Clear()
            return
        cats = []
        seen = set()
        for p in self._presets:
            c = p.get("category") or "Other"
            if c not in seen:
                seen.add(c)
                cats.append(c)
        cats.sort()
        self._categories = cats
        self.cb_category.Items.Clear()
        self.cb_category.Items.Add("All")
        for c in cats:
            self.cb_category.Items.Add(c)
        # Restore last category from prefs (2026-04-28). Falls back to "All"
        # if the saved category no longer exists in the curated list.
        saved_cat = self._prefs.get("category_text") if self._prefs else None
        cat_idx = 0
        if saved_cat:
            for i in range(self.cb_category.Items.Count):
                if _items_text(self.cb_category, i) == saved_cat:
                    cat_idx = i
                    break
        self.cb_category.SelectedIndex = cat_idx
        self._refresh_style_list()

    def _refresh_style_list(self):
        self.cb_style.Items.Clear()
        idx = self.cb_category.SelectedIndex
        if idx <= 0:
            self._filtered_presets = list(self._presets)
        else:
            cat = _items_text(self.cb_category, idx)
            self._filtered_presets = [p for p in self._presets if p.get("category") == cat]
        for p in self._filtered_presets:
            self.cb_style.Items.Add(p.get("name") or "?")
        # Hover tooltip listing every preset in the current category
        # with its first-line preview. Same rationale as cb_my_prompts:
        # users don't have to click each one to remember what it does.
        try:
            self.cb_style.ToolTip = self._build_prompt_list_tooltip(
                self._filtered_presets,
                "Rendering styles in this category")
        except Exception:
            pass
        if self._filtered_presets:
            # Restore last style from prefs (2026-04-28). Falls back to first
            # entry if the saved name isn't in the current category's list.
            saved_style = self._prefs.get("style_text") if self._prefs else None
            style_idx = 0
            if saved_style:
                for i in range(self.cb_style.Items.Count):
                    if _items_text(self.cb_style, i) == saved_style:
                        style_idx = i
                        break
            self.cb_style.SelectedIndex = style_idx
            sel = self._filtered_presets[style_idx]
            first_prompt = sel.get("prompt", "")
            if not (self.tbox_prompt.Text or "").strip():
                self.tbox_prompt.Text = first_prompt
                self._initial_prompt_for_reset = first_prompt

    def _on_interior_changed(self, sender, e):
        try:
            self._save_pref("interior", bool(self.cb_interior.Checked))
        except Exception:
            pass

    def _on_category_changed(self, sender, e):
        self._refresh_style_list()
        try:
            self._save_pref("category_text",
                            _items_text(self.cb_category, self.cb_category.SelectedIndex))
        except Exception:
            pass

    def _on_style_changed(self, sender, e):
        idx = self.cb_style.SelectedIndex
        if 0 <= idx < len(self._filtered_presets):
            new_prompt = self._filtered_presets[idx].get("prompt", "")
            self._push_prompt_undo()
            self.tbox_prompt.Text = new_prompt
            self._initial_prompt_for_reset = new_prompt
        try:
            self._save_pref("style_text",
                            _items_text(self.cb_style, self.cb_style.SelectedIndex))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Prompt action buttons
    # ------------------------------------------------------------------

    def _push_prompt_undo(self):
        cur = self.tbox_prompt.Text
        if not cur:
            return
        self._prompt_undo.append(cur)
        if len(self._prompt_undo) > PROMPT_UNDO_CAP:
            self._prompt_undo = self._prompt_undo[-PROMPT_UNDO_CAP:]
        self.bt_undo_prompt.Enabled = True

    def _on_undo_prompt(self, sender, e):
        if not self._prompt_undo:
            self.bt_undo_prompt.Enabled = False
            return
        prev = self._prompt_undo.pop()
        self.tbox_prompt.Text = prev
        if not self._prompt_undo:
            self.bt_undo_prompt.Enabled = False

    def _on_reset_prompt(self, sender, e):
        self._push_prompt_undo()
        self.tbox_prompt.Text = self._initial_prompt_for_reset or ""

    def _run_prompt_api(self, btn, api_fn, action_name):
        prompt = (self.tbox_prompt.Text or "").strip()
        if not prompt:
            self.status_label.Text = "Enter a prompt first."
            return
        btn.Enabled = False
        old_text = btn.Text
        btn.Text = "..."
        self._push_prompt_undo()
        self.status_label.Text = "{}...".format(action_name)

        def _safe_unicode(v):
            # 2026-04-28 — IronPython 2.7's json.loads can return Python
            # `str` (bytes) for ASCII-only JSON strings; setting that as
            # Eto TextArea.Text triggers bytes->unicode coercion via
            # sys.getdefaultencoding() (= "unknown" on Windows non-en-US),
            # which dies on UTF-8 multibyte sequences (e.g. byte 0xE7 in
            # the middle of an em-dash or curly quote the AI added). Same
            # class for str(ex) when the .NET exception Message has
            # non-ASCII chars. Force-decode here so the boundary is safe.
            if v is None:
                return u""
            if isinstance(v, bytes):
                try:
                    return v.decode("utf-8")
                except Exception:
                    try:
                        return v.decode("utf-8", "replace")
                    except Exception:
                        return v.decode("latin-1", "replace")
            try:
                return unicode(v)
            except Exception:
                try:
                    return v.encode("utf-8", "replace").decode("utf-8", "replace")
                except Exception:
                    return u""

        def worker(state):
            token = AUTH.get_token()
            if not token:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Sign in required."))
                self._invoke_ui(lambda: self._restore_btn(btn, old_text))
                return
            try:
                new_text = _safe_unicode(api_fn(token, prompt))
                self._invoke_ui(lambda: setattr(self.tbox_prompt, 'Text', new_text))
                self._invoke_ui(lambda: setattr(self.status_label, 'Text', "Done."))
            except Exception as ex:
                err_text = _safe_unicode(ex)[:200]
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                u"Failed: {}".format(err_text)))
            finally:
                self._invoke_ui(lambda: self._restore_btn(btn, old_text))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _restore_btn(self, btn, old_text):
        btn.Enabled = True
        btn.Text = old_text

    def _on_spell(self, sender, e):
        self._run_prompt_api(self.bt_spell,
                             lambda tok, p: AI_CHAT.spell_check_with_token(tok, p),
                             "Checking")

    def _on_lengthen(self, sender, e):
        is_int = bool(self.cb_interior.Checked)
        self._run_prompt_api(self.bt_lengthen,
                             lambda tok, p: AI_CHAT.improve_prompt_with_token(
                                 tok, p, mode="image", action="improve", is_interior=is_int),
                             "Improving")

    def _on_shorten(self, sender, e):
        self._run_prompt_api(self.bt_shorten,
                             lambda tok, p: AI_CHAT.improve_prompt_with_token(
                                 tok, p, mode="image", action="summarize"),
                             "Summarizing")

    # ------------------------------------------------------------------
    # Style reference
    # ------------------------------------------------------------------

    def _on_browse_style(self, sender, e):
        dlg = Eto.Forms.OpenFileDialog()
        dlg.Filters.Add(Eto.Forms.FileFilter("Images", ".png", ".jpg", ".jpeg", ".webp"))
        if dlg.ShowDialog(self) == Eto.Forms.DialogResult.Ok:
            self._set_style_ref(dlg.FileName)

    def _on_paste_style(self, sender, e):
        try:
            clipboard = Eto.Forms.Clipboard()
            if not clipboard.ContainsImage:
                self.status_label.Text = "No image in clipboard."
                return
            tmp_name = "clip_{}.png".format(int(time.time() * 1000))
            temp_path = os.path.join(FOLDER.DUMP_FOLDER, tmp_name)
            if not os.path.exists(FOLDER.DUMP_FOLDER):
                os.makedirs(FOLDER.DUMP_FOLDER)
            eto_img = clipboard.Image
            # Eto API rename — Rhino 7 uses ToSystemDrawing, newer uses ToSD.
            ext = Rhino.UI.EtoExtensions
            converter = getattr(ext, "ToSD", None) or getattr(ext, "ToSystemDrawing", None)
            if converter is None:
                self.status_label.Text = "Clipboard paste not supported on this Rhino version."
                return
            sys_bmp = converter(eto_img)
            try:
                sys_bmp.Save(temp_path, System.Drawing.Imaging.ImageFormat.Png)
            finally:
                sys_bmp.Dispose()
            self._set_style_ref(temp_path)
        except Exception as ex:
            self.status_label.Text = "Paste failed: {}".format(str(ex)[:150])

    def _on_library_style(self, sender, e):
        self.status_label.Text = "Loading style library..."
        def worker(state):
            # 2026-04-21 — .NET worker exception = process termination. Wrap
            # EVERYTHING in try/except. Audit Lens B, P0. Mirrored in Revit.
            try:
                token = AUTH.get_token()
                if not token:
                    self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                    "Sign in required."))
                    return
                items = AI_RENDER.get_demo_style_images(token)
                self._invoke_ui(lambda: self._show_library_picker(items))
            except Exception as ex:
                _trace("worker.library_style SWALLOWED {}".format(ex))
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Style library failed: {}".format(str(ex)[:120])))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _show_library_picker(self, items):
        """Thumbnail grid (4 columns) of curated Ennead style refs.

        Eto DynamicLayout filled with ImageView buttons. Thumbnails fill
        from cache on a background thread so the modal opens instantly.
        """
        if not items:
            self.status_label.Text = "Style library is empty or unavailable."
            return
        dlg = Eto.Forms.Dialog()
        dlg.Title = "Ennead Style Reference Library ({})".format(len(items))
        dlg.Size = Eto.Drawing.Size(720, 540)

        scroll = Eto.Forms.Scrollable()
        grid = Eto.Forms.DynamicLayout()
        grid.Spacing = Eto.Drawing.Size(6, 6)
        grid.Padding = Eto.Drawing.Padding(8)

        cols = 4
        tiles = []  # list of (item, image_view)
        for i in range(0, len(items), cols):
            row_items = items[i:i+cols]
            grid.BeginHorizontal()
            for item in row_items:
                tile = Eto.Forms.DynamicLayout()
                iv = Eto.Forms.ImageView()
                iv.Size = Eto.Drawing.Size(160, 100)
                tile.Add(iv)
                lbl = Eto.Forms.Label(Text=item["filename"][:24])
                lbl.TextColor = _hex_to_color("#CBCBCB")
                tile.Add(lbl)
                # Click handler — left-button only (Round 3 P2-2 — no filter
                # meant right-click also fired download). Closes modal on
                # success OR failure so user isn't stuck staring at the picker
                # if the network drops mid-download.
                def on_click(s, a, it=item):
                    if a.Buttons != Eto.Forms.MouseButtons.Primary:
                        return
                    self.status_label.Text = "Selected {}".format(it["filename"])
                    def dl_worker(state, it=it):
                        try:
                            path = AI_RENDER.get_or_cache_demo_style_image(
                                it["url"], it["filename"])
                            self._invoke_ui(lambda: self._set_style_ref(path))
                        except Exception as ex:
                            self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                            "Download failed: {}".format(str(ex)[:150])))
                        finally:
                            self._invoke_ui(lambda: dlg.Close())
                    System.Threading.ThreadPool.QueueUserWorkItem(
                        System.Threading.WaitCallback(dl_worker))
                iv.MouseDown += on_click
                tiles.append((item, iv))
                grid.Add(tile)
            grid.EndHorizontal()

        scroll.Content = grid
        dlg.Content = scroll

        # Background-fill thumbnails from cache (downloads on miss).
        def fill_worker(state):
            for item, iv in tiles:
                try:
                    path = AI_RENDER.get_or_cache_demo_style_image(
                        item["url"], item["filename"])
                    bmp = G.bitmap_from_path(path, 160, 100)
                    if bmp is not None:
                        self._invoke_ui(lambda im=iv, b=bmp: setattr(im, "Image", b))
                except Exception:
                    continue
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(fill_worker))

        dlg.ShowModal(self)

    def _on_clear_style(self, sender, e):
        self._style_ref_path = None
        self.style_preview.Image = None
        self.bt_clear_style.Visible = False
        self.status_label.Text = "Style reference cleared."

    def _set_style_ref(self, path):
        self._style_ref_path = path
        bmp = G.bitmap_from_path(path, 120, 92)
        if bmp:
            self.style_preview.Image = bmp
        self.bt_clear_style.Visible = True
        self.status_label.Text = "Style reference: {}".format(os.path.basename(path))

    # ------------------------------------------------------------------
    # My Prompts
    # ------------------------------------------------------------------

    def _set_status(self, msg):
        """Set status_label text from any thread context (when wrapped
        in _invoke_ui) or directly from the UI thread. Phase B1 helper
        - mirrors the dozens of existing direct status_label.Text=...
        sites without introducing a stringly-typed setattr pattern.
        """
        try:
            self.status_label.Text = msg
        except Exception:
            pass

    def _refresh_my_prompts_async(self):
        token = AUTH.get_token()
        if not token:
            self._set_status(
                "My prompts unavailable - sign in or check connection.")
            return
        def worker(state):
            # 2026-04-21 — .NET worker exception = host process termination.
            # Audit Lens B P0. Mirrored in Revit.
            try:
                prompts = AI_RENDER.list_prompts_with_token(token)
                self._invoke_ui(lambda: self._apply_my_prompts(prompts))
            except Exception as ex:
                _trace("worker.my_prompts SWALLOWED {}".format(ex))
                # Phase B1 2026-04-30: surface coherent error instead of silent no-op
                self._invoke_ui(lambda: self._set_status(
                    "My prompts unavailable - check connection."))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _apply_my_prompts(self, prompts):
        self._my_prompts = prompts or []
        self.cb_my_prompts.Items.Clear()
        if not self._my_prompts:
            self.cb_my_prompts.Items.Add("(none — click Save current...)")
            self.cb_my_prompts.SelectedIndex = 0
            self.cb_my_prompts.Enabled = False
            try:
                self.cb_my_prompts.ToolTip = (
                    "No saved prompts yet. Edit the prompt textbox, then "
                    "click 'Save current' to add one.")
            except Exception:
                pass
            return
        self.cb_my_prompts.Enabled = True
        self.cb_my_prompts.Items.Add("— select a saved prompt —")
        for p in self._my_prompts:
            label = p.get("name") or "(unnamed)"
            cat = p.get("category")
            if cat:
                label = "{} · {}".format(label, cat)
            self.cb_my_prompts.Items.Add(label)
        self.cb_my_prompts.SelectedIndex = 0
        # 2026-04-28 — Eto's ComboBox doesn't support per-item hover
        # tooltips, but we can stuff a multi-line preview list into the
        # control's overall ToolTip. Hovering the dropdown trigger now
        # surfaces every saved prompt's name + first-line preview so
        # users don't have to click each one to remember what it says.
        try:
            self.cb_my_prompts.ToolTip = self._build_prompt_list_tooltip(
                self._my_prompts, "Saved prompts")
        except Exception:
            pass

    def _build_prompt_list_tooltip(self, items, header):
        """Format a list of {name, prompt, category?} dicts into a
        multi-line tooltip string. Each line: 'NAME — first ~120 chars'."""
        lines = ["{} ({}):".format(header, len(items)), ""]
        max_per_line = 120
        max_items = 30  # avoid a tooltip that's taller than the screen
        for p in items[:max_items]:
            name = (p.get("name") or "(unnamed)").strip()
            text = (p.get("prompt") or "").strip().replace("\n", " ")
            if len(text) > max_per_line:
                text = text[:max_per_line].rstrip() + "..."
            cat = p.get("category")
            if cat:
                lines.append(u"• {} [{}]".format(name, cat))
            else:
                lines.append(u"• {}".format(name))
            if text:
                lines.append(u"   {}".format(text))
        if len(items) > max_items:
            lines.append("")
            lines.append("... and {} more".format(len(items) - max_items))
        return u"\n".join(lines)

    def _on_browse_my_prompts(self, sender, e):
        """Open the modal prompt browser for saved prompts."""
        if not self._my_prompts:
            self.status_label.Text = (
                "No saved prompts yet — edit the prompt then click Save current.")
            return
        def _on_pick(idx):
            if 0 <= idx < len(self._my_prompts):
                chosen = self._my_prompts[idx]
                text = chosen.get("prompt") or ""
                if text:
                    self._push_prompt_undo()
                    self.tbox_prompt.Text = text
                    self.status_label.Text = u"Loaded prompt: {}".format(
                        chosen.get("name") or "")
        self._show_prompt_browser_modal(
            self._my_prompts, "Browse Saved Prompts", _on_pick)

    def _show_prompt_browser_modal(self, items, title, on_select):
        """Modal picker with a name list (left) and live full-prompt
        preview pane (right). 2026-04-28 — built because Eto ComboBox
        tooltips don't render on this Rhino build, so the multi-line
        tooltip preview attempt was invisible."""
        try:
            dlg = Eto.Forms.Dialog()
            dlg.Title = title
            dlg.Padding = Eto.Drawing.Padding(10)
            dlg.Resizable = True
            try:
                dlg.Size = Eto.Drawing.Size(900, 560)
                dlg.MinimumSize = Eto.Drawing.Size(640, 400)
            except Exception:
                pass

            state = {"idx": 0 if items else -1}

            row = Eto.Forms.DynamicLayout()
            row.Spacing = Eto.Drawing.Size(10, 0)
            row.BeginHorizontal()

            # Left column: list of names + categories
            listbox = Eto.Forms.ListBox()
            try:
                listbox.Width = 280
            except Exception:
                pass
            for p in items:
                item = Eto.Forms.ListItem()
                name = p.get("name") or "(unnamed)"
                cat = p.get("category")
                item.Text = u"{}  [{}]".format(name, cat) if cat else name
                listbox.Items.Add(item)

            # Right column: name header + scrollable full prompt preview
            right = Eto.Forms.DynamicLayout()
            right.Spacing = Eto.Drawing.Size(0, 6)
            lbl_name = Eto.Forms.Label(Text="")
            try:
                lbl_name.Font = Eto.Drawing.Font(
                    Eto.Drawing.SystemFont.Bold, 13)
                lbl_name.TextColor = _hex_to_color("#FFE59C")
            except Exception:
                pass
            right.Add(lbl_name)

            preview = Eto.Forms.TextArea()
            try:
                preview.ReadOnly = True
                preview.Wrap = True
                preview.Font = Eto.Drawing.Font(
                    Eto.Drawing.SystemFont.Default, 11)
            except Exception:
                pass
            right.Add(preview, yscale=True)

            def _refresh_preview(idx):
                if 0 <= idx < len(items):
                    p = items[idx]
                    lbl_name.Text = p.get("name") or "(unnamed)"
                    preview.Text = p.get("prompt") or ""
                else:
                    lbl_name.Text = ""
                    preview.Text = ""

            def _on_sel_changed(s, ev):
                state["idx"] = listbox.SelectedIndex
                _refresh_preview(state["idx"])
            listbox.SelectedIndexChanged += _on_sel_changed

            row.Add(listbox)
            row.Add(right, xscale=True)
            row.EndHorizontal()
            dlg.Content = row

            # Buttons via Dialog's positive/negative slots so Enter/Esc work.
            bt_ok = Eto.Forms.Button(Text="Load Prompt")
            def _on_ok(s, ev):
                if state["idx"] >= 0:
                    try:
                        on_select(state["idx"])
                    except Exception as ex:
                        _trace("browser on_select failed: " + str(ex))
                dlg.Close()
            bt_ok.Click += _on_ok
            dlg.DefaultButton = bt_ok
            dlg.PositiveButtons.Add(bt_ok)

            bt_cancel = Eto.Forms.Button(Text="Cancel")
            bt_cancel.Click += lambda s, ev: dlg.Close()
            dlg.AbortButton = bt_cancel
            dlg.NegativeButtons.Add(bt_cancel)

            # Pre-select first item.
            if items:
                listbox.SelectedIndex = 0
                _refresh_preview(0)

            dlg.ShowModal(self)
        except Exception as ex:
            _trace("browser dialog FAILED: " + str(ex))
            self.status_label.Text = u"Browser failed: {}".format(str(ex)[:120])

    def _on_my_prompt_changed(self, sender, e):
        idx = self.cb_my_prompts.SelectedIndex
        if idx <= 0 or idx > len(self._my_prompts):
            return
        chosen = self._my_prompts[idx - 1]
        text = chosen.get("prompt") or ""
        if text:
            self._push_prompt_undo()
            self.tbox_prompt.Text = text
            self.status_label.Text = "Loaded prompt: {}".format(chosen.get("name") or "")

    def _on_save_prompt(self, sender, e):
        prompt_text = (self.tbox_prompt.Text or "").strip()
        if not prompt_text:
            self.status_label.Text = "Nothing to save."
            return
        # Eto's input dialog
        name = self._prompt_for_text("Save prompt", "Name this prompt:", "")
        if not name:
            return
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        idx = self.cb_style.SelectedIndex
        category = None
        if 0 <= idx < len(self._filtered_presets):
            category = self._filtered_presets[idx].get("category")
        def worker(state):
            try:
                AI_RENDER.save_prompt_with_token(token, name, prompt_text, category=category)
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Saved prompt '{}'".format(name)))
                self._invoke_ui(self._refresh_my_prompts_async)
            except Exception as ex:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Save failed: {}".format(str(ex)[:200])))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _prompt_for_text(self, title, label_text, default=""):
        dlg = Eto.Forms.Dialog()
        dlg.Title = title
        dlg.Size = Eto.Drawing.Size(360, 140)
        layout = Eto.Forms.DynamicLayout()
        layout.Padding = Eto.Drawing.Padding(10)
        layout.Add(Eto.Forms.Label(Text=label_text))
        tb = Eto.Forms.TextBox()
        tb.Text = default
        layout.Add(tb)
        result = [None]
        ok = Eto.Forms.Button(Text="OK")
        cancel = Eto.Forms.Button(Text="Cancel")
        def on_ok(s, a):
            txt = (tb.Text or "").strip()
            result[0] = txt if txt else None
            dlg.Close()
        ok.Click += on_ok
        cancel.Click += lambda s, a: dlg.Close()
        layout.AddSeparateRow(None, ok, cancel)
        dlg.Content = layout
        dlg.ShowModal(self)
        return result[0]

    # ------------------------------------------------------------------
    # Queue Render
    # ------------------------------------------------------------------

    @ERROR_HANDLE.try_catch_error()
    def _on_render(self, sender, e):
        # 2026-04-21 — Queue Render is the active crash surface. Trace each
        # step to %APPDATA%/EnneadTab/ai_render_trace.log so the next crash
        # leaves a breadcrumb trail showing exactly where execution died,
        # even if the failure is a native AccessViolation that no Python
        # exception handler can intercept. Remove the trace once stable.
        _trace("Queue.START")
        if not self._capture_path or not os.path.exists(self._capture_path):
            self.status_label.Text = "Capture a view first."
            _trace("Queue.ABORT no_capture")
            return
        prompt = (self.tbox_prompt.Text or "").strip()
        if not prompt:
            self.status_label.Text = "Please enter a prompt first."
            _trace("Queue.ABORT no_prompt")
            return
        if not AI_RENDER.can_enqueue(self._jobs, self._jobs_lock):
            self.status_label.Text = "Queue full ({} active). Wait for one to finish.".format(AI_RENDER.ACTIVE_CAP)
            _trace("Queue.ABORT queue_full")
            return
        _trace("Queue.preflight_ok prompt_len={} style_idx={}".format(
            len(prompt), self.cb_style.SelectedIndex))
        style_name = ""
        idx = self.cb_style.SelectedIndex
        if 0 <= idx < len(self._filtered_presets):
            style_name = self._filtered_presets[idx].get("name") or ""

        _trace("Queue.before_RenderJob_init")
        job = AI_RENDER.RenderJob(
            original_path=None,
            prompt=prompt,
            style_preset=style_name,
            style_ref_path=self._style_ref_path,
            aspect_ratio=self._current_aspect(),
            long_edge=self._current_long_edge(),
            view_name=self._capture_view_name,
            is_interior=bool(self.cb_interior.Checked),
            kind=AI_RENDER.KIND_IMAGE,
            host="rhino",
            auto_save_gallery=self._auto_save_enabled)
        _trace("Queue.RenderJob_created job_id={}".format(job.job_id[:8]))
        snapshot = os.path.join(job.job_folder,
                                "original" + os.path.splitext(self._capture_path)[1])
        try:
            shutil.copy2(self._capture_path, snapshot)
        except Exception as ex:
            self.status_label.Text = "Snapshot failed: {}".format(ex)
            _trace("Queue.snapshot_FAILED {}".format(ex))
            return
        job.original_path = snapshot
        _trace("Queue.snapshot_ok size={} bytes".format(
            os.path.getsize(snapshot) if os.path.exists(snapshot) else -1))

        Monitor.Enter(self._jobs_lock)
        try:
            self._jobs.append(job)
        finally:
            Monitor.Exit(self._jobs_lock)
        _trace("Queue.before_worker_wake jobs_count={}".format(len(self._jobs)))
        self._image_worker.wake()
        _trace("Queue.after_worker_wake")
        self.status_label.Text = "Queued (job #{}).".format(job.job_id[:6])
        # Do NOT call self._rebuild_rows() here. The worker fires _on_job_update
        # → _invoke_ui(self._rebuild_rows) within milliseconds; calling it
        # synchronously creates a re-entry race against both that AsyncInvoke
        # AND the 1 Hz tick rebuild, which mutates StackLayout.Items from
        # multiple paths in one message-pump cycle and crashes Rhino on Eto's
        # native backend. (2026-04-21 audit P0-2.)
        self._update_active_jobs_label()
        _trace("Queue.END")

    def _on_job_update(self, job):
        # Worker thread — marshal to UI and check for pause state.
        _trace("on_job_update.START job={} status={}".format(
            getattr(job, "job_id", "?")[:8], getattr(job, "status", "?")))
        Monitor.Enter(self._jobs_lock)
        try:
            paused = any(
                j.status == AI_RENDER.STATUS_PENDING and j.error_msg
                and "auth" in (j.error_msg or "").lower()
                for j in self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        self._invoke_ui(self._rebuild_rows)
        self._invoke_ui(self._update_active_jobs_label)
        self._invoke_ui(lambda: setattr(self.bt_resume, 'Visible', paused))
        _trace("on_job_update.END job={}".format(getattr(job, "job_id", "?")[:8]))

    def _on_any_job_complete(self, job):
        self._invoke_ui(self._refresh_quota_async)
        Monitor.Enter(self._jobs_lock)
        try:
            still_going = any(j.status in (AI_RENDER.STATUS_PENDING, AI_RENDER.STATUS_ACTIVE)
                              for j in self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        if not still_going:
            AI_RENDER.play_completion_sound()

    def _on_resume(self, sender, e):
        AUTH.clear_token()
        if not AUTH.is_auth_in_progress():
            AUTH.request_auth()
        if AUTH.get_token():
            self._image_worker.resume()
            self._video_worker.resume()
            self.bt_resume.Visible = False
            self.status_label.Text = "Queue resumed."
        else:
            self.status_label.Text = "Sign in via the browser, then click Resume again."

    # ------------------------------------------------------------------
    # Gallery rebuild + filters
    # ------------------------------------------------------------------

    def _rebuild_rows(self):
        # Snapshot under lock, build rows OUTSIDE lock (no I/O while workers
        # are blocked) — Round 2 P0-perf-3 port from Revit.
        _trace("rebuild.START")
        Monitor.Enter(self._jobs_lock)
        try:
            jobs_snapshot = list(self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        _trace("rebuild.snapshot jobs={}".format(len(jobs_snapshot)))
        job_rows = [G.row_from_job(j) for j in jobs_snapshot]
        # Dedup: cloud rows whose ID matches a local job's gallery_id are
        # already on screen via the local job row (P0-state-2 from Round 2 —
        # was comparing job_id to cloud_id, never matched).
        local_gallery_ids = set(j.gallery_id for j in jobs_snapshot if j.gallery_id)
        cloud_only = [r for r in self._all_rows if r.cloud_item
                      and r.id not in local_gallery_ids]
        merged = G.filter_rows(job_rows + cloud_only,
                               self._filter_seconds, self._filter_query)
        _trace("rebuild.merged total={} job_rows={} cloud_only={}".format(
            len(merged), len(job_rows), len(cloud_only)))
        # While the initial cloud history is still loading, never collapse to an
        # empty "0 items" list -- hold the skeleton loading state so the gallery
        # reads as "loading", not "you have nothing". Any rebuild that fires
        # before _apply_gallery_rows lands (a stray tick, a large-thumbs toggle)
        # used to wipe the skeleton ~1s after open and show "0 items" for the
        # rest of the fetch window. Only the genuine "loaded but empty" case
        # (history_loaded True, 0 rows) shows the empty list.
        if not merged and not self._history_loaded:
            try:
                self._rebuild_timer.Stop()
            except Exception:
                pass
            self._render_skeleton_rows()
            try:
                self.gallery_count.Text = "loading..."
            except Exception:
                pass
            _trace("rebuild.skeleton-hold (history not loaded)")
            return
        # Chunked rebuild: a new build supersedes any in-flight one. Stop the
        # timer and install `merged` as the single source of truth -- because
        # everything runs on the one UI thread and the timer reads self state
        # (no captured closures), an older chunked build simply stops the
        # moment its state is overwritten here; no stale or duplicate rows.
        try:
            self._rebuild_timer.Stop()
        except Exception:
            pass
        self._rebuild_merged = merged
        self._rebuild_total = len(merged)
        self._rebuild_pos = 0
        # Clear AND fill the first time-boxed slice in THIS pump cycle so the
        # StackLayout never sits empty across a yield -- an empty-then-paint is
        # the documented Rhino crash trigger (see the pre-2026-06-10 loop).
        try:
            self._rows_layout.Items.Clear()
            _trace("rebuild.cleared")
        except Exception as ex:
            _trace("rebuild.CLEAR_FAILED {}".format(ex))
            raise
        self._build_rows_chunk()
        # Remaining rows fill on the UITimer, which yields the message pump
        # between slices (keeps the dialog responsive on large lists).
        if self._rebuild_pos < self._rebuild_total:
            try:
                self._rebuild_timer.Start()
            except Exception:
                pass
        else:
            self._finish_rebuild_count()

    # Frame budget per build slice; once exceeded we yield so paint/input run.
    _REBUILD_SLICE_MS = 14

    def _build_rows_chunk(self):
        """Build one time-boxed slice of self._rebuild_merged onto the
        StackLayout, advancing self._rebuild_pos. UI-THREAD ONLY (called from
        _rebuild_rows and _on_rebuild_timer_tick, both UI-thread). Always
        builds at least one row so progress is guaranteed even if a single
        panel costs more than the slice budget."""
        merged = self._rebuild_merged
        total = self._rebuild_total
        t0 = time.time()
        while self._rebuild_pos < total:
            i = self._rebuild_pos
            r = merged[i]
            try:
                # 2026-04-21 — factory pattern. Direct GalleryRowPanel(...)
                # call hits IronPython's CLR-derived constructor binder bug;
                # the .create() factory + zero-arg __init__ is the McNeel-forum
                # workaround. Do NOT revert to GalleryRowPanel(...).
                panel = GalleryRowPanel.create(
                    r,
                    self._row_view_original,
                    self._row_view_result,
                    self._row_save,
                    self._row_context_menu,
                    self._row_copy)
                self._rows_layout.Items.Add(Eto.Forms.StackLayoutItem(panel,
                                                                      Eto.Forms.HorizontalAlignment.Stretch))
            except Exception as ex:
                # Skip the bad row, keep going — a half-built list still paints;
                # an aborted rebuild does not.
                _trace("rebuild.ROW_FAILED idx={} id={} {}".format(
                    i, getattr(r, "id", "?"), ex))
            self._rebuild_pos += 1
            if (time.time() - t0) * 1000.0 >= self._REBUILD_SLICE_MS:
                break
        # Progress feedback while more slices remain.
        if self._rebuild_pos < total:
            try:
                self.gallery_count.Text = "· loading {}/{}...".format(
                    self._rebuild_pos, total)
            except Exception:
                pass

    def _on_rebuild_timer_tick(self, sender, e):
        """Drive the remaining rebuild slices. UITimer.Elapsed does NOT inherit
        _invoke_ui._safe, so guard _form_closed + swallow here, or a tick after
        close touches disposed controls and hard-crashes Rhino (CLR
        0xE0434352)."""
        if self._form_closed:
            try:
                self._rebuild_timer.Stop()
            except Exception:
                pass
            return
        try:
            if self._rebuild_pos >= self._rebuild_total:
                self._rebuild_timer.Stop()
                self._finish_rebuild_count()
                return
            self._build_rows_chunk()
            if self._rebuild_pos >= self._rebuild_total:
                self._rebuild_timer.Stop()
                self._finish_rebuild_count()
        except Exception as ex:
            try:
                self._rebuild_timer.Stop()
            except Exception:
                pass
            _trace("rebuild.timer SWALLOWED {}".format(ex))

    def _finish_rebuild_count(self):
        """Set the final gallery count once the chunked build drains. Built may
        be < total if some rows failed; read the realized item count."""
        total = self._rebuild_total
        try:
            built = self._rows_layout.Items.Count
        except Exception:
            built = total
        try:
            if built >= total:
                self.gallery_count.Text = "· {} items".format(total)
            else:
                self.gallery_count.Text = "· {}/{} items (some failed)".format(
                    built, total)
        except Exception:
            pass
        _trace("rebuild.END built={} of {}".format(built, total))

    def _refresh_gallery_async(self):
        token = AUTH.get_token()
        if not token:
            # Phase B1 2026-04-30: surface coherent error instead of silent no-op
            self._set_status(
                "Gallery unavailable - sign in or check connection.")
            return
        def on_done(rows):
            if rows is None:
                # Fetch failed (network or auth). Don't clear existing
                # rows on failure - just surface a status.
                self._invoke_ui(lambda: self._set_status(
                    "Gallery refresh failed - check connection."))
                return
            self._invoke_ui(lambda: self._apply_gallery_rows(rows))
        G.fetch_gallery_index_async(token, on_done, limit=500)

    def _apply_gallery_rows(self, rows):
        self._all_rows = rows
        self._history_loaded = True
        self._rebuild_rows()
        self._update_cache_size()

    def _render_skeleton_rows(self, count=4):
        """Show dimmed loading rows so an empty gallery during initial
        cloud-fetch doesn't look like 'you have nothing'. Replaced by
        real rows the moment _apply_gallery_rows fires (~0.5-3s after
        dialog open depending on network).

        2026-04-28 v2 — earlier version used Eto.Forms.Panel for
        placeholders, which doesn't paint BackgroundColor on this
        Rhino 8 build (same bug that hid the viewer's bar backgrounds).
        Switched to Scrollable-wrapped Label rows which DO paint.
        """
        try:
            self._rows_layout.Items.Clear()
            for i in range(count):
                placeholder = Eto.Forms.Scrollable()
                placeholder.BackgroundColor = _hex_to_color("#FF2A2A2A")
                try:
                    # getattr, not Eto.Forms.BorderType.None: `None` is a keyword, so the
                    # dotted form is a hard SyntaxError under CPython 3. IronPython 2.7
                    # tolerates it at runtime, but both knowledge harvesters ast.parse this
                    # file under CPython 3 -- one unparseable line silently dropped the whole
                    # button from the Rhino tooltip ("N/A") and from the Wiki catalog.
                    placeholder.Border = getattr(Eto.Forms.BorderType, "None")
                    placeholder.ExpandContentWidth = True
                    placeholder.ExpandContentHeight = True
                except Exception:
                    pass
                placeholder.Padding = Eto.Drawing.Padding(16, 28)
                placeholder.Height = 80
                # Honesty fix 2026-04-30: previously said "(1/4)"..(4/4)"
                # which read as 25%-stages of progress. It's just 4
                # identical placeholder rows - all say the same thing.
                label = Eto.Forms.Label(Text="Loading recent renders...")
                try:
                    label.TextColor = _hex_to_color("#FF6A6A6A")
                    label.Font = Eto.Drawing.Font(
                        Eto.Drawing.SystemFont.Default, 11)
                except Exception:
                    pass
                placeholder.Content = label
                self._rows_layout.Items.Add(
                    Eto.Forms.StackLayoutItem(
                        placeholder,
                        Eto.Forms.HorizontalAlignment.Stretch))
            try:
                self._rows_layout.Invalidate()
            except Exception:
                pass
            _trace("skeleton rendered {} placeholder rows".format(count))
        except Exception as ex:
            _trace("skeleton render failed: {}".format(ex))

    def _on_date_filter_changed(self, sender, e):
        idx = self.cb_date_filter.SelectedIndex
        if 0 <= idx < len(G.DATE_FILTERS):
            _, secs = G.DATE_FILTERS[idx]
            self._filter_seconds = secs
            self._rebuild_rows()

    def _on_search_changed(self, sender, e):
        self._filter_query = (self.tbox_search.Text or "").strip()
        self._rebuild_rows()

    @ERROR_HANDLE.try_catch_error()
    def _on_large_thumbs_changed(self, sender, e):
        # 2026-04-21 — Eto CheckBox.CheckedChanged fires on the UI thread;
        # any uncaught exception here escapes into the WPF/Eto message pump
        # as an unhandled managed exception (CLR 0xE0434352) and crashes
        # Rhino. Wrap in @ERROR_HANDLE.try_catch_error() AND hand all real
        # work off via _invoke_ui so the checkbox event handler returns
        # quickly — the actual rebuild happens on the next pump cycle
        # without re-entering from the event handler stack frame.
        _trace("large_thumbs.changed checked={}".format(
            bool(self.cb_large_thumbs.Checked)))
        try:
            if bool(self.cb_large_thumbs.Checked):
                G.set_thumb_size(G.THUMB_W_LARGE, G.THUMB_H_LARGE)
            else:
                G.set_thumb_size(G.THUMB_W_SMALL, G.THUMB_H_SMALL)
            self._save_pref("large_thumbs", bool(self.cb_large_thumbs.Checked))
        except Exception as ex:
            _trace("large_thumbs.set_size FAILED {}".format(ex))
            return
        # Defer both the server refresh and the local rebuild so the
        # CheckedChanged event returns immediately without re-entering.
        self._invoke_ui(self._refresh_gallery_async)
        self._invoke_ui(self._rebuild_rows)

    def _on_refresh_gallery(self, sender, e):
        self.status_label.Text = "Refreshing gallery..."
        self._refresh_gallery_async()

    def _on_scroll_to_active(self, sender, e):
        try:
            if self._rows_layout.Items.Count > 0:
                self._scroll.ScrollPosition = Eto.Drawing.Point(0, 0)
        except Exception:
            pass

    def _update_active_jobs_label(self):
        n = AI_RENDER.count_inflight(self._jobs, self._jobs_lock)
        self.bt_active_jobs.Text = "Active jobs ({})".format(n)

    # ------------------------------------------------------------------
    # Row interactions
    # ------------------------------------------------------------------

    @ERROR_HANDLE.try_catch_error()
    def _row_view_original(self, row):
        # 2026-04-28 — open in the native Eto viewer (was os.startfile).
        # 2026-04-28 v3 — wrapped in try_catch_error AND deferred via
        # _invoke_ui so any failure during viewer construction can't
        # escape into the GalleryRowPanel MouseDown event pump (CLR
        # 0xE0434352 crash class). Same pattern as _on_large_thumbs_changed.
        self._invoke_ui(lambda: self._open_in_viewer(row, "original"))

    @ERROR_HANDLE.try_catch_error()
    def _row_view_result(self, row):
        self._invoke_ui(lambda: self._open_in_viewer(row, "result"))

    def _gallery_rows_snapshot(self):
        """Snapshot the rows currently DISPLAYED in the gallery, in
        display order. Mirrors the Revit sibling's _gallery_rows_snapshot
        (which reads lv_gallery.ItemsSource); the Eto equivalent walks
        the StackLayout items and pulls each GalleryRowPanel's _row.
        Skeleton placeholders (plain Scrollables) carry no _row and are
        skipped, as are rows whose panel failed to build (they never
        reached Items).

        2026-06-10: _open_in_viewer previously iterated self._all_rows --
        the CLOUD gallery cache, empty until a cloud fetch lands -- so a
        fresh local render opened the viewer with one path and no
        alternate (trace: show_viewer paths=1 alts=0). The viewer then
        correctly disabled Prev/Next (n=1) and the Input/Result toggle
        had nothing to swap to. Walking the live UI keeps the viewer
        bound to exactly what the user sees, date/search filters
        included.
        """
        rows = []
        try:
            for item in self._rows_layout.Items:
                ctrl = getattr(item, "Control", item)
                r = getattr(ctrl, "_row", None)
                if r is not None:
                    rows.append(r)
        except Exception as ex:
            _trace("gallery_rows_snapshot FAILED {}".format(ex))
        return rows

    @ERROR_HANDLE.try_catch_error()
    def _open_in_viewer(self, row, prefer):
        """prefer = 'original' or 'result'. Shows the native viewer with
        all currently-loaded rows as siblings so left/right navigates
        through the visible gallery."""
        Rhino.RhinoApp.WriteLine(
            "[ai_render] _open_in_viewer prefer={} row.original={} row.result={} cloud={} viewer_loaded={}".format(
                prefer,
                bool(row.original_path), bool(row.result_path),
                bool(row.cloud_item),
                _SHOW_VIEWER is not None))
        if _SHOW_VIEWER is None:
            Rhino.RhinoApp.WriteLine(
                "[ai_render] viewer module not loaded - falling back to os.startfile")
            self._legacy_open(row, prefer)
            return
        if getattr(row, "kind", None) == "video":
            # Eto.Drawing.Bitmap can't decode mp4 -- the image viewer
            # would show a blank (or, worse, the previous row's bitmap).
            # Hand video rows to the OS player like the pre-viewer path.
            self._legacy_open(row, prefer)
            return
        show_viewer = _SHOW_VIEWER
        # Build parallel lists so the viewer can:
        # - Walk every row in the visible gallery (Next/Prev)
        # - Toggle Input <-> Result at the current row (Tab)
        # - Show the full prompt and rich metadata in the viewer chrome
        paths = []
        alternates = []
        titles = []
        prompts = []
        subtitles = []
        viewer_rows = []
        start_idx = 0
        clicked_path = (row.result_path if prefer == "result"
                        else row.original_path)
        Rhino.RhinoApp.WriteLine(
            "[ai_render] clicked row path={} exists={}".format(
                clicked_path,
                bool(clicked_path and os.path.exists(clicked_path))))
        # 2026-04-28 — gather EVERY visible row, not just rows with a
        # local file. Cloud-only rows now contribute their stored
        # thumbnail (~512px) as the displayed image so Prev/Next can
        # actually walk the whole history. Full-res download still
        # available via Save Image... button.
        # 2026-06-10 — source switched from self._all_rows (cloud cache,
        # empty for fresh local sessions) to the displayed-row snapshot;
        # see _gallery_rows_snapshot docstring for the trace evidence.
        start_matched = False
        for r in self._gallery_rows_snapshot():
            if getattr(r, "kind", None) == "video":
                continue  # image viewer can't decode video results
            primary_kind = "result" if prefer == "result" else "input"
            alt_kind = "input" if prefer == "result" else "result"
            primary_local = (r.result_path if prefer == "result"
                             else r.original_path)
            alt_local = (r.original_path if prefer == "result"
                         else r.result_path)

            # Pick best available source for primary side.
            primary_path = None
            if primary_local and os.path.exists(primary_local):
                primary_path = primary_local
            elif getattr(r, "cloud_item", None):
                primary_path = self._materialize_thumb(r, primary_kind)
            if not primary_path:
                continue  # nothing to show for this row

            # Pick best available source for alternate side.
            alt_path = None
            if alt_local and os.path.exists(alt_local):
                alt_path = alt_local
            elif getattr(r, "cloud_item", None):
                alt_path = self._materialize_thumb(r, alt_kind)

            paths.append(primary_path)
            alternates.append(alt_path)
            titles.append(r.StyleName or "-")
            prompts.append(r.full_prompt or r.PromptPreview or "")
            subtitles.append(r.Subtitle or "")
            viewer_rows.append(r)
            # First match wins. Identity first, but the 1Hz rebuild
            # creates FRESH row objects every tick and the click is
            # deferred via _invoke_ui, so the stable id equality is the
            # workhorse, not a nicety. If the clicked row got filtered
            # out by an intervening rebuild, start_idx stays 0 (defined
            # behavior: viewer opens at the top of the visible set).
            if not start_matched and (
                    r is row or
                    getattr(r, "id", None) == getattr(row, "id", "MISS")):
                start_idx = len(paths) - 1
                start_matched = True
        Rhino.RhinoApp.WriteLine(
            "[ai_render] gathered {} paths ({} with alternates), start_idx={}".format(
                len(paths),
                sum(1 for a in alternates if a),
                start_idx))
        # 2026-04-28 fix: if the clicked row's local file is missing
        # but the gallery has OTHER local rows, still open the viewer
        # with whatever IS local — start_idx falls back to 0. And if
        # NOTHING is local but the clicked row has a cloud item,
        # fetch then open. Old code's "0 paths -> bail to status bar"
        # was leaving the user stuck whenever they clicked a cloud-only
        # history row that had original_path/result_path attribute set
        # to a stale or never-downloaded local path.
        if not paths:
            if row.cloud_item:
                Rhino.RhinoApp.WriteLine(
                    "[ai_render] no local paths, fetching cloud item")
                self._fetch_and_open_full(row)
                return
            if clicked_path:
                Rhino.RhinoApp.WriteLine(
                    "[ai_render] no exists() match - trying single-path mode")
                # 2026-06-10: carry the clicked row's OTHER side as the
                # alternate when it exists on disk -- the old [None] left
                # the Input/Result toggle a no-op even with both files
                # sitting in the job folder.
                alt_fallback = (row.original_path if prefer == "result"
                                else row.result_path)
                if not (alt_fallback and os.path.exists(alt_fallback)):
                    alt_fallback = None
                paths = [clicked_path]
                alternates = [alt_fallback]
                titles = [row.StyleName or "-"]
                prompts = [row.full_prompt or row.PromptPreview or ""]
                subtitles = [row.Subtitle or ""]
                viewer_rows = [row]
                start_idx = 0
            else:
                Rhino.RhinoApp.WriteLine(
                    "[ai_render] no paths AND no cloud_item - cannot open")
                self.status_label.Text = "No image available."
                return

        # Save / Open callbacks let the viewer act on the gallery row
        # without re-implementing the file-save dialog flow.
        def _viewer_save(viewer_idx, show_alt):
            if not (0 <= viewer_idx < len(viewer_rows)):
                return
            r = viewer_rows[viewer_idx]
            self._invoke_ui(lambda: self._row_save(r))

        def _viewer_open_external(viewer_idx, show_alt):
            if not (0 <= viewer_idx < len(viewer_rows)):
                return
            r = viewer_rows[viewer_idx]
            p = r.original_path if show_alt else r.result_path
            if p and os.path.exists(p):
                try:
                    os.startfile(p)
                except Exception:
                    pass

        try:
            f = show_viewer(
                self, paths,
                start_index=start_idx,
                titles=titles,
                alternates=alternates,
                prompts=prompts,
                subtitles=subtitles,
                on_save_index=_viewer_save,
                on_open_external_index=_viewer_open_external)
            if f is None:
                Rhino.RhinoApp.WriteLine(
                    "[ai_render] show_viewer returned None - falling back")
                self._legacy_open(row, prefer)
            else:
                self.status_label.Text = "Viewing {}/{}".format(
                    start_idx + 1, len(paths))
        except Exception as ex:
            Rhino.RhinoApp.WriteLine(
                "[ai_render] show_viewer raised: {}".format(ex))
            self.status_label.Text = "Viewer failed: {}".format(str(ex)[:120])
            self._legacy_open(row, prefer)

    def _materialize_input_thumb(self, row):
        return self._materialize_thumb(row, "input")

    def _materialize_thumb(self, row, kind):
        """Write a cloud row's stored thumbnail (input OR result) to a
        temp PNG and return the path. Used as a viewer-path fallback so
        the History viewer's Prev/Next can walk every row even when the
        full local file isn't cached. Resolution is small (~512px max);
        users still need 'Save Image...' to get the full original.

        kind = 'input'  -> originalThumbnailData
        kind = 'result' -> thumbnailData"""
        try:
            cloud = getattr(row, "cloud_item", None) or {}
            meta = cloud.get("metadata") or {}
            if kind == "input":
                data_url = (cloud.get("originalThumbnailData") or
                            meta.get("originalThumbnailData"))
                suffix = "_input_thumb.png"
            else:
                data_url = (cloud.get("thumbnailData") or
                            cloud.get("thumbnailVideo") or
                            meta.get("thumbnailData"))
                suffix = "_result_thumb.png"
            if not data_url:
                return None
            base = os.environ.get("TEMP") or FOLDER.DUMP_FOLDER
            thumb_dir = os.path.join(base, "EnneadTab_Ai_Rendering",
                                     "viewer_thumbs")
            if not os.path.isdir(thumb_dir):
                try:
                    os.makedirs(thumb_dir)
                except Exception:
                    pass
            row_id = getattr(row, "id", None) or "row"
            out = os.path.join(thumb_dir, "{}{}".format(row_id, suffix))
            if not os.path.exists(out):
                try:
                    G.write_data_url_to_file(data_url, out)
                except Exception as ex:
                    Rhino.RhinoApp.WriteLine(
                        "[ai_render] _materialize_thumb({}) FAILED: {}".format(
                            kind, ex))
                    return None
            return out if os.path.exists(out) else None
        except Exception:
            return None

    def _legacy_open(self, row, prefer):
        path = row.result_path if prefer == "result" else row.original_path
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception:
                pass
        elif row.cloud_item:
            self._fetch_and_open_full(row)

    def _fetch_and_open_full(self, row):
        self.status_label.Text = "Loading full-size image..."
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def on_done(_bmp, path):
            if path:
                self._invoke_ui(lambda: self._open_path(path, row))
            else:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Failed to load image."))
        G.fetch_full_item_async(token, row.id, on_done)

    def _open_path(self, path, row=None):
        # Single-image cloud fetch — use the native viewer with one entry.
        # 2026-04-28: when a row is supplied, pass its prompt + subtitle +
        # style name so the cloud-fetched view has the same chrome as the
        # local rows, not a bare filename. Save callback wired so the
        # toolbar Save button isn't disabled for cloud-fetched items.
        if _SHOW_VIEWER is not None:
            try:
                title = (row.StyleName if row else os.path.basename(path))
                prompts = [row.full_prompt or row.PromptPreview or ""] if row else None
                subtitles = [row.Subtitle or ""] if row else None

                # Save callback for the single-row cloud-fetched case.
                def _viewer_save(viewer_idx, show_alt):
                    if row is None:
                        return
                    self._invoke_ui(lambda: self._row_save(row))

                # Try to surface the input thumbnail as the alternate so
                # "View Input" shows SOMETHING for cloud-only rows. The
                # thumbnail is small but useful for quick before/after.
                alternates = None
                if row is not None and getattr(row, "cloud_item", None):
                    alt_thumb = self._materialize_input_thumb(row)
                    if alt_thumb:
                        alternates = [alt_thumb]

                f = _SHOW_VIEWER(self, [path], start_index=0,
                                 titles=[title],
                                 prompts=prompts,
                                 subtitles=subtitles,
                                 alternates=alternates,
                                 on_save_index=_viewer_save)
                if f is not None:
                    self.status_label.Text = "Opened {}".format(
                        os.path.basename(path))
                    return
            except Exception as ex:
                Rhino.RhinoApp.WriteLine(
                    "[ai_render] viewer open failed: {}".format(ex))
        try:
            os.startfile(path)
            self.status_label.Text = "Opened {}".format(os.path.basename(path))
        except Exception as ex:
            self.status_label.Text = "Open failed: {}".format(ex)

    def _row_save(self, row):
        src = row.result_path
        if not src or not os.path.exists(src):
            if row.cloud_item:
                self._fetch_and_save(row)
                return
            self.status_label.Text = "No local result to save."
            return
        self._save_path_as(src, row)

    def _row_copy(self, row):
        src = row.result_path
        if not src or not os.path.exists(src):
            if row.cloud_item:
                self._fetch_and_copy(row)
                return
            self.status_label.Text = "No local result to copy."
            return
        if IMAGE.copy_image_to_clipboard(src):
            self.status_label.Text = "Copied to clipboard."
        else:
            self.status_label.Text = "Copy failed."

    def _fetch_and_copy(self, row):
        self.status_label.Text = "Downloading for copy..."
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def on_done(_bmp, path):
            if path:
                def finish():
                    if IMAGE.copy_image_to_clipboard(path):
                        self.status_label.Text = "Copied to clipboard."
                    else:
                        self.status_label.Text = "Copy failed."
                self._invoke_ui(finish)
            else:
                self._invoke_ui(lambda: setattr(
                    self.status_label, 'Text', "Download failed."))
        G.fetch_full_item_async(token, row.id, on_done)

    def _save_path_as(self, src, row):
        dlg = Eto.Forms.SaveFileDialog()
        ext = os.path.splitext(src)[1]
        dlg.Filters.Add(Eto.Forms.FileFilter("Image (*{})".format(ext), "*{}".format(ext)))
        dlg.FileName = "{}_{}_{}{}".format(
            _safe_filename(row.view_name or "View"),
            _safe_filename(row.StyleName or "Style"),
            row.id[:6], ext)
        # Bug-finder P2-dead-7: previous code constructed a throwaway
        # SelectFolderDialog just to read .Directory — copy-paste artifact.
        if self._last_save_folder and os.path.isdir(self._last_save_folder):
            dlg.Directory = self._last_save_folder
        if dlg.ShowDialog(self) == Eto.Forms.DialogResult.Ok:
            try:
                shutil.copyfile(src, dlg.FileName)
                self._last_save_folder = os.path.dirname(dlg.FileName)
                self.status_label.Text = "Saved {}".format(os.path.basename(dlg.FileName))
            except Exception as ex:
                self.status_label.Text = "Save failed: {}".format(ex)

    def _fetch_and_save(self, row):
        self.status_label.Text = "Downloading for save..."
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def on_done(_bmp, path):
            if path:
                self._invoke_ui(lambda: self._save_path_as(path, row))
            else:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Failed to fetch image."))
        G.fetch_full_item_async(token, row.id, on_done)

    def _row_context_menu(self, row, anchor):
        cm = Eto.Forms.ContextMenu()
        def add(label, handler, enabled=True):
            mi = Eto.Forms.ButtonMenuItem(Text=label)
            mi.Enabled = enabled
            mi.Click += lambda s, a: handler()
            cm.Items.Add(mi)

        has_local_result = bool(row.result_path and os.path.exists(row.result_path or ""))
        has_local_original = bool(row.original_path and os.path.exists(row.original_path or ""))
        has_cloud = bool(row.cloud_item)
        is_active = bool(row.job_ref and row.job_ref.status in (AI_RENDER.STATUS_PENDING, AI_RENDER.STATUS_ACTIVE))
        gallery_id = (row.cloud_item or {}).get("id") if has_cloud else (
            row.job_ref.gallery_id if row.job_ref else None)

        add("Show full prompt", lambda: self._ctx_show_prompt(row))
        cm.Items.AddSeparator()
        add("Save result as...", lambda: self._row_save(row),
            enabled=has_local_result or has_cloud)
        add("Save bundle (.zip)...", lambda: self._ctx_save_bundle(row),
            enabled=has_local_result and has_local_original)
        add("Copy result to clipboard", lambda: self._row_copy(row),
            enabled=has_local_result or has_cloud)
        cm.Items.AddSeparator()
        is_failed = bool(row.job_ref and row.job_ref.status == AI_RENDER.STATUS_FAILED)
        rerun_label = "Retry" if is_failed else "Re-run with same prompt"
        add(rerun_label, lambda: self._ctx_rerun(row),
            enabled=not is_active and (has_local_original or has_cloud))
        add("Animate (Image → Video)...", lambda: self._ctx_animate(row),
            enabled=not is_active and (has_local_result or has_cloud))
        cm.Items.AddSeparator()
        add("Open in ennead-ai.com Studio", lambda: self._ctx_open_studio(row),
            enabled=bool(gallery_id))
        cm.Items.AddSeparator()
        add("Remove from local cache only", lambda: self._ctx_remove_local(row),
            enabled=has_local_result or has_local_original)
        add("Delete from Gallery (all devices)...",
            lambda: self._ctx_delete_gallery(row, gallery_id),
            enabled=bool(gallery_id))

        cm.Show(anchor)

    def _ctx_show_prompt(self, row):
        cloud_meta = (row.cloud_item or {}).get("metadata") or {}
        if row.job_ref:
            aspect = row.job_ref.aspect_ratio
            long_edge = row.job_ref.long_edge
            interior = "yes" if row.job_ref.is_interior else "no"
            style_ref = (os.path.basename(row.job_ref.style_ref_path)
                         if row.job_ref.style_ref_path else "—")
        else:
            aspect = cloud_meta.get("aspectRatio") or "?"
            long_edge = cloud_meta.get("longEdge") or "?"
            interior = "yes" if cloud_meta.get("isInterior") else "no"
            style_ref = cloud_meta.get("styleRefName") or "—"
        Eto.Forms.MessageBox.Show(
            self,
            ("Style: {}\nView: {}\nHost: {}\n"
             "Aspect: {}\nLong edge: {}px\nInterior: {}\nStyle ref: {}\n\n{}").format(
                row.StyleName or "—", row.view_name or "—", row.host or "—",
                aspect, long_edge, interior, style_ref,
                row.full_prompt or "(empty)"),
            "Prompt for {}".format(row.id[:8]))

    def _row_copy(self, row):
        src = row.result_path
        if not src or not os.path.exists(src):
            if row.cloud_item:
                self._fetch_and_copy(row)
                return
            self.status_label.Text = "No result to copy."
            return
        if IMAGE.copy_image_to_clipboard(src):
            self.status_label.Text = "Copied to clipboard."
        else:
            self.status_label.Text = "Copy failed."

    def _fetch_and_copy(self, row):
        self.status_label.Text = "Downloading for copy..."
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def on_done(bmp, path):
            if path:
                def finish():
                    if IMAGE.copy_image_to_clipboard(path):
                        self.status_label.Text = "Copied to clipboard."
                    else:
                        self.status_label.Text = "Copy failed."
                self._invoke_ui(finish)
            else:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Failed to fetch image."))
        G.fetch_full_item_async(token, row.id, on_done)

    def _ctx_remove_local(self, row):
        """Purge local result/original/sidecar files for this row.
        Item remains in cloud Gallery.
        """
        try:
            if row.job_ref and row.job_ref.job_folder and os.path.isdir(row.job_ref.job_folder):
                shutil.rmtree(row.job_ref.job_folder, ignore_errors=True)
            self.status_label.Text = "Local files removed for this row."
            # Remove from in-memory list so it stops appearing as local.
            if row.job_ref:
                Monitor.Enter(self._jobs_lock)
                try:
                    if row.job_ref in self._jobs:
                        self._jobs.remove(row.job_ref)
                finally:
                    Monitor.Exit(self._jobs_lock)
            self._rebuild_rows()
        except Exception as ex:
            self.status_label.Text = "Remove failed: {}".format(str(ex)[:200])

    def _ctx_save_bundle(self, row):
        if not (row.original_path and row.result_path
                and os.path.exists(row.original_path) and os.path.exists(row.result_path)):
            self.status_label.Text = "Bundle requires both original + result locally."
            return
        dlg = Eto.Forms.SaveFileDialog()
        dlg.Filters.Add(Eto.Forms.FileFilter("ZIP archive", ".zip"))
        dlg.FileName = "{}_{}_{}.zip".format(
            _safe_filename(row.view_name or "View"),
            _safe_filename(row.StyleName or "Style"),
            row.id[:6])
        if dlg.ShowDialog(self) != Eto.Forms.DialogResult.Ok:
            return
        try:
            import zipfile
            with zipfile.ZipFile(dlg.FileName, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(row.original_path, "original" + os.path.splitext(row.original_path)[1])
                zf.write(row.result_path, "result" + os.path.splitext(row.result_path)[1])
                meta = "\n".join([
                    "Prompt: " + (row.full_prompt or ""),
                    "Style: " + (row.StyleName or ""),
                    "View: " + (row.view_name or ""),
                    "Host: " + (row.host or ""),
                    "Created: " + time.strftime("%Y-%m-%d %H:%M:%S",
                                                 time.localtime(row.created_at or time.time())),
                    "ID: " + (row.id or ""),
                ])
                zf.writestr("prompt.txt", meta)
            self.status_label.Text = "Bundle saved: {}".format(os.path.basename(dlg.FileName))
        except Exception as ex:
            self.status_label.Text = "Bundle failed: {}".format(str(ex)[:200])

    def _ctx_rerun(self, row):
        if row.original_path and os.path.exists(row.original_path):
            self._enqueue_rerun(row, row.original_path)
            return
        if row.cloud_item:
            self.status_label.Text = "Downloading original for re-run..."
            token = AUTH.get_token()
            if not token:
                self.status_label.Text = "Sign in required."
                return
            def on_done(_bmp, path):
                if path:
                    self._invoke_ui(lambda: self._enqueue_rerun(row, path))
                else:
                    self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                    "Failed to fetch original."))
            G.fetch_full_item_async(token, row.id, on_done)

    def _enqueue_rerun(self, row, original_path):
        if not AI_RENDER.can_enqueue(self._jobs, self._jobs_lock):
            self.status_label.Text = "Queue full."
            return
        # Pull every reproducibility field from the source row (Audit P0).
        meta = (row.cloud_item or {}).get("metadata") or {}
        if row.job_ref:
            aspect = row.job_ref.aspect_ratio
            long_edge = row.job_ref.long_edge
            is_interior = row.job_ref.is_interior
            style_ref = row.job_ref.style_ref_path
        else:
            aspect = meta.get("aspectRatio") or self._current_aspect()
            long_edge = meta.get("longEdge") or self._current_long_edge()
            is_interior = bool(meta.get("isInterior"))
            style_ref = None
        # Preserve video kind/duration/resolution (Round 3 P2-7).
        is_video = (row.kind == "video")
        if row.job_ref and is_video:
            video_dur = row.job_ref.video_duration
            video_res = row.job_ref.video_resolution
        else:
            video_dur = int(meta.get("duration") or 4) if is_video else 4
            video_res = meta.get("resolution") or "720p"
        job = AI_RENDER.RenderJob(
            original_path=original_path, prompt=row.full_prompt,
            style_preset=row.StyleName, style_ref_path=style_ref,
            aspect_ratio=aspect, long_edge=long_edge,
            view_name=row.view_name, is_interior=is_interior,
            kind=(AI_RENDER.KIND_VIDEO if is_video else AI_RENDER.KIND_IMAGE),
            host="rhino", video_duration=video_dur, video_resolution=video_res,
            auto_save_gallery=self._auto_save_enabled)
        Monitor.Enter(self._jobs_lock)
        try:
            self._jobs.append(job)
        finally:
            Monitor.Exit(self._jobs_lock)
        self._image_worker.wake()
        self.status_label.Text = "Re-queued (job #{}).".format(job.job_id[:6])
        self._rebuild_rows()
        self._update_active_jobs_label()

    def _ctx_open_studio(self, row):
        # Parity with Revit ai_render_script._ctx_open_studio (2026-06-04): the
        # menu used to silent-return when the row had no cloud gallery_id (rows
        # not yet uploaded), so the user saw nothing happen. Now we explain why,
        # and surface any open failure.
        gallery_id = (row.cloud_item or {}).get("id") if row.cloud_item else (
            row.job_ref.gallery_id if row.job_ref else None)
        if not gallery_id:
            self.status_label.Text = ("This render isn't in the cloud Gallery yet "
                                      "- enable Auto-save or wait for upload.")
            return
        # Route confirmed 2026-06-04 against EnneadTab-RenderPolisher source (see
        # the Revit sibling for the full note): no per-item deep-link exists. The
        # standalone app exposes /home /studio /museum /about /contact and NO
        # /gallery; /studio renders the whole cloud gallery and ignores any URL
        # id. The prior /gallery/<id> guess 404'd. Open /studio. Keep both sides
        # identical per the Rhino<->Revit parity rule.
        try:
            webbrowser.open("{}/studio".format(STUDIO_URL))
            self.status_label.Text = "Opening your Gallery in ennead-ai.com Studio..."
        except Exception as ex:
            self.status_label.Text = "Couldn't open browser: {}".format(str(ex)[:150])

    def _ctx_delete_gallery(self, row, gallery_id):
        if not gallery_id:
            return
        # Confirm
        dlg = Eto.Forms.MessageBox.Show(
            self,
            "Delete this item from your Gallery?\n\n"
            "Removes it from the cloud — every signed-in device stops showing it.",
            "Delete from Gallery",
            Eto.Forms.MessageBoxButtons.YesNo)
        if dlg != Eto.Forms.DialogResult.Yes:
            return
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def worker(state):
            try:
                AI_RENDER.delete_gallery_item_with_token(token, gallery_id)
                self._invoke_ui(lambda: setattr(self.status_label, 'Text', "Deleted from Gallery."))
                self._invoke_ui(self._refresh_gallery_async)
            except Exception as ex:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Delete failed: {}".format(str(ex)[:200])))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _on_auto_save_changed(self, sender, e):
        self._auto_save_enabled = bool(self.cb_auto_save.Checked)
        self._save_pref("auto_save", self._auto_save_enabled)
        # Visual confirmation in status bar so user knows the toggle stuck
        # (Round 3 P2 — Rhino had no NDA-mode visual cue).
        if self._auto_save_enabled:
            self.status_label.Text = "Auto-save ON — new renders saved to cloud Gallery."
        else:
            self.status_label.Text = "Auto-save OFF — new renders stay local only (NDA mode)."

    def _on_manage_cache(self, sender, e):
        """Open the manage-local-cache modal — clear the gallery cache.
        Cloud is canonical so wipe is non-destructive.
        """
        n = AI_RENDER.cache_size_bytes()
        msg = ("Local gallery cache: {}\n\n"
               "Cloud Gallery is canonical — clearing the local cache only "
               "frees disk space. Items re-download on next view.\n\n"
               "Clear cache now?").format(AI_RENDER.fmt_bytes(n))
        res = Eto.Forms.MessageBox.Show(
            self, msg, "Manage local cache",
            Eto.Forms.MessageBoxButtons.YesNo)
        if res == Eto.Forms.DialogResult.Yes:
            try:
                AI_RENDER.clear_cache()
                self.status_label.Text = "Local cache cleared."
                self._update_cache_size()
            except Exception as ex:
                self.status_label.Text = "Clear failed: {}".format(str(ex)[:200])

    def _on_open_folder(self, sender, e):
        folder = os.path.join(FOLDER.DUMP_FOLDER, "EnneadTab_Ai_Rendering")
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except Exception:
                pass
        try:
            os.startfile(folder)
        except Exception:
            pass

    def _update_cache_size(self):
        def worker(state):
            try:
                n = G.cache_size_bytes()
                self._invoke_ui(lambda: setattr(self.cache_size_label, 'Text',
                                                "{} cached".format(G.fmt_bytes(n))))
            except Exception:
                pass
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _refresh_quota_async(self):
        token = AUTH.get_token()
        if not token:
            self.quota_label.Text = "Quota: -"
            # Phase B1 2026-04-30: surface coherent error instead of silent dash
            self._set_status(
                "Quota unavailable - sign in or check connection.")
            return
        def worker(state):
            # 2026-04-21 — .NET worker exception = host termination.
            # Audit Lens B P0. Mirrored in Revit. The int(...) calls below
            # raise ValueError on non-int strings if the API returns them.
            txt = "Quota: -"
            had_error = False
            try:
                q = AI_RENDER.get_quota_with_token(token)
                if q:
                    txt = "Quota: {:,}/{:,}".format(
                        int(q.get("requestsRemaining") or 0),
                        int(q.get("requestsLimit") or 0))
            except Exception as ex:
                _trace("worker.quota SWALLOWED {}".format(ex))
                had_error = True
            self._invoke_ui(lambda: setattr(self.quota_label, 'Text', txt))
            if had_error:
                # Phase B1 2026-04-30: surface coherent error instead of silent dash
                self._invoke_ui(lambda: self._set_status(
                    "Quota check failed - check connection."))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _open_browser_if_needed(self):
        if AUTH.get_token():
            return
        if not AUTH.is_auth_in_progress():
            AUTH.request_auth()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def view2render():
    if sc.sticky.has_key("EA_AI_RENDER_FORM"):
        existing = sc.sticky["EA_AI_RENDER_FORM"]
        try:
            existing.BringToFront()
            return
        except Exception:
            sc.sticky.Remove("EA_AI_RENDER_FORM")
    form = AiRenderForm()
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Show()
    sc.sticky["EA_AI_RENDER_FORM"] = form


if __name__ == "__main__":
    view2render()
