"""Ambient progress bar for long-running Revit/Rhino loops.

IRONPYTHON 2.7 -- imported by Revit button scripts. No f-strings, no type
hints, no pathlib. (The repo CLAUDE.md runtime table calls Apps/lib CPython-3;
that table is wrong for this file.)

HOW IT WORKS
------------
Each ProgressBarManager owns ONE state file in Dump/progress_jobs/, which the
persistent NotificationHost daemon polls and renders as a thin strip across the
top of the screen. Replaces the old standalone ProgressBar.exe, which drove a
single global "progressbar" file -- so two concurrent tools, or a nested
progress_bar inside another, stomped each other and the inner one's exit killed
the outer one's bar.

FOUR THINGS HERE ARE LOAD-BEARING. Read before editing.
-------------------------------------------------------
1. The public signature of progress_bar() is frozen. Callers pass it BOTH ways:
   rename_nesting_family passes two positional args, bigrhino2revit passes
   everything by keyword. So neither the parameter ORDER nor the names `items`
   and `func` may change, and `items` may not become keyword-only.

2. We do NOT use DATA_FILE.set_data. It retries a locked file three times with
   time.sleep(1.0) doubling -- up to 7 seconds frozen on Revit's API thread per
   write -- and it returns None on the local-dump branch, so its result cannot
   be checked. Progress is disposable state: the next update is 100 ms away, so
   retrying it is strictly wrong. _write_job_file() below is one attempt, no
   retry, no sleep.

3. Nothing here may take down the caller's real work. A progress bar failing is
   an inconvenience; a family-load loop dying because a JSON write failed is a
   bug. __enter__ never raises, and func(item) is never wrapped -- the caller's
   own exception must propagate untouched.

4. total can legitimately be 0 (block2family builds its list from os.listdir
   with no empty guard). Today that is a harmless no-op because progress is only
   computed inside update(). Seeding a percentage in __enter__ would turn it
   into a ZeroDivisionError BEFORE the with-body, killing the caller on input
   that works fine now.
"""

import os
import json
import time

import ENVIRONMENT
import ERROR_HANDLE
import EXE
import SOUND

JOBS_SUBDIR = "progress_jobs"
CAPABILITY_FILE = "notification_host_capability.sexyDuck"

# The host refreshes its stamp on a dedicated 1s timer. 10s tolerates ordinary
# event-loop jitter on a busy machine without declaring a live host dead.
CAPABILITY_MAX_AGE = 10.0
CAPABILITY_RECHECK_SECONDS = 5.0

# >=100ms between writes. The per-item work at every call site is a Revit API
# operation measured in tens of ms to seconds, so a small JSON write is noise --
# but thousands of items still adds up.
MIN_WRITE_INTERVAL = 0.1

# Module-level: the stack of live job ids, innermost last. The finish sound
# fires only when this empties, so a nested progress_bar does not play it once
# per outer item.
_ACTIVE_JOBS = []
_JOB_SEQUENCE = [0]


def _jobs_dir():
    """Dump/progress_jobs, created if absent.

    Guarded rather than exists-then-create: two Revit sessions starting a job at
    the same moment race this, and an unguarded os.makedirs raises on the loser.
    FOLDER.secure_folder has exactly that bug; NOTIFICATION._ensure_inbox_dir is
    the pattern copied here.
    """
    path = os.path.join(ENVIRONMENT.DUMP_FOLDER, JOBS_SUBDIR)
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except Exception:
            pass
    return path


def _new_job_id():
    """pid + ms + a monotonic counter.

    The counter is not decoration: two managers can be constructed inside one
    clock tick (the nesting case), and Windows wall-clock granularity is coarser
    than a millisecond. uuid IS available under IronPython here, but pid is
    wanted anyway -- it is how the host detects that a crashed Revit's job is
    dead, which a uuid cannot express.
    """
    _JOB_SEQUENCE[0] += 1
    return "job_{}_{}_{}".format(os.getpid(), int(time.time() * 1000),
                                 _JOB_SEQUENCE[0])


def _warn(message, func_name, throttle_key):
    """Tell the operator, quietly. Never raises.

    print_note alone is not enough -- it early-returns unless USER.IS_DEVELOPER,
    so on a fleet machine it reaches nobody.
    """
    try:
        ERROR_HANDLE.print_note(message)
    except Exception:
        pass
    try:
        ERROR_HANDLE.report_infra_warning_to_error_dump_async(
            message, func_name, throttle_key=throttle_key)
    except Exception:
        pass


def host_can_render_progress():
    """True if a live NotificationHost advertises the progress surface.

    Deliberately NOT EXE.ensure_notification_host(): that answers "is A host
    alive", never "does that host understand progress jobs". An older daemon
    holding the single-instance mutex would pass a liveness check and silently
    ignore every job file we write.
    """
    try:
        path = os.path.join(ENVIRONMENT.DUMP_FOLDER, CAPABILITY_FILE)
        if not os.path.exists(path):
            return False
        handle = open(path, "r")
        try:
            data = json.load(handle)
        finally:
            handle.close()
        if not isinstance(data, dict):
            return False
        if "progress" not in (data.get("surfaces") or []):
            return False
        stamp = float(data.get("stamp") or 0)
        return (time.time() - stamp) <= CAPABILITY_MAX_AGE
    except Exception:
        return False


class ProgressBarManager(object):
    def __init__(self, items=None, title="Processing...", label_func=None):
        # Materialise once: items is consumed twice (len, then iteration), so a
        # generator call site would silently iterate nothing the second time.
        self.items = list(items) if items is not None else []
        self.title = title
        self.total = len(self.items) if items is not None else 100
        self.counter = 0
        self.current_item = None
        self.label_func = label_func
        self.start_time = time.time()

        self.job_id = _new_job_id()
        self._path = os.path.join(_jobs_dir(), self.job_id + ".sexyDuck")
        self._last_write = 0.0
        self._last_capability_check = 0.0
        self._use_host = False
        self._fallback_notified = False

    # -- transport --------------------------------------------------------

    def _payload(self, progress, label):
        return {
            "job_id": self.job_id,
            "pid": os.getpid(),
            "machine": ENVIRONMENT.get_computer_name()
                       if hasattr(ENVIRONMENT, "get_computer_name")
                       else os.environ.get("COMPUTERNAME", ""),
            "title": self.title,
            "label": label,
            "progress": progress,
            "counter": self.counter,
            "total": self.total,
            "start_time": self.start_time,
            "heartbeat": time.time(),
        }

    def _write_job_file(self, payload):
        """One attempt. No retry, no sleep, no exception. Returns bool."""
        try:
            handle = open(self._path, "w")
            try:
                json.dump(payload, handle)
            finally:
                handle.close()
            return True
        except Exception:
            return False

    def _terminal_fallback(self, progress):
        """Text bar when no capable host is present.

        Throttled to the same rate as the file writes. pyRevit's output window
        is not a VT terminal, so the '\\r' overwrite in FUTURE.print_progress_bar
        likely appends rather than overwrites -- printing per item over
        thousands of items would be its own performance problem.
        """
        if not self._fallback_notified:
            self._fallback_notified = True
            _warn("NotificationHost is not advertising the progress surface; "
                  "falling back to a text progress line.",
                  "UI.ProgressBarManager", "progress_host_missing")
        try:
            print("{}  {:.0f}%  ({} of {})".format(
                self.title, progress, self.counter, self.total))
        except Exception:
            pass

    # -- lifecycle --------------------------------------------------------

    def __enter__(self):
        _ACTIVE_JOBS.append(self.job_id)
        try:
            self._use_host = host_can_render_progress()
            if not self._use_host:
                # Start it for NEXT time; it cannot serve this run.
                try:
                    EXE.ensure_notification_host()
                except Exception:
                    pass
            # Seed a literal 0.0 -- never a computed percentage (see note 4).
            if self._use_host:
                self._write_job_file(self._payload(0.0, self.title))
                self._last_write = time.time()
        except Exception:
            # __enter__ must never raise: the caller's work has not started yet
            # and a progress bar is not worth losing it over.
            self._use_host = False
        return self

    def update(self, amount=1):
        self.counter += amount
        try:
            total = float(self.total) or 1.0
            progress = max(0.0, min(100.0, (float(self.counter) / total) * 100.0))

            if self.label_func is not None:
                label = self.label_func(self.current_item)
            else:
                label = "Processing item {}".format(self.counter)

            now = time.time()
            is_final = self.counter >= self.total

            # Re-check the host mid-job: a long run can outlive the daemon (the
            # tray Quit is user-reachable), and a write failure is invisible
            # because the writer cannot distinguish "wrote" from "nobody reads".
            if (now - self._last_capability_check) >= CAPABILITY_RECHECK_SECONDS:
                self._last_capability_check = now
                self._use_host = host_can_render_progress()

            if not self._use_host:
                if is_final or (now - self._last_write) >= MIN_WRITE_INTERVAL:
                    self._last_write = now
                    self._terminal_fallback(progress)
                return

            # Always write the final update, or the strip freezes short of 100%.
            if not is_final and (now - self._last_write) < MIN_WRITE_INTERVAL:
                return
            self._last_write = now
            self._write_job_file(self._payload(progress, label))
        except Exception:
            # Never let progress accounting break the caller's loop.
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Pop FIRST and by job_id. If the delete below raised before the pop,
        # the entry would leak forever and the finish sound would never fire
        # again for the life of this engine. A blind pop() would also take the
        # wrong entry off an already-leaked stack.
        try:
            if self.job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS.remove(self.job_id)
        except Exception:
            pass

        try:
            if os.path.exists(self._path):
                os.remove(self._path)
        except Exception:
            # The host reaps it on pid-death / stale heartbeat anyway.
            pass

        try:
            if not _ACTIVE_JOBS:
                SOUND.play_finished_sound()
        except Exception:
            pass
        return False


def progress_bar(items, func, label_func=None, title="Iterating through items"):
    """Run func over items while showing an ambient progress strip.

    SIGNATURE IS FROZEN -- see note 1 in the module docstring.

    Args:
        items: Iterable of items to process
        func: Function applied to each item
        label_func: Optional function producing a label for an item
        title: Title shown on the strip

    Example:
        def work(item):
            do_something(item)

        progress_bar(items, work,
                     label_func=lambda x: "Working on [{}]".format(x),
                     title="Processing")
    """
    with ProgressBarManager(items=items, title=title,
                            label_func=label_func) as progress:
        for item in progress.items:
            progress.current_item = item
            func(item)          # NEVER wrapped: caller exceptions propagate
            progress.update()


def unit_test():
    import random

    products = ["UltraGlow Pro X1000", "QuickSlice Master", "DreamWeaver Elite",
                "PowerFlex 360", "SmartHome Hub Plus", "EcoClean Supreme",
                "TechMaster 2000", "ComfortZone Deluxe", "SpeedBrew Max",
                "FitTracker Prime"]

    def work(item):
        time.sleep(random.randint(1, 6) / 10.0)
        print("simulated [{}]".format(item))

    progress_bar(products, work,
                 label_func=lambda x: "Processing [{}]".format(x),
                 title="Unit test")


if __name__ == "__main__":
    unit_test()
