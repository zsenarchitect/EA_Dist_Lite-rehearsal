# -*- coding: utf-8 -*-
"""Shared Windows Task Scheduler registration for EnneadTab APPS entries.

Used by INFRAWATCH.register_if_needed() (IronPython repair hook) and
RegisterAutoStartup.exe (enrollment pass). IronPython 2.7 compatible.
"""

import hashlib
import subprocess

try:
    from EnneadTab.SYSTEM import TaskType
except ImportError:
    class TaskType(object):
        STARTUP = "startup"
        REPEAT = "repeat"
        DAILY = "daily"
        WEEKLY = "weekly"


def task_exists(name):
    cmd = 'schtasks /query /tn "{}" >nul 2>&1'.format(name)
    try:
        rc = subprocess.call(cmd, shell=True)
        return rc == 0
    except Exception:
        return False


def delete_task(name):
    cmd = 'schtasks /delete /tn "{}" /f >nul 2>&1'.format(name)
    try:
        subprocess.call(cmd, shell=True)
    except Exception:
        pass


def build_task_run_command(program_path, task_args):
    """Quote program path; append optional CLI args for schtasks /tr."""
    args = (task_args or "").strip()
    if args:
        return '\\"{}\\" {}'.format(program_path, args)
    return '\\"{}\\"'.format(program_path)


def compute_weekly_stagger(hostname):
    """Deterministic weekly day + off-hours time from hostname hash."""
    digest = hashlib.md5(hostname.upper().encode("ascii")).hexdigest()
    h = int(digest, 16)
    days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
    weekly_day = days[h % 7]
    offset_min = (h // 7) % 360
    weekly_time = "{:02d}:{:02d}".format(2 + offset_min // 60, offset_min % 60)
    return weekly_day, weekly_time


def weekly_schedule_from_app(app_config, hostname):
    if app_config.get("stagger_weekly"):
        return compute_weekly_stagger(hostname)
    return app_config.get("weekly_day", "SUN"), app_config.get("weekly_time", "02:00")


def create_repeat_task(name, program_path, task_args, interval_minutes):
    tr = build_task_run_command(program_path, task_args)
    cmd = (
        'schtasks /create /tn "{}" /tr "{}" /sc minute /mo {} /f >nul 2>&1'
    ).format(name, tr, int(interval_minutes))
    try:
        rc = subprocess.call(cmd, shell=True)
        return rc == 0
    except Exception:
        return False


def create_weekly_task(name, program_path, task_args, weekly_day, weekly_time):
    tr = build_task_run_command(program_path, task_args)
    cmd = (
        'schtasks /create /tn "{}" /tr "{}" /sc WEEKLY /D {} /ST {} /f >nul 2>&1'
    ).format(name, tr, weekly_day, weekly_time)
    try:
        rc = subprocess.call(cmd, shell=True)
        return rc == 0
    except Exception:
        return False


def create_daily_task(name, program_path, task_args, daily_time):
    tr = build_task_run_command(program_path, task_args)
    cmd = (
        'schtasks /create /tn "{}" /tr "{}" /sc daily /st {} /f >nul 2>&1'
    ).format(name, tr, daily_time)
    try:
        rc = subprocess.call(cmd, shell=True)
        return rc == 0
    except Exception:
        return False


def register_app_task(program_path, app_config, hostname, skip_if_exists=True):
    """Create scheduled task from an APPS entry. Returns True if created."""
    task_name = app_config.get("task_name")
    if not task_name:
        return False
    if skip_if_exists and task_exists(task_name):
        return False

    task_type = app_config.get("task_type")
    task_args = app_config.get("task_args", "")

    if task_type == TaskType.REPEAT:
        interval = app_config.get("interval_minutes", 60)
        return create_repeat_task(task_name, program_path, task_args, interval)
    if task_type == TaskType.WEEKLY:
        weekly_day, weekly_time = weekly_schedule_from_app(app_config, hostname)
        return create_weekly_task(
            task_name, program_path, task_args, weekly_day, weekly_time
        )
    if task_type == TaskType.DAILY:
        daily_time = app_config.get("daily_time", "02:00")
        return create_daily_task(task_name, program_path, task_args, daily_time)
    return False
