"""The ambient progress strip: a thin, click-through band across the top edge.

Replaces the standalone tkinter ProgressBar.exe (senzhang-todo #3793). This is
a deliberately FORKED window class, not a plug-in to a renderer seam -- there is
no such seam. ToastCard is a concrete QWidget with no base class, enqueue() has
no payload-type dispatch, and _layout_stack hardcodes the bottom-left corner.
Building a Surface abstraction for n=2 would be worse than the fork.

WHY THE WINDOW FLAGS LOOK LIKE THIS (all measured 2026-08-12, PyQt5 5.15.11)
---------------------------------------------------------------------------
* Click-through needs the window FLAG Qt.WindowTransparentForInput, NOT the
  widget attribute Qt.WA_TransparentForMouseEvents. The attribute leaves the
  native exstyle byte-identical (WS_EX_TRANSPARENT never appears) and Windows
  still reports the strip as owning the pixel, so Revit loses the click. With
  the flag the exstyle gains WS_EX_TRANSPARENT and clicks pass through.
* This matters more than it sounds. With WA_TranslucentBackground the alpha-0
  region is already click-through for free, so interception is PROGRESSIVE --
  it grows with the bar and is worst at 100%, exactly when the filled band
  covers the whole ribbon zone. "It only blocks a few pixels" is not true.
* Because the strip is unclickable it also cannot steal focus from Revit
  mid-command. Qt.WindowDoesNotAcceptFocus alone did NOT produce
  WS_EX_NOACTIVATE and did not prevent click-activation.
* Consequence, accepted by design: hover-to-expand is impossible alongside
  click-through, so the strip expands on JOB STATE (start, milestones, finish)
  instead. Same affordance, zero input conflict.

GEOMETRY
--------
No DPI policy is set anywhere in this app (AA_EnableHighDpiScaling is off,
devicePixelRatio is 1.0), so Qt reports raw DEVICE pixels and every styles.py
token is device-px by accident rather than intent. A hardcoded 2px strip is a
1.33-logical-px hairline on a 150%-scaled 4K panel, so heights are derived from
the screen's own logicalDotsPerInch instead.

We hold the QScreen object, never a cached QRect: a frozen rect goes stale on
unplug / resolution change / rescale and parks the strip at coordinates that no
longer exist. The window is sized ONCE at its maximum height and the band is
painted inside it -- resizing a translucent layered top-level every frame forces
DWM recomposition and is what made the tkinter version expensive.
"""

from __future__ import print_function

import ctypes
import time
from ctypes import wintypes

from PyQt5.QtCore import QPoint, QTimer, Qt
from PyQt5.QtGui import QColor, QGuiApplication, QPainter
from PyQt5.QtWidgets import QWidget

# Strip-local tokens. Deliberately not added to styles.py: those constants are
# toast geometry, and mixing a second surface's tokens into them invites the
# accidental-device-px coupling described above.
IDLE_HEIGHT_DIP = 3.0
ACTIVE_HEIGHT_DIP = 6.0
EXPANDED_HEIGHT_DIP = 18.0
# Seconds of silence after which a live job drops from active back to idle.
# Longer than the producer's write throttle so a steady job never flickers.
ACTIVE_WINDOW_S = 3.0
ANIM_INTERVAL_MS = 40
ANIM_INTERVAL_MS_RDP = 250
EASE = 0.18
HUE_STEP = 0.35
ATTENTION_MS = 2200
MILESTONE_STEP = 25.0
TRACK_ALPHA = 38

_SM_REMOTESESSION = 0x1000


def _is_remote_session():
    """True under RDP. A continuously hue-shifting full-width strip is a real
    bandwidth sink over a remote session, so animation degrades there."""
    try:
        return ctypes.windll.user32.GetSystemMetrics(_SM_REMOTESESSION) != 0
    except Exception:
        return False


def _main_hwnd_for_pid(pid):
    """Largest visible top-level window owned by pid, or None."""
    if not pid:
        return None
    try:
        user32 = ctypes.windll.user32
        best = [None, 0]

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != int(pid):
                return True
            if not user32.IsWindowVisible(hwnd):
                return True
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            area = (rect.right - rect.left) * (rect.bottom - rect.top)
            if area > best[1]:
                best[0], best[1] = hwnd, area
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return best[0]
    except Exception:
        return None


def screen_for_pid(pid):
    """Anchor screen: the one showing the job's owning application.

    Deliberately NOT screen_for_cursor() (what the toasts use). The host creates
    a strip when it first sees the job file, and the cursor at that instant is
    wherever the user left it -- not necessarily Revit's monitor. Falls back to
    the primary screen, which reproduces the old tkinter winfo_screenwidth()
    behaviour.

    Mixing Win32 GetWindowRect coordinates with Qt's screenAt() is only valid
    because devicePixelRatio is 1.0 app-wide; if HighDpi scaling is ever
    enabled, this needs a unit conversion.
    """
    hwnd = _main_hwnd_for_pid(pid)
    if hwnd:
        try:
            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                center = QPoint((rect.left + rect.right) // 2,
                                (rect.top + rect.bottom) // 2)
                screen = QGuiApplication.screenAt(center)
                if screen is not None:
                    return screen
        except Exception:
            pass
    return QGuiApplication.primaryScreen()


class ProgressStrip(QWidget):
    """One ambient strip for one job."""

    def __init__(self, job_id, pid=None, parent=None):
        super(ProgressStrip, self).__init__(parent)
        self.job_id = job_id
        self._progress = 0.0
        self._label = ""
        self._title = ""
        self._hue = 0.0
        self._height = 0.0
        self._attention_ms_left = ATTENTION_MS
        self._last_milestone = 0.0
        self._stack_index = 0
        self._remote = _is_remote_session()
        self._hovering = False
        self._counter = 0
        self._total = 0
        self._start_time = None
        self._last_update = time.time()

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput   # the flag, not the attribute
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._screen = screen_for_pid(pid)
        self._connect_screen(self._screen)
        try:
            QGuiApplication.instance().screenRemoved.connect(self._on_screen_removed)
        except Exception:
            pass

        self._apply_geometry()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(ANIM_INTERVAL_MS_RDP if self._remote
                          else ANIM_INTERVAL_MS)

    # -- geometry ---------------------------------------------------------

    def _connect_screen(self, screen):
        if screen is None:
            return
        for signal_name in ("geometryChanged", "availableGeometryChanged",
                            "logicalDotsPerInchChanged"):
            try:
                getattr(screen, signal_name).connect(self._apply_geometry)
            except Exception:
                pass

    def _scale(self):
        try:
            return max(1.0, self._screen.logicalDotsPerInch() / 96.0)
        except Exception:
            return 1.0

    def _max_height_px(self):
        return int(round(EXPANDED_HEIGHT_DIP * self._scale()))

    def _idle_height_px(self):
        return max(2, int(round(IDLE_HEIGHT_DIP * self._scale())))

    def _active_height_px(self):
        return max(2, int(round(ACTIVE_HEIGHT_DIP * self._scale())))

    def _cursor_over_strip(self):
        """Hover detection by POLLING the cursor, not by mouse events.

        The original tkinter bar bound <Enter>/<Leave> on its canvas. That is
        unavailable here: Qt.WindowTransparentForInput puts WS_EX_TRANSPARENT
        on the window, so it never receives an enter or leave event at all --
        which is why hover-to-expand was dropped when the strip became
        click-through.

        Dropping it was one step too far. Asking Windows where the cursor IS
        requires no input delivery whatsoever, and we already run a timer every
        40ms, so GetCursorPos restores the original affordance with the
        click-through guarantee fully intact -- Revit still never loses a click.

        Comparing Win32 device coordinates against Qt's geometry() is only
        valid because devicePixelRatio is 1.0 app-wide, the same assumption
        screen_for_pid() documents above.
        """
        try:
            point = wintypes.POINT()
            if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return False
            box = self.geometry()
            return (box.left() <= point.x <= box.right()
                    and box.top() <= point.y <= box.bottom())
        except Exception:
            return False

    def set_stack_index(self, index):
        """Position this strip in the top-edge stack (0 = topmost).

        Concurrent jobs are real -- two Revit sessions, or a nested
        progress_bar inside another -- so strips stack downward rather than
        overdrawing each other.
        """
        index = max(0, int(index))
        if index != self._stack_index:
            self._stack_index = index
            self._apply_geometry()

    def _apply_geometry(self, *_args):
        """Size the window ONCE at max height; never resize per frame."""
        if self._screen is None:
            self._screen = QGuiApplication.primaryScreen()
        try:
            avail = self._screen.availableGeometry()
        except Exception:
            return
        band = self._max_height_px()
        self.setGeometry(avail.left(), avail.top() + (self._stack_index * band),
                         avail.width(), band)

    def _on_screen_removed(self, screen):
        if screen is self._screen:
            self._screen = QGuiApplication.primaryScreen()
            self._connect_screen(self._screen)
            self._apply_geometry()

    # -- data -------------------------------------------------------------

    def update_job(self, payload):
        try:
            progress = float(payload.get("progress") or 0.0)
        except (TypeError, ValueError):
            progress = self._progress
        progress = max(0.0, min(100.0, progress))

        # State-driven attention, replacing mouse hover.
        if progress >= 100.0 and self._progress < 100.0:
            self._attention_ms_left = ATTENTION_MS
        elif (progress - self._last_milestone) >= MILESTONE_STEP:
            self._last_milestone = progress - (progress % MILESTONE_STEP)
            self._attention_ms_left = ATTENTION_MS

        self._progress = progress
        self._label = payload.get("label") or ""
        self._title = payload.get("title") or ""

        # The producer has always sent these three; the renderer used to drop
        # them on the floor, which is why the strip lost the original's
        # "<n> of <total>: <elapsed>" readout. Nothing on the wire changed.
        try:
            self._counter = int(payload.get("counter") or 0)
            self._total = int(payload.get("total") or 0)
        except (TypeError, ValueError):
            pass
        try:
            start = payload.get("start_time")
            self._start_time = float(start) if start else self._start_time
        except (TypeError, ValueError):
            pass
        self._last_update = time.time()

    # -- animation --------------------------------------------------------

    def _tick(self):
        interval = ANIM_INTERVAL_MS_RDP if self._remote else ANIM_INTERVAL_MS
        if self._attention_ms_left > 0:
            self._attention_ms_left -= interval

        self._hovering = self._cursor_over_strip()

        # Three tiers, mirroring the original bar's min 2 / max 6 / hover 20:
        # expanded while the pointer is on it or a job milestone just landed,
        # a slim active band while the job is still ticking, hairline at rest.
        if self._hovering or self._attention_ms_left > 0:
            target = self._max_height_px()
        elif (time.time() - self._last_update) <= ACTIVE_WINDOW_S:
            target = self._active_height_px()
        else:
            target = self._idle_height_px()
        self._height += (target - self._height) * EASE
        if not self._remote:
            self._hue = (self._hue + HUE_STEP) % 360.0
        self.update()

    def _elapsed_text(self):
        """Original's format exactly: 01h02m03s, dropping empty leading units."""
        if not self._start_time:
            return ""
        seconds = max(0, int(time.time() - self._start_time))
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        parts = []
        if hours:
            parts.append("{:02d}h".format(hours))
        if minutes or hours:
            parts.append("{:02d}m".format(minutes))
        parts.append("{:02d}s".format(secs))
        return "".join(parts)

    def _status_text(self):
        """The original's second cluster: '<n> of <total>: <elapsed>'."""
        bits = []
        if self._total:
            bits.append("{} of {}".format(self._counter, self._total))
        elapsed = self._elapsed_text()
        if elapsed:
            bits.append(elapsed)
        return ": ".join(bits)

    def _current_color(self):
        if self._remote:
            return QColor(70, 160, 240)
        return QColor.fromHsvF((self._hue / 360.0), 0.72, 0.98)

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, False)
            height = max(1, int(round(self._height)))
            width = self.width()

            # Faint full-width track so a 0% job is still visibly "running".
            track = self._current_color()
            track.setAlpha(TRACK_ALPHA)
            painter.fillRect(0, 0, width, height, track)

            filled = int(width * (self._progress / 100.0))
            if filled > 0:
                painter.fillRect(0, 0, filled, height, self._current_color())

            # Text whenever the band is tall enough to hold it. The height
            # already encodes "expanded" (hover or milestone), so gating on
            # _attention_ms_left as well hid the label during hover -- the one
            # moment the user is deliberately asking to read it.
            if height >= 12:
                painter.setPen(QColor(255, 255, 255, 235))
                text = self._label or self._title
                if text:
                    painter.drawText(8, 0, max(0, width - 16), height,
                                     int(Qt.AlignVCenter | Qt.AlignLeft),
                                     "{}  {:.0f}%".format(text, self._progress))
                status = self._status_text()
                if status:
                    painter.drawText(8, 0, max(0, width - 16), height,
                                     int(Qt.AlignVCenter | Qt.AlignRight),
                                     status)
        finally:
            painter.end()

    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        self.hide()
