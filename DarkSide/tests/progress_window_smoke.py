"""Native-window assertions for NotificationHost/progress_window.ProgressStrip.

Run:  .venv/Scripts/python.exe DarkSide/tests/progress_window_smoke.py

REQUIRES AN INTERACTIVE DESKTOP SESSION (it creates a real top-level window and
queries the Win32 window manager). Not a CI test -- headless agents and service
accounts cannot produce a meaningful result here, and a "pass" from such an
environment would be a false green.

Why this exists rather than trusting the Qt docs: the obvious way to make a
window click-through -- setAttribute(Qt.WA_TransparentForMouseEvents) -- does
NOT work. Measured 2026-08-12 on PyQt5 5.15.11 / Qt 5.15.2, it leaves the native
exstyle byte-identical at 0x00080088; WS_EX_TRANSPARENT never appears and
Windows still reports the strip as owning the pixel, so Revit loses the click.
The window FLAG Qt.WindowTransparentForInput is what actually works, yielding
0x000800A8. That difference is invisible from Python-side state, so it has to be
asserted against the OS.
"""

import ctypes
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOST = os.path.join(_HERE, os.pardir, "exes", "source code", "NotificationHost")
sys.path.insert(0, os.path.normpath(_HOST))

from PyQt5.QtWidgets import QApplication      # noqa: E402
from PyQt5.QtGui import QGuiApplication       # noqa: E402

import progress_window                        # noqa: E402

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000

_FAILS = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          ("" if cond else " :: " + detail))
    if not cond:
        _FAILS.append(name)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def main():
    app = QApplication(sys.argv)
    strip = progress_window.ProgressStrip("job_smoke", pid=os.getpid())
    strip.update_job({"progress": 40.0, "label": "smoke", "title": "T"})
    strip.show()
    app.processEvents()

    hwnd = int(strip.winId())
    exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    print("exstyle = 0x%08X" % exstyle)

    check("WS_EX_TRANSPARENT set (click-through)",
          bool(exstyle & WS_EX_TRANSPARENT),
          "the flag did not reach the native window -- did someone swap "
          "Qt.WindowTransparentForInput back to WA_TransparentForMouseEvents?")
    check("WS_EX_TOPMOST set", bool(exstyle & WS_EX_TOPMOST))
    check("WS_EX_LAYERED set (translucency)", bool(exstyle & WS_EX_LAYERED))

    screen = strip._screen or QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    geo = strip.geometry()

    check("spans the full available width", geo.width() == avail.width(),
          "%d vs %d" % (geo.width(), avail.width()))
    check("pinned to the top edge", geo.top() == avail.top(),
          "%d vs %d" % (geo.top(), avail.top()))
    check("height derived from DPI rather than a hardcoded 2px",
          geo.height() > 2,
          "height=%d scale=%.2f" % (geo.height(), strip._scale()))
    print("  info: logicalDPI=%.0f scale=%.2f idle=%dpx max=%dpx"
          % (screen.logicalDotsPerInch(), strip._scale(),
             strip._idle_height_px(), strip._max_height_px()))

    # The decisive one: ask the OS who owns a pixel inside the PAINTED band.
    # Sampling in the transparent region would pass even for a mouse-opaque
    # window, because WA_TranslucentBackground makes alpha-0 areas
    # click-through for free -- an earlier probe made exactly that mistake.
    point = POINT(int(geo.left() + geo.width() * 0.10), int(geo.top() + 1))
    under = ctypes.windll.user32.WindowFromPoint(point)
    check("clicks pass through the painted band", int(under or 0) != hwnd,
          "WindowFromPoint returned the strip itself")

    strip.shutdown()
    print("\n" + ("ALL PASS" if not _FAILS else "FAILURES: " + ", ".join(_FAILS)))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
