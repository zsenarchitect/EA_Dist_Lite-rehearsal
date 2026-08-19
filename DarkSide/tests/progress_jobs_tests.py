"""Known-bad fixtures for NotificationHost/progress_jobs.JobStore.

Run:  python DarkSide/tests/progress_jobs_tests.py     (exit 0 = pass)

Every case asserts BOTH directions -- what must survive AND what must be
reaped. That matters here specifically: a reaper that only ever answers "still
alive" looks identical to a working one under a naive smoke test, and a reaper
that reaps too eagerly makes progress bars vanish mid-job. Each case below is a
failure mode identified during the 2026-08-12 review (senzhang-todo #3793).

The store is redirected at a temp sandbox; nothing touches the real Dump folder.
"""

import json
import os
import shutil
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOST = os.path.join(_HERE, os.pardir, "exes", "source code", "NotificationHost")
sys.path.insert(0, os.path.normpath(_HOST))

import paths            # noqa: E402
import progress_jobs    # noqa: E402

TMP = tempfile.mkdtemp(prefix="progjobs_")
paths.get_dump_folder = lambda: TMP
progress_jobs.paths = paths

MACHINE = progress_jobs.this_machine()
LIVE_PID = os.getpid()
DEAD_PID = 999999   # not a running process

_FAILS = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" :: " + detail if detail and not cond else ""))
    if not cond:
        _FAILS.append(name)


def write_job(job_id, pid=LIVE_PID, machine=None, progress=10.0,
              heartbeat=None, raw=None):
    path = os.path.join(progress_jobs.get_jobs_dir(),
                        "job_" + job_id + progress_jobs.FILE_SUFFIX)
    if raw is not None:
        with open(path, "w") as handle:
            handle.write(raw)
        return path
    payload = {
        "job_id": "job_" + job_id,
        "pid": pid,
        "machine": MACHINE if machine is None else machine,
        "title": "T", "label": "L",
        "progress": progress, "counter": 1, "total": 10,
        "start_time": time.time(),
        "heartbeat": time.time() if heartbeat is None else heartbeat,
    }
    with open(path, "w") as handle:
        json.dump(payload, handle)
    return path


def rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def clean():
    """Start each case from an empty jobs dir.

    Without this, files from earlier cases linger and get re-reaped, which
    surfaces as a bogus failure attributed to the case under test.
    """
    jobs_dir = progress_jobs.get_jobs_dir()
    for name in os.listdir(jobs_dir):
        rm(os.path.join(jobs_dir, name))


def main():
    print("\n[1] torn write: file vanishes for ONE poll -> job must SURVIVE")
    print("    (DATA_FILE's write is remove-then-move, so this happens on every update)")
    clean()
    store = progress_jobs.JobStore()
    path = write_job("a")
    store.poll()
    rm(path)
    active, ended = store.poll()
    check("survives a single miss", ended == [] and len(active) == 1,
          "ended={} active={}".format(ended, len(active)))

    print("\n[2] real completion: file gone for TWO polls -> job must END")
    active, ended = store.poll()
    check("ends on the second consecutive miss", "job_a" in ended,
          "ended={}".format(ended))

    print("\n[3] half-written JSON -> keep last value, never end, never quarantine")
    clean()
    store = progress_jobs.JobStore()
    path = write_job("b", progress=42.0)
    store.poll()
    with open(path, "w") as handle:
        handle.write('{"job_id": "job_b", "progr')
    active, ended = store.poll()
    kept = active[0].get("progress") if active else None
    check("torn JSON does not end the job", ended == [], "ended={}".format(ended))
    check("torn JSON keeps last known progress", kept == 42.0, "got {}".format(kept))
    check("torn JSON file is NOT quarantined (inbox.py's instinct is wrong here)",
          os.path.exists(path))

    print("\n[4] dead pid on THIS machine -> job must END immediately")
    print("    AND its file must be deleted -- the owner is gone, so __exit__")
    print("    never ran and nothing else will ever clean it up.")
    clean()
    store = progress_jobs.JobStore()
    dead_file = write_job("c", pid=DEAD_PID)
    active, ended = store.poll()
    check("dead pid reaped on first poll", "job_c" in ended, "ended={}".format(ended))
    # Regression: the original implementation ended the job but left the file
    # on disk forever (sweep_orphans only runs at host startup). Caught by
    # dogfooding, not by this suite -- the old case checked only `ended`.
    check("dead job's FILE is deleted by poll, not just the strip",
          not os.path.exists(dead_file), "file survived poll()")

    print("\n[5] live pid -> job must NOT be reaped")
    clean()
    store = progress_jobs.JobStore()
    write_job("d", pid=LIVE_PID)
    active, ended = store.poll()
    check("live pid survives", ended == [] and len(active) == 1,
          "ended={} active={}".format(ended, len(active)))

    print("\n[6] FOREIGN machine -> pid liveness must NOT be trusted")
    print("    (a synced Dump folder can surface a foreign pid matching a live local one)")
    clean()
    store = progress_jobs.JobStore()
    write_job("e", pid=LIVE_PID, machine="SOME-OTHER-BOX")
    active, ended = store.poll()
    check("foreign-machine job not pid-reaped", ended == [], "ended={}".format(ended))

    print("\n[7] cold heartbeat -> the backstop must END it")
    clean()
    store = progress_jobs.JobStore()
    write_job("f", pid=LIVE_PID, machine="SOME-OTHER-BOX",
              heartbeat=time.time() - (progress_jobs.STALE_HEARTBEAT_SECONDS + 60))
    active, ended = store.poll()
    check("stale heartbeat reaped", "job_f" in ended, "ended={}".format(ended))

    print("\n[8] .tmp sibling must be ignored by the scan")
    clean()
    write_job("g")
    with open(os.path.join(progress_jobs.get_jobs_dir(),
                           "job_g.sexyDuck.tmp"), "w") as handle:
        handle.write("{garbage")
    files = progress_jobs.list_job_files()
    check("tmp sibling excluded",
          all(not f.endswith(".tmp") for f in files),
          str([os.path.basename(f) for f in files]))

    print("\n[9] sweep_orphans: reap dead, spare live, spare unreadable")
    clean()
    dead_path = write_job("h", pid=DEAD_PID)
    live_path = write_job("i", pid=LIVE_PID)
    torn_path = write_job("j", raw='{"job_id": "job_j", "pi')
    removed = progress_jobs.sweep_orphans()
    check("orphan swept", not os.path.exists(dead_path))
    check("live job spared", os.path.exists(live_path))
    check("unreadable file spared (may be mid-write)", os.path.exists(torn_path))
    check("sweep reported exactly 1 removal", removed == 1, "n={}".format(removed))

    print("\n" + ("ALL PASS" if not _FAILS else "FAILURES: " + ", ".join(_FAILS)))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
