"""
EnneadTab NotificationHost — persistent PyQt5 toast daemon.

Single-instance (held msvcrt lock). Watches Dump/messenger_inbox for unique
JSON payloads written by NOTIFICATION.messenger(), stacks up to 5 cards,
supports optional action buttons (open_path / open_url / copy / dismiss).
"""

from __future__ import print_function

import os
import sys
import threading

# Allow `python NotificationHost.py` from this folder and frozen onefile.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction

import inbox
import lock
import mute
import styles
import error_report
import youtube_thumb
import capability
import progress_jobs
import progress_window
from toast_window import ToastCard, anchor_geometry


POLL_MS = 400

# Progress polls on its own cadence, and the capability stamp on a third: that
# stamp must measure event-loop liveness, so it cannot share a tick that also
# does directory listing, JSON reads and card layout.
PROGRESS_POLL_MS = 400
MAX_PROGRESS_STRIPS = 3


def _resolve_duck_icon():
    candidates = [
        os.path.join(_HERE, "icon_duck.ico"),
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))),
            "Apps",
            "lib",
            "EnneadTab",
            "images",
            "icon_duck.ico",
        ),
    ]
    # Frozen: look next to _MEIPASS / exe
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.insert(0, os.path.join(meipass, "icon_duck.ico"))
        candidates.insert(0, os.path.join(os.path.dirname(sys.executable), "icon_duck.ico"))

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


class NotificationHost(object):
    def __init__(self, app):
        self.app = app
        self.toasts = []
        self._icon_path = _resolve_duck_icon()
        self._setup_tray()

        self._poll = QTimer()
        self._poll.timeout.connect(self._poll_inbox)
        self._poll.start(POLL_MS)

        # Progress surface: its own store, strips and tick.
        self._job_store = progress_jobs.JobStore()
        self._strips = {}
        self._progress_poll = QTimer()
        self._progress_poll.timeout.connect(self._poll_progress)
        self._progress_poll.start(PROGRESS_POLL_MS)

        # Capability stamp on a dedicated timer -- see capability.py for why it
        # must not ride the inbox tick. Written once here as well as in main():
        # a host object that exists must advertise itself regardless of which
        # entry path built it, and without this the guarantee would hold only
        # for main() while any other caller waited a full tick with no stamp on
        # disk. A producer reading in that gap would wrongly fall back.
        self._refresh_capability()
        self._capability_poll = QTimer()
        self._capability_poll.timeout.connect(self._refresh_capability)
        self._capability_poll.start(capability.REFRESH_MS)

        # Drain backlog on startup
        QTimer.singleShot(50, self._drain_startup)
        # Reap job files orphaned by a Revit that died BEFORE this host started.
        # Their pid is gone and their heartbeat is cold, so nothing else will
        # ever clear them -- the poll tick alone is not enough.
        QTimer.singleShot(60, self._sweep_progress_orphans)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.app)
        if self._icon_path:
            self.tray.setIcon(QIcon(self._icon_path))
        else:
            self.tray.setIcon(self.app.style().standardIcon(
                self.app.style().SP_MessageBoxInformation
            ))
        self.tray.setToolTip("EnneadTab Notifications")

        menu = QMenu()
        clear_action = QAction("Clear all", menu)
        clear_action.triggered.connect(self.clear_all)
        menu.addAction(clear_action)

        unmute_action = QAction("Unmute notifications", menu)
        unmute_action.triggered.connect(self._unmute)
        menu.addAction(unmute_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _unmute(self):
        mute.clear_mute()

    def _drain_startup(self):
        try:
            if mute.is_muted():
                inbox.drain(max_items=styles.MAX_VISIBLE * 4)
                return
            for payload in inbox.drain(max_items=styles.MAX_VISIBLE * 2):
                self.enqueue(payload)
        except Exception:
            error_report.report_exc("NotificationHost._drain_startup")

    def _poll_inbox(self):
        try:
            if mute.is_muted():
                for path in inbox.list_ready_files():
                    inbox.read_and_consume(path)
                return
            for path in inbox.list_ready_files():
                payload = inbox.read_and_consume(path)
                if payload:
                    self.enqueue(payload)
        except Exception:
            error_report.report_exc("NotificationHost._poll_inbox")

    def _refresh_capability(self):
        try:
            capability.refresh()
        except Exception:
            error_report.report_exc("NotificationHost._refresh_capability")

    def _sweep_progress_orphans(self):
        try:
            removed = progress_jobs.sweep_orphans()
            if removed:
                print("Reaped {} orphaned progress job file(s).".format(removed))
        except Exception:
            error_report.report_exc("NotificationHost._sweep_progress_orphans")

    def _poll_progress(self):
        """Reconcile progress strips against the job directory.

        Deliberately NOT gated on mute.is_muted(): a progress bar is not a
        notification, and a user silencing toasts for an hour should not lose
        the feedback that a 20-minute Revit operation is still running.

        The whole body is wrapped, per the pattern every other poll here uses:
        an unhandled exception on a QTimer tick takes the toast daemon down
        with it, and progress is the lower-value surface of the two.
        """
        try:
            if not capability.should_own_progress():
                # A second live host owns the surface. Two bottom-left toast
                # stacks are survivable; two full-width top strips are a mess.
                self._clear_strips()
                return

            active, ended = self._job_store.poll()

            for job_id in ended:
                strip = self._strips.pop(job_id, None)
                if strip is not None:
                    strip.shutdown()
                    strip.deleteLater()

            for payload in active[:MAX_PROGRESS_STRIPS]:
                job_id = payload.get("job_id")
                if not job_id:
                    continue
                strip = self._strips.get(job_id)
                if strip is None:
                    strip = progress_window.ProgressStrip(
                        job_id, pid=payload.get("pid"))
                    self._strips[job_id] = strip
                    strip.show()
                strip.update_job(payload)

            for index, job_id in enumerate(sorted(self._strips.keys())):
                self._strips[job_id].set_stack_index(index)
        except Exception:
            error_report.report_exc("NotificationHost._poll_progress")

    def _clear_strips(self):
        for job_id in list(self._strips.keys()):
            strip = self._strips.pop(job_id, None)
            if strip is not None:
                try:
                    strip.shutdown()
                    strip.deleteLater()
                except Exception:
                    pass

    def enqueue(self, payload):
        try:
            if mute.is_muted():
                return
            # Never block the Qt UI thread on YouTube thumb HTTP.
            if youtube_thumb.needs_network_fetch(payload):
                def _bg():
                    try:
                        enriched = youtube_thumb.enrich_payload(
                            dict(payload), allow_network=True
                        )
                    except Exception:
                        error_report.report_exc("NotificationHost.enqueue.yt_bg")
                        enriched = payload
                    QTimer.singleShot(0, lambda: self._enqueue_card(enriched))

                threading.Thread(target=_bg, daemon=True).start()
                return
            enriched = youtube_thumb.enrich_payload(payload, allow_network=False)
            self._enqueue_card(enriched)
        except Exception:
            error_report.report_exc("NotificationHost.enqueue")

    def _enqueue_card(self, payload):
        try:
            if mute.is_muted():
                return
            while len(self.toasts) >= styles.MAX_VISIBLE:
                oldest = self.toasts.pop(0)
                try:
                    oldest.closed.disconnect(self._on_card_closed)
                except TypeError:
                    pass
                try:
                    oldest.mute_requested.disconnect(self._on_mute_requested)
                except TypeError:
                    pass
                try:
                    oldest.layout_needed.disconnect(self._on_card_layout_needed)
                except TypeError:
                    pass
                oldest.begin_close()

            card = ToastCard(payload)
            card.closed.connect(self._on_card_closed)
            card.mute_requested.connect(self._on_mute_requested)
            card.layout_needed.connect(self._on_card_layout_needed)
            self.toasts.append(card)
            self._layout_stack(animate_new=True)
        except Exception:
            error_report.report_exc("NotificationHost._enqueue_card")

    def _on_mute_requested(self):
        try:
            mute.mute_for(mute.MUTE_SECONDS)
            self.clear_all()
            try:
                self.tray.showMessage(
                    "EnneadTab",
                    "Notifications muted for 1 hour",
                    QSystemTrayIcon.Information,
                    2500,
                )
            except Exception:
                pass
        except Exception:
            error_report.report_exc("NotificationHost._on_mute_requested")

    def _on_card_layout_needed(self):
        # Action buttons shown/hidden on hover — restack without enter anim.
        self._layout_stack(animate_new=False, animate_existing=False)

    def _on_card_closed(self, card):
        if card in self.toasts:
            self.toasts.remove(card)
        self._layout_stack(animate_new=False)

    def _layout_stack(self, animate_new=False, animate_existing=True):
        # Bottom-left: avoid MS Teams / Windows Action Center (bottom-right).
        # Window includes SHADOW_PAD; align the visible card (not the pad).
        geo = anchor_geometry()
        left = geo.left() + styles.SCREEN_EDGE_PAD
        bottom = geo.bottom() - styles.SCREEN_EDGE_PAD
        pad = styles.SHADOW_PAD

        cursor = bottom
        # Layout from bottom (newest) upward: last in list sits lowest
        for i, card in enumerate(reversed(self.toasts)):
            h = card.card_height()
            content_h = max(h - (pad * 2), 1)
            visual_top = cursor - content_h
            x = left - pad
            y = visual_top - pad
            is_newest = i == 0
            if not card.isVisible():
                card.show_at(x, y, animate=animate_new and is_newest)
            else:
                card.move_to(x, y, animate=animate_existing)
            cursor = visual_top - styles.CARD_GAP

    def clear_all(self):
        for card in list(self.toasts):
            card.begin_close()

    def quit(self):
        self.clear_all()
        self._clear_strips()
        self.tray.hide()
        self.app.quit()


def set_app_user_model_id():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "EnneadTab.NotificationHost"
        )
    except Exception:
        pass


def main():
    error_report.install_excepthook()
    set_app_user_model_id()

    if not lock.acquire_single_instance():
        print("NotificationHost already running.")
        return 0

    # Capability handshake. Supersedes the old notification_host_alive.txt,
    # which was written once at startup, never refreshed, and never read by
    # anything -- it kept asserting a live host after a crash. Removed rather
    # than left alongside: two liveness artifacts that can disagree are worse
    # than one. Written before QApplication so a producer that just launched us
    # sees it as early as possible.
    try:
        capability.refresh()
        capability.remove_legacy_alive_marker()
    except Exception:
        error_report.report_exc("NotificationHost.capability")

    # Ensure inbox exists
    try:
        inbox.get_inbox_dir()
    except Exception:
        error_report.report_exc("NotificationHost.get_inbox_dir")

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName("EnneadTab NotificationHost")

    host = NotificationHost(qt_app)
    # Keep reference alive
    qt_app._ennead_notification_host = host

    return qt_app.exec_()


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            err_path = os.path.join(
                os.environ.get("USERPROFILE", "."),
                "Documents",
                "EnneadTab Ecosystem",
                "Dump",
                "notification_host_crash.txt",
            )
            with open(err_path, "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        try:
            error_report.report(
                tb,
                func_name="NotificationHost.main",
                is_silent=False,
            )
        except Exception:
            pass
        raise
