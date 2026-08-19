"""Progress-job state store: discover, read and reap per-job progress files.

TRANSPORT CONTRACT
------------------
One file per live job at Dump/progress_jobs/job_<pid>_<ms>_<seq>.sexyDuck,
written by EnneadTab.UI.ProgressBarManager (IronPython 2.7, inside Revit) and
read here. Payload:

    {"job_id", "pid", "machine", "title", "label",
     "progress", "counter", "total", "start_time", "heartbeat"}

This is deliberately NOT the messenger_inbox transport. That inbox is an EVENT
queue -- it deletes each file on read, quarantines anything lacking "main_text",
and drops everything while muted. Progress is STATE: it must be re-readable,
must survive mute, and must not be consumed.

WHY THIS MODULE IS DEFENSIVE
----------------------------
Three properties of the producer side are NOT what you would assume, and each
one dictates a rule here. Do not "simplify" these away:

1. The write is NOT atomic. DATA_FILE._save_dict_to_json does os.remove(target)
   then shutil.move(tmp, target), so on EVERY update there is a window where the
   file does not exist. => a missing file must NOT immediately mean "job over".
   See MISS_TOLERANCE.

2. For the same reason a read can catch a half-written file. => a JSON parse
   failure must mean "keep the last known value", never "job gone", and never
   quarantine. inbox.py quarantines unparseable files; copying that instinct
   here would permanently kill a live strip.

3. The producer runs a synchronous loop on Revit's API thread, so it cannot run
   a heartbeat timer. Its heartbeat only advances when it happens to update.
   => pid liveness is the PRIMARY death signal and the heartbeat is a generous
   backstop, not the other way round.
"""

from __future__ import print_function

import ctypes
import json
import os
import socket
import time

import paths

JOBS_SUBDIR = "progress_jobs"
FILE_PREFIX = "job_"
FILE_SUFFIX = ".sexyDuck"

# A missing file is only believed after this many CONSECUTIVE polls (see note 1).
# 2 misses at the host's poll interval costs a fraction of a second of latency
# at real completion and removes the whole torn-write failure class.
MISS_TOLERANCE = 2

# Backstop only -- pid liveness is the real signal (see note 3). Deliberately
# generous: a single Revit operation (a large family load) can legitimately run
# for many minutes without the producer ever calling update().
STALE_HEARTBEAT_SECONDS = 600.0

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_jobs_dir():
    return paths.get_dump_subdir(JOBS_SUBDIR)


def this_machine():
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _pid_alive(pid):
    """True if a process with this pid exists and has not exited.

    Checking the exit code matters: a handle can still be opened for a process
    that has already terminated but is not yet reaped, and that would read as
    alive on a plain open-succeeded test.
    """
    if not pid:
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == _STILL_ACTIVE
            # Could not determine -- fail SAFE (assume alive) so we never reap a
            # living job. A stuck strip is recoverable; a vanished one is not.
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return True


def list_job_files():
    """Return job files, oldest first, excluding partial writes.

    The extension filter is load-bearing: the producer's temp file lands as a
    sibling in this same directory, and parsing it would read a half-written
    payload.
    """
    jobs_dir = get_jobs_dir()
    if not os.path.isdir(jobs_dir):
        return []
    found = []
    for name in os.listdir(jobs_dir):
        if not name.startswith(FILE_PREFIX):
            continue
        if not name.endswith(FILE_SUFFIX):
            continue
        full = os.path.join(jobs_dir, name)
        if not os.path.isfile(full):
            continue
        try:
            found.append((os.path.getmtime(full), full))
        except OSError:
            continue
    found.sort()
    return [path for _mtime, path in found]


def _read_job_file(path):
    """Parse one job file. Returns a dict, or None if unreadable THIS poll.

    None means "could not read right now", NOT "job gone" -- the caller keeps
    the last known payload. See note 2 in the module docstring.
    """
    try:
        with open(path, "r") as handle:
            raw = handle.read()
        if not raw.strip():
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if "job_id" not in data:
            return None
        return data
    except Exception:
        return None


def job_id_from_path(path):
    name = os.path.basename(path)
    return name[:-len(FILE_SUFFIX)] if name.endswith(FILE_SUFFIX) else name


class JobStore(object):
    """Tracks live progress jobs across polls.

    Holds last-known payloads so a torn write or a transient miss degrades to a
    momentarily stale bar rather than a disappearing one.
    """

    def __init__(self, miss_tolerance=MISS_TOLERANCE,
                 stale_after=STALE_HEARTBEAT_SECONDS):
        self._jobs = {}     # job_id -> payload
        self._misses = {}   # job_id -> consecutive polls with no readable file
        self._miss_tolerance = miss_tolerance
        self._stale_after = stale_after
        self._machine = this_machine()

    def _is_dead(self, payload, now):
        """Death test. Ordered cheapest-and-most-certain first."""
        pid = payload.get("pid")
        machine = payload.get("machine") or ""

        # Only trust pid liveness for jobs from THIS machine. A Dump folder that
        # is being synced between a user's own boxes (a fully KFM-redirected
        # profile) can surface a foreign pid that happens to match a live local
        # process, which would keep a dead job's strip up forever.
        if machine and machine == self._machine:
            if not _pid_alive(pid):
                return True

        heartbeat = payload.get("heartbeat") or payload.get("start_time") or 0
        try:
            if heartbeat and (now - float(heartbeat)) > self._stale_after:
                return True
        except (TypeError, ValueError):
            pass
        return False

    def poll(self):
        """Re-scan the job directory.

        Returns:
            (active, ended): active is a list of payload dicts to render,
            ended is a list of job_ids whose strips should be torn down.
        """
        now = time.time()
        seen = {}
        paths_by_job = {}
        for path in list_job_files():
            job_id = job_id_from_path(path)
            paths_by_job[job_id] = path
            payload = _read_job_file(path)
            if payload is None:
                # Unreadable this poll (torn write). Hold the last known value
                # if we have one; a brand-new job we have never read is simply
                # not shown yet.
                if job_id in self._jobs:
                    seen[job_id] = self._jobs[job_id]
                continue
            payload.setdefault("job_id", job_id)
            seen[job_id] = payload

        ended = []

        # Jobs whose file was present but whose owner is gone.
        for job_id, payload in list(seen.items()):
            if self._is_dead(payload, now):
                ended.append(job_id)
                seen.pop(job_id, None)
                self.forget(job_id)
                # Delete the file too, not just the strip. The owner is gone,
                # so nobody will ever clean it up: __exit__ never ran, and
                # sweep_orphans only fires at host startup. Found by dogfooding
                # -- killing a producer mid-job correctly removed the strip and
                # left the job file on disk indefinitely.
                self._delete_job_file(paths_by_job.get(job_id))

        # Jobs we knew about whose file did not appear this poll.
        for job_id in list(self._jobs.keys()):
            if job_id in seen:
                self._misses[job_id] = 0
                continue
            if job_id in ended:
                continue
            misses = self._misses.get(job_id, 0) + 1
            self._misses[job_id] = misses
            if misses >= self._miss_tolerance:
                ended.append(job_id)
                self.forget(job_id)
            else:
                # Not believed yet -- keep rendering the last known state.
                seen[job_id] = self._jobs[job_id]

        self._jobs = seen
        for job_id in list(self._misses.keys()):
            if job_id not in self._jobs:
                self._misses.pop(job_id, None)

        return list(seen.values()), ended

    def _delete_job_file(self, path):
        """Remove a dead owner's file. Never raises -- if it fails, the next
        poll (or the startup sweep) tries again."""
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def forget(self, job_id):
        self._jobs.pop(job_id, None)
        self._misses.pop(job_id, None)

    def active_count(self):
        return len(self._jobs)


def sweep_orphans():
    """Delete job files whose owning process is gone. Returns count removed.

    Must run on the host's STARTUP path as well as the poll tick: files left by
    a Revit that crashed BEFORE this host launched have a dead pid and a cold
    heartbeat, and nothing else will ever clear them.
    """
    now = time.time()
    machine = this_machine()
    removed = 0
    for path in list_job_files():
        payload = _read_job_file(path)
        if payload is None:
            # Do not delete what we could not read -- it may be mid-write.
            continue
        pid = payload.get("pid")
        owner = payload.get("machine") or ""
        heartbeat = payload.get("heartbeat") or payload.get("start_time") or 0

        dead = False
        if owner and owner == machine and not _pid_alive(pid):
            dead = True
        else:
            try:
                if heartbeat and (now - float(heartbeat)) > STALE_HEARTBEAT_SECONDS:
                    dead = True
            except (TypeError, ValueError):
                dead = False

        if dead:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed
