"""Timed mute for NotificationHost (shared dump marker)."""

from __future__ import print_function

import os
import time

MUTE_FILENAME = "notification_host_mute_until.txt"
MUTE_SECONDS = 60 * 60  # 1 hour


def _mute_path():
    eco = os.path.join(
        os.environ.get("USERPROFILE", ""),
        "Documents",
        "EnneadTab Ecosystem",
        "Dump",
    )
    if not os.path.exists(eco):
        try:
            os.makedirs(eco)
        except OSError:
            pass
    return os.path.join(eco, MUTE_FILENAME)


def is_muted(now=None):
    """True if notifications are muted until a future timestamp."""
    if now is None:
        now = time.time()
    path = _mute_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            raw = f.read().strip()
        until = float(raw)
        if until > now:
            return True
        # Expired -- clean up
        try:
            os.remove(path)
        except OSError:
            pass
        return False
    except Exception:
        return False


def mute_for(seconds=MUTE_SECONDS):
    """Mute notifications until now + seconds. Returns until timestamp."""
    until = time.time() + float(seconds)
    path = _mute_path()
    try:
        with open(path, "w") as f:
            f.write(str(until))
    except Exception as e:
        print("Failed to write mute marker: {}".format(e))
    return until


def clear_mute():
    path = _mute_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
