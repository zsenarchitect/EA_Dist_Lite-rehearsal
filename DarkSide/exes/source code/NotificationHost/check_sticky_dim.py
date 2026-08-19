"""Tests for the sticky-card idle-dim / hover-undim behavior in toast_window.

Run: python check_sticky_dim.py   (PyQt5, real Windows desktop session).

A sticky card (payload["sticky"]) never auto-dismisses; this feature makes it fade
to a resting opacity after a quiet interval and snap back to full opacity on hover.
A normal (auto-closing) card must be completely unaffected.

No test calls show(), so nothing pops on screen -- the dim/undim wiring is asserted
via timer + opacity-animation STATE, so the 10s idle countdown is never waited out.
Runs under the native `windows` platform, not `offscreen`: the redesigned card's
drop-shadow effect needs a real paint device and the offscreen stand-in crashes at
construction (a harness limitation, not a product bug -- the toast ships and runs
under this same windows platform).
"""

from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication

import styles
from toast_window import ToastCard

_FAILURES = []


def check(label, condition):
    print("  {} {}".format("ok  " if condition else "FAIL", label))
    if not condition:
        _FAILURES.append(label)


def _card(**payload):
    payload.setdefault("main_text", "hello")
    return ToastCard(dict(payload))


def test_tokens_sane():
    print("test_tokens_sane")
    check("delay is 10s", styles.STICKY_DIM_DELAY_MS == 10000)
    check("resting opacity in (0,1)", 0.0 < styles.STICKY_DIM_OPACITY < 1.0)
    check("fade duration positive", styles.STICKY_DIM_FADE_MS > 0)


def test_sticky_flag_and_timer_wired():
    print("test_sticky_flag_and_timer_wired")
    sticky = _card(sticky=True)
    normal = _card()
    check("sticky payload -> sticky True", sticky.sticky is True)
    check("plain payload -> sticky False", normal.sticky is False)
    check("dim timer exists", hasattr(sticky, "_dim_timer"))
    check("dim timer idle at construction", not sticky._dim_timer.isActive())
    check("opacity anim starts empty", sticky._opacity_anim is None)


def test_begin_dwell_arms_dim_for_sticky_only():
    # _begin_dwell is the single post-entrance hook both show_at branches call;
    # driving it directly avoids show() (no window pops) while exercising the
    # exact sticky-vs-normal decision.
    print("test_begin_dwell_arms_dim_for_sticky_only")
    sticky = _card(sticky=True)
    sticky._begin_dwell()
    check("sticky: dim countdown armed", sticky._dim_timer.isActive())
    check("sticky: lifetime NOT started", not sticky._lifetime.isActive())

    normal = _card()
    normal._begin_dwell()
    check("normal: lifetime started", normal._lifetime.isActive())
    check("normal: dim countdown NOT armed", not normal._dim_timer.isActive())


def test_dim_targets_resting_opacity():
    print("test_dim_targets_resting_opacity")
    sticky = _card(sticky=True)
    sticky._dim()
    check("dim created an opacity animation", sticky._opacity_anim is not None)
    check("dim end value == resting opacity",
          abs(sticky._opacity_anim.endValue() - styles.STICKY_DIM_OPACITY) < 1e-6)


def test_hover_wakes_to_full_opacity():
    print("test_hover_wakes_to_full_opacity")
    sticky = _card(sticky=True)
    sticky._arm_dim_countdown()
    check("countdown armed before hover", sticky._dim_timer.isActive())
    sticky._dim()   # pretend the idle countdown already fired
    sticky._on_hover_enter()
    check("hover stops the dim countdown", not sticky._dim_timer.isActive())
    check("hover animates back to full opacity",
          abs(sticky._opacity_anim.endValue() - 1.0) < 1e-6)
    # Leaving re-arms the countdown so it dims again after another quiet interval.
    sticky._on_hover_leave()
    check("leave re-arms the countdown", sticky._dim_timer.isActive())


def test_event_dispatch_hits_hover_hooks():
    print("test_event_dispatch_hits_hover_hooks")
    sticky = _card(sticky=True)
    sticky._dim()   # dimmed
    sticky.event(QEvent(QEvent.HoverEnter))
    check("HoverEnter event -> wake to full opacity",
          abs(sticky._opacity_anim.endValue() - 1.0) < 1e-6)
    check("HoverEnter event -> countdown stopped", not sticky._dim_timer.isActive())
    sticky.event(QEvent(QEvent.HoverLeave))
    check("HoverLeave event -> countdown re-armed", sticky._dim_timer.isActive())


def test_normal_card_is_unaffected():
    print("test_normal_card_is_unaffected")
    normal = _card()
    normal._arm_dim_countdown()
    check("arm is a no-op for normal card", not normal._dim_timer.isActive())
    normal._dim()
    check("dim is a no-op for normal card", normal._opacity_anim is None)
    normal._on_hover_enter()
    check("hover-enter is a no-op for normal card", normal._opacity_anim is None)


def test_close_stops_dim():
    print("test_close_stops_dim")
    sticky = _card(sticky=True)
    sticky._arm_dim_countdown()
    sticky.begin_close()
    check("close stops the dim countdown", not sticky._dim_timer.isActive())
    # After closing, a stray idle fire must not animate a dying card.
    sticky._dim()
    check("dim after close is inert", sticky._opacity_anim is None)


def main():
    # Must bind the app: an unreferenced QApplication is garbage-collected mid-run
    # and the next widget construction then crashes the process natively.
    app = QApplication(sys.argv)
    for test in (
        test_tokens_sane,
        test_sticky_flag_and_timer_wired,
        test_begin_dwell_arms_dim_for_sticky_only,
        test_dim_targets_resting_opacity,
        test_hover_wakes_to_full_opacity,
        test_event_dispatch_hits_hover_hooks,
        test_normal_card_is_unaffected,
        test_close_stops_dim,
    ):
        test()
    print("-" * 52)
    if _FAILURES:
        print("FAILED {} check(s):".format(len(_FAILURES)))
        for label in _FAILURES:
            print("  - {}".format(label))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
