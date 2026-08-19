"""Capability handshake: what THIS host build can actually render, refreshed live.

WHY A CAPABILITY FILE AND NOT A LIVENESS CHECK
----------------------------------------------
The producer (EnneadTab.EXE.ensure_notification_host) can only ask "is A host
alive?" -- via the named mutex or the process list. It cannot ask "does that
host understand progress jobs?", and the difference is not academic:

NotificationHost.exe ships in Apps/lib/ExeProducts through the same git EA_Dist
sync as Apps/lib, but the host is a DAEMON holding a mutex released only on
process exit. A user who syncs mid-week has the new exe on disk and the OLD
process still running for days. A liveness check sees the mutex held, reports
success, and the new binary never starts -- silently, until they reboot. A
presence check standing in for a capability check is the same class of defect
that hid the notification outage (senzhang-todo #3895).

So the host states its capabilities affirmatively and keeps restating them. The
stamp is refreshed on its OWN timer, deliberately not on the inbox poll: that
tick also does directory listing, JSON reads, card construction and layout
animation, so its jitter reflects inbox workload rather than event-loop
liveness, and a producer thresholding on it would see spurious "host is dead".

WHAT IT REPLACES
----------------
`notification_host_alive.txt` was written ONCE at startup, before QApplication
even existed, was never refreshed, and nothing ever read it. Presence, not
liveness -- it kept asserting a live host after a crash. It is removed here
rather than left alongside this file: two liveness artifacts that can disagree
are worse than one.

HONEST LIMIT
------------
A host whose Qt loop still turns but whose progress rendering is broken will
keep refreshing this stamp and keep advertising "progress". No file-based
handshake can detect that. It is an explicit non-goal, not an oversight.
"""

from __future__ import print_function

import json
import os
import socket
import time

import paths

CAPABILITY_FILE = "notification_host_capability.sexyDuck"
LEGACY_ALIVE_MARKER = "notification_host_alive.txt"

REFRESH_MS = 1000

# Bumped when the payload contract or the surface set changes.
CAPABILITY_VERSION = 1

# Surfaces this build genuinely renders. "chart" is deliberately ABSENT: there
# is no chart renderer anywhere in this package (grep it), even though RECAP
# sends a chart payload and a comment there claims the host draws it. The one
# artifact whose entire job is stating capability truthfully must not carry a
# fabricated entry.
SURFACES = ["toast", "progress"]


def capability_path():
    return os.path.join(paths.get_dump_folder(), CAPABILITY_FILE)


def _machine():
    try:
        return socket.gethostname()
    except Exception:
        return ""


def refresh():
    """Write/refresh the capability stamp. Safe to call on a timer."""
    payload = {
        "surfaces": SURFACES,
        "version": CAPABILITY_VERSION,
        "pid": os.getpid(),
        "machine": _machine(),
        "stamp": time.time(),
    }
    path = capability_path()
    try:
        with open(path, "w") as handle:
            json.dump(payload, handle)
        return True
    except Exception:
        return False


def read():
    """Return the current capability payload, or None."""
    try:
        with open(capability_path(), "r") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def should_own_progress():
    """True if this process should render the progress surface.

    lock.acquire_single_instance() fails OPEN in two places -- a null handle and
    any exception both return True -- so two hosts can legitimately run. Two
    bottom-left toast stacks are survivable; two full-width strips pinned to the
    top edge are a visible mess. The capability file carries the owning pid, and
    a host that finds a DIFFERENT still-live pid there yields the surface.
    """
    data = read()
    if not data:
        return True
    other_pid = data.get("pid")
    if not other_pid or int(other_pid) == os.getpid():
        return True
    if (data.get("machine") or "") != _machine():
        return True
    try:
        import progress_jobs
        return not progress_jobs._pid_alive(other_pid)
    except Exception:
        return True


def remove_legacy_alive_marker():
    """Delete the never-read startup marker this file supersedes."""
    try:
        legacy = os.path.join(paths.get_dump_folder(), LEGACY_ALIVE_MARKER)
        if os.path.exists(legacy):
            os.remove(legacy)
    except Exception:
        pass
