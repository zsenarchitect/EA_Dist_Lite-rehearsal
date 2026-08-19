try:
    import os
    import winshell
    import subprocess
    import ctypes
    import _Exe_Util
    import logging


    print("🦆 Quack! All my ducky modules loaded successfully!")
except ImportError as e:
    print(f"🦆 Missing module: {str(e)}")


try:
    import sys
    sys.path.append(os.path.join(_Exe_Util.CORE_LIB_FOLDER, _Exe_Util.PLUGIN_NAME))
    from SYSTEM import APPS, TaskType
    from TASK_REGISTER import weekly_schedule_from_app
    all_good = True
except:
    all_good = False


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "startup_registration.log"))
    ]
)




def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def create_shortcut(app_path, shortcut_name, description):
    startup_folder = os.path.join(
        os.environ['APPDATA'], 
        'Microsoft', 
        'Windows', 
        'Start Menu', 
        'Programs', 
        'Startup'
    )
    shortcut_path = os.path.join(startup_folder, f"{shortcut_name}.lnk")
    
    winshell.CreateShortcut(
        Path=shortcut_path,
        Target=app_path,
        Description=description
    )
    logging.info("Created startup shortcut: %s", shortcut_path)

def remove_shortcut(shortcut_name):
    """Remove shortcut from startup folder if it exists."""
    startup_folder = os.path.join(
        os.environ['APPDATA'], 
        'Microsoft', 
        'Windows', 
        'Start Menu', 
        'Programs', 
        'Startup'
    )
    shortcut_path = os.path.join(startup_folder, f"{shortcut_name}.lnk")
    
    if os.path.exists(shortcut_path):
        try:
            os.remove(shortcut_path)
            logging.info("Removed startup shortcut: %s", shortcut_path)
            return True
        except Exception as e:
            logging.error("Failed to remove shortcut %s: %s", shortcut_path, str(e))
            return False
    else:
        logging.info("Shortcut not found to remove: %s", shortcut_path)
        return True  # Not an error if it doesn't exist

def _task_run_value(app_path, task_args=""):
    """Build the schtasks /tr value with the program path in ESCAPED quotes.

    The program path must be quoted so a space (e.g. the "EnneadTab Ecosystem"
    folder every EA_Dist lives under) does not split it into program + args.
    Because the whole /tr value is itself wrapped in quotes on the command
    line, those inner quotes must be BACKSLASH-escaped:

        /tr "\\"C:\\EnneadTab Ecosystem\\...\\x.exe\\""

    The old code emitted plain doubled quotes (/tr ""C:\\...Ecosystem\\...x.exe""),
    which cmd split at the space -> "ERROR: Invalid argument" -> the non-zero
    exit was swallowed -> the task silently never registered. A single pair of
    quotes is worse still: schtasks exits 0 but stores a CORRUPTED action
    (program = everything before the space). Escaped quotes are the only form
    that both succeeds and stores a resolvable program path.
    """
    quoted = '\\"{}\\"'.format(app_path)
    if task_args:
        return '{} {}'.format(quoted, task_args)
    return quoted


def _create_task(cmd, task_name, kind):
    """Run a schtasks /create command and VERIFY the task actually landed.

    A zero exit code is NOT proof the task is correct: schtasks can exit 0
    while silently corrupting the stored action (an unquoted spaced path is
    kept split). So we do not trust the return code -- we query the task back.
    Captured stderr is logged instead of being swallowed, so a future failure
    is diagnosable from startup_registration.log instead of invisible.
    """
    try:
        result = subprocess.run(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except Exception as e:
        logging.error("Failed to invoke schtasks for %s task %s: %s", kind, task_name, str(e))
        return False
    if result.returncode != 0:
        logging.error(
            "schtasks failed (rc=%s) for %s task %s. cmd=%s stderr=%s",
            result.returncode, kind, task_name, cmd, (result.stderr or "").strip(),
        )
        return False
    check = subprocess.run(
        'schtasks /query /tn "{}"'.format(task_name), shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    if check.returncode != 0:
        logging.error(
            "%s task %s reported created but is NOT present on query. stderr=%s",
            kind, task_name, (check.stderr or "").strip(),
        )
        return False
    logging.info("Scheduled %s task created and verified: %s", kind, task_name)
    return True


def schedule_repeat_task(task_name, app_path, interval_minutes, task_args=""):
    """Schedule a task to run at specified intervals."""
    cmd_base = 'schtasks /create /f /tn "{}" /tr "{}" /sc minute /mo {}'
    tr = _task_run_value(app_path, task_args)
    cmd = cmd_base.format(task_name, tr, interval_minutes)
    if is_admin():
        cmd += ' /rl highest'
    _create_task(cmd, task_name, "repeat (every {} min)".format(interval_minutes))

def schedule_daily_task(task_name, app_path, daily_time, task_args=""):
    """Schedule a task to run daily at a specific time."""
    tr = _task_run_value(app_path, task_args)
    cmd = 'schtasks /create /f /tn "{}" /tr "{}" /sc daily /st {}'.format(
        task_name, tr, daily_time
    )
    if is_admin():
        cmd += ' /rl highest'
    _create_task(cmd, task_name, "daily @ {}".format(daily_time))

def schedule_weekly_task(task_name, app_path, weekly_day, weekly_time, task_args=""):
    """Schedule a task to run weekly on a given day/time."""
    tr = _task_run_value(app_path, task_args)
    cmd = 'schtasks /create /f /tn "{}" /tr "{}" /sc WEEKLY /D {} /ST {}'.format(
        task_name, tr, weekly_day, weekly_time
    )
    if is_admin():
        cmd += ' /rl highest'
    _create_task(cmd, task_name, "weekly {} @ {}".format(weekly_day, weekly_time))

def remove_task(task_name):
    """Remove scheduled task if it exists."""
    cmd = f'schtasks /query /tn "{task_name}" > nul 2>&1'
    
    # Check if task exists
    if subprocess.run(cmd, shell=True).returncode == 0:
        try:
            delete_cmd = f'schtasks /delete /f /tn "{task_name}"'
            subprocess.run(delete_cmd, shell=True, check=True)
            logging.info("Removed scheduled task: %s", task_name)
            return True
        except subprocess.CalledProcessError as e:
            logging.error("Failed to remove scheduled task %s: %s", task_name, str(e))
            return False
    else:
        logging.info("Task not found to remove: %s", task_name)
        return True  # Not an error if it doesn't exist

def process_application(app_config):
    """Process an application configuration to set up startup and scheduled tasks.
    
    Args:
        app_config (dict): Configuration dictionary containing app details
            - app_name: Name of the application
            - file_name: Executable filename
            - shortcut_name: Name for the startup shortcut
            - description: Description for the shortcut
            - active: Whether the app should be active
            - task_type: TaskType enum (STARTUP, REPEAT, DAILY, WEEKLY)
            - task_name: (optional) Name for scheduled task
            - task_args: (optional) CLI args appended to /tr
            - interval_minutes: (required for REPEAT) Minutes between task runs
            - daily_time: (required for DAILY) Time to run daily (e.g. "11:45")
            - weekly_day / weekly_time / stagger_weekly: (WEEKLY) schedule
    """
    app_name = app_config["app_name"]
    is_active = app_config.get("active", True)
    shortcut_name = app_config["shortcut_name"]
    task_type = app_config.get("task_type", TaskType.STARTUP)

    # InfraWatch_* tasks are owned by INFRAWATCH.register_if_needed() (repair hook).
    if app_name.startswith("InfraWatch_"):
        if not is_active and "task_name" in app_config:
            remove_task(app_config["task_name"])
        return
    if is_active:
        logging.info("Processing active application: %s", app_name)
        
        app_path = os.path.join(_Exe_Util.EXE_PRODUCT_FOLDER, app_config["file_name"])
        if not os.path.exists(app_path):
            logging.warning("Application file not found: %s", app_path)
            return

        # Always create a startup shortcut regardless of task type
        create_shortcut(app_path, 
                       shortcut_name,
                       app_config["description"])
        
        # Process based on task type
        task_args = app_config.get("task_args", "")
        hostname = os.environ.get("COMPUTERNAME", "")

        if task_type == TaskType.STARTUP:
            # No scheduled task needed, just the startup shortcut
            pass
        
        elif task_type == TaskType.REPEAT and "task_name" in app_config and "interval_minutes" in app_config:
            schedule_repeat_task(
                app_config["task_name"],
                app_path,
                app_config["interval_minutes"],
                task_args,
            )
        
        elif task_type == TaskType.DAILY and "task_name" in app_config and "daily_time" in app_config:
            schedule_daily_task(
                app_config["task_name"],
                app_path,
                app_config["daily_time"],
                task_args,
            )

        elif task_type == TaskType.WEEKLY and "task_name" in app_config:
            weekly_day, weekly_time = weekly_schedule_from_app(app_config, hostname)
            schedule_weekly_task(
                app_config["task_name"],
                app_path,
                weekly_day,
                weekly_time,
                task_args,
            )
    
    else:
        logging.info("Processing inactive application: %s", app_name)
        
        # Remove shortcut for inactive apps
        remove_shortcut(shortcut_name)
        
        # Remove scheduled task if it exists
        if "task_name" in app_config:
            remove_task(app_config["task_name"])




@_Exe_Util.try_catch_error
def main():
    if not all_good:
        logging.error("Failed to import APPS module")
        return
    logging.info("Starting RegisterAutoStartup process")
    for app in APPS:
        process_application(app)
    logging.info("Completed RegisterAutoStartup process")

if __name__ == "__main__":
    main()
