"""EnneadTab Schedule Publisher

A sophisticated automation tool for managing EnneadTab's publishing cycle.
Features an advanced interactive GUI with animations, lighting effects,
and real-time status tracking of publish jobs.

Usage:
    Production scheduling uses Windows Task Scheduler (see DarkSide/publish/click me to setup publisher machine.bat).
    Each scheduled run executes one check/publish cycle and exits (--tick).

    python _schedule_publish.py              # Manual monitoring GUI (optional)
    python _schedule_publish.py --tick       # One headless cycle (Task Scheduler)
    python _schedule_publish.py --tick --force  # Same, but skip keyboard/mouse idle gate
    python _schedule_publish.py --console      # Legacy alias for --tick
    
Requirements:
    - Only publishes on a machine ENROLLED via DarkSide/publish/setup-publisher.ps1
      (this used to read 'Only runs on computer named "SZHANG"', which had been
      wrong through at least one machine migration -- the constant beside it said
      EANY-1X8MWP3. A stale pin that matches nothing fails silently.)
    - Pulls from main branch before each publish run
    - Requires internet connection for GitHub operations
"""

import os
import sys
import gc  # Garbage collection for long-running processes
import uuid
import tempfile
import queue as _queue_mod
import ctypes
from ctypes import wintypes
import shutil

# Fix Unicode encoding issues on Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'
    # Force stdout/stderr to use UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import time
import datetime
import subprocess
import traceback
import threading
import random
import math
import json
import socket
import tkinter as tk
from tkinter import ttk, font, messagebox
import winsound
try:
    import win32com.client  # For Windows Task Scheduler
except ImportError:
    win32com = None  # Fallback for systems without pywin32


# Constants
# Publisher eligibility is machine-local ENROLLMENT, not a committed hostname list.
# See publisher_enrollment.py for why (three pins that disagreed, one of them dead,
# read from two different hostname sources). Enroll with setup-publisher.ps1.
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "publish_history.json")
SCHEDULER_STATE_FILE = os.path.join(os.path.dirname(__file__), "scheduler_state.json")  # Persist scheduler state across restarts
PUBLISH_RUN_STATE_FILE = os.path.join(os.path.dirname(__file__), "publish_run_state.json")
HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), "scheduler_heartbeat.json")
LAST_TICK_RUN_FILE = os.path.join(os.path.dirname(__file__), "last_tick_run.txt")
TICK_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
TICK_LOG_FILE = os.path.join(TICK_LOG_DIR, "tick.log")
MAX_HISTORY_ENTRIES = 500  # Limit history to prevent unbounded growth
SCHEDULER_SCHEMA_VERSION = 1
STALE_PUBLISH_RUN_SEC = 600
STALE_TICK_SEC = 1800  # Kill tick processes stuck longer than 30 min (credential hang guard)
# Idle gate: only auto-publish when there is no keyboard/mouse activity.
# Office hours stay out of the user's way (longer idle required).
OFFICE_HOUR_START = 9   # local wall clock, inclusive
OFFICE_HOUR_END = 18    # local wall clock, exclusive (9:00–17:59)
IDLE_REQUIRED_SEC_OFFICE = 15 * 60  # 15 min no input during Mon–Fri office hours
IDLE_REQUIRED_SEC_OFF_HOURS = 5 * 60  # 5 min no input evenings / weekends
_SESSION_ID = str(uuid.uuid4())
_SINGLE_INSTANCE_MUTEX_HANDLE = None
_NO_QUEUE_LINE = object()
_SCHEDULER_COUNTERS = {
    "consecutive_check_errors": 0,
    "consecutive_pull_failures": 0,
    "consecutive_publish_failures": 0,
}
_BREAKERS = {}

_PUBLISH_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_PUBLISH_DIR, "..", ".."))


# Minimal "zen" grayscale UI
THEME_COLOR_PRIMARY = "#565b62"
THEME_COLOR_SECONDARY = "#5d6269"
THEME_COLOR_SUCCESS = "#6c7671"
THEME_COLOR_FAILURE = "#766d70"
THEME_COLOR_WARNING = "#7a7468"
THEME_COLOR_BACKGROUND = "#141618"
THEME_COLOR_CARD = "#1b1e21"
THEME_COLOR_ELEVATED = "#23272b"
THEME_COLOR_CANVAS = "#181b1f"
THEME_COLOR_TEXT = "#d0d4d8"
THEME_COLOR_TEXT_SECONDARY = "#a2a8af"
THEME_COLOR_TEXT_MUTED = "#828990"
THEME_COLOR_BORDER = "#2d3238"
THEME_COLOR_BORDER_FOCUS = "#3a4047"
THEME_COLOR_ACCENT = "#636a73"

# Animation constants
ANIMATION_SPEED = 16  # 60 FPS
GLOW_INTENSITY = 0.3
HOVER_SCALE = 1.05


def _acquire_single_instance_mutex():
    """Ensure only one publisher process runs (Windows named mutex). No-op elsewhere."""
    global _SINGLE_INSTANCE_MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE
    name = "Local\\EnneadTabSchedulePublisherMutex"
    handle = CreateMutexW(None, False, name)
    err = kernel32.GetLastError()
    if not handle:
        print("Failed to create single-instance mutex (error {})".format(err))
        return False
    if err == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        print("Another Schedule Publisher instance is already running. Exiting.")
        return False
    _SINGLE_INSTANCE_MUTEX_HANDLE = handle
    return True


def _atomic_write_json_file(path, data, indent=2):
    """Write JSON atomically (temp + fsync + replace)."""
    directory = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    fd, tmp_path = tempfile.mkstemp(prefix="._json_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


def _utc_now_iso():
    """UTC timestamp string for logs and heartbeat files."""
    try:
        return (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except AttributeError:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _log_json_event(level, event, **fields):
    """One-line JSON log for operators and log aggregators."""
    rec = {
        "ts": _utc_now_iso(),
        "level": level,
        "event": event,
        "session_id": _SESSION_ID,
        "pid": os.getpid(),
    }
    for k, v in fields.items():
        if v is not None:
            rec[k] = v
    try:
        print(json.dumps(rec, ensure_ascii=False))
    except Exception:
        print("[{}] {} {}".format(level, event, fields))


def write_tick_status(status, detail=None):
    """Human-readable last-run summary (Task Scheduler has no GUI)."""
    lines = [
        "Updated: {}".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "Status: {}".format(status),
    ]
    if detail:
        lines.append("Detail: {}".format(detail))
    lines.append("Log: {}".format(TICK_LOG_FILE))
    lines.append("Heartbeat: {}".format(HEARTBEAT_FILE))
    try:
        os.makedirs(TICK_LOG_DIR, exist_ok=True)
        with open(LAST_TICK_RUN_FILE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception as e:
        print("Failed to write tick status: {}".format(e))


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def get_user_idle_seconds():
    """Seconds since last keyboard/mouse input (Windows GetLastInputInfo)."""
    if sys.platform != "win32":
        return float("inf")
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # GetTickCount wraps ~49.7 days; unsigned subtraction handles wrap.
    millis = wintypes.DWORD(
        ctypes.windll.kernel32.GetTickCount() - info.dwTime
    ).value
    return millis / 1000.0


def is_office_hours(now=None):
    """True Mon–Fri during local office hours (busy interactive use expected)."""
    now = now or datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    return OFFICE_HOUR_START <= now.hour < OFFICE_HOUR_END


def required_idle_seconds(now=None):
    """Idle requirement: longer during office hours, shorter evenings/weekends."""
    if is_office_hours(now):
        return IDLE_REQUIRED_SEC_OFFICE
    return IDLE_REQUIRED_SEC_OFF_HOURS


def check_user_idle_for_publish():
    """
    Gate auto-publish on real user inactivity (keyboard/mouse).

    Returns (ok, detail). When ok is False, the tick must exit without
    pulling or publishing so it does not fight office-hour interactive work.
    """
    idle_sec = get_user_idle_seconds()
    need_sec = required_idle_seconds()
    office = is_office_hours()
    window = "office hours" if office else "off-hours"
    detail = (
        "user idle {idle:.0f}s; need {need}s ({window}, {start:02d}:00-{end:02d}:00 Mon-Fri)".format(
            idle=idle_sec,
            need=need_sec,
            window=window,
            start=OFFICE_HOUR_START,
            end=OFFICE_HOUR_END,
        )
    )
    if idle_sec < need_sec:
        return False, detail
    return True, detail


def write_heartbeat_file(**fields):
    """Durable heartbeat for external watchdogs."""
    base = {
        "ts_utc": _utc_now_iso(),
        "session_id": _SESSION_ID,
        "pid": os.getpid(),
        "machine": socket.gethostname(),
    }
    base.update(fields)
    try:
        _atomic_write_json_file(HEARTBEAT_FILE, base, indent=2)
    except Exception as e:
        print("Heartbeat write failed: {}".format(e))


def _breaker_should_block(op_key):
    b = _BREAKERS.get(op_key)
    if not b:
        return False, None
    until = b.get("open_until")
    if until and time.time() < until:
        return True, until
    return False, until


def _breaker_failure(op_key):
    b = _BREAKERS.setdefault(op_key, {"fails": 0, "open_until": None, "opens": 0})
    b["fails"] += 1
    if b["fails"] < 5:
        return
    b["opens"] += 1
    cool = min(900 * (2 ** min(b["opens"] - 1, 2)), 3600)
    b["open_until"] = time.time() + cool
    b["fails"] = 0
    _log_json_event("warn", "circuit_open", operation=op_key, cooldown_sec=cool)


def _breaker_success(op_key):
    b = _BREAKERS.get(op_key)
    if not b:
        return
    b["fails"] = 0
    b["open_until"] = None


def _sleep_jitter_backoff(attempt_1based, base=2.0, cap=120.0):
    delay = min(base * (2 ** (attempt_1based - 1)), cap)
    time.sleep(random.uniform(0, delay))


def _stderr_retryable(text):
    if not text:
        return True
    t = text.lower()
    non_retry = (
        "permission denied",
        "authentication failed",
        "could not read from remote repository",
        "repository not found",
        "fatal: refusing to merge",
        "merge conflict",
        "your local changes",
        "not a git repository",
    )
    for s in non_retry:
        if s in t:
            return False
    return True


def _git_subprocess_env():
    """Headless git env: fail fast instead of blocking on missing creds or GUI prompts."""
    env = os.environ.copy()
    for key in list(env.keys()):
        if key == "GIT_CONFIG_COUNT" or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    return env


def subprocess_run_with_retry(
    args,
    cwd,
    timeout,
    attempts=5,
    capture_output=True,
    text=True,
    op_key="git",
    env=None,
):
    """Run git subprocess with jittered backoff; integrates circuit breaker."""
    run_env = _git_subprocess_env()
    if env:
        run_env.update(env)
    last_result = None
    for attempt in range(1, attempts + 1):
        blocked, _ = _breaker_should_block(op_key)
        if blocked:
            raise RuntimeError("circuit_open:{}".format(op_key))
        try:
            r = subprocess.run(
                args,
                cwd=cwd,
                timeout=timeout,
                capture_output=capture_output,
                text=text,
                env=run_env,
            )
            last_result = r
            if r.returncode == 0:
                _breaker_success(op_key)
                return r
            stderr = (r.stderr or "") if capture_output else ""
            if not _stderr_retryable(stderr):
                _breaker_failure(op_key)
                return r
        except subprocess.TimeoutExpired:
            if attempt == attempts:
                _breaker_failure(op_key)
                raise
        except Exception:
            if attempt == attempts:
                _breaker_failure(op_key)
                raise
        if attempt < attempts:
            _sleep_jitter_backoff(attempt)
    if last_result is not None:
        _breaker_failure(op_key)
    return last_result


def _recover_stale_publish_run_state():
    """If a publish was marked running and process crashed, clear stale marker."""
    if not os.path.exists(PUBLISH_RUN_STATE_FILE):
        return
    try:
        with open(PUBLISH_RUN_STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
        if st.get("phase") != "running":
            return
        started = st.get("started_at")
        if not started:
            return
        t0 = datetime.datetime.fromisoformat(started)
        if (datetime.datetime.now() - t0).total_seconds() <= STALE_PUBLISH_RUN_SEC:
            return
        _log_json_event(
            "warn",
            "recovered_stale_publish_run",
            run_id=st.get("run_id"),
            started_at=started,
        )
        _atomic_write_json_file(
            PUBLISH_RUN_STATE_FILE,
            {
                "phase": "idle",
                "recovered_at": datetime.datetime.now().isoformat(),
                "note": "recovered_stale_running_marker",
            },
            indent=2,
        )
    except Exception as e:
        print("publish_run_state recovery skipped: {}".format(e))


def mark_publish_run_started(run_id, mode):
    global _pending_commit_messages
    snap = list(_pending_commit_messages) if _pending_commit_messages else []
    _atomic_write_json_file(
        PUBLISH_RUN_STATE_FILE,
        {
            "phase": "running",
            "run_id": run_id,
            "started_at": datetime.datetime.now().isoformat(),
            "mode": mode,
            "pending_commit_messages": snap,
        },
        indent=2,
    )


def mark_publish_run_finished(success, error_reason=None):
    payload = {
        "phase": "idle",
        "finished_at": datetime.datetime.now().isoformat(),
        "last_success": bool(success),
        "last_error": (error_reason or "")[:500] if error_reason else None,
    }
    if success:
        os_sha = get_local_head_sha()
        if os_sha:
            payload["os_sha"] = os_sha
    _atomic_write_json_file(
        PUBLISH_RUN_STATE_FILE,
        payload,
        indent=2,
    )


def _popen_stdout_reader(pipe, out_queue, stop_event):
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            line = pipe.readline()
            if line == "":
                break
            out_queue.put(line)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass
        out_queue.put(None)


def _pid_is_alive(pid):
    """Return True if pid is still running (Windows OpenProcess probe)."""
    if not pid or sys.platform != "win32":
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _kill_process_tree(pid):
    """Force-kill a process tree on Windows."""
    if not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass


def _recover_stale_tick_lock():
    """If a prior tick hung (e.g. git credential prompt), clear it before we start."""
    if not os.path.exists(HEARTBEAT_FILE):
        return
    try:
        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as fh:
            hb = json.load(fh)
    except Exception:
        return

    state = (hb.get("state") or "").lower()
    if state not in ("checking", "running", "publishing", "pulling"):
        return

    stale_pid = hb.get("pid")
    stale = False
    ts_raw = hb.get("ts_utc")
    if ts_raw:
        try:
            ts = datetime.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            age = (datetime.datetime.utcnow() - ts).total_seconds()
            if age > STALE_TICK_SEC:
                stale = True
        except Exception:
            pass

    if stale_pid and not _pid_is_alive(stale_pid):
        stale = True

    if not stale:
        return

    note = "recovered_stale_tick pid={} state={}".format(stale_pid, state)
    print("WARNING: {}".format(note))
    _log_json_event("warn", "recovered_stale_tick", pid=stale_pid, state=state)
    if stale_pid and _pid_is_alive(stale_pid):
        _kill_process_tree(stale_pid)
    try:
        write_heartbeat_file(
            state="recovered",
            note=note,
            recovered_pid=stale_pid,
            consecutive_check_errors=0,
            consecutive_publish_failures=0,
            consecutive_pull_failures=0,
        )
    except Exception:
        pass


def _warn_if_gh_auth_missing():
    """Surface missing GitHub CLI auth before fetch fails opaquely."""
    gh = os.path.join(os.path.expanduser("~"), "gh-cli", "bin", "gh.exe")
    if not os.path.isfile(gh):
        return
    try:
        r = subprocess.run(
            [gh, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_git_subprocess_env(),
        )
    except Exception:
        return
    if r.returncode == 0:
        return
    print(
        "WARNING: GitHub CLI is not authenticated. "
        "Run once on this PC: {} auth login".format(gh)
    )


def _terminate_publish_process_tree(proc):
    """Terminate publish child; escalate to kill and taskkill /T on Windows."""
    if proc.poll() is not None:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        return
    try:
        proc.terminate()
    except Exception:
        pass
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            return
        time.sleep(0.2)
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=15)
    except Exception:
        pass
    if sys.platform == "win32" and getattr(proc, "pid", None):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            pass


def check_for_new_commits():
    """
    Check if there are new commits on remote without pulling.
    This is a lightweight check to determine if publish is needed.
    
    Returns:
        tuple: (has_new_commits, error_message, commit_messages) where:
            - has_new_commits: bool indicating if remote has new commits
            - error_message: str with error details if check failed, None otherwise
            - commit_messages: list of commit messages if new commits found, empty list otherwise
    """
    try:
        # Get repository root directory
        repo_dir = _REPO_ROOT
        
        # Fetch latest refs (this updates remote tracking branches without merging)
        try:
            fetch_result = subprocess_run_with_retry(
                [get_git_executable(), "fetch", "origin", "main"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=60 * 2,
                attempts=5,
                op_key="git_fetch_check",
            )
        except RuntimeError as e:
            if "circuit_open" in str(e):
                return False, "Git fetch paused (circuit breaker cooldown)", []
            raise
        except subprocess.TimeoutExpired:
            return False, "Timeout checking for new commits (fetch)", []
        
        if fetch_result is None or fetch_result.returncode != 0:
            err = fetch_result.stderr.strip() if fetch_result and fetch_result.stderr else "fetch failed"
            return False, "Failed to fetch from remote: {}".format(err), []
        
        # Get local HEAD commit hash
        local_head_result = subprocess.run(
            [get_git_executable(), "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if local_head_result.returncode != 0:
            return False, "Failed to get local HEAD: {}".format(local_head_result.stderr.strip()), []
        
        local_head = local_head_result.stdout.strip()
        
        # Get remote tracking branch HEAD (origin/main)
        remote_head_result = subprocess.run(
            [get_git_executable(), "rev-parse", "origin/main"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if remote_head_result.returncode != 0:
            return False, "Failed to get remote HEAD: {}".format(remote_head_result.stderr.strip()), []
        
        remote_head = remote_head_result.stdout.strip()
        
        # Check if remote is ahead
        if remote_head == local_head:
            return False, None, []  # No new commits
        
        # Check if remote is actually ahead (not just diverged)
        merge_base_result = subprocess.run(
            [get_git_executable(), "merge-base", local_head, remote_head],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Get commit messages for new commits
        commit_messages = []
        log_result = subprocess.run(
            [get_git_executable(), "log", "--format=%s", "{}..{}".format(local_head, remote_head)],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if log_result.returncode == 0 and log_result.stdout.strip():
            # Parse commit messages (one per line)
            commit_messages = [msg.strip() for msg in log_result.stdout.strip().split('\n') if msg.strip()]
        
        if merge_base_result.returncode == 0:
            merge_base = merge_base_result.stdout.strip()
            # If merge base is local HEAD, remote is ahead
            if merge_base == local_head:
                return True, None, commit_messages  # Remote has new commits
            else:
                # Diverged - check if remote has commits we don't have
                if commit_messages:
                    return True, None, commit_messages  # Remote has commits we don't have
                return False, None, []  # Diverged, but remote not ahead
        else:
            # If we can't determine merge base, check if remote has commits we don't have
            if commit_messages:
                return True, None, commit_messages  # Remote has commits we don't have
            return False, "Could not determine if remote is ahead", []
        
    except subprocess.TimeoutExpired:
        return False, "Timeout checking for new commits", []
    except Exception as e:
        return False, "Error checking for new commits: {}".format(str(e)), []


def get_local_head_sha():
    """Return full SHA of local HEAD, or None on failure."""
    try:
        result = subprocess.run(
            [get_git_executable(), "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print("Note: could not read local HEAD: {}".format(e))
    return None


def get_head_commit_datetime(sha=None):
    """Return commit datetime for sha (default HEAD), or None."""
    ref = sha or "HEAD"
    try:
        result = subprocess.run(
            [get_git_executable(), "log", "-1", "--format=%ct", ref],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return datetime.datetime.fromtimestamp(int(result.stdout.strip()))
    except Exception as e:
        print("Note: could not read commit time for {}: {}".format(ref, e))
    return None


def _get_commit_messages_between(from_sha, to_sha):
    """Return subject lines for commits reachable from to_sha but not from_sha."""
    if not from_sha or not to_sha or from_sha == to_sha:
        return []
    try:
        result = subprocess.run(
            [
                get_git_executable(),
                "log",
                "--format=%s",
                "{}..{}".format(from_sha, to_sha),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [
                msg.strip()
                for msg in result.stdout.strip().split("\n")
                if msg.strip()
            ]
    except Exception as e:
        print("Note: could not list commits {}..{}: {}".format(from_sha[:8], to_sha[:8], e))
    return []


def _bootstrap_last_published_os_sha():
    """
    Infer last published OS SHA from publish_run_state when scheduler state has none.
    Uses git rev-list --before the last successful publish finish time.
    """
    if not os.path.exists(PUBLISH_RUN_STATE_FILE):
        return None
    try:
        with open(PUBLISH_RUN_STATE_FILE, "r", encoding="utf-8") as f:
            prs = json.load(f)
        if not prs.get("last_success"):
            return None
        if prs.get("os_sha"):
            return str(prs["os_sha"])
        finished = prs.get("finished_at")
        if not finished:
            return None
        finished_dt = datetime.datetime.fromisoformat(finished)
        before_arg = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
        result = subprocess.run(
            [
                get_git_executable(),
                "rev-list",
                "-1",
                "--before={}".format(before_arg),
                "HEAD",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print("Note: could not bootstrap last_published_os_sha: {}".format(e))
    return None


def check_os_dist_drift():
    """
    Detect OS commits on local HEAD that have not been published to dist yet.

    Unlike check_for_new_commits(), this catches commits made and pushed from the
    publisher machine itself (local HEAD == origin/main but dist is stale).

    Returns:
        tuple: (has_drift, commit_messages)
    """
    global _last_published_os_sha
    head = get_local_head_sha()
    if not head:
        return False, []
    if not _last_published_os_sha:
        return False, []
    if head == _last_published_os_sha:
        return False, []

    messages = _get_commit_messages_between(_last_published_os_sha, head)
    if not messages:
        messages = ["Unpublished OS commit(s) since {}".format(_last_published_os_sha[:8])]
    return True, messages


def _note_last_published_os_sha(sha=None):
    """Persist OS HEAD as last successfully published commit."""
    global _last_published_os_sha
    resolved = sha or get_local_head_sha()
    if not resolved:
        return
    _last_published_os_sha = resolved
    save_scheduler_state()
    print("Recorded last_published_os_sha: {}".format(resolved[:12]))


# Global state for adaptive checking
_last_new_commit_time = None
_last_commit_detected_time = None  # When we last detected new commits
_pending_commit_messages = []  # Commit messages for pending publish
_last_published_os_sha = None  # OS repo HEAD last successfully published to dist
_ACTIVE_MODE_DURATION = 3600  # 1 hour in seconds
_ACTIVE_CHECK_INTERVAL = 10 * 60  # 10 minutes when active (frequent checking)
_STABILITY_WAIT_TIME = 3600  # Wait 1 hour after last commit before publishing (stability check)
# Strategy: Check frequently when active, but only publish after commit wave stabilizes (no commits for 1 hour)

def load_scheduler_state():
    """Load scheduler state from disk to persist across restarts."""
    global _last_new_commit_time, _last_commit_detected_time, _pending_commit_messages
    global _last_published_os_sha
    _last_new_commit_time = None
    _last_commit_detected_time = None
    _pending_commit_messages = []
    _last_published_os_sha = None

    paths = []
    if os.path.exists(SCHEDULER_STATE_FILE):
        paths.append(SCHEDULER_STATE_FILE)
    bak_path = SCHEDULER_STATE_FILE + ".bak"
    if os.path.exists(bak_path):
        paths.append(bak_path)

    state = None
    last_error = None
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            break
        except Exception as e:
            last_error = e
            state = None
            continue

    if state is None:
        if last_error:
            print("⚠️ Failed to load scheduler state: {}".format(str(last_error)))
        return

    if not isinstance(state, dict):
        print("⚠️ Invalid scheduler state structure")
        return

    msgs = state.get("pending_commit_messages", [])
    if msgs is None:
        msgs = []
    if not isinstance(msgs, list):
        msgs = []
    _pending_commit_messages = [str(x) for x in msgs if x is not None]

    try:
        if state.get("last_new_commit_time"):
            _last_new_commit_time = datetime.datetime.fromisoformat(state["last_new_commit_time"])
        if state.get("last_commit_detected_time"):
            _last_commit_detected_time = datetime.datetime.fromisoformat(state["last_commit_detected_time"])
        if state.get("last_published_os_sha"):
            _last_published_os_sha = str(state["last_published_os_sha"])
    except Exception as e:
        print("⚠️ Bad timestamps in scheduler state: {}".format(e))
        _last_new_commit_time = None
        _last_commit_detected_time = None

    if not _last_published_os_sha:
        boot = _bootstrap_last_published_os_sha()
        if boot:
            _last_published_os_sha = boot
            print("Bootstrapped last_published_os_sha: {}".format(boot[:12]))
            save_scheduler_state()

    print("✅ Loaded scheduler state from disk")
    if _last_published_os_sha:
        head = get_local_head_sha()
        if head and head != _last_published_os_sha:
            print(
                "   Unpublished OS commits since last dist publish ({})".format(
                    _last_published_os_sha[:12]
                )
            )
    if _last_commit_detected_time:
        time_since = (datetime.datetime.now() - _last_commit_detected_time).total_seconds()
        print("   Last commit detected: {} min ago".format(int(time_since / 60)))

def save_scheduler_state():
    """Save scheduler state to disk to persist across restarts."""
    global _last_new_commit_time, _last_commit_detected_time, _pending_commit_messages
    global _last_published_os_sha
    try:
        state = {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "last_new_commit_time": _last_new_commit_time.isoformat() if _last_new_commit_time else None,
            "last_commit_detected_time": _last_commit_detected_time.isoformat() if _last_commit_detected_time else None,
            "pending_commit_messages": _pending_commit_messages,
            "last_published_os_sha": _last_published_os_sha,
        }
        if os.path.exists(SCHEDULER_STATE_FILE):
            try:
                shutil.copy2(SCHEDULER_STATE_FILE, SCHEDULER_STATE_FILE + ".bak")
            except Exception:
                pass
        _atomic_write_json_file(SCHEDULER_STATE_FILE, state, indent=2)
    except Exception as e:
        print("⚠️ Failed to save scheduler state: {}".format(str(e)))

def get_next_pull_check_time(force_active_mode=False):
    """
    Calculate the next time to check for new commits with adaptive frequency.
    
    Adaptive behavior:
    - Normal mode (no recent activity): Less frequent checks
      - Weekdays 10 AM-7 PM: every 2 hours
      - Weekdays other times: every 4 hours
      - Weekends: every 8 hours
    - Active mode (new commits detected): More frequent checks, but holds publish
      - Every 10 minutes when active (frequent monitoring)
      - Detects new commits but waits for stability before publishing
      - Only publishes after 1 hour of no new commits (commit wave stabilized)
      - Timer resets whenever new commits are detected
      - This prevents publishing unstable first commits, waits for fixes
    
    Args:
        force_active_mode (bool): Force active mode (used when new commits detected)
    
    Returns:
        datetime.datetime: Next pull check time
    """
    global _last_new_commit_time
    
    now = datetime.datetime.now()
    
    # Check if we're in active mode (new commits detected in last hour)
    in_active_mode = False
    if _last_new_commit_time is not None:
        time_since_last_commit = (now - _last_new_commit_time).total_seconds()
        if time_since_last_commit < _ACTIVE_MODE_DURATION:
            in_active_mode = True
    
    # Force active mode if requested (new commits just detected)
    if force_active_mode:
        _last_new_commit_time = now
        in_active_mode = True
    
    if in_active_mode:
        # Active mode: check every 10 minutes (frequent monitoring while waiting for stability)
        next_check = now + datetime.timedelta(seconds=_ACTIVE_CHECK_INTERVAL)
        # Round to nearest minute for cleaner scheduling
        next_check = next_check.replace(second=0, microsecond=0)
        return next_check
    
    # Normal mode: less frequent checks
    weekday = now.weekday()  # Monday is 0, Sunday is 6
    hour = now.hour
    is_weekend = weekday >= 5  # Saturday=5, Sunday=6
    
    if is_weekend:
        # Weekends: check every 8 hours
        interval_hours = 8
    elif 10 <= hour < 19:  # Weekdays 10 AM to 7 PM
        # Business hours: check every 2 hours
        interval_hours = 2
    else:
        # Other weekday times: check every 4 hours
        interval_hours = 4
    
    # Calculate next check time
    next_check = now + datetime.timedelta(hours=interval_hours)
    # Round to nearest hour for cleaner scheduling
    next_check = next_check.replace(minute=0, second=0, microsecond=0)
    
    return next_check

def reset_active_mode():
    """Reset active mode (call when no new commits found for extended period)"""
    global _last_new_commit_time, _last_commit_detected_time, _pending_commit_messages
    _last_new_commit_time = None
    _last_commit_detected_time = None
    _pending_commit_messages = []
    save_scheduler_state()  # Persist the reset

def get_next_scheduled_time():
    """
    Calculate the next scheduled publish time based on current time and day.
    
    NOTE: This is now used as a fallback. The scheduler primarily uses
    pull checks (get_next_pull_check_time) and only publishes when
    new commits are detected.
    
    Rules:
    - Weekdays: once at noon (12:00 PM) and once at midnight (12:00 AM)
    - Weekends: once at midnight (12:00 AM) only
    
    Returns:
        datetime.datetime: Next scheduled publish time
    """
    now = datetime.datetime.now()
    weekday = now.weekday()  # Monday is 0, Sunday is 6
    is_weekend = weekday >= 5  # Saturday=5, Sunday=6
    
    # Get today's noon and midnight
    today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get tomorrow's midnight
    tomorrow = now + datetime.timedelta(days=1)
    tomorrow_midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if is_weekend:
        # Weekends: only midnight
        if now < today_midnight:
            # Before midnight today, schedule for today's midnight
            return today_midnight
        else:
            # After midnight today, schedule for tomorrow's midnight
            return tomorrow_midnight
    else:
        # Weekdays: noon and midnight
        if now < today_noon:
            # Before noon today, schedule for today's noon
            return today_noon
        elif now < today_midnight:
            # After noon but before midnight, schedule for today's midnight
            return today_midnight
        else:
            # After midnight, schedule for tomorrow's noon
            tomorrow_noon = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
            return tomorrow_noon

def check_computer_name_for_pull_by_self():
    """
    Verify that THIS machine is enrolled as the publisher.

    Was a committed hostname allowlist; is now a machine-local enrollment marker,
    so moving the publisher is an operation (run setup-publisher.ps1 there,
    teardown-publisher.ps1 here) rather than a source edit. Fails closed.

    Returns:
        bool: True if this machine is enrolled to auto-pull and auto-publish
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import publisher_enrollment
    finally:
        if sys.path and sys.path[0] == os.path.dirname(os.path.abspath(__file__)):
            sys.path.pop(0)

    if not publisher_enrollment.is_enrolled():
        print("This machine is not enrolled as the EnneadTab publisher, so it will not")
        print("pull or publish. {}".format(publisher_enrollment.describe()))
        print("To enroll it, run: DarkSide/publish/setup-publisher.ps1")
        return False

    print("Publisher enrollment OK: {}".format(publisher_enrollment.describe()))
    return True

def get_git_executable():
    """Get the full path to git executable."""
    git_paths = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "bin", "git.exe"),
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\bin\git.exe"
    ]
    
    for git_path in git_paths:
        if os.path.exists(git_path):
            return git_path
    
    # Fallback to just 'git' if none found
    return "git"

def _clear_exe_products_junction_for_git(repo_dir):
    """Remove local ExeProducts junction/untracked tree so git merge is not blocked."""
    exe_dir = os.path.join(repo_dir, "Apps", "lib", "ExeProducts")
    if not os.path.exists(exe_dir):
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "rmdir", exe_dir],
                cwd=repo_dir,
                timeout=30,
                capture_output=True,
            )
        else:
            shutil.rmtree(exe_dir)
        print("Removed local ExeProducts link before git pull (restored after publish if needed)")
    except Exception as e:
        print("Note: could not remove ExeProducts before pull: {}".format(e))


def git_pull_main():
    """
    Pull latest changes from main branch with intelligent conflict resolution.
    First attempts to merge, then falls back to reset if conflicts can't be resolved.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get repository root directory
        repo_dir = _REPO_ROOT

        _clear_exe_products_junction_for_git(repo_dir)
        
        print("Pulling latest changes from main branch on repo {}...".format(os.path.basename(repo_dir)))
        
        # First fetch to get latest changes
        try:
            fetch_run = subprocess_run_with_retry(
                [get_git_executable(), "fetch", "origin", "main"],
                cwd=repo_dir,
                timeout=60 * 5,
                attempts=5,
                op_key="git_fetch_pull",
            )
        except RuntimeError as e:
            if "circuit_open" in str(e):
                print("Git fetch skipped (circuit breaker cooldown)")
            else:
                print("Git fetch error: {}".format(e))
            return False
        except subprocess.TimeoutExpired:
            print("Git fetch timed out")
            return False

        if fetch_run is None or fetch_run.returncode != 0:
            code = fetch_run.returncode if fetch_run else -1
            print("Git fetch failed with exit code {}".format(code))
            return False
        
        # Check if we have any uncommitted changes
        status_result = subprocess.run(
            [get_git_executable(), "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        has_changes = bool(status_result.stdout.strip())

        # Skip commit if only non-essential state files changed
        if has_changes:
            changed_files = [line.split()[-1] for line in status_result.stdout.strip().splitlines() if line.strip()]
            non_essential = {
                "DarkSide/publish/publish_history.json",
                "DarkSide/publish/scheduler_state.json",
                "DarkSide/publish/scheduler_state.json.bak",
                "DarkSide/publish/publish_run_state.json",
                "DarkSide/publish/scheduler_heartbeat.json",
            }
            if all(f in non_essential for f in changed_files):
                print("Only publish_history/scheduler_state changed, skipping temp commit")
                has_changes = False

        if has_changes:
            print("Local changes detected, attempting to preserve them...")
            
            # Stage all changes for potential commit
            add_result = subprocess.call(
                [get_git_executable(), "add", "."],
                cwd=repo_dir,
                timeout=60
            )
            
            if add_result != 0:
                print("Failed to stage changes, falling back to reset")
                return _fallback_reset(repo_dir)
            
            # Create a temporary commit to preserve changes
            temp_commit_result = subprocess.call(
                [get_git_executable(), "commit", "-m", "Temp commit before merge - AutoDist {}".format(
                    datetime.datetime.now().strftime("%Y%m%d %H%M%S"))],
                cwd=repo_dir,
                timeout=60
            )
            
            if temp_commit_result != 0:
                print("Failed to create temp commit, falling back to reset")
                return _fallback_reset(repo_dir)
        
        # Attempt to merge origin/main
        print("Attempting to merge origin/main...")
        merge_result = subprocess.call(
            [get_git_executable(), "merge", "origin/main", "--no-edit"],
            cwd=repo_dir,
            timeout=60*5
        )
        
        if merge_result == 0:
            print("Git merge successful.")
            return True
        else:
            print("Git merge failed with exit code {}, checking for conflicts...".format(merge_result))
            
            # Check if it's a merge conflict
            conflict_check = subprocess.run(
                [get_git_executable(), "status", "--porcelain"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if "UU" in conflict_check.stdout or "AA" in conflict_check.stdout:
                print("Merge conflicts detected, attempting automatic resolution...")
                
                # Try to resolve conflicts automatically by preferring remote changes
                resolve_result = subprocess.call(
                    [get_git_executable(), "checkout", "--theirs", "."],
                    cwd=repo_dir,
                    timeout=60
                )
                
                if resolve_result == 0:
                    # Add resolved files
                    add_resolved = subprocess.call(
                        [get_git_executable(), "add", "."],
                        cwd=repo_dir,
                        timeout=60
                    )
                    
                    if add_resolved == 0:
                        # Complete the merge with automatic commit
                        complete_merge = subprocess.call(
                            [get_git_executable(), "commit", "--no-edit"],
                            cwd=repo_dir,
                            timeout=60
                        )
                        
                        if complete_merge == 0:
                            print("Merge conflicts resolved automatically, merge commit created.")
                            return True
                
                print("Automatic conflict resolution failed, falling back to reset")
            
            # If merge failed for other reasons or conflict resolution failed, fall back to reset
            return _fallback_reset(repo_dir)
            
    except subprocess.TimeoutExpired:
        print("Git operation timed out")
        return False
    except Exception:
        print("Error during git pull:")
        print(traceback.format_exc())
        return False

def _fallback_reset(repo_dir):
    """
    Fallback function to reset to origin/main, discarding local changes.
    
    Args:
        repo_dir (str): Repository directory path
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        print("Falling back to reset strategy, discarding local changes...")
        
        # Abort any ongoing merge
        subprocess.call(
            [get_git_executable(), "merge", "--abort"],
            cwd=repo_dir,
            timeout=60
        )
        
        # Clean untracked files and directories
        clean_result = subprocess.call(
            [get_git_executable(), "clean", "-fd"],  # -f: force, -d: include directories
            cwd=repo_dir,
            timeout=60*5
        )
        
        if clean_result != 0:
            print("Git clean failed with exit code {}".format(clean_result))
            return False
            
        # Reset to origin/main to ensure clean state
        reset_result = subprocess.call(
            [get_git_executable(), "reset", "--hard", "origin/main"],
            cwd=repo_dir,
            timeout=60*5
        )
        
        if reset_result == 0:
            print("Git reset successful.")
            return True
        else:
            print("Git reset failed with exit code {}".format(reset_result))
            return False
            
    except subprocess.TimeoutExpired:
        print("Git reset operation timed out")
        return False
    except Exception:
        print("Error during git reset fallback:")
        print(traceback.format_exc())
        return False

class ParticleEffect:
    """Animated particle system for visual feedback effects.

    This class creates and manages a system of particles that can be used
    to provide visual feedback for various events in the GUI.

    Attributes:
        canvas (tk.Canvas): The canvas to draw particles on
        x (int): Initial x-coordinate for particle system
        y (int): Initial y-coordinate for particle system
        color (str): Base color for particles in hex format
        count (int): Number of particles to create
        is_success (bool): Whether this is a success or failure effect
    """
    
    def __init__(self, canvas, x, y, color, count=20, is_success=True):
        self.canvas = canvas
        self.particles = []
        self.is_alive = True
        self.frames = 0
        
        try:
            for _ in range(count):
                speed = random.uniform(2, 8)
                angle = random.uniform(0, 2 * math.pi)
                size = random.randint(2, 8)
                life = random.randint(20, 40)
                
                # Create particle with velocity vector
                particle = {
                    'id': None,
                    'x': x,
                    'y': y,
                    'vx': math.cos(angle) * speed,
                    'vy': math.sin(angle) * speed,
                    'size': size,
                    'color': color,
                    'life': life,
                    'original_life': life,
                    'rotation': random.uniform(0, 360)
                }
                
                # Create either circle or star shape
                if is_success:
                    shape = self._create_star_particle(particle)
                else:
                    shape = self._create_circle_particle(particle)
                    
                particle['id'] = shape
                self.particles.append(particle)
        except Exception as e:
            print("Error creating particle effect: {}".format(str(e)))
            self.is_alive = False
    
    def _create_star_particle(self, particle):
        """Create a star-shaped particle"""
        try:
            size = particle['size']
            x, y = particle['x'], particle['y']
            points = []
            
            # 5-point star
            for i in range(10):
                angle = math.pi/5 * i
                radius = size if i % 2 == 0 else size/2
                points.append(x + radius * math.cos(angle))
                points.append(y + radius * math.sin(angle))
                
            return self.canvas.create_polygon(points, fill=particle['color'], outline="")
        except Exception as e:
            print("Error creating star particle: {}".format(str(e)))
            return None
    
    def _create_circle_particle(self, particle):
        """Create a circular particle"""
        try:
            size = particle['size']
            x, y = particle['x'], particle['y']
            return self.canvas.create_oval(x-size, y-size, x+size, y+size, fill=particle['color'], outline="")
        except Exception as e:
            print("Error creating circle particle: {}".format(str(e)))
            return None
    
    def update(self):
        """Update all particles in the system"""
        if not self.is_alive:
            return False
            
        try:
            self.frames += 1
            still_alive = False
            
            for p in self.particles:
                if p['life'] <= 0:
                    if p['id']:
                        try:
                            self.canvas.delete(p['id'])
                            p['id'] = None
                        except Exception:
                            p['id'] = None
                    continue
                    
                still_alive = True
                p['life'] -= 1
                opacity = p['life'] / p['original_life']
                
                # Apply physics
                p['x'] += p['vx']
                p['y'] += p['vy']
                p['vy'] += 0.2  # gravity
                
                # Slow down over time
                p['vx'] *= 0.95
                p['vy'] *= 0.95
                
                # Update visuals
                p['rotation'] += 5
                
                # Delete and recreate with new position and opacity-adjusted color
                if p['id']:
                    try:
                        self.canvas.delete(p['id'])
                    except Exception:
                        pass
                
                color = self._adjust_color_opacity(p['color'], opacity)
                
                try:
                    if "star" in str(p['id']):
                        p['id'] = self._create_star_particle(p)
                    else:
                        p['id'] = self._create_circle_particle(p)
                        
                    if p['id']:
                        self.canvas.itemconfig(p['id'], fill=color)
                except Exception as e:
                    print("Error updating particle: {}".format(str(e)))
            
            self.is_alive = still_alive
            return still_alive
        except Exception as e:
            print("Error in particle effect update: {}".format(str(e)))
            self.is_alive = False
            return False
    
    def _adjust_color_opacity(self, hex_color, opacity):
        """Adjust color with opacity"""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            
            return "#{:02x}{:02x}{:02x}".format(r, g, b)
        except Exception:
            return hex_color

class ToolTip:
    """Tooltip widget for showing helpful information on hover.
    
    A lightweight tooltip that appears when the mouse hovers over a widget
    and disappears when the mouse leaves or after a timeout.
    """
    
    def __init__(self, widget, text="", delay=500, wraplength=250):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self.tooltip_window = None
        self.id = None
        self.x = self.y = 0
        
        # Bind events
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)
        self.widget.bind("<Motion>", self._on_motion)
    
    def _on_enter(self, event=None):
        """Mouse entered widget"""
        self._schedule_tooltip()
    
    def _on_leave(self, event=None):
        """Mouse left widget"""
        self._cancel_tooltip()
        self._hide_tooltip()
    
    def _on_motion(self, event=None):
        """Mouse moved within widget"""
        if event:
            self.x, self.y = event.x_root, event.y_root
    
    def _schedule_tooltip(self):
        """Schedule tooltip to appear after delay"""
        self._cancel_tooltip()
        self.id = self.widget.after(self.delay, self._show_tooltip)
    
    def _cancel_tooltip(self):
        """Cancel scheduled tooltip"""
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
    
    def _show_tooltip(self):
        """Show the tooltip window"""
        if self.tooltip_window or not self.text:
            return
        
        # Create tooltip window
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        
        # Position tooltip
        x = self.x + 10
        y = self.y + 10
        
        # Adjust position to keep tooltip on screen
        screen_width = tw.winfo_screenwidth()
        screen_height = tw.winfo_screenheight()
        
        # Create a temporary label to measure text size
        temp_label = tk.Label(tw, text=self.text, font=("Segoe UI", 10), 
                             bg=THEME_COLOR_CARD, fg=THEME_COLOR_TEXT,
                             wraplength=self.wraplength, justify=tk.LEFT)
        temp_label.pack()
        tw.update_idletasks()
        
        # Get tooltip dimensions
        tooltip_width = tw.winfo_reqwidth()
        tooltip_height = tw.winfo_reqheight()
        
        # Adjust position if tooltip would go off screen
        if x + tooltip_width > screen_width:
            x = screen_width - tooltip_width - 10
        if y + tooltip_height > screen_height:
            y = y - tooltip_height - 20
        
        # Position and style the tooltip
        tw.wm_geometry(f"+{x}+{y}")
        
        # Style the tooltip with border
        frame = tk.Frame(tw, bg=THEME_COLOR_BORDER, bd=1, relief="solid")
        frame.pack(fill=tk.BOTH, expand=True)
        
        label = tk.Label(frame, text=self.text, font=("Segoe UI", 10),
                        bg=THEME_COLOR_CARD, fg=THEME_COLOR_TEXT,
                        wraplength=self.wraplength, justify=tk.LEFT,
                        padx=8, pady=6)
        label.pack()
    
    def _hide_tooltip(self):
        """Hide the tooltip window"""
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

class GlowingButton(tk.Canvas):
    """Modern button widget with enhanced glow effects and smooth animations.

    A sophisticated canvas-based button featuring:
    - Smooth hover animations with scaling
    - Dynamic glow effects
    - Ripple effect on click
    - Modern iOS-style design
    - Sound feedback

    Attributes:
        master (tk.Widget): Parent widget
        text (str): Button label text
        command (callable): Function to execute on click
        width (int): Button width in pixels
        height (int): Button height in pixels
        color (str): Base color in hex format
        disabled (bool): Whether the button is disabled
    """
    
    def __init__(self, master, text, command=None, width=140, height=44, color=THEME_COLOR_PRIMARY, disabled=False, tooltip_text=""):
        try:
            _canvas_bg = master.cget("bg")
        except Exception:
            _canvas_bg = THEME_COLOR_CARD
        super().__init__(master, width=width, height=height, bg=_canvas_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        
        self.command = command
        self.color = color
        self.width = width
        self.height = height
        self.text = text
        self.disabled = disabled
        self.hover = False
        self.pressed = False
        
        # Create tooltip if text is provided
        if tooltip_text:
            self.tooltip = ToolTip(self, tooltip_text)
        
        # Quiet button states with subtle transitions
        self.normal_color = color if not disabled else THEME_COLOR_TEXT_SECONDARY
        self.hover_color = self._lighten_color(color, 0.05) if not disabled else THEME_COLOR_TEXT_SECONDARY
        self.pressed_color = self._darken_color(color, 0.08) if not disabled else THEME_COLOR_TEXT_SECONDARY
        
        # Create flat rectangular button shell
        self._create_button_elements()
        
        # Create button text with better typography
        text_font = font.Font(family="Segoe UI", size=11, weight="normal")
        self.button_text = self.create_text(
            width//2, height//2, text=text, fill=THEME_COLOR_TEXT, font=text_font
        )
        
        # Bind events
        if not disabled:
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)
            self.bind("<Button-1>", self._on_press)
            self.bind("<ButtonRelease-1>", self._on_release)
        
        # Render initial style (no animated glow)
        self._apply_visual_state()
    
    def _create_button_elements(self):
        """Create flat rectangular button visuals (no rounded corners)."""
        self.button_shape = self.create_rectangle(
            4, 4, self.width - 4, self.height - 4, fill=self.normal_color, outline=""
        )
        self.border = self.create_rectangle(
            4, 4, self.width - 4, self.height - 4,
            fill="",
            outline=self._darken_color(self.normal_color, 0.2),
            width=1
        )
    
    def _apply_visual_state(self):
        """Apply current visual state with minimal, non-animated changes."""
        if self.disabled:
            current_color = THEME_COLOR_ELEVATED
        elif self.pressed:
            current_color = self.pressed_color
        elif self.hover:
            current_color = self.hover_color
        else:
            current_color = self.normal_color
        self.itemconfig(self.button_shape, fill=current_color)
        self.itemconfig(self.border, outline=self._darken_color(current_color, 0.2))
        self.itemconfig(self.button_text, fill=THEME_COLOR_TEXT)
    
    def _on_enter(self, event):
        """Mouse enter event."""
        if self.disabled:
            return
        self.hover = True
        self._apply_visual_state()
    
    def _on_leave(self, event):
        """Mouse leave event."""
        if self.disabled:
            return
        self.hover = False
        self.pressed = False
        self._apply_visual_state()
    
    def _on_press(self, event):
        """Mouse press event."""
        if self.disabled:
            return
        self.pressed = True
        self._apply_visual_state()
    
    def _on_release(self, event):
        """Mouse release event."""
        if self.disabled:
            return
        if self.pressed and self.hover and self.command:
            self.command()
        self.pressed = False
        self._apply_visual_state()
    
    def set_disabled(self, disabled):
        """Enable or disable the button"""
        self.disabled = disabled
        if disabled:
            self.config(cursor="")
            self.hover = False
            self.pressed = False
        else:
            self.config(cursor="hand2")
    
    def _lighten_color(self, hex_color, factor=0.1):
        """Lighten a color by the given factor"""
        # Handle named colors
        if hex_color == "white":
            hex_color = "#ffffff"
        elif hex_color == "black":
            hex_color = "#000000"
            
        r = min(255, int(int(hex_color[1:3], 16) * (1 + factor)))
        g = min(255, int(int(hex_color[3:5], 16) * (1 + factor)))
        b = min(255, int(int(hex_color[5:7], 16) * (1 + factor)))
        
        return "#{:02x}{:02x}{:02x}".format(r, g, b)
    
    def _darken_color(self, hex_color, factor=0.1):
        """Darken a color by the given factor"""
        # Handle named colors
        if hex_color == "white":
            hex_color = "#ffffff"
        elif hex_color == "black":
            hex_color = "#000000"
            
        r = max(0, int(int(hex_color[1:3], 16) * (1 - factor)))
        g = max(0, int(int(hex_color[3:5], 16) * (1 - factor)))
        b = max(0, int(int(hex_color[5:7], 16) * (1 - factor)))
        
        return "#{:02x}{:02x}{:02x}".format(r, g, b)

class PublishHistoryTracker:
    """Tracks and manages publish job history.

    This class maintains a record of publish job executions, including
    success/failure status and duration. History is persisted to a JSON file.

    Attributes:
        history_file (str): Path to the JSON file storing history
        history (list): List of publish job records
    """
    
    def __init__(self, history_file=HISTORY_FILE):
        self.history_file = history_file
        self.history = self._load_history()
        # Ensure directory exists for history file
        history_dir = os.path.dirname(self.history_file)
        if history_dir:  # Only create directory if there is a path
            os.makedirs(history_dir, exist_ok=True)
    
    def _load_history(self):
        """Load history from file or create empty history"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                # Validate structure
                if not isinstance(data, dict) or 'runs' not in data or not isinstance(data['runs'], list):
                    print("History file has invalid structure, creating new history")
                    return {'runs': []}
                return data
            except (json.JSONDecodeError, IOError) as e:
                print("Error loading history: {}".format(str(e)))
                # Backup corrupted file
                if os.path.exists(self.history_file):
                    backup_file = self.history_file + ".bak"
                    try:
                        os.rename(self.history_file, backup_file)
                        print("Backed up corrupted history to {}".format(backup_file))
                    except Exception:
                        pass
                return {'runs': []}
        return {'runs': []}
    
    def _save_history(self):
        """Save history to file"""
        try:
            # Write to temporary file first
            temp_file = self.history_file + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Then rename to actual file (safer against corruption)
            if os.path.exists(temp_file):
                if os.path.exists(self.history_file):
                    os.replace(temp_file, self.history_file)  # Atomic on most systems
                else:
                    os.rename(temp_file, self.history_file)
        except Exception as e:
            print("Error saving history: {}".format(str(e)))
            print(traceback.format_exc())
    
    def add_run(self, success, duration=None, error_reason=None, traceback_info=None, commit_messages=None, run_id=None, os_sha=None):
        """Add a new run to history. Posts to EnneadTab-DB API and keeps local JSON as fallback."""
        if success is None:
            success = False
            if not error_reason:
                error_reason = "Unknown error - function returned None"

        run = {
            'timestamp': datetime.datetime.now().strftime("%Y%m%d %H%M%S"),
            'success': bool(success),
            'duration': duration
        }

        if commit_messages:
            run['commit_messages'] = commit_messages
        if run_id:
            run['run_id'] = run_id
        if os_sha:
            run['os_sha'] = os_sha

        if not success:
            if error_reason:
                run['error_reason'] = error_reason
            if traceback_info:
                run['traceback'] = traceback_info

        # Post to EnneadTab-DB API (primary)
        self._post_to_api(success, duration, error_reason, traceback_info, commit_messages, run_id=run_id)

        # Local JSON fallback
        self.history['runs'].append(run)
        if len(self.history['runs']) > MAX_HISTORY_ENTRIES:
            self.history['runs'] = self.history['runs'][-MAX_HISTORY_ENTRIES:]
        self._save_history()

        return run

    def _post_to_api(self, success, duration, error_reason, traceback_info, commit_messages, run_id=None):
        """Post publish event to InfraWatch. Fire-and-forget with 10s timeout."""
        import urllib.request
        payload_obj = {
            "success": bool(success),
            "duration_seconds": int(duration) if duration is not None else None,
            "machine_name": os.environ.get("COMPUTERNAME", "unknown"),
            "error_reason": str(error_reason)[:2000] if error_reason else None,
            "traceback": str(traceback_info)[:10000] if traceback_info else None,
            "commit_messages": commit_messages,
            "run_id": run_id,
            "session_id": _SESSION_ID,
        }
        # Never send None values: json.dumps turns them into JSON null, which
        # strict server schemas reject (root cause of the 2026-03..06 window
        # where every publish report silently 400'd)
        payload_obj = {k: v for k, v in payload_obj.items() if v is not None}
        for attempt in range(1, 4):
            try:
                payload = json.dumps(payload_obj).encode("utf-8")
                req = urllib.request.Request(
                    "https://infrawatch-ennead-projects.vercel.app/infra/api/ingest/publish-status",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp = urllib.request.urlopen(req, timeout=10)
                if resp.status == 200:
                    print("Publish status posted to InfraWatch")
                else:
                    print("InfraWatch returned status {}".format(resp.status))
                return
            except Exception as e:
                if attempt >= 3:
                    print("Failed to post to InfraWatch (non-blocking): {}".format(e))
                    self._report_post_failure_to_errordump(e)
                else:
                    _sleep_jitter_backoff(attempt, base=1.0, cap=20.0)

    def _report_post_failure_to_errordump(self, error):
        """One-shot ErrorDump report when all publish-status POSTs failed.

        The print() above lands in a tick log nobody reads; without this, a
        broken status pipeline stays invisible for months (it did).
        """
        try:
            import urllib.request
            payload = json.dumps({
                "source_app": "EnneadTab-OS",
                "environment": "terminal",
                "error_message": "publish-status POST failed after 3 attempts: {}".format(repr(error)[:500]),
                "function_name": "_post_to_api",
                "user_name": os.environ.get("USERNAME", "unknown"),
                "machine_name": os.environ.get("COMPUTERNAME", "unknown"),
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://error-dump-ennead-projects.vercel.app/error-dump/api/ingest",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # reporting must never break the publish run
    
    def get_runs(self, limit=None):
        """Get recent runs, with optional limit"""
        runs = self.history.get('runs', [])
        if limit:
            return runs[-limit:]
        return runs
    
    def get_success_rate(self):
        """Calculate success rate"""
        runs = self.history.get('runs', [])
        if not runs:
            return 0
            
        successful = sum(1 for run in runs if run.get('success'))
        return successful / len(runs)
        
    def export_to_desktop(self):
        """
        Export publish history to the desktop
        
        Returns:
            tuple: (success, filepath) indicating if export was successful and path to exported file
        """
        try:
            # Get desktop path
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.exists(desktop_path):
                # Fallback to documents if desktop not found
                desktop_path = os.path.join(os.path.expanduser("~"), "Documents")
                if not os.path.exists(desktop_path):
                    # Last resort, use home directory
                    desktop_path = os.path.expanduser("~")
            
            # Create filename with timestamp
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            export_filename = "EnneadTab_Publish_History_{}.json".format(timestamp)
            export_path = os.path.join(desktop_path, export_filename)
            
            # Export the data
            with open(export_path, 'w') as f:
                json.dump(self.history, f, indent=2)
                
            print("Successfully exported history to: {}".format(export_path))
            return True, export_path
        except Exception as e:
            print("Error exporting history: {}".format(str(e)))
            print(traceback.format_exc())
            return False, None


def _schedule_gui_callback(gui, callback):
    """Run a callback on the Tk main thread when a GUI instance is attached."""
    if gui is None:
        return
    try:
        gui.root.after(0, callback)
    except Exception as e:
        print("Error scheduling GUI callback: {}".format(str(e)))


def _record_publish_run(tracker, gui, success, duration, error_reason, traceback_info, commit_messages, run_id):
    try:
        os_sha = get_local_head_sha() if success else None
        tracker.add_run(
            success,
            duration,
            error_reason=error_reason,
            traceback_info=traceback_info,
            commit_messages=commit_messages,
            run_id=run_id,
            os_sha=os_sha,
        )
        if success:
            _note_last_published_os_sha(os_sha)
        if gui is not None:
            _schedule_gui_callback(gui, lambda s=success: gui._update_after_run(s))
    except Exception as e:
        print("Error recording run: {}".format(str(e)))


def _execute_scheduler_check_cycle(tracker, stop_event=None, gui=None):
    """Run one commit-check / publish cycle (shared by GUI thread and --tick mode)."""
    global _last_new_commit_time, _last_commit_detected_time, _pending_commit_messages

    check_id = str(uuid.uuid4())
    write_heartbeat_file(
        state="checking",
        check_id=check_id,
        consecutive_check_errors=_SCHEDULER_COUNTERS["consecutive_check_errors"],
        consecutive_publish_failures=_SCHEDULER_COUNTERS["consecutive_publish_failures"],
        consecutive_pull_failures=_SCHEDULER_COUNTERS["consecutive_pull_failures"],
    )

    now = datetime.datetime.now()

    print("\n" + "=" * 80)
    print("Checking for new commits at {}...".format(now.strftime("%Y%m%d %H%M%S")))
    print("DEBUG: _last_commit_detected_time = {}".format(_last_commit_detected_time))
    print("DEBUG: _last_new_commit_time = {}".format(_last_new_commit_time))
    print("DEBUG: _last_published_os_sha = {}".format(
        _last_published_os_sha[:12] if _last_published_os_sha else None
    ))

    has_new_commits, check_error, commit_messages = check_for_new_commits()

    has_drift, drift_messages = check_os_dist_drift()
    if has_drift:
        print(
            "📦 Dist drift: {} OS commit(s) on local HEAD not yet published".format(
                len(drift_messages) if drift_messages else 0
            )
        )
        if not has_new_commits:
            has_new_commits = True
            commit_messages = drift_messages
            if _last_commit_detected_time is None:
                _last_commit_detected_time = get_head_commit_datetime() or now
                _last_new_commit_time = _last_commit_detected_time
                _pending_commit_messages = drift_messages.copy() if drift_messages else []
                save_scheduler_state()
        elif drift_messages:
            seen = set(_pending_commit_messages)
            for msg in drift_messages:
                if msg not in seen:
                    _pending_commit_messages.append(msg)
                    seen.add(msg)

    print(
        "DEBUG: has_new_commits = {}, check_error = {}, commit_messages count = {}".format(
            has_new_commits, check_error, len(commit_messages) if commit_messages else 0
        )
    )

    if check_error and not has_new_commits:
        _SCHEDULER_COUNTERS["consecutive_check_errors"] += 1
        write_heartbeat_file(
            state="check_error",
            check_id=check_id,
            last_error=check_error[:300],
            consecutive_check_errors=_SCHEDULER_COUNTERS["consecutive_check_errors"],
        )
        print("⚠️ Error checking for new commits: {}".format(check_error))
        print("Will retry on next check cycle")
        return

    _SCHEDULER_COUNTERS["consecutive_check_errors"] = 0

    if not has_new_commits:
        next_check = get_next_pull_check_time()
        next_check_seconds = (next_check - datetime.datetime.now()).total_seconds()

        should_publish = False
        if _last_commit_detected_time is not None:
            time_since_last_commit = (now - _last_commit_detected_time).total_seconds()
            if time_since_last_commit >= _STABILITY_WAIT_TIME:
                should_publish = True
                print(
                    "✅ Commit wave stabilized! ({} min since last commit)".format(
                        int(time_since_last_commit / 60)
                    )
                )
                print("🚀 Proceeding with publish...")

        if should_publish:
            start_time = time.time()
            run_id = str(uuid.uuid4())
            success, error_reason, traceback_info = run_publish_script(
                mode="scheduler",
                stop_event=stop_event,
                run_id=run_id,
            )
            duration = time.time() - start_time
            _record_publish_run(
                tracker,
                gui,
                success,
                duration,
                error_reason,
                traceback_info,
                _pending_commit_messages.copy() if _pending_commit_messages else None,
                run_id,
            )
            _last_commit_detected_time = None
            _pending_commit_messages = []
            save_scheduler_state()
        else:
            if _last_commit_detected_time is not None:
                time_since_last_commit = (now - _last_commit_detected_time).total_seconds()
                remaining_wait = _STABILITY_WAIT_TIME - time_since_last_commit
                if remaining_wait > 0:
                    print(
                        "⏳ Waiting for commit wave to stabilize... ({} min remaining)".format(
                            int(remaining_wait / 60)
                        )
                    )
                else:
                    print(
                        "✅ No new commits. Next check in {} minutes".format(
                            int(next_check_seconds / 60)
                        )
                    )
            else:
                print(
                    "✅ No new commits. Next check in {} minutes".format(
                        int(next_check_seconds / 60)
                    )
                )

            if next_check_seconds > 3600:
                reset_active_mode()
            print("=" * 80 + "\n")
            _schedule_gui_callback(gui, gui._update_status_display if gui else None)
        return

    should_publish_immediately = False
    print("DEBUG: Checking if should publish immediately...")
    print("DEBUG: _last_commit_detected_time = {}".format(_last_commit_detected_time))

    if _last_commit_detected_time is not None:
        time_since_last_detection = (now - _last_commit_detected_time).total_seconds()
        print(
            "DEBUG: time_since_last_detection = {} seconds ({} hours)".format(
                time_since_last_detection, time_since_last_detection / 3600
            )
        )
        print("DEBUG: _STABILITY_WAIT_TIME = {} seconds".format(_STABILITY_WAIT_TIME))
        if time_since_last_detection >= _STABILITY_WAIT_TIME:
            should_publish_immediately = True
            print(
                "🕐 Commits were detected {} hours ago - stability period already passed!".format(
                    int(time_since_last_detection / 3600)
                )
            )
            print("🚀 Will publish immediately after pulling...")
        else:
            print(
                "DEBUG: Not enough time has passed ({} < {})".format(
                    time_since_last_detection, _STABILITY_WAIT_TIME
                )
            )
    else:
        print("DEBUG: _last_commit_detected_time is None - checking if local HEAD is old...")
        try:
            repo_dir = _REPO_ROOT
            local_commit_time_result = subprocess.run(
                [get_git_executable(), "log", "-1", "--format=%ct", "HEAD"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if local_commit_time_result.returncode == 0 and local_commit_time_result.stdout.strip():
                local_commit_timestamp = int(local_commit_time_result.stdout.strip())
                local_commit_time = datetime.datetime.fromtimestamp(local_commit_timestamp)
                time_since_local_commit = (now - local_commit_time).total_seconds()
                print(
                    "DEBUG: Local HEAD commit is {} hours old".format(
                        time_since_local_commit / 3600
                    )
                )
                if time_since_local_commit >= _STABILITY_WAIT_TIME * 2:
                    should_publish_immediately = True
                    print(
                        "🕐 Local HEAD is {} hours old - detected commits are old, publishing immediately!".format(
                            int(time_since_local_commit / 3600)
                        )
                    )
                    print("🚀 Will publish immediately after pulling...")
        except Exception as e:
            print("DEBUG: Could not check local commit age: {}".format(str(e)))

    print("DEBUG: should_publish_immediately = {}".format(should_publish_immediately))

    was_in_active = (
        _last_new_commit_time is not None
        and (now - _last_new_commit_time).total_seconds() < _ACTIVE_MODE_DURATION
    )

    if was_in_active and not should_publish_immediately:
        print("🆕 New commits detected! Resetting stability timer (waiting for wave to settle)...")
        if commit_messages:
            _pending_commit_messages.extend(commit_messages)
    elif not should_publish_immediately:
        print(
            "🆕 New commits detected! Entering active mode (checking every 10 min, waiting for stability)..."
        )
        _pending_commit_messages = commit_messages.copy() if commit_messages else []
    else:
        if commit_messages:
            if _pending_commit_messages:
                _pending_commit_messages.extend(commit_messages)
            else:
                _pending_commit_messages = commit_messages.copy()

    if commit_messages:
        print("📝 Commit messages:")
        for msg in commit_messages:
            print("   - {}".format(msg))

    print("DEBUG: About to check computer name for pull...")
    computer_allowed = check_computer_name_for_pull_by_self()
    print("DEBUG: computer_allowed = {}".format(computer_allowed))
    if computer_allowed:
        print("\n🔄 Pulling latest changes immediately...")
        pull_success = git_pull_main()
        print("DEBUG: pull_success = {}".format(pull_success))
        if not pull_success:
            _SCHEDULER_COUNTERS["consecutive_pull_failures"] += 1
            print(
                "⚠️ Warning: Git pull failed, but will continue monitoring. Will retry on next check."
            )
        else:
            _SCHEDULER_COUNTERS["consecutive_pull_failures"] = 0
            print("✅ Successfully pulled latest changes")
    else:
        print("⚠️ DEBUG: Computer name check failed - pull will not happen on this computer")

    print("DEBUG: Checking if should_publish_immediately = {}".format(should_publish_immediately))
    if should_publish_immediately:
        print("🚀 Publishing immediately (stability period already passed)...")
        start_time = time.time()
        run_id = str(uuid.uuid4())
        success, error_reason, traceback_info = run_publish_script(
            mode="scheduler",
            stop_event=stop_event,
            run_id=run_id,
        )
        duration = time.time() - start_time
        print(
            "DEBUG: Publish completed: success = {}, error_reason = {}".format(
                success, error_reason
            )
        )
        _record_publish_run(
            tracker,
            gui,
            success,
            duration,
            error_reason,
            traceback_info,
            _pending_commit_messages.copy() if _pending_commit_messages else None,
            run_id,
        )
        _last_commit_detected_time = None
        _pending_commit_messages = []
        save_scheduler_state()
        print("=" * 80 + "\n")
        return

    print("⏸️  Holding publish - waiting 1 hour for commit wave to stabilize before publishing")
    print("=" * 80)

    get_next_pull_check_time(force_active_mode=True)

    if _last_commit_detected_time is None:
        _last_commit_detected_time = now
    save_scheduler_state()


def run_scheduler_tick(dry_run=False, force=False):
    """
    Headless one-shot scheduler cycle for Windows Task Scheduler.

    Loads persisted state and runs one check/publish cycle, then exits.
    Throttling between checks is handled by Task Scheduler (e.g. every 10 min),
    not by get_next_pull_check_time() — that interval is for the GUI thread only.

    dry_run: print planned actions only (no git check, pull, or publish).
    force: skip keyboard/mouse idle gate (manual grant publish now).
    """
    write_tick_status(
        "running",
        "tick started"
        + (" (dry run)" if dry_run else "")
        + (" (force)" if force else ""),
    )

    if dry_run:
        print("[DRY RUN] Schedule publisher tick — no git or publish actions.")

    if not check_computer_name_for_pull_by_self():
        print("Not an allowed publish computer; tick skipped.")
        write_tick_status("skipped", "not an allowed publish computer")
        return 0

    idle_ok, idle_detail = check_user_idle_for_publish()
    print("Idle gate: {}".format(idle_detail))
    if not idle_ok and force:
        print("Idle gate OVERRIDE (--force): granting publish despite busy user.")
        idle_detail = "force override; was: {}".format(idle_detail)
        idle_ok = True
    if not idle_ok:
        print("Computer is in use (keyboard/mouse activity); tick skipped.")
        write_tick_status("skipped_busy_user", idle_detail)
        write_heartbeat_file(state="skipped_busy_user", detail=idle_detail)
        return 0

    load_scheduler_state()
    if dry_run:
        if _last_commit_detected_time:
            print(
                "[DRY RUN] Pending commits since: {}".format(
                    _last_commit_detected_time.strftime("%Y-%m-%d %H:%M:%S")
                )
            )
        if _pending_commit_messages:
            print("[DRY RUN] {} pending commit message(s) in state.".format(len(_pending_commit_messages)))
        has_drift, drift_messages = check_os_dist_drift()
        if has_drift:
            print(
                "[DRY RUN] Dist drift: {} unpublished OS commit(s) since {}".format(
                    len(drift_messages),
                    (_last_published_os_sha or "?")[:12],
                )
            )
            for msg in drift_messages[:5]:
                print("   - {}".format(msg))

    if not dry_run:
        _recover_stale_publish_run_state()

    if dry_run:
        print("[DRY RUN] Would run commit check, pull (if allowed), and publish if rules match.")
        write_tick_status("dry_run", "would run commit check / publish if due; {}".format(idle_detail))
        return 0

    tracker = PublishHistoryTracker()
    try:
        _execute_scheduler_check_cycle(tracker, stop_event=None, gui=None)
        write_tick_status("finished", "check cycle completed; {}".format(idle_detail))
        return 0
    except Exception as e:
        write_tick_status("error", str(e))
        raise


class PublisherGUI:
    """Advanced GUI for the EnneadTab Publisher.

    This class implements the main user interface for the schedule publisher,
    featuring real-time status updates, history visualization, and interactive
    controls for manual operations.
    
    Resource Optimization for 24/7 Operation:
    - Adaptive animation rates: Fast (20 FPS) when active, Slow (2 FPS) when idle, 
      Paused (0.5 FPS) when minimized
    - Automatic animation pausing when window is minimized
    - Idle detection: Reduces animation rate after 5 minutes of inactivity
    - Window state monitoring: Adjusts resource usage based on visibility
    - All animations respect window state and user activity

    Attributes:
        root (tk.Tk): Root window instance
        history_tracker (PublishHistoryTracker): History management instance
        scheduler_thread (threading.Thread): Background scheduler thread
        scheduler_stop_event (threading.Event): Requests cooperative cancel of in-flight publish
        window_minimized (bool): Whether window is minimized
        animations_paused (bool): Whether animations are paused
        current_animation_interval (int): Current animation frame interval in ms
    """
    
    def __init__(self, root):
        self.root = root
        self.root.title("EnneadTab · Publisher")
        self.root.configure(bg=THEME_COLOR_BACKGROUND)
        self.root.geometry("1120x760")
        self.root.minsize(960, 640)
        
        # Center the window on screen
        self._center_window()
        
        # Set window icon (placeholder)
        # self.root.iconbitmap('path_to_icon.ico')
        
        # Initialize components
        self.tracker = PublishHistoryTracker()
        self.is_running = False
        self.scheduler_thread = None
        self.scheduler_stop_event = threading.Event()
        self.anim_objects = []
        self.effect_objects = []
        self.countdown_active = True
        self.countdown_seconds = 30
        
        # Resource optimization: track window state and animation state
        self.window_minimized = False
        self.animations_paused = False
        self.last_activity_time = time.time()
        self.idle_threshold = 300  # 5 minutes of inactivity
        self.animation_interval_fast = 50  # Fast mode: 20 FPS
        self.animation_interval_slow = 500  # Slow mode: 2 FPS
        self.animation_interval_paused = 2000  # Paused mode: 0.5 FPS
        self.current_animation_interval = self.animation_interval_fast
        
        # Memory management for long-running operation
        self.last_gc_time = time.time()
        self.gc_interval = 3600  # Run GC every hour
        self.start_time = time.time()
        
        # Create UI
        self._setup_fonts()
        self._create_widgets()
        self._setup_animation_loop()
        self._setup_resource_optimization()
        
        # Start countdown
        self._start_countdown()
        
        # Play startup sound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ASYNC)
        
        # Add window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _center_window(self):
        """Center the window on the screen"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
    
    def _setup_resource_optimization(self):
        """Setup resource optimization for 24/7 operation.
        
        Monitors window state and adjusts animation rates accordingly
        to minimize CPU and memory usage when not actively being viewed.
        """
        # Monitor window state changes
        self.root.bind("<Unmap>", self._on_window_minimized)  # Window minimized
        self.root.bind("<Map>", self._on_window_restored)  # Window restored
        self.root.bind("<FocusIn>", self._on_window_focused)  # Window focused
        self.root.bind("<FocusOut>", self._on_window_unfocused)  # Window unfocused
        
        # Track user activity (mouse/keyboard)
        self.root.bind("<Motion>", self._on_user_activity)
        self.root.bind("<Button>", self._on_user_activity)
        self.root.bind("<Key>", self._on_user_activity)
        
        # Start resource monitoring loop
        self._resource_monitor_loop()
    
    def _on_window_minimized(self, event=None):
        """Handle window minimization - pause heavy animations"""
        self.window_minimized = True
        self.animations_paused = True
        self.current_animation_interval = self.animation_interval_paused
        print("[Resource] Window minimized - animations paused")
    
    def _on_window_restored(self, event=None):
        """Handle window restoration - resume animations"""
        self.window_minimized = False
        self.animations_paused = False
        self.current_animation_interval = self.animation_interval_fast
        self.last_activity_time = time.time()
        print("[Resource] Window restored - animations resumed")
    
    def _on_window_focused(self, event=None):
        """Handle window focus - resume fast animations"""
        if not self.window_minimized:
            self.animations_paused = False
            self.current_animation_interval = self.animation_interval_fast
            self.last_activity_time = time.time()
    
    def _on_window_unfocused(self, event=None):
        """Handle window unfocus - slow down animations"""
        if not self.window_minimized:
            self.current_animation_interval = self.animation_interval_slow
    
    def _on_user_activity(self, event=None):
        """Track user activity to determine if we should speed up animations"""
        self.last_activity_time = time.time()
        if not self.window_minimized and not self.animations_paused:
            self.current_animation_interval = self.animation_interval_fast
    
    def _resource_monitor_loop(self):
        """Monitor resource usage and adjust animation rates dynamically, with memory management"""
        try:
            # Check if window is actually visible
            try:
                # Check if window is minimized (Windows-specific check)
                if hasattr(self.root, 'wm_state'):
                    state = self.root.wm_state()
                    if state == 'iconic':
                        self.window_minimized = True
                        self.animations_paused = True
                        self.current_animation_interval = self.animation_interval_paused
            except Exception:
                pass
            
            # Check for idle state (no user activity for threshold time)
            time_since_activity = time.time() - self.last_activity_time
            if time_since_activity > self.idle_threshold and not self.window_minimized:
                # Slow down but don't pause completely
                if self.current_animation_interval < self.animation_interval_slow:
                    self.current_animation_interval = self.animation_interval_slow
            elif time_since_activity < self.idle_threshold and not self.window_minimized:
                # Speed up if user was recently active
                if self.current_animation_interval > self.animation_interval_fast:
                    self.current_animation_interval = self.animation_interval_fast
            
            # Periodic garbage collection for long-running processes
            current_time = time.time()
            if current_time - self.last_gc_time > self.gc_interval:
                try:
                    # Force garbage collection to free up memory
                    collected = gc.collect()
                    uptime_hours = (current_time - self.start_time) / 3600
                    if collected > 0:
                        print("[Memory] GC collected {} objects after {:.1f} hours uptime".format(collected, uptime_hours))
                    self.last_gc_time = current_time
                except Exception as e:
                    print("[Memory] Error during garbage collection: {}".format(str(e)))
            
            # Schedule next check (every 30 seconds)
            self.root.after(30000, self._resource_monitor_loop)
        except Exception as e:
            print("Error in resource monitor: {}".format(str(e)))
            # Continue monitoring even if there's an error
            self.root.after(30000, self._resource_monitor_loop)
    
    def _on_closing(self):
        """Handle window closing"""
        if self.is_running:
            if messagebox.askokcancel("Quit", "Scheduler is running. Are you sure you want to quit?"):
                self.stop_scheduler()
                if self.scheduler_thread and self.scheduler_thread.is_alive():
                    self.scheduler_thread.join(timeout=120)
                self.root.destroy()
        else:
            self.root.destroy()
    
    def _setup_fonts(self):
        """Initialize custom fonts for the GUI.

        Sets up the font styles used throughout the interface,
        including title, subtitle, and body text fonts.
        """
        self.title_font = font.Font(family="Segoe UI", size=22, weight="bold")
        self.card_title_font = font.Font(family="Segoe UI", size=11, weight="bold")
        self.normal_font = font.Font(family="Segoe UI", size=11)
        self.small_font = font.Font(family="Segoe UI", size=10)
        self.caption_font = font.Font(family="Segoe UI", size=9)
        self.mono_font = font.Font(family="Consolas", size=10)
    
    def _create_widgets(self):
        """Create and layout all GUI components with modern design.

        Initializes and positions all widgets including:
        - Enhanced header with status indicators
        - Modern card-based layout
        - Improved control panels
        - Better visual hierarchy
        """
        self._setup_ttk_style()
        
        # Main container with padding
        self.main_frame = tk.Frame(self.root, bg=THEME_COLOR_BACKGROUND)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=28, pady=28)
        
        # Enhanced header section
        self._create_header()
        
        # Main content area with cards
        self._create_main_content()
        
        # Initialize with existing data
        self._update_history_display()
        self._update_status_display()
    
    def _setup_ttk_style(self):
        """Dark-theme ttk scrollbars (clam) for a consistent modern shell."""
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        sb_bg = THEME_COLOR_ELEVATED
        sb_trough = THEME_COLOR_BACKGROUND
        for orient in ("Horizontal", "Vertical"):
            name = "{}.TScrollbar".format(orient)
            style.configure(
                name,
                background=sb_bg,
                troughcolor=sb_trough,
                borderwidth=0,
                lightcolor=sb_bg,
                darkcolor=sb_bg,
                arrowsize=13,
                thickness=11,
            )
            style.map(
                name,
                background=[
                    ("pressed", THEME_COLOR_BORDER_FOCUS),
                    ("active", THEME_COLOR_BORDER_FOCUS),
                ],
            )
    
    def _create_header(self):
        """Create the enhanced header section"""
        header_frame = tk.Frame(self.main_frame, bg=THEME_COLOR_BACKGROUND)
        header_frame.pack(fill=tk.X, pady=(0, 22))
        
        # Top row: Title and status
        top_row = tk.Frame(header_frame, bg=THEME_COLOR_BACKGROUND)
        top_row.pack(fill=tk.X, pady=(0, 12))
        
        # Minimal title section
        title_frame = tk.Frame(top_row, bg=THEME_COLOR_BACKGROUND)
        title_frame.pack(side=tk.LEFT, padx=(0, 24))
        
        title_container = tk.Frame(title_frame, bg=THEME_COLOR_BACKGROUND)
        title_container.pack(anchor=tk.W)
        
        tk.Label(
            title_container,
            text="EnneadTab Publisher",
            font=self.title_font,
            fg=THEME_COLOR_TEXT,
            bg=THEME_COLOR_BACKGROUND,
        ).pack(anchor=tk.W)
        
        subtitle_label = tk.Label(
            title_container,
            text="Automated publish monitor",
            font=self.caption_font,
            fg=THEME_COLOR_TEXT_MUTED,
            bg=THEME_COLOR_BACKGROUND,
        )
        subtitle_label.pack(anchor=tk.W, pady=(4, 0))
        
        self.countdown_label = tk.Label(
            title_frame,
            text="",
            font=self.small_font,
            fg=THEME_COLOR_WARNING,
            bg=THEME_COLOR_BACKGROUND,
        )
        self.countdown_label.pack(anchor=tk.W, pady=(8, 0))
        
        # Simple status text (running / stopped)
        status_frame = tk.Frame(top_row, bg=THEME_COLOR_BACKGROUND)
        status_frame.pack(side=tk.RIGHT)
        
        self.status_indicator = tk.Label(
            status_frame,
            text="●",
            font=font.Font(family="Segoe UI", size=12),
            fg=THEME_COLOR_FAILURE,
            bg=THEME_COLOR_BACKGROUND,
        )
        self.status_indicator.pack(side=tk.LEFT, padx=(0, 6))
        
        self.header_status_label = tk.Label(
            status_frame,
            text="Stopped",
            font=self.small_font,
            fg=THEME_COLOR_TEXT_SECONDARY,
            bg=THEME_COLOR_BACKGROUND,
        )
        self.header_status_label.pack(side=tk.LEFT)
        
        # Control panels row
        self._create_control_panels(header_frame)
    
    def _create_control_panels(self, parent):
        """Create the control panels with modern card design"""
        controls_frame = tk.Frame(parent, bg=THEME_COLOR_BACKGROUND)
        controls_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Scheduler control card
        scheduler_card = self._create_card(controls_frame, "Scheduler")
        scheduler_card.pack(side=tk.LEFT, padx=(0, 12), fill=tk.X, expand=True)
        
        scheduler_content = tk.Frame(scheduler_card, bg=THEME_COLOR_CARD)
        scheduler_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        self.start_button = GlowingButton(
            scheduler_content, 
            text="Start scheduler", 
            command=self.start_scheduler,
            color=THEME_COLOR_ELEVATED,
            width=158
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_button = GlowingButton(
            scheduler_content, 
            text="Stop scheduler", 
            command=self.stop_scheduler,
            color=THEME_COLOR_ELEVATED,
            width=158
        )
        self.stop_button.pack(side=tk.LEFT)
        
        # Manual operations card
        manual_card = self._create_card(controls_frame, "Manual runs")
        manual_card.pack(side=tk.LEFT, padx=(0, 12), fill=tk.X, expand=True)
        
        manual_content = tk.Frame(manual_card, bg=THEME_COLOR_CARD)
        manual_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        self.manual_publish_button = GlowingButton(
            manual_content,
            text="Run full publish",
            command=self.manual_publish,
            color=THEME_COLOR_ELEVATED,
            width=158,
            tooltip_text="Executes the complete publish process:\n• Pulls latest changes from GitHub\n• Runs the full publish script\n• Builds and distributes all components\n• Updates all systems and packages"
        )
        self.manual_publish_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.manual_push_button = GlowingButton(
            manual_content,
            text="Commit & push",
            command=self.manual_push,
            color=THEME_COLOR_ELEVATED,
            width=158,
            tooltip_text="Only performs Git operations:\n• Commits current local changes\n• Pushes changes to GitHub repository\n• Does NOT run the publish process\n• Quick way to save work to remote"
        )
        self.manual_push_button.pack(side=tk.LEFT)
        
        # Export card
        export_card = self._create_card(controls_frame, "Export")
        export_card.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        export_content = tk.Frame(export_card, bg=THEME_COLOR_CARD)
        export_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        self.export_button = GlowingButton(
            export_content, 
            text="Export history", 
            command=self.export_history,
            color=THEME_COLOR_ELEVATED,
            width=148
        )
        self.export_button.pack()
    
    def _create_card(self, parent, title):
        """Card shell with quiet border and title."""
        card = tk.Frame(
            parent,
            bg=THEME_COLOR_CARD,
            highlightthickness=1,
            highlightbackground=THEME_COLOR_BORDER,
            bd=0,
        )
        title_label = tk.Label(
            card,
            text=title,
            font=self.card_title_font,
            fg=THEME_COLOR_TEXT_SECONDARY,
            bg=THEME_COLOR_CARD,
        )
        title_label.pack(anchor=tk.W, padx=16, pady=(10, 6))
        return card
    
    def _create_main_content(self):
        """Create the main content area with status, visualization, and history"""
        # Main content container
        content_frame = tk.Frame(self.main_frame, bg=THEME_COLOR_BACKGROUND)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # Status and visualization row
        top_content = tk.Frame(content_frame, bg=THEME_COLOR_BACKGROUND)
        top_content.pack(fill=tk.BOTH, expand=True, pady=(0, 20))
        
        # Status panel (left side)
        status_card = self._create_card(top_content, "System status")
        status_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        status_content = tk.Frame(status_card, bg=THEME_COLOR_CARD)
        status_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        status_grid = tk.Frame(status_content, bg=THEME_COLOR_CARD)
        status_grid.pack(fill=tk.BOTH, expand=True)
        
        # Status details (2-column grid: denser, less empty space)
        self.run_status_label = tk.Label(
            status_grid,
            text="Scheduler stopped",
            font=self.normal_font,
            fg=THEME_COLOR_TEXT,
            bg=THEME_COLOR_CARD
        )
        self.run_status_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        
        self.next_run_label = tk.Label(
            status_grid,
            text="Next check: -",
            font=self.small_font,
            fg=THEME_COLOR_TEXT_SECONDARY,
            bg=THEME_COLOR_CARD,
            wraplength=340,
            justify=tk.LEFT,
        )
        self.next_run_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        
        self.total_runs_label = tk.Label(
            status_grid,
            text="Total runs: 0",
            font=self.small_font,
            fg=THEME_COLOR_TEXT,
            bg=THEME_COLOR_CARD
        )
        self.total_runs_label.grid(row=2, column=0, sticky="w", padx=(0, 12), pady=2)
        
        self.success_rate_label = tk.Label(
            status_grid,
            text="Success rate: 0%",
            font=self.small_font,
            fg=THEME_COLOR_TEXT,
            bg=THEME_COLOR_CARD
        )
        self.success_rate_label.grid(row=2, column=1, sticky="w", pady=2)
        
        self.last_run_label = tk.Label(
            status_grid,
            text="Last publish: -",
            font=self.small_font,
            fg=THEME_COLOR_TEXT_SECONDARY,
            bg=THEME_COLOR_CARD,
            wraplength=340,
            justify=tk.LEFT,
        )
        self.last_run_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        
        self.failures_summary_label = tk.Label(
            status_grid,
            text="Failed runs (all time): 0",
            font=self.small_font,
            fg=THEME_COLOR_TEXT_SECONDARY,
            bg=THEME_COLOR_CARD
        )
        self.failures_summary_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=2)
        
        status_grid.columnconfigure(1, weight=1)
        
        # Visualization panel (right side)
        viz_card = self._create_card(top_content, "Publish timeline")
        viz_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        viz_content = tk.Frame(viz_card, bg=THEME_COLOR_CARD)
        viz_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        legend_row = tk.Frame(viz_content, bg=THEME_COLOR_CARD)
        legend_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            legend_row,
            text="●",
            font=self.small_font,
            fg=THEME_COLOR_SUCCESS,
            bg=THEME_COLOR_CARD,
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(
            legend_row,
            text="Success",
            font=self.caption_font,
            fg=THEME_COLOR_TEXT_MUTED,
            bg=THEME_COLOR_CARD,
        ).pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(
            legend_row,
            text="●",
            font=self.small_font,
            fg=THEME_COLOR_FAILURE,
            bg=THEME_COLOR_CARD,
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(
            legend_row,
            text="Failure",
            font=self.caption_font,
            fg=THEME_COLOR_TEXT_MUTED,
            bg=THEME_COLOR_CARD,
        ).pack(side=tk.LEFT, padx=(0, 20))
        tk.Label(
            legend_row,
            text="Older left · newer right",
            font=self.caption_font,
            fg=THEME_COLOR_TEXT_MUTED,
            bg=THEME_COLOR_CARD,
        ).pack(side=tk.LEFT)
        
        scroll_wrap = tk.Frame(viz_content, bg=THEME_COLOR_CARD)
        scroll_wrap.pack(fill=tk.BOTH, expand=True)
        
        self.timeline_hscroll = ttk.Scrollbar(scroll_wrap, orient=tk.HORIZONTAL)
        self.timeline_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.canvas = tk.Canvas(
            scroll_wrap,
            bg=THEME_COLOR_CANVAS,
            highlightthickness=0,
            bd=0,
            xscrollcommand=self.timeline_hscroll.set,
        )
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.timeline_hscroll.config(command=self.canvas.xview)
        
        self.canvas.bind("<MouseWheel>", self._on_timeline_mousewheel)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Motion>", self._on_timeline_motion)
        self.canvas.bind("<Button-1>", self._on_timeline_button_click)
        self.canvas.bind("<Leave>", self._on_timeline_canvas_leave)
        
        self.timeline_detail_label = tk.Label(
            viz_content,
            text="Hover a point for details · Click to highlight a row in Recent runs",
            font=self.caption_font,
            fg=THEME_COLOR_TEXT_SECONDARY,
            bg=THEME_COLOR_CARD,
            wraplength=560,
            justify=tk.LEFT,
            anchor="w",
        )
        self.timeline_detail_label.pack(fill=tk.X, pady=(8, 0))
        
        self._timeline_runs_snapshot = []
        self._timeline_default_hint = (
            "Hover a point for details · Click to highlight a row in Recent runs"
        )
        
        # History panel (bottom)
        history_card = self._create_card(content_frame, "Recent runs")
        history_card.pack(fill=tk.BOTH, expand=True)
        
        history_content = tk.Frame(history_card, bg=THEME_COLOR_CARD)
        history_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        # Create history list with scrollbar
        scrollbar = ttk.Scrollbar(history_content)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.history_list = tk.Listbox(
            history_content,
            bg=THEME_COLOR_CANVAS,
            fg=THEME_COLOR_TEXT,
            font=self.mono_font,
            bd=0,
            highlightthickness=0,
            selectbackground=THEME_COLOR_BORDER_FOCUS,
            selectforeground=THEME_COLOR_TEXT,
            height=7
        )
        self.history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Connect scrollbar
        scrollbar.config(command=self.history_list.yview)
        self.history_list.config(yscrollcommand=scrollbar.set)
        
        # Add right-click context menu for error details
        self.history_context_menu = tk.Menu(self.root, tearoff=0, bg=THEME_COLOR_CARD, fg=THEME_COLOR_TEXT)
        self.history_context_menu.add_command(label="Show Error Details", command=self._show_error_details)
        self.history_list.bind("<Button-3>", self._show_context_menu)  # Right-click
    
    def _setup_animation_loop(self):
        """Initialize the main animation system.

        Sets up the periodic update loop for all animations
        and visual effects in the GUI.
        """
        self._draw_visualization()
        self._animation_loop()
    
    def _animation_loop(self):
        """Main animation loop with adaptive frame rate.

        Updates all active animations and effects at regular intervals.
        Frame rate adapts based on window state and user activity.
        """
        # Skip updates if animations are paused
        if self.animations_paused:
            self.root.after(self.current_animation_interval, self._animation_loop)
            return
        
        # Redraw if window is resized (only if visible)
        if not self.window_minimized:
            if hasattr(self, '_last_canvas_size'):
                if (self.canvas.winfo_width(), self.canvas.winfo_height()) != self._last_canvas_size:
                    self._draw_visualization()
            
            self._last_canvas_size = (self.canvas.winfo_width(), self.canvas.winfo_height())
            
            # Update particle effects (only if visible)
            self._update_effects()
        
        # Schedule next frame with adaptive interval
        self.root.after(self.current_animation_interval, self._animation_loop)
    
    def _update_effects(self):
        """Update all particle effects in the system.

        Advances the animation state of all active particle effects
        and removes completed effects from the system.
        Ensures proper cleanup to prevent memory leaks.
        """
        # Update existing effects and remove dead ones
        dead_effects = []
        for i, effect in enumerate(self.effect_objects):
            if not effect.update():
                dead_effects.append(i)
        
        # Remove dead effects in reverse order to maintain indices
        for i in reversed(dead_effects):
                try:
                    effect = self.effect_objects.pop(i)
                    # Explicitly clear references
                    if hasattr(effect, 'particles'):
                        effect.particles = []
                    del effect
                except (IndexError, Exception):
                    # Ignore errors during cleanup
                    pass
        
        # Limit maximum concurrent effects to prevent memory buildup
        MAX_CONCURRENT_EFFECTS = 10
        if len(self.effect_objects) > MAX_CONCURRENT_EFFECTS:
            # Remove oldest effects
            excess = len(self.effect_objects) - MAX_CONCURRENT_EFFECTS
            for _ in range(excess):
                try:
                    effect = self.effect_objects.pop(0)
                    if hasattr(effect, 'particles'):
                        effect.particles = []
                    del effect
                except Exception:
                    pass
    
    def _on_timeline_mousewheel(self, event):
        """Scroll the timeline horizontally with the mouse wheel."""
        try:
            d = getattr(event, "delta", 0) or 0
            if d:
                self.canvas.xview_scroll(int(-1 * (d / 120)), "units")
        except Exception:
            pass
        return "break"
    
    def _format_timeline_run_summary(self, run):
        """Compact readable summary for timeline hover and status line."""
        ts = run.get("timestamp") or "?"
        ok = run.get("success", False)
        st = "OK" if ok else "FAILED"
        parts = [ts, st]
        dur = run.get("duration")
        if dur is not None:
            try:
                parts.append("{:.1f}s".format(float(dur)))
            except (TypeError, ValueError):
                pass
        msgs = run.get("commit_messages") or []
        if msgs:
            m = msgs[0]
            if len(m) > 100:
                m = m[:97] + "..."
            parts.append(m)
        if not ok and run.get("error_reason"):
            er = run["error_reason"]
            if len(er) > 80:
                er = er[:77] + "..."
            parts.append(er)
        return " · ".join(parts)
    
    def _timeline_pick_run_index(self, event_x, event_y):
        """Return run index from canvas window coords, or None."""
        cx = self.canvas.canvasx(event_x)
        cy = self.canvas.canvasy(event_y)
        items = self.canvas.find_closest(cx, cy)
        if not items:
            return None
        for t in self.canvas.gettags(items[0]):
            if t.startswith("run_"):
                try:
                    return int(t[4:])
                except ValueError:
                    return None
        return None
    
    def _timeline_hover_index(self, idx):
        if idx is None or idx < 0 or idx >= len(self._timeline_runs_snapshot):
            self.timeline_detail_label.config(
                text=self._timeline_default_hint,
                fg=THEME_COLOR_TEXT_SECONDARY,
            )
            return
        run = self._timeline_runs_snapshot[idx]
        self.timeline_detail_label.config(
            text=self._format_timeline_run_summary(run),
            fg=THEME_COLOR_SUCCESS if run.get("success") else THEME_COLOR_FAILURE,
        )
    
    def _on_timeline_motion(self, event):
        idx = self._timeline_pick_run_index(event.x, event.y)
        if idx is not None:
            self._timeline_hover_index(idx)
            self.canvas.config(cursor="hand2")
        else:
            self.canvas.config(cursor="")
            self.timeline_detail_label.config(
                text=self._timeline_default_hint,
                fg=THEME_COLOR_TEXT_SECONDARY,
            )
    
    def _on_timeline_canvas_leave(self, _event=None):
        self.canvas.config(cursor="")
        self.timeline_detail_label.config(
            text=self._timeline_default_hint,
            fg=THEME_COLOR_TEXT_SECONDARY,
        )
    
    def _on_timeline_button_click(self, event):
        idx = self._timeline_pick_run_index(event.x, event.y)
        if idx is not None:
            self._select_timeline_in_listbox(idx)
    
    def _select_timeline_in_listbox(self, snap_idx):
        """Map timeline dot index (window oldest→newest) to listbox row and scroll to it."""
        runs = self.tracker.get_runs()
        if not runs or not self._timeline_runs_snapshot:
            return
        if snap_idx < 0 or snap_idx >= len(self._timeline_runs_snapshot):
            return
        listbox_idx = len(runs) - len(self._timeline_runs_snapshot) + snap_idx
        if listbox_idx < 0 or listbox_idx >= self.history_list.size():
            return
        self.history_list.selection_clear(0, tk.END)
        self.history_list.selection_set(listbox_idx)
        self.history_list.activate(listbox_idx)
        self.history_list.see(listbox_idx)
    
    def _draw_visualization(self):
        """Chronological timeline: even spacing, horizontal scroll, details on hover/click (no rotated labels)."""
        self.canvas.delete("all")
        viewport_w = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if viewport_w < 50 or height < 50:
            return

        runs = self.tracker.get_runs(30)
        self._timeline_runs_snapshot = list(runs)

        pad_x = 40
        circle_r = 8
        bottom_margin = 36
        timeline_y = max(36, (height - bottom_margin) // 2)
        min_gap = 42

        if not runs:
            self.canvas.create_rectangle(
                0, 0, viewport_w, height, fill=THEME_COLOR_CANVAS, outline=""
            )
            self.canvas.create_text(
                viewport_w / 2,
                height / 2,
                text="No publish history yet",
                font=self.normal_font,
                fill=THEME_COLOR_TEXT,
            )
            self.canvas.config(scrollregion=(0, 0, viewport_w, height))
            return

        n = len(runs)
        content_w = max(viewport_w, pad_x * 2 + max(0, (n - 1)) * min_gap)

        usable = float(content_w - 2 * pad_x)
        if n == 1:
            positions = [int(pad_x + usable / 2.0)]
        else:
            step = usable / float(n - 1)
            positions = [int(round(pad_x + i * step)) for i in range(n)]

        self.canvas.create_rectangle(0, 0, content_w, height, fill=THEME_COLOR_CANVAS, outline="")

        line_x0 = positions[0]
        line_x1 = positions[-1]
        self.canvas.create_line(
            line_x0,
            timeline_y,
            line_x1,
            timeline_y,
            fill=THEME_COLOR_BORDER,
            width=2,
        )

        for i, run in enumerate(runs):
            x = positions[i]
            success = run.get("success", False)
            color = THEME_COLOR_SUCCESS if success else THEME_COLOR_FAILURE
            hit_r = circle_r + 6
            self.canvas.create_oval(
                x - hit_r,
                timeline_y - hit_r,
                x + hit_r,
                timeline_y + hit_r,
                fill=THEME_COLOR_CANVAS,
                outline="",
                tags=("timeline_hit", "run_{}".format(i)),
            )
            self.canvas.create_oval(
                x - circle_r,
                timeline_y - circle_r,
                x + circle_r,
                timeline_y + circle_r,
                fill=color,
                outline=THEME_COLOR_BORDER_FOCUS,
                width=2,
                tags=("timeline_node", "run_{}".format(i)),
            )
            self.canvas.create_text(
                x,
                timeline_y + circle_r + 16,
                text=str(i + 1),
                font=self.small_font,
                fill=THEME_COLOR_TEXT_MUTED,
                tags=("timeline_tick", "run_{}".format(i)),
            )

        self.canvas.config(scrollregion=(0, 0, content_w, height))
        self.canvas.update_idletasks()
        self.canvas.xview_moveto(1.0)

    def _update_history_display(self):
        """Update the history listbox with latest entries and enhanced formatting.

        Refreshes the display of historical publish jobs,
        showing the most recent entries at the top with enhanced visual indicators.
        """
        self.history_list.delete(0, tk.END)
        
        runs = self.tracker.get_runs()
        for run in reversed(runs):  # Show newest first
            success = run.get('success', False)
            timestamp = run.get('timestamp', 'Unknown time')
            duration = run.get('duration')
            error_reason = run.get('error_reason')
            
            # Enhanced status indicators with emojis
            if success:
                status_icon = "✅"
                status_text = "SUCCESS"
                base_color = THEME_COLOR_SUCCESS
            else:
                status_icon = "❌"
                status_text = "FAILURE"
                base_color = THEME_COLOR_FAILURE
            
            # Format timestamp for better readability
            if ' ' in timestamp:
                date, time = timestamp.split(' ')
                formatted_time = f"{date} {time[:4]}"  # Show only HH:MM
            else:
                formatted_time = timestamp[:8] + '-' + timestamp[8:12]
            
            # Build enhanced display string
            display_parts = [f"{status_icon} {status_text}"]
            display_parts.append(f"📅 {formatted_time}")
            
            if duration:
                display_parts.append(f"⏱️ {duration:.1f}s")
            
            # Add commit messages if available
            commit_messages = run.get('commit_messages', [])
            if commit_messages:
                if len(commit_messages) == 1:
                    msg = commit_messages[0]
                    if len(msg) > 50:
                        msg = msg[:47] + "..."
                    display_parts.append(f"📝 {msg}")
                else:
                    display_parts.append(f"📝 {len(commit_messages)} commits")
            
            if not success and error_reason:
                # Truncate error reason if too long
                if len(error_reason) > 40:
                    display_parts.append(f"💥 {error_reason[:37]}...")
                else:
                    display_parts.append(f"💥 {error_reason}")
            
            display = " | ".join(display_parts)
            
            # Insert with color coding
            self.history_list.insert(0, display)
            
            # Apply color to the inserted item
            index = 0
            self.history_list.itemconfig(index, fg=base_color)
        
        # Auto-scroll to the most recent entry (bottom of list)
        if self.history_list.size() > 0:
            self.history_list.see(tk.END)
    
    def _show_context_menu(self, event):
        """Show context menu on right-click"""
        try:
            # Get the clicked item
            index = self.history_list.nearest(event.y)
            if index >= 0:
                self.history_list.selection_clear(0, tk.END)
                self.history_list.selection_set(index)
                self.history_list.activate(index)
                
                # Show context menu
                self.history_context_menu.post(event.x_root, event.y_root)
        except Exception as e:
            print("Error showing context menu: {}".format(str(e)))
    
    def _show_error_details(self):
        """Show detailed error information for selected history item"""
        try:
            selection = self.history_list.curselection()
            if not selection:
                return
                
            index = selection[0]
            runs = self.tracker.get_runs()
            # Listbox order matches chronological runs (oldest at top, newest at bottom)
            actual_index = index
            if actual_index < 0 or actual_index >= len(runs):
                return
                
            run = runs[actual_index]
            
            if run.get('success', True):  # Skip if successful
                return
                
            # Create error details window
            error_window = tk.Toplevel(self.root)
            error_window.title("Error Details - {}".format(run.get('timestamp', 'Unknown')))
            error_window.geometry("800x600")
            error_window.configure(bg=THEME_COLOR_CARD)
            
            # Add scrollable text widget
            text_frame = tk.Frame(error_window, bg=THEME_COLOR_CARD)
            text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            scrollbar = ttk.Scrollbar(text_frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            text_widget = tk.Text(
                text_frame,
                bg=THEME_COLOR_CANVAS,
                fg=THEME_COLOR_TEXT,
                font=self.mono_font,
                wrap=tk.WORD,
                yscrollcommand=scrollbar.set
            )
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            scrollbar.config(command=text_widget.yview)
            
            # Add error information
            text_widget.insert(tk.END, "TIMESTAMP: {}\n".format(run.get('timestamp', 'Unknown')))
            text_widget.insert(tk.END, "DURATION: {:.2f} seconds\n".format(run.get('duration', 0)))
            text_widget.insert(tk.END, "STATUS: FAILED\n\n")
            
            if run.get('error_reason'):
                text_widget.insert(tk.END, "ERROR REASON:\n")
                text_widget.insert(tk.END, "{}\n\n".format(run.get('error_reason')))
            
            if run.get('traceback'):
                text_widget.insert(tk.END, "FULL TRACEBACK:\n")
                text_widget.insert(tk.END, "{}\n".format(run.get('traceback')))
            
            # Make text read-only
            text_widget.config(state=tk.DISABLED)
            
            # Add close button
            close_button = tk.Button(
                error_window,
                text="Close",
                command=error_window.destroy,
                bg=THEME_COLOR_PRIMARY,
                fg=THEME_COLOR_TEXT,
                font=self.small_font,
                padx=22,
                pady=6,
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                activebackground=THEME_COLOR_BORDER_FOCUS,
                activeforeground=THEME_COLOR_TEXT,
            )
            close_button.pack(pady=10)
            
        except Exception as e:
            print("Error showing error details: {}".format(str(e)))
    
    def _update_status_display(self):
        """Update status display with current information and enhanced visual feedback.

        Refreshes the status panel with the latest:
        - Next scheduled publish time
        - Last publish status
        - Current system status
        - Enhanced status indicators
        """
        runs = self.tracker.get_runs()
        success_rate = self.tracker.get_success_rate() * 100
        
        # Update labels with enhanced formatting
        self.total_runs_label.config(text="Total runs: {}".format(len(runs)))
        
        # Color-code success rate
        if success_rate >= 90:
            success_color = THEME_COLOR_SUCCESS
        elif success_rate >= 70:
            success_color = THEME_COLOR_WARNING
        else:
            success_color = THEME_COLOR_FAILURE
        
        self.success_rate_label.config(
            text="Success rate: {:.1f}%".format(success_rate),
            fg=success_color
        )
        
        failed_ct = sum(1 for r in runs if not r.get("success"))
        self.failures_summary_label.config(
            text="Failed runs (all time): {} of {}".format(failed_ct, len(runs))
        )
        
        if runs:
            last = runs[-1]
            summary = self._format_timeline_run_summary(last)
            self.last_run_label.config(
                text="Last publish: {}".format(summary),
                fg=THEME_COLOR_SUCCESS if last.get("success") else THEME_COLOR_FAILURE,
            )
        else:
            self.last_run_label.config(
                text="Last publish: -",
                fg=THEME_COLOR_TEXT_SECONDARY,
            )
        
        # Update scheduler status with enhanced indicators
        if self.is_running:
            self.run_status_label.config(
                text="Scheduler running",
                fg=THEME_COLOR_SUCCESS
            )
            self.status_indicator.config(
                text="●",
                fg=THEME_COLOR_SUCCESS
            )
            self.header_status_label.config(
                text="Running",
                fg=THEME_COLOR_SUCCESS,
            )
        else:
            self.run_status_label.config(
                text="Scheduler stopped",
                fg=THEME_COLOR_FAILURE
            )
            self.status_indicator.config(
                text="●",
                fg=THEME_COLOR_FAILURE
            )
            self.header_status_label.config(
                text="Stopped",
                fg=THEME_COLOR_TEXT_SECONDARY,
            )
    
    def _spawn_effect(self, x, y, is_success=True):
        """Spawn a particle effect at the given position.

        Args:
            x (int): X-coordinate for effect center
            y (int): Y-coordinate for effect center
            is_success (bool): Whether this is a success or failure effect
        """
        color = THEME_COLOR_SUCCESS if is_success else THEME_COLOR_FAILURE
        effect = ParticleEffect(self.canvas, x, y, color, is_success=is_success)
        self.effect_objects.append(effect)
    
    def _start_countdown(self):
        """Start the 30-second countdown to auto-start the scheduler."""
        if not self.countdown_active:
            return
            
        if self.countdown_seconds > 0:
            self.countdown_label.config(
                text="Auto-starting in {} seconds...".format(self.countdown_seconds)
            )
            self.countdown_seconds -= 1
            self.root.after(1000, self._start_countdown)
        else:
            self.countdown_label.config(text="")
            self.start_scheduler()
            
    def start_scheduler(self):
        """Start the publisher scheduler.

        Initializes and begins the background thread that manages
        the periodic publishing cycle.
        """
        if self.is_running:
            return
            
        # Cancel countdown if active
        self.countdown_active = False
        self.countdown_label.config(text="")
            
        self.scheduler_stop_event.clear()
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_thread)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        
        self._update_status_display()
        
        # Play start sound
        winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)
        
        # Visual feedback
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self._spawn_effect(width/2, height/2, True)
    
    def stop_scheduler(self):
        """Stop the publisher scheduler.

        Gracefully terminates the background scheduler thread
        and cleans up associated resources.
        """
        if not self.is_running:
            return
            
        self.scheduler_stop_event.set()
        self.is_running = False
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=120)
            if self.scheduler_thread.is_alive():
                print("⚠️ Scheduler thread did not exit within join timeout")
        self.scheduler_stop_event.clear()
        self._update_status_display()
        
        # Play stop sound
        winsound.PlaySound("SystemHand", winsound.SND_ASYNC)
        
        # Visual feedback
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self._spawn_effect(width/2, height/2, False)
    
    def _scheduler_thread(self):
        """Background thread for running the scheduler.

        Manages the periodic execution of publish jobs with intelligent pull checking.
        Checks for new commits frequently, but only publishes when new commits are detected.
        """
        # Declare globals at the start of the function
        global _last_new_commit_time, _last_commit_detected_time, _pending_commit_messages
        
        # Load persisted state on startup
        load_scheduler_state()
        _recover_stale_publish_run_state()
        
        try:
            while self.is_running:
                check_id = str(uuid.uuid4())
                write_heartbeat_file(
                    state="waiting_next_check",
                    check_id=check_id,
                    consecutive_check_errors=_SCHEDULER_COUNTERS["consecutive_check_errors"],
                    consecutive_publish_failures=_SCHEDULER_COUNTERS["consecutive_publish_failures"],
                    consecutive_pull_failures=_SCHEDULER_COUNTERS["consecutive_pull_failures"],
                )
                # Calculate next pull check time (adaptive frequency)
                next_check = get_next_pull_check_time()
                next_check_str = next_check.strftime("%Y-%m-%d %H:%M:%S")
                
                # Determine current mode for display
                now = datetime.datetime.now()
                if _last_new_commit_time is not None:
                    time_since_last_commit = (now - _last_new_commit_time).total_seconds()
                    if time_since_last_commit < _ACTIVE_MODE_DURATION:
                        remaining_active = _ACTIVE_MODE_DURATION - time_since_last_commit
                        # Check if we're waiting for stability
                        if _last_commit_detected_time is not None:
                            time_since_detected = (now - _last_commit_detected_time).total_seconds()
                            if time_since_detected < _STABILITY_WAIT_TIME:
                                remaining_stability = _STABILITY_WAIT_TIME - time_since_detected
                                mode_str = "ACTIVE (waiting {} min for stability)".format(int(remaining_stability / 60))
                            else:
                                mode_str = "ACTIVE (ready to publish)"
                        else:
                            mode_str = "ACTIVE ({} min remaining)".format(int(remaining_active / 60))
                    else:
                        mode_str = "NORMAL"
                else:
                    mode_str = "NORMAL"
                
                # Calculate time until next check
                wait_seconds = (next_check - now).total_seconds()
                
                # If we're past the check time (shouldn't happen, but handle gracefully)
                if wait_seconds < 0:
                    wait_seconds = 0
                
                # Update next check time display with mode
                try:
                    self.root.after(0, lambda s=next_check_str, m=mode_str: self.next_run_label.config(
                        text="Next Check: {} [{}]".format(s, m)
                    ))
                except Exception as e:
                    print("Error updating next check label: {}".format(str(e)))
                
                # Wait until the next check time with periodic UI updates
                wait_interval = 1  # 1 second check interval
                next_update = 60  # Update UI every minute
                elapsed = 0
                
                while elapsed < wait_seconds and self.is_running:
                    try:
                        time.sleep(wait_interval)
                    except Exception:
                        # Handle interruption
                        break
                        
                    elapsed += wait_interval
                    
                    if elapsed % 30 == 0:
                        write_heartbeat_file(
                            state="waiting_next_check",
                            check_id=check_id,
                            wait_elapsed_sec=elapsed,
                            consecutive_check_errors=_SCHEDULER_COUNTERS["consecutive_check_errors"],
                        )
                    
                    if elapsed % next_update == 0:  # Update every minute
                        try:
                            # Recalculate next check time in case we crossed a time boundary
                            current_next_check = get_next_pull_check_time()
                            remaining = (current_next_check - datetime.datetime.now()).total_seconds()
                            if remaining < 0:
                                remaining = 0
                            current_next_str = current_next_check.strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Update mode display
                            current_now = datetime.datetime.now()
                            if _last_new_commit_time is not None:
                                time_since = (current_now - _last_new_commit_time).total_seconds()
                                if time_since < _ACTIVE_MODE_DURATION:
                                    remaining_active = _ACTIVE_MODE_DURATION - time_since
                                    # Check if we're waiting for stability
                                    if _last_commit_detected_time is not None:
                                        time_since_detected = (current_now - _last_commit_detected_time).total_seconds()
                                        if time_since_detected < _STABILITY_WAIT_TIME:
                                            remaining_stability = _STABILITY_WAIT_TIME - time_since_detected
                                            current_mode_str = "ACTIVE (waiting {} min for stability)".format(int(remaining_stability / 60))
                                        else:
                                            current_mode_str = "ACTIVE (ready to publish)"
                                    else:
                                        current_mode_str = "ACTIVE ({} min remaining)".format(int(remaining_active / 60))
                                else:
                                    current_mode_str = "NORMAL"
                            else:
                                current_mode_str = "NORMAL"
                            
                            self.root.after(0, lambda s=current_next_str, m=current_mode_str: self.next_run_label.config(
                                text="Next Check: {} [{}]".format(s, m)
                            ))
                        except Exception as e:
                            print("Error updating next check countdown: {}".format(str(e)))
                
                # Check if we should still run (user might have stopped scheduler)
                if not self.is_running:
                    break
                
                _execute_scheduler_check_cycle(
                    self.tracker,
                    stop_event=self.scheduler_stop_event,
                    gui=self,
                )
                    
        except Exception as e:
            print("Scheduler thread error: {}".format(str(e)))
            print(traceback.format_exc())
            # Attempt to recover by resetting the running state
            try:
                self.is_running = False
                self.root.after(0, self._update_status_display)
            except Exception:
                pass
    
    def _update_after_run(self, success):
        """Update the UI after a publish run.

        Args:
            success (bool): Whether the publish run was successful
        """
        # Update displays
        self._update_history_display()
        self._update_status_display()
        self._draw_visualization()
        
        # Create effect at a random position in the canvas
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        x = random.randint(width//4, 3*width//4)
        y = random.randint(height//4, 3*height//4)
        self._spawn_effect(x, y, success)
        
        # Play sound based on result
        if success:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ASYNC)
        else:
            winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)

    def export_history(self):
        """Export publish history to desktop.

        Creates a JSON file containing the complete publish history
        and saves it to the user's desktop.
        """
        success, filepath = self.tracker.export_to_desktop()
        
        # Show feedback based on result
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if success:
            self._spawn_effect(width/2, height/2, True)
            
            # Create a popup notification
            popup = tk.Toplevel(self.root)
            popup.title("Export Successful")
            popup.geometry("400x100")
            popup.resizable(False, False)
            popup.configure(bg=THEME_COLOR_CARD)
            
            # Add message
            message = "History exported successfully to:\n{}".format(filepath)
            msg_label = tk.Label(
                popup,
                text=message,
                font=self.normal_font,
                fg=THEME_COLOR_TEXT,
                bg=THEME_COLOR_CARD,
                wraplength=380
            )
            msg_label.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
            
            # Auto-close after 5 seconds
            popup.after(5000, popup.destroy)
            
            # Play success sound
            winsound.PlaySound("SystemAsterisk", winsound.SND_ASYNC)
        else:
            self._spawn_effect(width/2, height/2, False)
            
            # Play error sound
            winsound.PlaySound("SystemHand", winsound.SND_ASYNC)

    def manual_publish(self):
        """Run a manual publish job.

        Executes the publish process immediately, bypassing
        the scheduled timing.
        """
        try:
            # Disable the manual publish button during the process
            self.manual_publish_button.config(state=tk.DISABLED)
            
            # Run the publish script
            start_time = time.time()
            run_id = str(uuid.uuid4())
            success, error_reason, traceback_info = run_publish_script(
                mode="manual",
                stop_event=None,
                run_id=run_id,
            )
            duration = time.time() - start_time
            
            # Record the run
            self.tracker.add_run(
                success,
                duration,
                error_reason=error_reason,
                traceback_info=traceback_info,
                run_id=run_id,
            )
            
            # Update UI
            self._update_after_run(success)
            
            # Show feedback
            width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
            self._spawn_effect(width/2, height/2, success)
            
            # Play sound based on result
            if success:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)
                
        finally:
            # Re-enable the manual publish button
            self.manual_publish_button.config(state=tk.NORMAL)
    
    def manual_push(self):
        """Run a manual push to GitHub.

        Pushes the current state to GitHub immediately,
        bypassing the scheduled timing.
        """
        try:
            # Disable the manual push button during the process
            self.manual_push_button.config(state=tk.DISABLED)
            
            # Run the push
            success = push_back_to_github()
            
            # Show feedback
            width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
            self._spawn_effect(width/2, height/2, success)
            
            # Play sound based on result
            if success:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)
                
        finally:
            # Re-enable the manual push button
            self.manual_push_button.config(state=tk.NORMAL)

def _report_publish_error_to_errordump(message):
    """Make an AutoDist git failure LOUD (senzhang-todo #1709).

    Module-level twin of PublishHistory._report_post_failure_to_errordump, which
    is a method and so unreachable from push_back_to_github().

    Without this, a failed `git add`/`git commit` only ever print()s into a tick
    log nobody reads, and the publisher goes on force-pushing and reporting
    success having committed nothing. That is precisely how a stale index.lock
    wedged publishing for 13 and then 22 minutes on 2026-07-13 without a single
    alarm firing on the publish machine itself.
    """
    try:
        import urllib.request
        payload = json.dumps({
            "source_app": "EnneadTab-OS",
            "environment": "terminal",
            "error_message": str(message)[:1000],
            "function_name": "push_back_to_github",
            "user_name": os.environ.get("USERNAME", "unknown"),
            "machine_name": os.environ.get("COMPUTERNAME", "unknown"),
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://error-dump-ennead-projects.vercel.app/error-dump/api/ingest",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # reporting must never break the publish run


def push_back_to_github():
    """Commit and push current changes to GitHub.

    This function handles the Git operations to commit and push
    changes to the remote repository. The commit message includes
    the current timestamp.

    Returns:
        bool: True if the operation was successful, False otherwise
    """
    try:
        # Get repository root directory
        repo_dir = _REPO_ROOT

        # Check if there are meaningful changes (not just state files)
        status_result = subprocess.run(
            [get_git_executable(), "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        if status_result.stdout.strip():
            changed_files = [line.split()[-1] for line in status_result.stdout.strip().splitlines() if line.strip()]
            non_essential = {
                "DarkSide/publish/publish_history.json",
                "DarkSide/publish/scheduler_state.json",
                "DarkSide/publish/scheduler_state.json.bak",
                "DarkSide/publish/publish_run_state.json",
                "DarkSide/publish/scheduler_heartbeat.json",
            }
            if all(f in non_essential for f in changed_files):
                print("Only state files changed, skipping AutoDist commit")
                return True

        current_time = datetime.datetime.now().strftime("%Y%m%d %H%M%S")
        commit_message = "AutoDist at {}".format(current_time)

        # Add and commit must FAIL CLOSED (senzhang-todo #1709).
        #
        # These two used to be bare subprocess.run() with no returncode check, and
        # the code then force-pushed regardless. So when `git add` hit a stale
        # .git/index.lock, it failed, the commit failed, and the publisher pushed
        # and reported success having committed nothing -- every tick, silently,
        # for as long as the lock sat there. Observed twice on 2026-07-13 (wedged
        # 13 min, then 22 min). The user-visible symptom is on OTHER machines: no
        # publish lands, so no publish-status reaches InfraWatch, so EA_Dist's
        # SYSTEM.alert_missing_schedule_update() duck-pops "Last publish was N days
        # ago". The alarm was right; this was the bug it was pointing at.

        add_result = subprocess.run(
            [get_git_executable(), "add", "."],
            cwd=repo_dir, capture_output=True, text=True, timeout=120,
        )
        if add_result.returncode != 0:
            stderr = (add_result.stderr or "").strip()
            # By far the most common cause, and it is self-inflicted: a previous
            # run died mid-operation and left the lock behind. Name it explicitly
            # so the fix is obvious instead of buried in a generic git error.
            if "index.lock" in stderr:
                msg = (
                    "AutoDist: git add failed on a stale .git/index.lock. A previous "
                    "run died mid-operation. Publishing is BLOCKED until it is removed: "
                    "delete {}".format(os.path.join(repo_dir, ".git", "index.lock"))
                )
            else:
                msg = "AutoDist: git add failed (rc={}): {}".format(
                    add_result.returncode, stderr[:500])
            print(msg)
            _report_publish_error_to_errordump(msg)
            return False  # do NOT push a commit that was never made

        commit_result = subprocess.run(
            [get_git_executable(), "commit", "-m", commit_message],
            cwd=repo_dir, capture_output=True, text=True, timeout=120,
        )
        if commit_result.returncode != 0:
            combined = ((commit_result.stdout or "") + (commit_result.stderr or "")).lower()
            # `git commit` exits non-zero when there is simply nothing staged. That
            # is a normal no-op, not a failure -- do not alarm on it.
            if "nothing to commit" in combined or "working tree clean" in combined:
                print("AutoDist: nothing to commit, skipping push")
                return True
            msg = "AutoDist: git commit failed (rc={}): {}".format(
                commit_result.returncode,
                ((commit_result.stderr or commit_result.stdout) or "").strip()[:500])
            print(msg)
            _report_publish_error_to_errordump(msg)
            return False  # do NOT force-push on a failed commit


        # Try multiple push strategies with retry logic
        push_strategies = [
            [get_git_executable(), "push", "-f", "--no-verify", "origin", "main"],
            [get_git_executable(), "push", "-f", "--no-verify", "--no-thin", "origin", "main"],
            [get_git_executable(), "push", "-f", "--no-verify", "--progress", "origin", "main"],
            [get_git_executable(), "push", "origin", "main"]  # Non-force push as last resort
        ]
        
        for attempt, push_command in enumerate(push_strategies, 1):
            print("Push attempt {}/{}: {}".format(attempt, len(push_strategies), ' '.join(push_command)))
            
            try:
                push_result = subprocess.run(
                    push_command,
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=60*10  # 10 minutes timeout
                )
                
                if push_result.returncode == 0:
                    print("✅ Git push successful using strategy {}".format(attempt))
                    return True
                else:
                    error_msg = push_result.stderr.strip()
                    print("❌ Push attempt {} failed: {}".format(attempt, error_msg))
                    
                    # Check for specific errors
                    if "HTTP 500" in error_msg or "curl 22" in error_msg:
                        print("🔍 HTTP 500 error detected - this is a server-side issue")
                        if attempt < len(push_strategies):
                            print("⏳ Waiting with jitter before next attempt...")
                            _sleep_jitter_backoff(4, base=30.0, cap=150.0)
                        else:
                            print("💡 All strategies failed. Consider:")
                            print("   - Checking GitHub status: https://www.githubstatus.com/")
                            print("   - Trying again later")
                            print("   - Using GitHub Desktop as alternative")
                    elif attempt < len(push_strategies):
                        print("⏳ Waiting with jitter before next attempt...")
                        _sleep_jitter_backoff(attempt, base=4.0, cap=90.0)
                        
            except subprocess.TimeoutExpired:
                print("⏰ Push attempt {} timed out after 10 minutes".format(attempt))
                if attempt < len(push_strategies):
                    print("⏳ Waiting with jitter before next attempt...")
                    _sleep_jitter_backoff(attempt + 2, base=8.0, cap=120.0)
            except Exception as e:
                print("❌ Unexpected error in push attempt {}: {}".format(attempt, str(e)))
                if attempt < len(push_strategies):
                    print("⏳ Waiting with jitter before next attempt...")
                    _sleep_jitter_backoff(attempt, base=4.0, cap=90.0)
        
        print("❌ All push strategies failed")
        return False
            
    except Exception as e:
        print("Error during git push:")
        print(traceback.format_exc())
        return False

def run_publish_script(mode="scheduler", stop_event=None, run_id=None):
    """Execute the main publish script with enhanced monitoring and error recovery.

    Runs the ________publish.py script and captures its output
    and return code to determine success or failure. Includes
    pre-execution checks and post-execution verification.

    Args:
        mode: ``scheduler`` or ``manual`` (passed to child via env).
        stop_event: Optional ``threading.Event``; when set, child process is terminated.
        run_id: Correlation id for logs and API; generated if omitted.

    Returns:
        tuple: (success, error_reason, traceback_info) where:
            - success: bool indicating if publish was successful
            - error_reason: str describing the error (None if successful)
            - traceback_info: str containing full traceback (None if successful)
    """
    run_id = run_id or str(uuid.uuid4())
    publish_started = False
    final_success = False
    final_err = None
    process = None
    reader_t = None
    try:
        print("\n" + "="*80)
        current_time = datetime.datetime.now().strftime("%Y%m%d %H%M%S")
        print("Starting publish job at {} run_id={}".format(current_time, run_id))
        _log_json_event("info", "publish_job_start", run_id=run_id, mode=mode)

        if not _pre_publish_health_check():
            final_err = "Pre-publish health check failed"
            print("❌ {}".format(final_err))
            return False, final_err, None

        if check_computer_name_for_pull_by_self():
            pull_success = git_pull_main()
            if not pull_success:
                print("Warning: Git pull failed, continuing with publish using local files")

        publish_script = os.path.join(os.path.dirname(__file__), "________publish.py")
        if not os.path.exists(publish_script):
            final_err = "Publish script not found at {}".format(publish_script)
            print("Error: {}".format(final_err))
            return False, final_err, None

        mark_publish_run_started(run_id, mode)
        publish_started = True

        env = os.environ.copy()
        env["GIT_HTTP_MAX_REQUEST_BUFFER"] = "100M"
        env["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"
        env["GIT_HTTP_LOW_SPEED_TIME"] = "600"
        env["GIT_TERMINAL_PROGRESS"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["ENNEADTAB_PUBLISH_MODE"] = mode
        env["ENNEADTAB_PUBLISH_RUN_ID"] = run_id

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        process = subprocess.Popen(
            [sys.executable, publish_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

        out_q = _queue_mod.Queue()
        reader_t = threading.Thread(
            target=_popen_stdout_reader,
            args=(process.stdout, out_q, stop_event),
        )
        reader_t.daemon = True
        reader_t.start()

        start_time = time.time()
        last_activity = start_time
        timeout_seconds = 7200
        lines_seen = 0
        last_silent_bucket = -1

        while True:
            if stop_event is not None and stop_event.is_set():
                _log_json_event("warn", "publish_cancelled", run_id=run_id)
                _terminate_publish_process_tree(process)
                final_err = "Cancelled by operator"
                try:
                    reader_t.join(timeout=5)
                except Exception:
                    pass
                return False, final_err, None

            try:
                line = out_q.get(timeout=1.0)
            except _queue_mod.Empty:
                line = _NO_QUEUE_LINE

            if line is _NO_QUEUE_LINE:
                if process.poll() is not None:
                    break
                idle = time.time() - last_activity
                if idle > 300:
                    idle_bucket = int(idle // 300)
                    if idle_bucket != last_silent_bucket:
                        last_silent_bucket = idle_bucket
                        if idle_bucket == 1:
                            print("[WARN] No output for 5+ minutes, process still running...")
                            _log_json_event("warn", "publish_silent_5m", run_id=run_id, silent_sec=int(idle))
                        elif idle_bucket == 3:
                            _log_json_event("error", "publish_silent_15m", run_id=run_id, silent_sec=int(idle))
                        elif idle_bucket >= 6:
                            _log_json_event("critical", "publish_silent_30m", run_id=run_id, silent_sec=int(idle))
                write_heartbeat_file(
                    state="publishing",
                    run_id=run_id,
                    mode=mode,
                    lines_seen=lines_seen,
                    silent_sec=int(time.time() - last_activity),
                )
                continue

            if line is None:
                break

            if not isinstance(line, str):
                continue

            print(line.rstrip())
            last_activity = time.time()
            lines_seen += 1
            last_silent_bucket = -1

            if time.time() - start_time > timeout_seconds:
                final_err = "Publish script timed out after {} hours".format(timeout_seconds // 3600)
                print("⏰ {}".format(final_err))
                _terminate_publish_process_tree(process)
                try:
                    reader_t.join(timeout=5)
                except Exception:
                    pass
                return False, final_err, None

        try:
            reader_t.join(timeout=15)
        except Exception:
            pass

        if process.poll() is None:
            try:
                process.wait(timeout=60)
            except Exception:
                pass

        result = process.poll()
        if result == 0:
            print("[OK] Publish completed successfully.")
            final_success = True
            return True, None, None

        final_err = "Publish failed with exit code {}".format(result)
        print("[ERROR] {}".format(final_err))
        return False, final_err, None

    except subprocess.TimeoutExpired:
        final_err = "Publish script timed out after 2 hours"
        print("⏰ {}".format(final_err))
        if process is not None:
            _terminate_publish_process_tree(process)
        return False, final_err, None
    except Exception as e:
        final_err = "Error during publish execution: {}".format(str(e))
        traceback_info = traceback.format_exc()
        print("[ERROR] {}".format(final_err))
        if process is not None:
            _terminate_publish_process_tree(process)
        return False, final_err, traceback_info
    finally:
        if publish_started:
            mark_publish_run_finished(final_success, final_err)
        if publish_started:
            if final_success:
                _SCHEDULER_COUNTERS["consecutive_publish_failures"] = 0
            elif final_err and "Cancelled by operator" not in final_err:
                _SCHEDULER_COUNTERS["consecutive_publish_failures"] += 1
        print("="*80 + "\n")

def _pre_publish_health_check():
    """
    Perform pre-publish health checks for the scheduler.
    
    Returns:
        bool: True if all checks pass, False otherwise
    """
    print("🔍 Performing scheduler pre-publish health checks...")
    
    try:
        # Check disk space
        import shutil
        script_dir = os.path.dirname(__file__)
        _total, _used, free = shutil.disk_usage(script_dir)
        free_gb = free / (1024**3)
        
        if free_gb < 10:  # Less than 10GB free
            print(f"[ERROR] Insufficient disk space: {free_gb:.1f}GB free (need at least 10GB)")
            return False
        else:
            print(f"[OK] Disk space: {free_gb:.1f}GB free")
        
        # Check network connectivity (short jittered retries)
        import urllib.request
        net_ok = False
        for attempt in range(1, 4):
            try:
                urllib.request.urlopen("https://github.com", timeout=10)
                net_ok = True
                break
            except Exception as e:
                if attempt >= 3:
                    print(f"[ERROR] Network connectivity failed: {str(e)}")
                    return False
                _sleep_jitter_backoff(attempt, base=2.0, cap=30.0)
        if net_ok:
            print("[OK] Network connectivity: OK")
        
        # Check if publish script exists and is accessible
        publish_script = os.path.join(script_dir, "________publish.py")
        if not os.path.exists(publish_script):
            print(f"[ERROR] Publish script not found: {publish_script}")
            return False
        
        # Check script permissions
        if not os.access(publish_script, os.R_OK):
            print(f"[ERROR] Publish script not readable: {publish_script}")
            return False
        
        print("[OK] Publish script accessible")
        
        # Check git remote status (ahead/behind) for better debugging visibility
        try:
            repo_dir = _REPO_ROOT
            status_result = subprocess.run(
                [get_git_executable(), "status", "--porcelain", "--branch"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if status_result.returncode == 0 and status_result.stdout.strip():
                lines = status_result.stdout.strip().splitlines()
                remote_status = "Unknown"
                for line in lines:
                    if line.startswith("##"):
                        if "ahead" in line and "behind" in line:
                            remote_status = "Diverged from remote"
                        elif "ahead" in line:
                            remote_status = "Ahead of remote"
                        elif "behind" in line:
                            remote_status = "Behind remote"
                        else:
                            remote_status = "Up to date with remote"
                        break
                print(f"[OK] Git remote status: {remote_status}")
                if remote_status in ("Behind remote", "Diverged from remote"):
                    print("⚠️  Scheduler starting while repository is not up-to-date with remote.")
            else:
                stderr = status_result.stderr.strip()
                if stderr:
                    print(f"[WARN] Could not determine git remote status: {stderr}")
                else:
                    print("[WARN] Could not determine git remote status (no output).")
        except Exception as e:
            print(f"[WARN] Git remote status check failed: {str(e)}")
        
        # Check Python environment
        try:
            result = subprocess.run([sys.executable, "--version"], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"✅ Python environment: {result.stdout.strip()}")
            else:
                print("[ERROR] Python environment check failed")
                return False
        except Exception as e:
            print(f"[ERROR] Python environment check failed: {str(e)}")
            return False
        
        print("✅ All scheduler pre-publish health checks passed")
        return True
        
    except Exception as e:
        print(f"❌ Scheduler pre-publish health check failed: {str(e)}")
        return False



def register_with_task_scheduler():
    """
    Register this script with Windows Task Scheduler to run on system startup.
    Only registers if running on an allowed computer.
    
    Returns:
        bool: True if registration was successful or not needed, False if failed
    """
    if not check_computer_name_for_pull_by_self():
        return True  # Not an error, just not needed
    
    if win32com is None:
        print("win32com not available, skipping Task Scheduler registration")
        return True  # Not an error, just not available
        
    try:
        tick_bat = os.path.join(_PUBLISH_DIR, "_run_schedule_publish_tick.bat")
        if not os.path.isfile(tick_bat):
            print("Tick batch not found: {}".format(tick_bat))
            return False

        # Create task scheduler object
        scheduler = win32com.client.Dispatch('Schedule.Service')
        scheduler.Connect()
        
        # Get the root folder
        root_folder = scheduler.GetFolder("\\")
        
        # Create task definition
        task_def = scheduler.NewTask(0)
        
        # Set task settings — logon trigger; prefer register bat for production (every 10 min)
        TASK_TRIGGER_LOGON = 9
        trigger = task_def.Triggers.Create(TASK_TRIGGER_LOGON)
        trigger.Id = "EnneadTabPublisherTrigger"
        trigger.Delay = "PT1M"  # Start 1 minute after logon
        
        # Create action
        TASK_ACTION_EXEC = 0
        action = task_def.Actions.Create(TASK_ACTION_EXEC)
        action.Path = "cmd.exe"
        action.Arguments = '/c "{}"'.format(tick_bat)
        
        # Set task settings
        task_def.Settings.Enabled = True
        task_def.Settings.StopIfGoingOnBatteries = False
        task_def.Settings.DisallowStartIfOnBatteries = False
        task_def.Settings.RunOnlyIfNetworkAvailable = True
        task_def.Settings.StartWhenAvailable = True
        task_def.Settings.RestartInterval = "PT1M"  # Retry every minute if failed
        task_def.Settings.RestartCount = 3  # Try 3 times
        try:
            TASK_MULTIPLE_INSTANCES_IGNORE_NEW = 2
            task_def.Settings.MultipleInstances = TASK_MULTIPLE_INSTANCES_IGNORE_NEW
        except Exception:
            pass
        
        # Register the task
        TASK_CREATE_OR_UPDATE = 6
        TASK_LOGON_NONE = 0
        root_folder.RegisterTaskDefinition(
            "EnneadTab Publisher",  # Task name
            task_def,
            TASK_CREATE_OR_UPDATE,
            None,  # No user
            None,  # No password
            TASK_LOGON_NONE
        )
        
        print("Successfully registered with Windows Task Scheduler")
        return True
        
    except Exception as e:
        print("Error registering with Task Scheduler: {}".format(str(e)))
        print(traceback.format_exc())
        return False

def main():
    """Main entry point for the schedule publisher.

    --tick / --console: one headless cycle for Task Scheduler (no GUI, exits).
    Default: optional monitoring GUI (start scheduler manually in the UI).
    """
    args = set(sys.argv[1:])
    tick_mode = "--tick" in args or "--console" in args
    dry_run = "--dry-run" in args
    force = "--force" in args

    if dry_run:
        tick_mode = True
    if force:
        tick_mode = True

    if tick_mode:
        if not dry_run:
            _recover_stale_tick_lock()
            _warn_if_gh_auth_missing()
        if not dry_run and not _acquire_single_instance_mutex():
            write_tick_status("skipped_busy", "another publisher instance is already running")
            sys.exit(0)
        exit_code = run_scheduler_tick(dry_run=dry_run, force=force)
        sys.exit(exit_code)

    if not dry_run and not _acquire_single_instance_mutex():
        sys.exit(0)

    root = tk.Tk()
    PublisherGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
