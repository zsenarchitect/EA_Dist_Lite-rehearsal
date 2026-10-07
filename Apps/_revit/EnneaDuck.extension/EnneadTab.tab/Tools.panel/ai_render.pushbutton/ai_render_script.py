#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Render the current view through Ennead's in-house AI style library.

Queue several renders at once and carry on modeling while they run. Your gallery
follows you between machines, so a render you start at one desk can be picked up
at another.

Features:
- Style references pulled straight from the Ennead library
- Prompt helpers from ennead-ai.com to sharpen a description
- Queue multiple views and collect the results in one gallery"""
__title__ = "AI\nRender"

# 2026-06-03 — ROOT CAUSE of the recurring 0xE0434352 Revit crash (CER
# 1780521027455 / 1780524566541 / 1780525396250). This is a MODELESS dialog:
# its DispatcherTimers, Dispatcher.BeginInvoke callbacks (_invoke_ui), and
# ThreadPool workers all fire AFTER the pushbutton command returns. Without a
# persistent engine, pyRevit (esp. in rocketmode) tears down the script's
# module scope once the command exits, so those deferred callbacks hit
# `UnboundNameException: name '_trace' is not defined` (confirmed via WinDbg on
# the CER minidump) the instant they touch ANY module global -> unhandled
# managed exception -> Revit hard-crash ~3s after the dialog shows. Every other
# EnneaDuck modeless dialog (search, translate_AI, family_browser, ...) already
# sets this; ai_render was the lone tool missing it. One line.
__persistentengine__ = True

import os
import time
import shutil
import webbrowser

import clr # pyright: ignore
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System # pyright: ignore
from System.Threading import Thread, ThreadStart, Monitor # pyright: ignore
from System.Windows import Visibility # pyright: ignore
from System.Windows.Threading import DispatcherTimer, DispatcherPriority # pyright: ignore
from System.Collections.ObjectModel import ObservableCollection # pyright: ignore
from Autodesk.Revit import DB # pyright: ignore

from pyrevit import script
from pyrevit.forms import WPFWindow # pyright: ignore

import proDUCKtion # pyright: ignore
proDUCKtion.validify()
from EnneadTab import ERROR_HANDLE, AUTH, IMAGE, LOG, FOLDER
from EnneadTab.AI import AI_CHAT, AI_RENDER

# Platform-specific gallery module (WPF bitmap loaders + GalleryRow view-model).
import ai_render_gallery_module as G

# Convenience aliases so existing handler code below stays readable.
Q = AI_RENDER  # RenderJob, QueueWorker, ACTIVE_CAP, KIND_IMAGE/VIDEO, STATUS_*
AI = AI_RENDER  # render_*_with_token, get_*, save_to_gallery_with_token, etc.

uidoc = __revit__.ActiveUIDocument  # pyright: ignore
doc = __revit__.ActiveUIDocument.Document  # pyright: ignore

_active_form = [None]  # module-level sentinel to prevent duplicate instances


# 2026-04-21 — Crash tracer. Queue Render is currently crashing Revit with a
# managed-side CLR unhandled exception (0xE0434352, confirmed via CER dump
# 1776796598887). _trace() flushes a timestamped breadcrumb to disk so the
# next crash leaves a trail showing exactly where execution died, even when
# the failure surfaces past the Python layer as a WPF dispatcher exception.
# Mirrors the Rhino tracer at view2render_left.py. Remove these calls once
# the crash class is identified and stable.
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
            _TRACE_PATH = os.path.join(d, "ai_render_revit_trace.log")
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

# Fallback presets are gone by design (see redesign plan — prime directive
# "REUSE, don't reinvent"). If /api/create/image GET fails, we show a
# placeholder instead of stale local data.

# Web deep-link to Studio — opened via the header link.
STUDIO_URL = "https://enneadtab.com/rendering"


# 2026-06-04: visible build stamp (mirrors the Rhino sibling) so a stale
# loaded copy is obvious at a glance. Derived from this file's own mtime at
# import -- no manual bumping. Revit loads from the dev repo so this is
# normally fresh; the stamp still confirms which copy is live.
def _compute_build_tag():
    # Use the NEWEST mtime across every dialog file in this folder (script,
    # XAML, helpers), not just this .py -- otherwise an XAML-only or
    # helper-only change leaves the stamp stale and the freshness signal lies
    # (2026-06-04: a panel-resize lived only in AiRenderForm.xaml and the stamp
    # didn't move). Any file change in the button folder now bumps the stamp.
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        newest = 0
        for fn in os.listdir(d):
            if fn.lower().endswith((".py", ".xaml")):
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

RESOLUTION_OPTIONS = [
    ("Low (768 px)", 768),
    ("Medium (1024 px)", 1024),
    ("High (1500 px)", 1500),
    ("Ultra (2048 px)", 2048),
]
ASPECT_OPTIONS = ["16:9", "4:3", "3:2", "1:1", "9:16", "21:9"]
DEFAULT_RESOLUTION_LABEL = "High (1500 px)"
DEFAULT_ASPECT = "16:9"
# Default Rendering Style category to preselect on open (user pref 2026-06-04).
# Falls back to "All" if the preset library doesn't expose this category.
DEFAULT_CATEGORY = "Technical Drawing"

PROMPT_UNDO_CAP = 10


_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _safe_filename(s):
    """Strip every Windows-illegal character so SaveFileDialog accepts it.

    Also strips trailing/leading underscores+whitespace so an all-illegal
    input like '<<<???>>>' returns 'untitled', not '_______' (Round 2 P1-edge-9).
    """
    out = []
    for c in (s or ""):
        if c in _INVALID_FILENAME_CHARS or ord(c) < 32:
            out.append("_")
        else:
            out.append(c)
    cleaned = "".join(out).strip("_ \t\r\n")
    return (cleaned or "untitled").replace(" ", "_")


def _compute_px(long_edge, aspect):
    """Given long-edge px and aspect ratio string, return (w, h)."""
    try:
        wp, hp = aspect.split(":")
        w, h = float(wp), float(hp)
    except Exception:
        w, h = 16.0, 9.0
    if w >= h:
        return (int(long_edge), int(round(long_edge * h / w)))
    return (int(round(long_edge * w / h)), int(long_edge))


def _load_presets_from_api():
    """Fetch presets from /api/create/image. Empty list on failure."""
    try:
        token = AUTH.get_token()
        return AI.get_render_presets(token=token) or []
    except Exception:
        return []


class AiRenderForm(WPFWindow):

    @ERROR_HANDLE.try_catch_error()
    def __init__(self):
        WPFWindow.__init__(self, "AiRenderForm.xaml")

        # Header assets
        logo_file = IMAGE.get_image_path_by_name("logo_vertical_light.png")
        if logo_file and os.path.exists(logo_file):
            self.set_image_source(self.logo_img, logo_file)

        # State
        self._form_closed = False
        self._rendering_auth_wait = False
        self._prompt_undo = []
        self._style_ref_path = None
        self._capture_path = None  # most-recent viewport export, used as the "original"
        self._capture_view_name = ""
        self._last_save_folder = None

        # Jobs list + lock (Review #2)
        self._jobs = []
        self._jobs_lock = System.Object()

        # Gallery rows (cloud-canonical) — kept in a plain list, bound to ListView
        # by wholesale ItemsSource replacement (Review #1 recommended pattern).
        self._all_rows = []  # jobs + cloud items merged
        # 2026-06-10: derive the initial date-filter window from
        # DEFAULT_DATE_FILTER ("All time" -> None) so it MATCHES the dropdown's
        # initial selection. The dropdown is set to DEFAULT_DATE_FILTER but its
        # SelectionChanged handler (date_filter_Changed) is wired after the
        # index is set and never fires on init -- a hardcoded `7 * 86400` here
        # meant the dropdown read "All time" while the gallery silently filtered
        # to the last 7 days. Invisible while the cloud index OOM'd (0 rows);
        # once the OOM fix landed and 160 rows returned, "All time" was hiding
        # everything older than a week. Keep in sync with the dropdown. Mirrors
        # the Rhino fix in view2render_left.py per the parity rule.
        self._filter_seconds = dict(G.DATE_FILTERS).get(G.DEFAULT_DATE_FILTER)
        self._filter_query = ""
        self._auto_save_enabled = True
        # Init tick state explicitly so first tick doesn't trigger a redundant
        # rebuild (Round 3 P2-9 — `getattr default None` worked but was wasteful).
        self._last_tick_state = None

        # Style presets
        self._presets = []
        self._categories = []
        self._filtered_presets = []
        self._initial_prompt_for_reset = ""

        # Wire resolution + aspect dropdowns
        for label, _px in RESOLUTION_OPTIONS:
            self.cb_resolution.Items.Add(label)
        self.cb_resolution.SelectedIndex = [l for l, _ in RESOLUTION_OPTIONS].index(DEFAULT_RESOLUTION_LABEL)
        self.cb_resolution.SelectionChanged += self._res_or_aspect_changed
        for a in ASPECT_OPTIONS:
            self.cb_aspect.Items.Add(a)
        self.cb_aspect.SelectedIndex = ASPECT_OPTIONS.index(DEFAULT_ASPECT)
        self.cb_aspect.SelectionChanged += self._res_or_aspect_changed
        self._update_resolution_hint()

        # Date filter dropdown
        for label, _ in G.DATE_FILTERS:
            self.cb_date_filter.Items.Add(label)
        default_idx = [l for l, _ in G.DATE_FILTERS].index(G.DEFAULT_DATE_FILTER)
        self.cb_date_filter.SelectedIndex = default_idx

        # Spell-check language (set at runtime to avoid XAML parse quirks)
        try:
            from System.Windows.Markup import XmlLanguage # pyright: ignore
            self.tbox_prompt.Language = XmlLanguage.GetLanguage("en-US")
        except Exception:
            pass

        # Keep #459 -- seed the prompt box with shared starter-prompt chips.
        self._populate_suggested_prompt_chips()

        # Workers: one image + one video per Review #2 recommendation (A) so
        # a 3-min video doesn't block a 30-sec image.
        self._image_worker = Q.QueueWorker(
            kind_filter=Q.KIND_IMAGE,
            jobs_list=self._jobs,
            lock_obj=self._jobs_lock,
            invoke_ui=self._invoke_ui,
            job_update_callback=self._on_job_update,
            is_form_closed_fn=lambda: self._form_closed,
            auto_save_enabled_fn=lambda: self._auto_save_enabled,
            on_completion=self._on_any_job_complete)
        self._video_worker = Q.QueueWorker(
            kind_filter=Q.KIND_VIDEO,
            jobs_list=self._jobs,
            lock_obj=self._jobs_lock,
            invoke_ui=self._invoke_ui,
            job_update_callback=self._on_job_update,
            is_form_closed_fn=lambda: self._form_closed,
            auto_save_enabled_fn=lambda: self._auto_save_enabled,
            on_completion=self._on_any_job_complete)
        self._image_worker.start()
        self._video_worker.start()

        # Ticking timer to refresh active-job elapsed times (once per second).
        self._tick_timer = DispatcherTimer(DispatcherPriority.Background)
        self._tick_timer.Interval = System.TimeSpan.FromSeconds(1)
        self._tick_timer.Tick += self._on_tick
        self._tick_timer.Start()

        # 2026-04-30 (Item A): auth banner polling timer. Runs only while
        # the auth banner is visible (started/stopped by _refresh_auth_banner).
        self._auth_timer = DispatcherTimer(DispatcherPriority.Background)
        self._auth_timer.Interval = System.TimeSpan.FromSeconds(1)
        self._auth_timer.Tick += self._on_auth_tick
        # Initial state: show banner if no token; timer starts only when shown.
        try:
            self._refresh_auth_banner()
        except Exception:
            pass

        self.Closed += self._on_closed

        # Wire context menu on the gallery list (programmatic — Review #1).
        self.lv_gallery.PreviewMouseRightButtonUp += self._on_row_right_click

        # Cleanup old capture_* folders (>7 days) — prevents unbounded disk
        # growth from daily use (Round 2 P1).
        try:
            AI_RENDER.cleanup_old_captures(FOLDER.DUMP_FOLDER, max_age_days=7)
        except Exception:
            pass

        # Kick off async loads: presets, capture, gallery index, quota, my prompts.
        self._load_presets_async()
        self._open_webbrowser_if_needed_token()
        self._refresh_gallery_async(initial=True)
        self._refresh_quota_async()
        self._refresh_my_prompts_async()

        # 2026-05-14 — register auth-complete listener so the dialog auto-
        # refreshes the moment the OAuth callback writes a token. Mirror of
        # the Rhino handler in view2render_left.py::_on_auth_complete (per
        # CLAUDE.md Rhino↔Revit parity rule). Without this, the user clicks
        # the sign-in button, completes auth in the browser, comes back to
        # Revit, and the dialog STILL shows "Sign in required" / empty
        # preset+gallery state until they click something. Now presets,
        # gallery, quota, my-prompts, and the auth banner all refresh
        # themselves automatically.
        try:
            AUTH.register_auth_complete_listener(self._on_auth_complete)
        except Exception:
            pass

        # Build stamp in the footer (parity with Rhino) so a stale copy shows.
        try:
            self.build_label.Text = "build {}".format(_BUILD_TAG)
        except Exception:
            pass

        # Show the dialog FIRST, then schedule the auto-capture asynchronously.
        # `doc.ExportImage` blocks the UI thread for 2-10s on large models —
        # if we capture before Show(), the user clicks the button and sees
        # nothing for seconds, thinks it's broken (Round 3 P1-startup-3).
        self.Show()
        self._invoke_ui(self._capture_view)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_closed(self, sender, e):
        self._form_closed = True
        # 2026-05-14 — unregister auth-complete listener FIRST so a callback
        # racing the close path cannot fire against a disposed WPF window
        # (would surface as CLR 0xE0434352 / unhandled managed exception,
        # the same crash class _invoke_ui guards against). Mirror of Rhino
        # _on_closed in view2render_left.py.
        try:
            AUTH.unregister_auth_complete_listener(self._on_auth_complete)
        except Exception:
            pass
        try:
            self._tick_timer.Stop()
        except Exception:
            pass
        try:
            self._image_worker.stop()
            self._video_worker.stop()
        except Exception:
            pass
        # Identity check — only clear the sentinel if it still points to us
        # (Bug-finder [P1-5-3] — prevents close+reopen race clobbering the
        # freshly-created new form's sentinel).
        if _active_form[0] is self:
            _active_form[0] = None

    def _invoke_ui(self, fn):
        """Marshal a zero-arg lambda onto the UI thread. Safe if form closed.

        Uses BeginInvoke (async, non-blocking) for progress-style updates so
        the worker never blocks on a disposed dispatcher (Review #2).

        2026-04-21 — Two race windows to guard:
        1. Form may close between this check and BeginInvoke being scheduled.
        2. Form may close between scheduling and the dispatcher actually
           running our lambda — by which point WPF controls are disposed
           and `setattr(self.X, 'Property', ...)` raises an exception that
           propagates out of the dispatcher delegate as an unhandled
           managed exception (CLR 0xE0434352) → Revit crash.
        Re-check inside the dispatched lambda AND swallow any exception so
        post-close callbacks can never reach the .NET CLR's unhandled
        exception handler. (Confirmed by CER dump 1776796598887: the
        dispatched fn raised mid-render, propagated out of BeginInvoke's
        delegate, CLR torn down with "An unrecoverable error has occurred".)
        """
        if self._form_closed:
            return
        def _safe():
            if self._form_closed:
                return
            try:
                fn()
            except Exception as ex:
                _trace("dispatcher.SWALLOWED {}".format(ex))
        try:
            self.Dispatcher.BeginInvoke(System.Action(_safe))
        except Exception as ex:
            _trace("dispatcher.SCHEDULE_FAILED {}".format(ex))

    def _on_tick(self, sender, e):
        """Refresh only when an active job's (status, progress) tuple changed.

        Diffing against `self._last_tick_state` avoids full gallery rebuild
        on every second when nothing visual changed.
        """
        if self._form_closed:
            return
        Monitor.Enter(self._jobs_lock)
        try:
            current_state = tuple(
                (j.job_id, j.status, j.progress_pct, int(j.elapsed_sec()))
                for j in self._jobs
                if j.status == Q.STATUS_ACTIVE)
        finally:
            Monitor.Exit(self._jobs_lock)
        if current_state != getattr(self, "_last_tick_state", None):
            self._last_tick_state = current_state
            self._rebuild_rows()

    # ------------------------------------------------------------------
    # Drag-to-move (WindowStyle=None requires manual)
    # ------------------------------------------------------------------

    def mouse_down_main_panel(self, sender, args):
        try:
            if args.ChangedButton == System.Windows.Input.MouseButton.Left:
                self.DragMove()
        except Exception:
            pass

    def close_Click(self, sender, args):
        # If there are pending/active jobs, confirm.
        in_flight = Q.count_inflight(self._jobs, self._jobs_lock)
        if in_flight > 0:
            import clr # pyright: ignore
            clr.AddReference("PresentationFramework")
            from System.Windows import MessageBox, MessageBoxButton, MessageBoxResult
            res = MessageBox.Show(
                "{} render(s) still running or pending.\n\n"
                "Yes = finish them in the background (dialog closes).\n"
                "No  = drop pending jobs and close now.\n"
                "Cancel = keep the dialog open.".format(in_flight),
                "Closing render",
                MessageBoxButton.YesNoCancel)
            if res == MessageBoxResult.Cancel:
                return
            if res == MessageBoxResult.No:
                # Mark all pending as failed so the worker exits promptly.
                Monitor.Enter(self._jobs_lock)
                try:
                    for j in self._jobs:
                        if j.status == Q.STATUS_PENDING:
                            j.status = Q.STATUS_FAILED
                            j.error_msg = "Cancelled on close"
                finally:
                    Monitor.Exit(self._jobs_lock)
        self.Close()

    def open_web_Click(self, sender, args):
        try:
            webbrowser.open(STUDIO_URL)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Auth banner (Item A, 2026-04-30)
    # ------------------------------------------------------------------

    def _refresh_auth_banner(self):
        """Show/hide the auth banner based on AUTH state. Called from
        __init__ once and from every auth_timer tick.

        DispatcherTimer auto-stops once token arrives -- avoids burning
        CPU on a 1Hz tick after the banner is dismissed.
        """
        try:
            has_token = bool(AUTH.get_token())
            in_progress = bool(AUTH.is_auth_in_progress())
        except Exception:
            has_token = False
            in_progress = False
        if has_token:
            self.auth_banner.Visibility = System.Windows.Visibility.Collapsed
            try:
                self._auth_timer.Stop()
            except Exception:
                pass
            return
        # Not authed -- show banner.
        self.auth_banner.Visibility = System.Windows.Visibility.Visible
        if in_progress:
            self.auth_heading.Text = AI_RENDER.AUTH_PANEL_HEADING
            self.auth_body.Text = AI_RENDER.AUTH_PANEL_WAITING
            self.auth_button.IsEnabled = False
        else:
            self.auth_heading.Text = AI_RENDER.AUTH_PANEL_HEADING
            self.auth_body.Text = AI_RENDER.AUTH_PANEL_BODY
            self.auth_button.IsEnabled = True
        try:
            self._auth_timer.Start()
        except Exception:
            pass

    def auth_signin_Click(self, sender, e):
        try:
            AUTH.request_auth()
        except Exception as ex:
            self.status_label.Text = "Sign-in failed: {}".format(ex)
            return
        self._refresh_auth_banner()

    def sign_out_Click(self, sender, e):
        """Clear the cached desktop token and CLOSE the dialog (2026-06-04).

        Per user direction: signing out closes the modeless tool rather than
        refreshing it in place -- protects account info, forces a clean reopen
        + re-auth, and avoids the crash that refreshing WPF state in place after
        clearing the token caused (CER 1780608322870). Minimal: clear, close.
        Mirror of the Rhino handler view2render_left.py::_on_sign_out per the
        parity rule."""
        try:
            AUTH.clear_token()
        except Exception:
            pass
        try:
            self.Close()
        except Exception:
            pass

    def _on_auth_tick(self, sender, e):
        self._refresh_auth_banner()

    def _on_auth_complete(self):
        """Fires (on the AUTH worker thread) once the user finishes browser
        sign-in and the token lands on disk. Mirror of the Rhino handler
        in view2render_left.py::_on_auth_complete (per CLAUDE.md
        Rhino↔Revit parity rule).

        Marshals every refresh back to the WPF Dispatcher; the AUTH module
        invokes us from a .NET background thread that cannot touch WPF
        widgets directly. _invoke_ui already swallows exceptions from
        post-close dispatches so an in-flight callback can't crash Revit
        if the user closes the dialog mid-callback.
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
                self._refresh_gallery_async(initial=False)
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
            # Wake any paused workers (mirrors resume_Click behavior for
            # the case where the queue paused on 401 and the user just
            # signed in via the banner instead of clicking Resume).
            try:
                self._image_worker.resume()
                self._video_worker.resume()
            except Exception:
                pass
            try:
                if hasattr(self, "resume_panel"):
                    self.resume_panel.Visibility = Visibility.Collapsed
            except Exception:
                pass
            try:
                self.status_label.Text = "Signed in. Dialog refreshed."
            except Exception:
                pass

        self._invoke_ui(_refresh_all)

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def _load_presets_async(self):
        def worker(state):
            try:
                presets = _load_presets_from_api()
                self._invoke_ui(lambda: self._apply_presets(presets))
            except Exception as ex:
                _trace("worker.load_presets SWALLOWED {}".format(ex))
                self._invoke_ui(lambda: self._apply_presets([]))
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
        # Preselect DEFAULT_CATEGORY if the library exposes it, else "All".
        sel = 0
        for i in range(self.cb_category.Items.Count):
            if str(self.cb_category.Items[i]).strip().lower() == DEFAULT_CATEGORY.lower():
                sel = i
                break
        self.cb_category.SelectedIndex = sel
        self._refresh_style_list()

    def _refresh_style_list(self):
        self.cb_style.Items.Clear()
        idx = self.cb_category.SelectedIndex
        if idx <= 0:
            self._filtered_presets = list(self._presets)
        else:
            cat = self.cb_category.Items[idx]
            self._filtered_presets = [p for p in self._presets if p.get("category") == cat]
        for p in self._filtered_presets:
            self.cb_style.Items.Add(p.get("name") or "?")
        if self._filtered_presets:
            self.cb_style.SelectedIndex = 0
            first_prompt = self._filtered_presets[0].get("prompt", "")
            if not self.tbox_prompt.Text.strip():
                self.tbox_prompt.Text = first_prompt
                self._initial_prompt_for_reset = first_prompt

    def category_changed(self, sender, e):
        self._refresh_style_list()

    def style_changed(self, sender, e):
        idx = self.cb_style.SelectedIndex
        if 0 <= idx < len(self._filtered_presets):
            new_prompt = self._filtered_presets[idx].get("prompt", "")
            # Save current for undo before replacing.
            self._push_prompt_undo()
            self.tbox_prompt.Text = new_prompt
            self._initial_prompt_for_reset = new_prompt

    # ------------------------------------------------------------------
    # Resolution/aspect
    # ------------------------------------------------------------------

    def _res_or_aspect_changed(self, sender, e):
        self._update_resolution_hint()

    def _update_resolution_hint(self):
        label = self.cb_resolution.Items[self.cb_resolution.SelectedIndex]
        asp = self.cb_aspect.Items[self.cb_aspect.SelectedIndex]
        long_edge = dict(RESOLUTION_OPTIONS)[label]
        w, h = _compute_px(long_edge, asp)
        self.resolution_hint.Text = "{} × {} ({} · {})".format(w, h, label.split(" ")[0], asp)

    def _current_long_edge(self):
        label = self.cb_resolution.Items[self.cb_resolution.SelectedIndex]
        return dict(RESOLUTION_OPTIONS)[label]

    def _current_aspect(self):
        return self.cb_aspect.Items[self.cb_aspect.SelectedIndex]

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    @ERROR_HANDLE.try_catch_error()
    def capture_Click(self, sender, e):
        self._capture_view()

    def _capture_view(self):
        if self._form_closed:
            return
        view = doc.ActiveView
        if view is None:
            self.status_label.Text = "No active Revit view to capture."
            return
        # Full ms (no rolling % 1000) — fixes collision when user clicks
        # Update Capture twice in the same second (Audit P1-runtime-2).
        session_ts = time.strftime("%Y%m%d-%H%M%S-") + str(int(time.time() * 1000))
        folder = os.path.join(FOLDER.DUMP_FOLDER, "EnneadTab_Ai_Rendering",
                              "capture_" + session_ts)
        if not os.path.exists(folder):
            os.makedirs(folder)
        target = os.path.join(folder, "Original.jpeg")

        opts = DB.ImageExportOptions()
        # VisibleRegionOfCurrentView exports only the on-screen (pan/zoom +
        # crop) portion of the ACTIVE view — the Revit equivalent of Rhino's
        # viewport capture. CurrentView always fit-to-page'd the WHOLE view
        # extent, so partial framing (zoom into a corner, render just that)
        # was impossible in Revit while it worked in Rhino (user report
        # 2026-06-10; Autodesk ExportRange enum, confirmed on revitapidocs +
        # McNeel/Kike Garcia: visible-region only works on the active UI view,
        # which is doc.ActiveView above). Per the Rhino<->Revit parity rule
        # this is framework-specific: Rhino already captures the live viewport,
        # so no Rhino-side change is needed.
        opts.ExportRange = DB.ExportRange.VisibleRegionOfCurrentView
        opts.FilePath = target
        opts.HLRandWFViewsFileType = DB.ImageFileType.JPEGMedium
        opts.ShadowViewsFileType = DB.ImageFileType.JPEGMedium
        opts.ImageResolution = DB.ImageResolution.DPI_300
        opts.ZoomType = DB.ZoomFitType.FitToPage
        opts.PixelSize = int(self._current_long_edge())
        try:
            doc.ExportImage(opts)
        except Exception as ex:
            # Some view types reject the visible-region range; fall back to the
            # whole-view export so capture never hard-fails (loses partial
            # framing for that view type, but still produces an image).
            try:
                opts.ExportRange = DB.ExportRange.CurrentView
                doc.ExportImage(opts)
                self.status_label.Text = ("Captured full view "
                                          "(visible-region unsupported here).")
            except Exception as ex2:
                self.status_label.Text = "Export failed: {}".format(str(ex2)[:150])
                return

        # Revit appends the view name; pick the newest JPEG in the folder (sorted by mtime desc).
        candidates = []
        for fn in os.listdir(folder):
            if fn.lower().endswith((".jpg", ".jpeg")):
                p = os.path.join(folder, fn)
                candidates.append((os.path.getmtime(p), p))
        candidates.sort(reverse=True)
        if not candidates:
            self.status_label.Text = "Capture failed — no file produced."
            return
        raw_path = candidates[0][1]

        # Revit's ZoomFitType.FitToPage exports at the VIEW's aspect ratio,
        # not the user's dropdown selection. Crop to the requested aspect now
        # so the API receives an image with the actual target proportions
        # (Audit P0 — Revit aspect dropdown was a lie until this fix).
        cropped_path = self._crop_to_aspect(raw_path, self._current_aspect())
        self._capture_path = cropped_path or raw_path
        self._capture_view_name = view.Name

        bmp = G.bitmap_from_path(self._capture_path)
        if bmp:
            self.capture_preview.Source = bmp
        self.preview_label.Text = "Captured: {}".format(self._capture_view_name)
        self.status_label.Text = "Ready. Click Queue Render to send."

    def _crop_to_aspect(self, src_path, aspect_str):
        """Center-crop the source JPEG to the requested aspect (e.g. '4:3').

        Returns the cropped file path on success, None on failure (caller
        falls back to original).
        """
        try:
            from System.Drawing import Bitmap as SDBitmap, Rectangle, Imaging
            wp, hp = aspect_str.split(":")
            target_ratio = float(wp) / float(hp)
            src = SDBitmap(src_path)
            cropped = None
            try:
                cur_w, cur_h = src.Width, src.Height
                cur_ratio = float(cur_w) / float(cur_h)
                if abs(cur_ratio - target_ratio) < 0.01:
                    return src_path  # already correct, no crop needed
                if cur_ratio > target_ratio:
                    # Too wide — crop sides
                    new_w = int(cur_h * target_ratio)
                    x = (cur_w - new_w) // 2
                    rect = Rectangle(x, 0, new_w, cur_h)
                else:
                    # Too tall — crop top/bottom
                    new_h = int(cur_w / target_ratio)
                    y = (cur_h - new_h) // 2
                    rect = Rectangle(0, y, cur_w, new_h)
                cropped = src.Clone(rect, src.PixelFormat)
                out_path = src_path + ".crop.jpg"
                cropped.Save(out_path, Imaging.ImageFormat.Jpeg)
                return out_path
            finally:
                if cropped is not None:
                    cropped.Dispose()
                src.Dispose()
        except Exception as ex:
            # Surface the crop failure prominently — silent fallback to
            # uncropped means the user gets the very bug R1 tried to fix
            # (Round 2 P1-crash-8).
            msg = "Aspect crop failed; rendering at view aspect: {}".format(str(ex)[:160])
            self.status_label.Text = msg
            try:
                LOG.log(__file__, msg)  # surfaces in EnneadTab log
            except Exception:
                pass
            return None

    # ------------------------------------------------------------------
    # Style reference
    # ------------------------------------------------------------------

    @ERROR_HANDLE.try_catch_error()
    def browse_style_Click(self, sender, e):
        from Microsoft.Win32 import OpenFileDialog # pyright: ignore
        dlg = OpenFileDialog()
        dlg.Filter = "Images|*.png;*.jpg;*.jpeg;*.webp"
        dlg.Title = "Select Style Reference Image"
        if dlg.ShowDialog():
            fn = dlg.FileName
            ext = os.path.splitext(fn)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                self.status_label.Text = "Unsupported image extension."
                return
            self._set_style_ref(fn)

    @ERROR_HANDLE.try_catch_error()
    def paste_style_Click(self, sender, e):
        if not System.Windows.Clipboard.ContainsImage():
            self.status_label.Text = "No image in clipboard."
            return
        try:
            bmp_source = System.Windows.Clipboard.GetImage()
            # Unique per-paste filename — Bug-finder [P1-2-2].
            tmp_name = "clip_{}.png".format(int(time.time() * 1000))
            temp_path = os.path.join(FOLDER.DUMP_FOLDER, tmp_name)
            if not os.path.exists(FOLDER.DUMP_FOLDER):
                os.makedirs(FOLDER.DUMP_FOLDER)
            from System.Windows.Media.Imaging import PngBitmapEncoder, BitmapFrame # pyright: ignore
            encoder = PngBitmapEncoder()
            encoder.Frames.Add(BitmapFrame.Create(bmp_source))
            stream = System.IO.FileStream(temp_path, System.IO.FileMode.Create)
            try:
                encoder.Save(stream)
            finally:
                stream.Close()
            self._set_style_ref(temp_path)
        except Exception as ex:
            self.status_label.Text = "Paste failed: {}".format(str(ex)[:150])

    @ERROR_HANDLE.try_catch_error()
    def library_style_Click(self, sender, e):
        # Open a lightweight picker dialog backed by /api/demo-images.
        self.status_label.Text = "Loading style library..."
        def worker(state):
            # 2026-04-21 — .NET worker exception = host process termination
            # (CLR 0xE0434352). Wrap EVERYTHING in try/except. Audit Lens B
            # P0. Mirrors Rhino fix in view2render_left.py::_on_library_style.
            try:
                token = AUTH.get_token()
                if not token:
                    self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                    "Please sign in first."))
                    return
                items = AI.get_demo_style_images(token)
                self._invoke_ui(lambda: self._show_library_picker(items))
            except Exception as ex:
                _trace("worker.library_style SWALLOWED {}".format(ex))
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Style library failed: {}".format(str(ex)[:120])))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _show_library_picker(self, items):
        """Thumbnail grid of the curated Ennead style references.

        WPF WrapPanel inside a ScrollViewer. Thumbnails lazy-loaded on a
        background thread so the modal opens instantly with placeholders,
        then fills in. Per-item click downloads full-res to local cache and
        sets it as the style reference.
        """
        if not items:
            self.status_label.Text = "Style library is empty or unavailable."
            return
        from System.Windows import Window as SysWindow, Thickness, WindowStartupLocation
        from System.Windows.Controls import (ScrollViewer, WrapPanel, Button as SysButton,
                                              StackPanel, TextBlock, Image as SysImage)
        from System.Windows.Media import Brushes
        picker = SysWindow()
        picker.Title = "Ennead Style Reference Library ({})".format(len(items))
        picker.Width = 760
        picker.Height = 560
        picker.WindowStartupLocation = WindowStartupLocation.CenterOwner
        picker.Owner = self
        picker.Background = Brushes.DarkGray
        scroll = ScrollViewer()
        scroll.HorizontalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Disabled
        scroll.VerticalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto
        wp = WrapPanel()
        wp.Margin = Thickness(8)

        # Build placeholder buttons up front, then fill each one's image
        # from the cache (downloads if missing) on a background thread.
        def make_tile(item):
            btn = SysButton()
            btn.Width = 160
            btn.Height = 130
            btn.Margin = Thickness(4)
            btn.Padding = Thickness(0)
            btn.Tag = item
            stack = StackPanel()
            img = SysImage()
            img.Width = 152
            img.Height = 100
            img.Stretch = System.Windows.Media.Stretch.UniformToFill
            stack.Children.Add(img)
            label = TextBlock()
            label.Text = item["filename"][:24]
            label.FontSize = 10
            label.HorizontalAlignment = System.Windows.HorizontalAlignment.Center
            stack.Children.Add(label)
            btn.Content = stack
            def on_click(s, a):
                chosen = s.Tag
                self.status_label.Text = "Selected {}".format(chosen["filename"])
                def dl_worker(state):
                    try:
                        path = AI.get_or_cache_demo_style_image(
                            chosen["url"], chosen["filename"])
                        self._invoke_ui(lambda: self._set_style_ref(path))
                    except Exception as ex:
                        self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                        "Download failed: {}".format(str(ex)[:150])))
                System.Threading.ThreadPool.QueueUserWorkItem(
                    System.Threading.WaitCallback(dl_worker))
                # Async close — never sync-Invoke from inside a modal
                # (Audit P1-edge-12 — deadlock candidate).
                self._invoke_ui(lambda: picker.Close())
            btn.Click += on_click
            return btn, img

        tiles = [make_tile(it) for it in items]
        for btn, _img in tiles:
            wp.Children.Add(btn)
        scroll.Content = wp
        picker.Content = scroll

        # Background-fill the thumbnails
        def fill_worker(state):
            for (btn, img), item in zip(tiles, items):
                try:
                    path = AI.get_or_cache_demo_style_image(item["url"], item["filename"])
                    bmp = G.bitmap_from_path(path)
                    if bmp is not None:
                        self._invoke_ui(lambda im=img, b=bmp: setattr(im, "Source", b))
                except Exception:
                    continue
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(fill_worker))

        picker.ShowDialog()

    def clear_style_Click(self, sender, e):
        self._style_ref_path = None
        self.style_preview.Source = None
        self.bt_clear_style.Visibility = Visibility.Collapsed
        self.status_label.Text = "Style reference cleared."

    def _set_style_ref(self, path):
        self._style_ref_path = path
        bmp = G.bitmap_from_path(path)
        if bmp:
            self.style_preview.Source = bmp
        self.bt_clear_style.Visibility = Visibility.Visible
        self.status_label.Text = "Style reference: {}".format(os.path.basename(path))

    def style_preview_Click(self, sender, e):
        # Click-to-zoom — open with system viewer.
        if self._style_ref_path and os.path.exists(self._style_ref_path):
            try:
                os.startfile(self._style_ref_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Suggested starter-prompt chips (Keep #459)
    # Shared list: AI_RENDER.get_suggested_starter_prompts()
    # ------------------------------------------------------------------

    def _populate_suggested_prompt_chips(self):
        """Build clickable chip bubbles above the prompt box from the shared
        starter list. Click fills tbox_prompt (undoable)."""
        panel = getattr(self, "wp_suggested_prompts", None)
        if panel is None:
            return
        # Local import: WPF Controls.Button. Matches other dialog helpers in
        # this file; duck-type Tag/Content so we never rely on typed names in
        # selection handlers (see CLAUDE.md modeless DataGrid checklist).
        from System.Windows.Controls import Button as SysButton  # pyright: ignore

        try:
            panel.Children.Clear()
        except Exception:
            pass

        style = None
        try:
            style = self.FindResource("ChipButton")
        except Exception:
            try:
                style = self.FindResource("SmallButton")
            except Exception:
                style = None

        items = AI_RENDER.get_suggested_starter_prompts()
        for item in items:
            label = item.get("label") or ""
            prompt = item.get("prompt") or label
            if not label:
                continue
            btn = SysButton()
            btn.Content = label
            btn.Tag = prompt
            btn.ToolTip = "Fill prompt box with: {}".format(prompt)
            if style is not None:
                try:
                    btn.Style = style
                except Exception:
                    pass
            btn.Click += self.suggested_prompt_chip_Click
            panel.Children.Add(btn)

    def suggested_prompt_chip_Click(self, sender, e):
        prompt = getattr(sender, "Tag", None) or ""
        if not prompt:
            return
        self._push_prompt_undo()
        self.tbox_prompt.Text = prompt
        try:
            self.status_label.Text = "Starter prompt loaded -- edit or queue as-is."
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Prompt action buttons (spell / lengthen / shorten / reset / undo)
    # ------------------------------------------------------------------

    def _push_prompt_undo(self):
        cur = self.tbox_prompt.Text
        if not cur:
            return
        self._prompt_undo.append(cur)
        if len(self._prompt_undo) > PROMPT_UNDO_CAP:
            self._prompt_undo = self._prompt_undo[-PROMPT_UNDO_CAP:]
        self.bt_undo_prompt.IsEnabled = True

    def undo_prompt_Click(self, sender, e):
        if not self._prompt_undo:
            self.bt_undo_prompt.IsEnabled = False
            return
        prev = self._prompt_undo.pop()
        self.tbox_prompt.Text = prev
        if not self._prompt_undo:
            self.bt_undo_prompt.IsEnabled = False

    def reset_prompt_Click(self, sender, e):
        self._push_prompt_undo()
        self.tbox_prompt.Text = self._initial_prompt_for_reset or ""

    def _run_prompt_api(self, btn, api_fn, action_name):
        """Shared pattern for spell/lengthen/shorten: disable button, fire API
        on background thread, restore text + button on result."""
        prompt = (self.tbox_prompt.Text or "").strip()
        if not prompt:
            self.status_label.Text = "Enter a prompt first."
            return
        btn.IsEnabled = False
        old_content = btn.Content
        btn.Content = "..."
        self._push_prompt_undo()
        self.status_label.Text = "{}...".format(action_name)

        def worker(state):
            token = AUTH.get_token()
            if not token:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Sign in required."))
                self._invoke_ui(lambda: self._restore_prompt_btn(btn, old_content))
                return
            try:
                new_text = api_fn(token, prompt)
                self._invoke_ui(lambda: setattr(self.tbox_prompt, 'Text', new_text))
                self._invoke_ui(lambda: setattr(self.status_label, 'Text', "Done."))
            except Exception as ex:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Failed: {}".format(str(ex)[:200])))
            finally:
                self._invoke_ui(lambda: self._restore_prompt_btn(btn, old_content))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _restore_prompt_btn(self, btn, old_content):
        btn.IsEnabled = True
        btn.Content = old_content

    def spell_Click(self, sender, e):
        self._run_prompt_api(
            self.bt_spell,
            lambda tok, p: AI_CHAT.spell_check_with_token(tok, p),
            "Checking")

    def lengthen_Click(self, sender, e):
        is_interior = bool(self.cb_interior.IsChecked)
        self._run_prompt_api(
            self.bt_lengthen,
            lambda tok, p: AI_CHAT.improve_prompt_with_token(
                tok, p, mode="image", action="improve", is_interior=is_interior),
            "Improving")

    def shorten_Click(self, sender, e):
        self._run_prompt_api(
            self.bt_shorten,
            lambda tok, p: AI_CHAT.improve_prompt_with_token(
                tok, p, mode="image", action="summarize"),
            "Summarizing")

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    @ERROR_HANDLE.try_catch_error()
    def render_Click(self, sender, e):
        if not self._capture_path or not os.path.exists(self._capture_path):
            self.status_label.Text = "Capture a view first."
            return
        prompt = (self.tbox_prompt.Text or "").strip()
        if not prompt:
            self.status_label.Text = "Please enter a prompt first."
            return
        if not Q.can_enqueue(self._jobs, self._jobs_lock):
            self.status_label.Text = "Queue full ({} active). Wait for one to finish.".format(Q.ACTIVE_CAP)
            return

        style_name = ""
        idx = self.cb_style.SelectedIndex
        if 0 <= idx < len(self._filtered_presets):
            style_name = self._filtered_presets[idx].get("name") or ""

        # Snapshot input path (Bug-finder [P1-4-4]): copy the capture into the
        # job folder so a subsequent Update Capture doesn't change it mid-flight.
        job = Q.RenderJob(
            original_path=None,  # set below after snapshot
            prompt=prompt,
            style_preset=style_name,
            style_ref_path=self._style_ref_path,
            aspect_ratio=self._current_aspect(),
            long_edge=self._current_long_edge(),
            view_name=self._capture_view_name,
            is_interior=bool(self.cb_interior.IsChecked),
            kind=Q.KIND_IMAGE,
            host="revit",
            auto_save_gallery=self._auto_save_enabled)
        snapshot = os.path.join(job.job_folder,
                                "original" + os.path.splitext(self._capture_path)[1])
        try:
            shutil.copy2(self._capture_path, snapshot)
        except Exception as ex:
            self.status_label.Text = "Failed to snapshot capture: {}".format(ex)
            return
        job.original_path = snapshot

        Monitor.Enter(self._jobs_lock)
        try:
            self._jobs.append(job)
        finally:
            Monitor.Exit(self._jobs_lock)

        self._image_worker.wake()
        self.status_label.Text = "Queued (job #{}).".format(job.job_id[:6])
        self._rebuild_rows()
        self._update_active_jobs_label()

    # ------------------------------------------------------------------
    # Job completion (fires from worker thread)
    # ------------------------------------------------------------------

    def _on_any_job_complete(self, job):
        # Quota refreshes after each render; play sound unless in a tight batch.
        self._invoke_ui(self._refresh_quota_async)
        # Play sound only when the queue goes idle — coalesce per Review #2.
        Monitor.Enter(self._jobs_lock)
        try:
            still_going = any(j.status in (Q.STATUS_PENDING, Q.STATUS_ACTIVE)
                              for j in self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        if not still_going:
            Q.play_completion_sound()

    # ------------------------------------------------------------------
    # Gallery list rebuild & bindings
    # ------------------------------------------------------------------

    def _rebuild_rows(self):
        """Merge in-flight jobs + cloud rows, apply filter, push to ListView.

        Snapshots the job list under the lock, builds rows OUTSIDE the lock
        (Audit P0-state-5 — bitmap I/O inside Monitor blocks both workers).
        Dedup uses `gallery_id` so a completed-then-uploaded job doesn't appear
        twice (P0-2-1).
        """
        if self._form_closed:
            return
        Monitor.Enter(self._jobs_lock)
        try:
            jobs_snapshot = list(self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        # I/O happens here, OUTSIDE the lock.
        job_rows = [G.row_from_job(j) for j in jobs_snapshot]
        # Dedup: any cloud row whose ID already lives on a local job's
        # gallery_id is already on screen (job_row pins to top with timer).
        local_gallery_ids = set(j.gallery_id for j in jobs_snapshot if j.gallery_id)
        cloud_only = [r for r in self._all_rows if r.cloud_item
                      and r.id not in local_gallery_ids]
        merged = G.filter_rows(job_rows + cloud_only,
                               self._filter_seconds, self._filter_query)
        self.lv_gallery.ItemsSource = merged
        self.gallery_count.Text = "· {} items".format(len(merged))
        # Any real content (cloud history OR an in-flight job) dismisses the
        # skeleton loading overlay so it never covers live rows.
        if len(merged) > 0:
            self._hide_gallery_loading()

    def _show_gallery_loading(self):
        """Show the dimmed skeleton placeholder rows during the initial cloud
        fetch. Mirrors the Rhino dialog's _render_skeleton_rows. Best-effort —
        a UI failure here must never escape into the WPF message pump (CLR
        0xE0434352 crash class on this modeless dialog)."""
        try:
            if self._form_closed:
                return
            self.gallery_loading_overlay.Visibility = Visibility.Visible
        except Exception as ex:
            _trace("show_gallery_loading SWALLOWED {}".format(ex))

    def _hide_gallery_loading(self):
        try:
            self.gallery_loading_overlay.Visibility = Visibility.Collapsed
        except Exception as ex:
            _trace("hide_gallery_loading SWALLOWED {}".format(ex))

    def _refresh_gallery_async(self, initial=False):
        token = AUTH.get_token()
        if not token:
            if initial:
                # Open auth flow proactively on first open if no token.
                if not AUTH.is_auth_in_progress():
                    AUTH.request_auth()
            return
        # Skeleton loading state only on first load with a token (auth banner
        # covers the no-token case). A manual Refresh with rows already on
        # screen must NOT blank them with placeholders, so gate on `initial`.
        if initial:
            self._show_gallery_loading()
        def on_done(rows):
            if rows is None:
                # Fetch failed — drop the skeleton so the gallery doesn't sit
                # on "Loading recent renders…" forever; existing rows (if any)
                # stay put.
                self._invoke_ui(self._hide_gallery_loading)
                return
            self._invoke_ui(lambda: self._apply_gallery_rows(rows))
        G.fetch_gallery_index_async(token, on_done, limit=500)

    def _apply_gallery_rows(self, rows):
        # Store the cloud rows; jobs are added dynamically from _jobs.
        self._all_rows = rows
        self._rebuild_rows()
        self._update_cache_size()
        # Cloud fetch resolved (even if it returned 0 rows) — clear skeleton.
        self._hide_gallery_loading()

    # ------------------------------------------------------------------
    # Filter bar
    # ------------------------------------------------------------------

    def date_filter_Changed(self, sender, e):
        idx = self.cb_date_filter.SelectedIndex
        if 0 <= idx < len(G.DATE_FILTERS):
            _, secs = G.DATE_FILTERS[idx]
            self._filter_seconds = secs
            self._rebuild_rows()

    def toggle_large_thumbs_Changed(self, sender, e):
        """Feature 1 (2026-06-04): swap the gallery ListView ItemTemplate
        between the small (84x60) and large (168x120) thumbnail templates.

        Session-state only -- there's no ai_render_prefs.json read/write helper
        in this dialog, so per spec we don't add persistence. Wrapped in
        try/except like every other modeless handler: an uncaught throw here
        (e.g. FindResource returning None mid-teardown) would propagate to the
        CLR as 0xE0434352 and hard-crash Revit.
        """
        try:
            if self._form_closed:
                return
            large = bool(self.cb_large_thumbs.IsChecked)
            key = "GalleryRowLarge" if large else "GalleryRowSmall"
            tmpl = self.FindResource(key)
            if tmpl is not None:
                self.lv_gallery.ItemTemplate = tmpl
        except Exception as ex:
            _trace("toggle_large_thumbs SWALLOWED {}".format(ex))

    def search_Changed(self, sender, e):
        self._filter_query = (self.tbox_search.Text or "").strip()
        self._rebuild_rows()

    def refresh_gallery_Click(self, sender, e):
        self.status_label.Text = "Refreshing gallery..."
        self._refresh_gallery_async()

    def scroll_to_active_Click(self, sender, e):
        # Active jobs always pinned to top — just scroll to index 0.
        try:
            if self.lv_gallery.Items.Count > 0:
                self.lv_gallery.ScrollIntoView(self.lv_gallery.Items[0])
        except Exception:
            pass

    def _update_active_jobs_label(self):
        if self._form_closed:
            return
        n = Q.count_inflight(self._jobs, self._jobs_lock)
        self.bt_active_jobs.Content = "Active jobs ({})".format(n)

    # ------------------------------------------------------------------
    # Row actions (context menu, save, view)
    # ------------------------------------------------------------------

    def row_more_Click(self, sender, e):
        """Explicit More button — opens the same context menu as right-click.
        Buttons inside a DataTemplate inherit DataContext from the row, so
        sender.DataContext is always the bound GalleryRow (Round 2 P2-edge-17
        flagged the VisualTree walk fallback as dead defensive code)."""
        row = getattr(sender, "DataContext", None)
        if row is None:
            return
        self._show_row_context_menu(row, sender)

    def row_view_original_Click(self, sender, e):
        # Feature 2 (2026-06-04): open the in-app WPF viewer instead of
        # handing the file off to os.startfile / the OS default app.
        try:
            row = getattr(sender, "DataContext", None)
            if not row:
                return
            rows = self._gallery_rows_snapshot()
            start = self._index_of_row(rows, row)
            self._open_image_viewer(rows, start, "original")
        except Exception as ex:
            _trace("row_view_original_Click SWALLOWED {}".format(ex))

    def row_view_result_Click(self, sender, e):
        try:
            row = getattr(sender, "DataContext", None)
            if not row:
                return
            rows = self._gallery_rows_snapshot()
            start = self._index_of_row(rows, row)
            self._open_image_viewer(rows, start, "result")
        except Exception as ex:
            _trace("row_view_result_Click SWALLOWED {}".format(ex))

    def _gallery_rows_snapshot(self):
        """Snapshot the current ListView ItemsSource into a plain Python list
        so the viewer can navigate a stable set even if the gallery rebuilds
        (a tick or refresh) while the viewer is open."""
        try:
            src = self.lv_gallery.ItemsSource
            if src is None:
                return []
            return [r for r in src]
        except Exception:
            return []

    def _index_of_row(self, rows, row):
        try:
            for i in range(len(rows)):
                if rows[i] is row:
                    return i
        except Exception:
            pass
        return 0

    def _fetch_and_open_full(self, row):
        # Retained for any callers; routes through the in-app viewer now.
        try:
            rows = self._gallery_rows_snapshot()
            start = self._index_of_row(rows, row)
            self._open_image_viewer(rows, start, "result")
        except Exception as ex:
            _trace("_fetch_and_open_full SWALLOWED {}".format(ex))

    def _open_path(self, path):
        if self._form_closed:
            return
        try:
            os.startfile(path)
            self.status_label.Text = "Opened {}".format(os.path.basename(path))
        except Exception as ex:
            self.status_label.Text = "Open failed: {}".format(ex)

    # ------------------------------------------------------------------
    # In-app enlarged image viewer (Feature 2, 2026-06-04)
    # Mirrors the BEHAVIOR of the Rhino Eto viewer (ai_render_image_viewer.py):
    # prev/next walks the current filtered gallery rows, Tab swaps
    # Input(original)/Output(result), Left/Right navigate, Esc closes. Built
    # with plain System.Windows.Window + closure handlers (no WPFWindow subclass
    # needed). EVERY handler/callback is wrapped in try/except — an uncaught
    # throw from a modeless dialog's button/key/async callback hard-crashes
    # Revit (CLR 0xE0434352).
    # ------------------------------------------------------------------

    def _open_image_viewer(self, rows, start_index, mode):
        try:
            if self._form_closed:
                return
            rows = list(rows or [])
            if not rows:
                self.status_label.Text = "Nothing to view."
                return
            if start_index < 0 or start_index >= len(rows):
                start_index = 0

            from System.Windows import (Window as SysWindow, Thickness,
                                        WindowStartupLocation, HorizontalAlignment,
                                        VerticalAlignment, GridLength, GridUnitType)
            from System.Windows.Controls import (Grid as SysGrid, Image as SysImage,
                                                  StackPanel, Button as SysButton,
                                                  TextBlock, RowDefinition,
                                                  Orientation as SysOrient)
            from System.Windows.Media import Brushes, Stretch as SysStretch
            from System.Windows.Input import Key

            win = SysWindow()
            win.Title = "EnneaDuck — Image Viewer"
            win.Width = 1000
            win.Height = 760
            win.WindowStartupLocation = WindowStartupLocation.CenterOwner
            win.Owner = self
            win.Background = Brushes.Black

            # State held in a single-element list / dict so closures can mutate
            # without `nonlocal` (IronPython 2.7 has no nonlocal keyword).
            state = {"idx": int(start_index), "mode": mode}

            root = SysGrid()
            rd_img = RowDefinition()
            rd_img.Height = GridLength(1, GridUnitType.Star)
            rd_bar = RowDefinition()
            rd_bar.Height = GridLength.Auto
            root.RowDefinitions.Add(rd_img)
            root.RowDefinitions.Add(rd_bar)

            img = SysImage()
            img.Stretch = SysStretch.Uniform
            img.Margin = Thickness(8)
            SysGrid.SetRow(img, 0)
            root.Children.Add(img)

            bar = StackPanel()
            bar.Orientation = SysOrient.Horizontal
            bar.HorizontalAlignment = HorizontalAlignment.Center
            bar.Margin = Thickness(8)
            SysGrid.SetRow(bar, 1)

            def mk_btn(text, w):
                b = SysButton()
                b.Content = text
                b.Width = w
                b.Height = 28
                b.Margin = Thickness(6, 0, 6, 0)
                return b

            bt_prev = mk_btn(u"◀ Prev", 90)
            bt_next = mk_btn(u"Next ▶", 90)
            bt_toggle = mk_btn("Showing: Result", 150)
            bt_close = mk_btn("Close", 90)

            caption = TextBlock()
            caption.Foreground = Brushes.White
            caption.VerticalAlignment = VerticalAlignment.Center
            caption.Margin = Thickness(16, 0, 16, 0)
            caption.FontSize = 12

            bar.Children.Add(bt_prev)
            bar.Children.Add(bt_toggle)
            bar.Children.Add(caption)
            bar.Children.Add(bt_next)
            bar.Children.Add(bt_close)
            root.Children.Add(bar)
            win.Content = root

            def set_caption(text):
                try:
                    caption.Text = text
                except Exception:
                    pass

            def current_row():
                try:
                    return rows[state["idx"]]
                except Exception:
                    return None

            def update_nav():
                try:
                    bt_prev.IsEnabled = state["idx"] > 0
                    bt_next.IsEnabled = state["idx"] < (len(rows) - 1)
                    bt_toggle.Content = ("Showing: Result"
                                         if state["mode"] == "result"
                                         else "Showing: Original")
                except Exception:
                    pass

            def show_current():
                # Load the image for (current row, current mode). Local path
                # first; cloud fetch fallback; placeholder if neither.
                try:
                    update_nav()
                    row = current_row()
                    if row is None:
                        img.Source = None
                        set_caption("No image")
                        return
                    if state["mode"] == "result":
                        local = getattr(row, "result_path", None)
                    else:
                        local = getattr(row, "original_path", None)
                    label = "{}/{}  ·  {}  ·  {}".format(
                        state["idx"] + 1, len(rows),
                        ("Result" if state["mode"] == "result" else "Original"),
                        getattr(row, "view_name", None) or getattr(row, "StyleName", None) or "")
                    if local and os.path.exists(local):
                        bmp = G.bitmap_from_path(local)
                        img.Source = bmp
                        set_caption(label)
                        return
                    # No local file — try cloud fetch if this row has an id.
                    if getattr(row, "cloud_item", None) and getattr(row, "id", None):
                        set_caption(u"Loading…  " + label)
                        token = AUTH.get_token()
                        if not token:
                            set_caption("Sign in required.")
                            return
                        # Capture the request's idx+mode so a late async result
                        # doesn't clobber the image if the user already moved on.
                        req_idx = state["idx"]
                        req_mode = state["mode"]
                        req_id = row.id

                        def on_done(bmp, path):
                            def apply_():
                                try:
                                    if state["idx"] != req_idx or state["mode"] != req_mode:
                                        return  # user navigated away; ignore
                                    if bmp is not None:
                                        img.Source = bmp
                                        set_caption(label)
                                    elif path and os.path.exists(path):
                                        b2 = G.bitmap_from_path(path)
                                        img.Source = b2
                                        set_caption(label)
                                    else:
                                        set_caption("No image")
                                except Exception:
                                    pass
                            # Marshal onto the UI thread via the dialog's helper
                            # (also guards against the main form being closed).
                            self._invoke_ui(apply_)
                        try:
                            G.fetch_full_item_async(token, req_id, on_done)
                        except Exception as ex:
                            set_caption("Load failed.")
                            _trace("viewer.fetch SWALLOWED {}".format(ex))
                        return
                    # Nothing to show.
                    img.Source = None
                    set_caption("No image")
                except Exception as ex:
                    _trace("viewer.show_current SWALLOWED {}".format(ex))

            def go_prev(*_a):
                try:
                    if state["idx"] > 0:
                        state["idx"] -= 1
                        show_current()
                except Exception as ex:
                    _trace("viewer.go_prev SWALLOWED {}".format(ex))

            def go_next(*_a):
                try:
                    if state["idx"] < (len(rows) - 1):
                        state["idx"] += 1
                        show_current()
                except Exception as ex:
                    _trace("viewer.go_next SWALLOWED {}".format(ex))

            def toggle_mode(*_a):
                try:
                    state["mode"] = ("original" if state["mode"] == "result"
                                     else "result")
                    show_current()
                except Exception as ex:
                    _trace("viewer.toggle_mode SWALLOWED {}".format(ex))

            def do_close(*_a):
                try:
                    win.Close()
                except Exception:
                    pass

            bt_prev.Click += lambda s, a: go_prev()
            bt_next.Click += lambda s, a: go_next()
            bt_toggle.Click += lambda s, a: toggle_mode()
            bt_close.Click += lambda s, a: do_close()

            def on_key(s, a):
                try:
                    k = a.Key
                    if k == Key.Left:
                        go_prev()
                        a.Handled = True
                    elif k == Key.Right:
                        go_next()
                        a.Handled = True
                    elif k == Key.Tab:
                        toggle_mode()
                        a.Handled = True
                    elif k == Key.Escape:
                        a.Handled = True
                        do_close()
                except Exception as ex:
                    _trace("viewer.on_key SWALLOWED {}".format(ex))

            win.KeyDown += on_key

            show_current()
            # Modal relative to the dialog; viewer owns its own message loop.
            win.ShowDialog()
        except Exception as ex:
            _trace("_open_image_viewer SWALLOWED {}".format(ex))
            try:
                self.status_label.Text = "Viewer failed: {}".format(str(ex)[:150])
            except Exception:
                pass

    @ERROR_HANDLE.try_catch_error()
    def row_save_Click(self, sender, e):
        row = getattr(sender, "DataContext", None)
        if not row:
            return
        src = row.result_path
        if not src or not os.path.exists(src):
            # Pull from cloud first.
            if row.cloud_item:
                self._fetch_and_save(row)
                return
            self.status_label.Text = "No local result to save."
            return
        self._save_path_as(src, row)

    def row_copy_Click(self, sender, e):
        row = getattr(sender, "DataContext", None)
        if not row:
            return
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

    def _save_path_as(self, src, row):
        if self._form_closed:
            return
        from Microsoft.Win32 import SaveFileDialog # pyright: ignore
        ext = os.path.splitext(src)[1]
        dlg = SaveFileDialog()
        dlg.Filter = "Image (*{})|*{}".format(ext, ext)
        # Smart default filename — handle ALL Windows-illegal chars via the
        # shared sanitizer (roleplay finding + bug-finder P1-security-4).
        dlg.FileName = "{}_{}_{}{}".format(
            _safe_filename(row.view_name or "View"),
            _safe_filename(row.StyleName or "Style"),
            row.id[:6], ext)
        if self._last_save_folder and os.path.isdir(self._last_save_folder):
            dlg.InitialDirectory = self._last_save_folder
        dlg.Title = "Save render"
        if dlg.ShowDialog():
            try:
                shutil.copyfile(src, dlg.FileName)
                self._last_save_folder = os.path.dirname(dlg.FileName)
                self.status_label.Text = "Saved to {}".format(os.path.basename(dlg.FileName))
            except Exception as ex:
                self.status_label.Text = "Save failed: {}".format(ex)

    def _fetch_and_save(self, row):
        self.status_label.Text = "Downloading for save..."
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def on_done(bmp, path):
            if path:
                self._invoke_ui(lambda: self._save_path_as(path, row))
            else:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Failed to fetch image."))
        G.fetch_full_item_async(token, row.id, on_done)

    # ------------------------------------------------------------------
    # Footer: auto-save toggle, cache size, quota
    # ------------------------------------------------------------------

    def auto_save_Changed(self, sender, e):
        self._auto_save_enabled = bool(self.cb_auto_save.IsChecked)

    def open_folder_Click(self, sender, e):
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
            self.quota_label.Text = "Quota: —"
            return
        def worker(state):
            # 2026-04-21 — .NET worker exception = host termination (0xE0434352).
            # int() raises ValueError on non-numeric strings from API. Audit
            # Lens B P0. Mirrors Rhino _refresh_quota_async.
            try:
                q = AI.get_quota_with_token(token)
                if q:
                    r_rem = q.get("requestsRemaining")
                    r_lim = q.get("requestsLimit")
                    txt = "Quota: {:,}/{:,}".format(int(r_rem or 0), int(r_lim or 0))
                else:
                    txt = "Quota: —"
            except Exception as ex:
                _trace("worker.quota SWALLOWED {}".format(ex))
                txt = "Quota: —"
            self._invoke_ui(lambda: setattr(self.quota_label, 'Text', txt))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    # ------------------------------------------------------------------
    # Auth helper
    # ------------------------------------------------------------------

    def _open_webbrowser_if_needed_token(self):
        """Non-blocking: if no cached token, trigger browser sign-in in background."""
        if AUTH.get_token():
            return
        if not AUTH.is_auth_in_progress():
            AUTH.request_auth()

    # ------------------------------------------------------------------
    # My Prompts (saved per-user via /api/prompts/list|save)
    # ------------------------------------------------------------------

    def _refresh_my_prompts_async(self):
        token = AUTH.get_token()
        if not token:
            return
        def worker(state):
            # 2026-04-21 — .NET worker exception = host termination.
            # Audit Lens B P0. Mirrors Rhino _refresh_my_prompts_async.
            try:
                prompts = AI.list_prompts_with_token(token)
                self._invoke_ui(lambda: self._apply_my_prompts(prompts))
            except Exception as ex:
                _trace("worker.my_prompts SWALLOWED {}".format(ex))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _apply_my_prompts(self, prompts):
        self._my_prompts = prompts or []
        self.cb_my_prompts.Items.Clear()
        if not self._my_prompts:
            self.cb_my_prompts.Items.Add("(none — click Save current...)")
            self.cb_my_prompts.SelectedIndex = 0
            self.cb_my_prompts.IsEnabled = False
            return
        self.cb_my_prompts.IsEnabled = True
        self.cb_my_prompts.Items.Add("— select a saved prompt —")
        for p in self._my_prompts:
            label = p.get("name") or "(unnamed)"
            cat = p.get("category")
            if cat:
                label = "{} · {}".format(label, cat)
            self.cb_my_prompts.Items.Add(label)
        self.cb_my_prompts.SelectedIndex = 0

    def my_prompt_Changed(self, sender, e):
        idx = self.cb_my_prompts.SelectedIndex
        if idx <= 0 or idx > len(getattr(self, "_my_prompts", [])):
            return
        chosen = self._my_prompts[idx - 1]
        text = chosen.get("prompt") or ""
        if text:
            self._push_prompt_undo()
            self.tbox_prompt.Text = text
            self.status_label.Text = "Loaded prompt: {}".format(chosen.get("name") or "")

    @ERROR_HANDLE.try_catch_error()
    def save_prompt_Click(self, sender, e):
        prompt_text = (self.tbox_prompt.Text or "").strip()
        if not prompt_text:
            self.status_label.Text = "Nothing to save."
            return
        # Quick name input — small inline modal.
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
                AI.save_prompt_with_token(token, name, prompt_text, category=category)
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Saved prompt '{}'".format(name)))
                self._invoke_ui(self._refresh_my_prompts_async)
            except Exception as ex:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Save failed: {}".format(str(ex)[:200])))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

    def _prompt_for_text(self, title, prompt_text, default=""):
        """Small modal asking for a single string. Returns text or None."""
        from System.Windows import Window as SysWindow, Thickness, WindowStartupLocation
        from System.Windows.Controls import StackPanel, TextBox, Button as SysButton, TextBlock
        win = SysWindow()
        win.Title = title
        win.Width = 360
        win.Height = 160
        win.WindowStartupLocation = WindowStartupLocation.CenterOwner
        win.Owner = self
        sp = StackPanel()
        sp.Margin = Thickness(12)
        lbl = TextBlock()
        lbl.Text = prompt_text
        sp.Children.Add(lbl)
        tb = TextBox()
        tb.Text = default
        tb.Margin = Thickness(0, 6, 0, 6)
        sp.Children.Add(tb)
        btn_row = StackPanel()
        btn_row.Orientation = System.Windows.Controls.Orientation.Horizontal
        btn_row.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        ok = SysButton(); ok.Content = "OK"; ok.Width = 60; ok.Margin = Thickness(4)
        cancel = SysButton(); cancel.Content = "Cancel"; cancel.Width = 60; cancel.Margin = Thickness(4)
        result = [None]
        def on_ok(s, a):
            # Strip first so a whitespace-only entry counts as empty
            # (Round 2 P2 — _prompt_for_text validation gap).
            txt = (tb.Text or "").strip()
            result[0] = txt if txt else None
            win.Close()
        def on_cancel(s, a):
            win.Close()
        ok.Click += on_ok
        cancel.Click += on_cancel
        btn_row.Children.Add(ok)
        btn_row.Children.Add(cancel)
        sp.Children.Add(btn_row)
        win.Content = sp
        win.ShowDialog()
        return result[0]

    # ------------------------------------------------------------------
    # Resume (queue paused on 401)
    # ------------------------------------------------------------------

    def resume_Click(self, sender, e):
        AUTH.clear_token()
        if not AUTH.is_auth_in_progress():
            AUTH.request_auth()
        self.status_label.Text = "Sign in via the browser, then click Resume again."
        # If we already have a token (auth completed quickly), resume both workers.
        if AUTH.get_token():
            self._image_worker.resume()
            self._video_worker.resume()
            self.resume_panel.Visibility = Visibility.Collapsed
            self.status_label.Text = "Queue resumed."

    def _show_pause_banner(self):
        self.resume_panel.Visibility = Visibility.Visible

    def _hide_pause_banner(self):
        self.resume_panel.Visibility = Visibility.Collapsed

    def _on_job_update(self, job):
        # Override of the earlier _on_job_update to also surface pause state.
        # If any pending job has 'Auth expired' message, show the resume banner.
        Monitor.Enter(self._jobs_lock)
        try:
            paused = any(
                j.status == Q.STATUS_PENDING and j.error_msg
                and "auth" in (j.error_msg or "").lower()
                for j in self._jobs)
        finally:
            Monitor.Exit(self._jobs_lock)
        self._invoke_ui(self._rebuild_rows)
        self._invoke_ui(self._update_active_jobs_label)
        self._invoke_ui(self._show_pause_banner if paused else self._hide_pause_banner)

    # ------------------------------------------------------------------
    # Right-click context menu on gallery rows
    # ------------------------------------------------------------------

    def _on_row_right_click(self, sender, e):
        # Walk up from e.OriginalSource to find the ListViewItem.
        from System.Windows.Controls import ListViewItem
        from System.Windows.Media import VisualTreeHelper
        node = e.OriginalSource
        while node is not None and not isinstance(node, ListViewItem):
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                node = None
        if node is None:
            return
        row = node.DataContext
        if row is None:
            return
        # Mark handled so the ListView doesn't also try to select-on-rclick.
        e.Handled = True
        self._show_row_context_menu(row, node)

    def _show_row_context_menu(self, row, anchor):
        from System.Windows.Controls import ContextMenu, MenuItem, Separator as MnSep
        cm = ContextMenu()

        def add(label, handler, enabled=True):
            mi = MenuItem()
            mi.Header = label
            mi.IsEnabled = enabled
            mi.Click += handler
            cm.Items.Add(mi)

        is_video = (row.kind == "video")
        has_local_result = bool(row.result_path and os.path.exists(row.result_path or ""))
        has_local_original = bool(row.original_path and os.path.exists(row.original_path or ""))
        has_cloud = bool(row.cloud_item)
        is_active = bool(row.job_ref and row.job_ref.status in (Q.STATUS_PENDING, Q.STATUS_ACTIVE))
        gallery_id = (row.cloud_item or {}).get("id") if has_cloud else (
            row.job_ref.gallery_id if row.job_ref else None)

        add("Show full prompt", lambda s, a: self._ctx_show_prompt(row))
        cm.Items.Add(MnSep())
        add("Save result as...", lambda s, a: self._ctx_save_result(row),
            enabled=has_local_result or has_cloud)
        add("Save original as...", lambda s, a: self._ctx_save_original(row),
            enabled=has_local_original or has_cloud)
        add("Save bundle (.zip)...", lambda s, a: self._ctx_save_bundle(row),
            enabled=(has_local_result and has_local_original))
        add("Copy result to clipboard", lambda s, a: self._ctx_copy_to_clipboard(row),
            enabled=has_local_result)
        cm.Items.Add(MnSep())
        # "Retry" reads better than "Re-run with same prompt" when the source
        # row is a failure (Round 3 P2 — terminology).
        is_failed = bool(row.job_ref and row.job_ref.status == Q.STATUS_FAILED)
        rerun_label = "Retry" if is_failed else "Re-run with same prompt"
        add(rerun_label, lambda s, a: self._ctx_rerun(row),
            enabled=not is_active and (has_local_original or has_cloud))
        add("Animate (Image → Video)...", lambda s, a: self._ctx_animate(row),
            enabled=not is_video and (has_local_result or has_cloud))
        cm.Items.Add(MnSep())
        add("Open in ennead-ai.com Studio", lambda s, a: self._ctx_open_studio(row),
            enabled=bool(gallery_id))
        cm.Items.Add(MnSep())
        add("Remove from local cache only", lambda s, a: self._ctx_remove_local(row),
            enabled=has_local_result or has_local_original)
        add("Delete from Gallery (all devices)...", lambda s, a: self._ctx_delete_gallery(row),
            enabled=bool(gallery_id))

        cm.PlacementTarget = anchor
        cm.IsOpen = True

    def _ctx_show_prompt(self, row):
        from System.Windows import MessageBox
        text = row.full_prompt or "(empty)"
        # Include all reproducibility fields so the user can recreate the render
        # by hand if needed (Audit P1 — Show prompt was missing these).
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
        meta = ("Style: {}\nView: {}\nHost: {}\n"
                "Aspect: {}\nLong edge: {}px\nInterior scene: {}\n"
                "Style reference: {}\n\n").format(
            row.StyleName or "—", row.view_name or "—", row.host or "—",
            aspect, long_edge, interior, style_ref)
        MessageBox.Show(meta + text, "Prompt for {}".format(row.id[:8]))

    def _ctx_save_result(self, row):
        if row.result_path and os.path.exists(row.result_path):
            self._save_path_as(row.result_path, row)
        elif row.cloud_item:
            self._fetch_and_save(row)

    def _ctx_save_original(self, row):
        if row.original_path and os.path.exists(row.original_path):
            self._save_path_as(row.original_path, row)
        else:
            self.status_label.Text = "Original not available locally for this row."

    def _ctx_save_bundle(self, row):
        if not (row.original_path and row.result_path
                and os.path.exists(row.original_path)
                and os.path.exists(row.result_path)):
            self.status_label.Text = "Bundle requires both original + result locally."
            return
        from Microsoft.Win32 import SaveFileDialog # pyright: ignore
        dlg = SaveFileDialog()
        dlg.Filter = "ZIP archive (*.zip)|*.zip"
        dlg.FileName = "{}_{}_{}.zip".format(
            _safe_filename(row.view_name or "View"),
            _safe_filename(row.StyleName or "Style"),
            row.id[:6])
        if not dlg.ShowDialog():
            return
        out_zip = dlg.FileName
        try:
            import zipfile
            with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(row.original_path, "original" + os.path.splitext(row.original_path)[1])
                zf.write(row.result_path, "result" + os.path.splitext(row.result_path)[1])
                # Inline a prompt.txt for portability.
                meta_lines = [
                    "Prompt: " + (row.full_prompt or ""),
                    "Style: " + (row.StyleName or ""),
                    "View: " + (row.view_name or ""),
                    "Host: " + (row.host or ""),
                    "Created: " + time.strftime("%Y-%m-%d %H:%M:%S",
                                                 time.localtime(row.created_at or time.time())),
                    "ID: " + (row.id or ""),
                ]
                zf.writestr("prompt.txt", "\n".join(meta_lines))
            self.status_label.Text = "Bundle saved: {}".format(os.path.basename(out_zip))
        except Exception as ex:
            self.status_label.Text = "Bundle failed: {}".format(str(ex)[:200])

    def _ctx_copy_to_clipboard(self, row):
        if not row.result_path or not os.path.exists(row.result_path):
            return
        try:
            bmp = G.bitmap_from_path(row.result_path)
            if bmp is not None:
                System.Windows.Clipboard.SetImage(bmp)
                self.status_label.Text = "Result copied to clipboard."
        except Exception as ex:
            self.status_label.Text = "Copy failed: {}".format(str(ex)[:200])

    def _ctx_rerun(self, row):
        # Need the original on disk; if only cloud, download first.
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
        if not Q.can_enqueue(self._jobs, self._jobs_lock):
            self.status_label.Text = "Queue full."
            return
        # Pull every reproducibility field from the source row so re-run is
        # actually "same prompt + same settings" not "same prompt + defaults"
        # (Audit P0 — Re-run silently dropped aspect/long_edge/interior/style_ref).
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
            style_ref = None  # cloud rows don't carry style ref file (yet)
        # Preserve video kind/duration/resolution (Round 3 P2-7 — was always
        # hard-coded to KIND_IMAGE so re-running a video silently demoted it).
        is_video = (row.kind == "video")
        if row.job_ref and is_video:
            video_dur = row.job_ref.video_duration
            video_res = row.job_ref.video_resolution
        else:
            video_dur = int(meta.get("duration") or 4) if is_video else 4
            video_res = meta.get("resolution") or "720p"
        job = Q.RenderJob(
            original_path=original_path,
            prompt=row.full_prompt,
            style_preset=row.StyleName,
            style_ref_path=style_ref,
            aspect_ratio=aspect,
            long_edge=long_edge,
            view_name=row.view_name,
            is_interior=is_interior,
            kind=(Q.KIND_VIDEO if is_video else Q.KIND_IMAGE),
            host="revit",
            video_duration=video_dur,
            video_resolution=video_res,
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
        # Feature 3 (2026-06-04): the menu used to silent-return when the row
        # had no cloud gallery_id (rows not yet uploaded), so the user saw
        # nothing happen. Now we explain why, and surface any open failure.
        gallery_id = (row.cloud_item or {}).get("id") if row.cloud_item else (
            row.job_ref.gallery_id if row.job_ref else None)
        if not gallery_id:
            self.status_label.Text = ("This render isn't in the cloud Gallery yet "
                                      "- enable Auto-save or wait for upload.")
            return
        # Route confirmed 2026-06-04 against EnneadTab-RenderPolisher source:
        # there is NO per-item deep-link. The app (next.config.ts basePath
        # removed 2026-04-02, standalone at ennead-ai.com root) exposes page
        # routes /home /studio /museum /about /contact and NO /gallery; the
        # /studio page renders the user's whole cloud gallery and does not read
        # an item id from the URL (no searchParams/[id] route). So the prior
        # /gallery/<id> guess 404'd. Open /studio - the user lands on the
        # gallery and finds the item there.
        try:
            webbrowser.open("{}/studio".format(STUDIO_URL))
            self.status_label.Text = "Opening your Gallery in ennead-ai.com Studio..."
        except Exception as ex:
            self.status_label.Text = "Couldn't open browser: {}".format(str(ex)[:150])

    def _ctx_remove_local(self, row):
        # Remove only the local files under this job's folder (don't touch cloud).
        from System.Windows import MessageBox, MessageBoxButton, MessageBoxResult
        res = MessageBox.Show(
            "Remove this row's files from local cache only?\n"
            "(Cloud Gallery copy will not be affected.)",
            "Remove from local cache", MessageBoxButton.YesNo)
        if res != MessageBoxResult.Yes:
            return
        try:
            if row.job_ref and row.job_ref.job_folder and os.path.isdir(row.job_ref.job_folder):
                shutil.rmtree(row.job_ref.job_folder, ignore_errors=True)
            self.status_label.Text = "Local cache cleared for this row."
            # Remove the job from in-memory list so it stops appearing as local.
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

    def _ctx_delete_gallery(self, row):
        from System.Windows import MessageBox, MessageBoxButton, MessageBoxResult
        gallery_id = (row.cloud_item or {}).get("id") if row.cloud_item else (
            row.job_ref.gallery_id if row.job_ref else None)
        if not gallery_id:
            return
        res = MessageBox.Show(
            "Delete this item from your Gallery?\n\n"
            "This removes it from the cloud — every device you're signed in on "
            "will stop showing it. Cannot be undone.",
            "Delete from Gallery", MessageBoxButton.YesNo)
        if res != MessageBoxResult.Yes:
            return
        token = AUTH.get_token()
        if not token:
            self.status_label.Text = "Sign in required."
            return
        def worker(state):
            try:
                AI.delete_gallery_item_with_token(token, gallery_id)
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Deleted from Gallery."))
                self._invoke_ui(self._refresh_gallery_async)
            except Exception as ex:
                self._invoke_ui(lambda: setattr(self.status_label, 'Text',
                                                "Delete failed: {}".format(str(ex)[:200])))
        System.Threading.ThreadPool.QueueUserWorkItem(
            System.Threading.WaitCallback(worker))

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
        from System.Windows import Window as SysWindow, Thickness, WindowStartupLocation
        from System.Windows.Controls import StackPanel, TextBox, Button as SysButton, \
            TextBlock, ComboBox as SysCombo, Orientation as SysOrient
        win = SysWindow()
        win.Title = "Animate — Image to Video"
        win.Width = 460
        win.Height = 320
        win.WindowStartupLocation = WindowStartupLocation.CenterOwner
        win.Owner = self
        sp = StackPanel()
        sp.Margin = Thickness(12)

        sp.Children.Add(self._lbl("Motion prompt (describe the animation):"))
        tb_prompt = TextBox()
        tb_prompt.Text = "Subtle camera push-in, gentle parallax, cinematic light shift"
        tb_prompt.Height = 60
        tb_prompt.AcceptsReturn = True
        tb_prompt.TextWrapping = System.Windows.TextWrapping.Wrap
        sp.Children.Add(tb_prompt)

        sp.Children.Add(self._lbl("Duration:"))
        cb_dur = SysCombo()
        cb_dur.Items.Add("4 seconds")
        cb_dur.Items.Add("6 seconds")
        cb_dur.Items.Add("8 seconds")
        cb_dur.SelectedIndex = 0
        sp.Children.Add(cb_dur)

        sp.Children.Add(self._lbl("Resolution:"))
        cb_res = SysCombo()
        cb_res.Items.Add("720p")
        cb_res.Items.Add("1080p")
        cb_res.SelectedIndex = 0
        sp.Children.Add(cb_res)

        btn_row = StackPanel()
        btn_row.Orientation = SysOrient.Horizontal
        btn_row.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        btn_row.Margin = Thickness(0, 12, 0, 0)
        ok = SysButton(); ok.Content = "Queue Video"; ok.Width = 100; ok.Margin = Thickness(4)
        cancel = SysButton(); cancel.Content = "Cancel"; cancel.Width = 80; cancel.Margin = Thickness(4)
        def on_ok(s, a):
            duration = [4, 6, 8][cb_dur.SelectedIndex]
            resolution = ["720p", "1080p"][cb_res.SelectedIndex]
            self._enqueue_video(image_path, tb_prompt.Text, duration, resolution,
                                row.view_name or "", row.StyleName or "")
            win.Close()
        ok.Click += on_ok
        cancel.Click += lambda s, a: win.Close()
        btn_row.Children.Add(ok)
        btn_row.Children.Add(cancel)
        sp.Children.Add(btn_row)
        win.Content = sp
        win.ShowDialog()

    def _lbl(self, text):
        from System.Windows.Controls import TextBlock
        from System.Windows import Thickness
        t = TextBlock()
        t.Text = text
        t.Margin = Thickness(0, 6, 0, 2)
        return t

    def _enqueue_video(self, image_path, motion_prompt, duration, resolution,
                       view_name, style_name):
        if not Q.can_enqueue(self._jobs, self._jobs_lock):
            self.status_label.Text = "Queue full."
            return
        job = Q.RenderJob(
            original_path=image_path,
            prompt=motion_prompt,
            style_preset=style_name,
            view_name=view_name,
            kind=Q.KIND_VIDEO,
            host="revit",
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
    # Manage local cache (right-click cache_size_label, or call directly)
    # ------------------------------------------------------------------

    def _show_manage_cache(self):
        from System.Windows import MessageBox, MessageBoxButton, MessageBoxResult
        n = G.cache_size_bytes()
        msg = ("Local gallery cache: {}\n\n"
               "Cloud Gallery is canonical — clearing the local cache only frees "
               "disk space. Items will re-download on next view.\n\n"
               "Clear cache now?").format(G.fmt_bytes(n))
        res = MessageBox.Show(msg, "Manage local cache", MessageBoxButton.YesNo)
        if res == MessageBoxResult.Yes:
            try:
                G.clear_cache()
                self.status_label.Text = "Local cache cleared."
                self._update_cache_size()
            except Exception as ex:
                self.status_label.Text = "Clear failed: {}".format(str(ex)[:200])

    # Allow clicking the cache size label to open the manage dialog.
    def cache_label_Click(self, sender, e):
        self._show_manage_cache()


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

_constructing = [False]


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    # Race fix: between AiRenderForm() returning and _active_form[0] = form,
    # a second click can squeak past the None check and spawn a duplicate.
    # Guard with a "constructing" flag (Audit P0-runtime-9).
    if _active_form[0] is not None or _constructing[0]:
        try:
            if _active_form[0] is not None:
                _active_form[0].Focus()
        except Exception:
            _active_form[0] = None
        return
    _constructing[0] = True
    try:
        output = script.get_output()
        try:
            output.close_others()
        except Exception:
            pass
        form = AiRenderForm()
        _active_form[0] = form
    finally:
        _constructing[0] = False


if __name__ == "__main__":
    main()
