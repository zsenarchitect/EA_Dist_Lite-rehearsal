#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
AutoExporter Orchestrator

Runs outside Revit (CPython 3.9). Discovers AutoExportConfig_*.json files and processes them sequentially.
Launches pyRevit to run scripts inside Revit (IronPython 2.7). Uses JSON files for inter-process communication.
"""

import os
import sys
import json
import time
import subprocess
import glob
import argparse
from datetime import datetime


# =============================================================================
# CONSTANTS
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIGS_DIR = os.path.join(SCRIPT_DIR, "configs")
PAYLOAD_FILE = os.path.join(SCRIPT_DIR, "current_job_payload.json")
STATUS_FILE = os.path.join(SCRIPT_DIR, "current_job_status.json")
LOCK_FILE = os.path.join(SCRIPT_DIR, "orchestrator.lock")

DEFAULT_TIMEOUT_MINUTES = 30
DEFAULT_COOLDOWN_SECONDS = 10
LOCK_FILE_MAX_AGE_HOURS = 24
MIN_DISK_SPACE_GB = 5

# Determine environment (dev vs dist)
DEV_ROOT = os.path.join(os.environ.get('USERPROFILE', ''), 'github', 'EnneadTab-OS')
DIST_ROOT = os.path.join(os.environ.get('USERPROFILE', ''), 'Documents', 'EnneadTab Ecosystem', 'EA_Dist')

if os.path.exists(os.path.join(DEV_ROOT, 'Apps', '_revit', 'KingDuck.lib')):
    ROOT_PATH = DEV_ROOT
else:
    ROOT_PATH = DIST_ROOT

IMPORT_PATH = os.path.join(ROOT_PATH, 'Apps', '_revit', 'KingDuck.lib')
EMPTY_DOC_DIR = os.path.join(ROOT_PATH, 'Apps', '_revit', 'DuckMaker.extension', 
                              'EnneadTab.tab', 'Magic.panel', 'misc.pulldown', 
                              'auto_upgrade.pushbutton')


# =============================================================================
# LOGGING
# =============================================================================

class OrchestratorLogger:
    """Logger for orchestrator events"""
    
    def __init__(self):
        self.log_dir = os.path.join(SCRIPT_DIR, "orchestrator_logs")
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        self.log_file = os.path.join(
            self.log_dir, 
            "orchestrator_{}.log".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        
        self._log("="*80)
        self._log("AUTOEXPORTER ORCHESTRATOR LOG")
        self._log("="*80)
    
    def _log(self, message, level="INFO"):
        """Write log entry"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = "[{}] [{}] {}".format(timestamp, level, message)
        print(log_line)
        
        with open(self.log_file, 'a') as f:
            f.write(log_line + "\n")
    
    def info(self, message):
        self._log(message, "INFO")
    
    def warning(self, message):
        self._log(message, "WARNING")
    
    def error(self, message):
        self._log(message, "ERROR")
    
    def success(self, message):
        self._log(message, "SUCCESS")
    
    def debug(self, message):
        self._log(message, "DEBUG")
    
    def get_log_file(self):
        return self.log_file


def write_orchestrator_heartbeat(job_id, step, message, is_error=False):
    """Write orchestrator-level heartbeat to track job progress from outside Revit
    
    This is critical for debugging jobs that hang before the Revit script runs.
    """
    try:
        heartbeat_dir = os.path.join(SCRIPT_DIR, "heartbeat")
        if not os.path.exists(heartbeat_dir):
            os.makedirs(heartbeat_dir)
        
        date_stamp = datetime.now().strftime("%Y%m%d")
        heartbeat_file = os.path.join(heartbeat_dir, "orchestrator_heartbeat_{}.log".format(date_stamp))
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "ERROR" if is_error else "OK"
        
        with open(heartbeat_file, 'a') as f:
            f.write("[{}] [JOB: {}] [ORCH-STEP {}] [{}] {}\n".format(
                timestamp, job_id, step, status, message))
        
        return heartbeat_file
    except Exception as e:
        print("Orchestrator heartbeat error: {}".format(e))
        return None


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def check_lock_file():
    """Check if orchestrator is already running"""
    if os.path.exists(LOCK_FILE):
        # Check if lock file is stale
        try:
            age_seconds = time.time() - os.path.getmtime(LOCK_FILE)
            age_hours = age_seconds / 3600.0
            
            if age_hours > LOCK_FILE_MAX_AGE_HOURS:
                print("Lock file is stale ({:.1f} hours old), removing...".format(age_hours))
                os.remove(LOCK_FILE)
                return False
            else:
                return True
        except:
            return True
    return False


def create_lock_file():
    """Create lock file"""
    with open(LOCK_FILE, 'w') as f:
        f.write("{}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def remove_lock_file():
    """Remove lock file"""
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except:
            pass


def cleanup_stale_files():
    """Remove stale payload and status files"""
    for filepath in [PAYLOAD_FILE, STATUS_FILE]:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print("Removed stale file: {}".format(os.path.basename(filepath)))
            except Exception as e:
                print("Warning: Could not remove {}: {}".format(filepath, e))


def cleanup_heartbeat_files():
    """Remove today's heartbeat files to prevent timestamp pollution between jobs
    
    This prevents the next job from inheriting old timestamps that trigger immediate timeouts.
    """
    heartbeat_dir = os.path.join(SCRIPT_DIR, "heartbeat")
    if os.path.exists(heartbeat_dir):
        try:
            date_stamp = datetime.now().strftime("%Y%m%d")
            heartbeat_file = os.path.join(heartbeat_dir, "heartbeat_{}.log".format(date_stamp))
            
            if os.path.exists(heartbeat_file):
                try:
                    os.remove(heartbeat_file)
                    print("Removed heartbeat file to reset activity tracking")
                except Exception as e:
                    print("Warning: Could not remove heartbeat file: {}".format(e))
        except Exception as e:
            print("Warning: Heartbeat cleanup error: {}".format(e))


def check_disk_space():
    """Check available disk space"""
    try:
        if sys.platform == 'win32':
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(SCRIPT_DIR), None, None, ctypes.pointer(free_bytes)
            )
            free_gb = free_bytes.value / (1024.0 ** 3)
            return free_gb
        return 999  # Unknown, assume OK
    except:
        return 999  # Unknown, assume OK


def check_pyrevit_available():
    """Check if pyrevit command is available"""
    try:
        result = subprocess.call(
            ['pyrevit', '--help'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        return result == 0
    except:
        return False


def kill_revit_processes(logger, specific_pid=None):
    """Kill Revit processes
    
    Args:
        logger: Logger instance
        specific_pid: If provided, kill only this specific PID. Otherwise kill all Revit.exe/RevitWorker.exe
    """
    try:
        import subprocess
        
        if specific_pid:
            # Kill specific PID only (and its children)
            try:
                # Check if PID still exists
                check_cmd = 'tasklist /FI "PID eq {}" /NH 2>NUL | find /I "{}"'.format(specific_pid, str(specific_pid))
                result = subprocess.call(check_cmd, shell=True, stdout=subprocess.PIPE)
                
                if result == 0:  # Process still exists
                    logger.info("Killing specific Revit PID {} and its children...".format(specific_pid))
                    # Kill process tree (parent and children)
                    kill_cmd = 'taskkill /F /T /PID {} >NUL 2>&1'.format(specific_pid)
                    subprocess.call(kill_cmd, shell=True)
                    time.sleep(2)  # Wait for cleanup
                else:
                    logger.info("Revit PID {} already terminated".format(specific_pid))
            except Exception as e:
                logger.warning("Error killing PID {}: {}".format(specific_pid, e))
        else:
            # Fallback: Kill ALL Revit.exe and RevitWorker.exe (old behavior)
            # Only kill Revit.exe and RevitWorker.exe, never pyrevit or python processes
            processes_to_kill = ['Revit.exe', 'RevitWorker.exe']
            
            for proc_name in processes_to_kill:
                try:
                    # Check if process exists
                    check_cmd = 'tasklist /FI "IMAGENAME eq {}" 2>NUL | find /I /N "{}"'.format(
                        proc_name, proc_name
                    )
                    result = subprocess.call(check_cmd, shell=True, stdout=subprocess.PIPE)
                    
                    if result == 0:  # Process found
                        logger.warning("Found lingering {}, killing ALL instances...".format(proc_name))
                        kill_cmd = 'taskkill /F /IM "{}" >NUL 2>&1'.format(proc_name)
                        subprocess.call(kill_cmd, shell=True)
                        time.sleep(2)  # Wait for cleanup
                except Exception as e:
                    logger.warning("Error checking/killing {}: {}".format(proc_name, e))
    except Exception as e:
        logger.error("Process cleanup error: {}".format(e))


# =============================================================================
# CONFIG DISCOVERY & VALIDATION
# =============================================================================

def discover_configs():
    """Discover all AutoExportConfig_*.json files in configs folder"""
    if not os.path.exists(CONFIGS_DIR):
        return []
    
    pattern = os.path.join(CONFIGS_DIR, "AutoExportConfig_*.json")
    config_files = glob.glob(pattern)
    
    # Sort alphabetically for consistent order
    config_files.sort()
    
    return config_files


def validate_config(config_path):
    """Validate a config file has required structure
    
    Returns:
        (is_valid, errors_list)
    """
    errors = []
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception as e:
        return (False, ["Failed to parse JSON: {}".format(str(e))])
    
    # Check required sections
    required_sections = ['project', 'models', 'export', 'email']
    for section in required_sections:
        if section not in config:
            errors.append("Missing required section: {}".format(section))
    
    # Check project section
    if 'project' in config:
        if 'project_name' not in config['project']:
            errors.append("Missing project.project_name")
    
    # Check models section
    if 'models' in config:
        if not config['models']:
            errors.append("No models defined")
        else:
            for model_name, model_data in config['models'].items():
                required_keys = ['model_guid', 'project_guid', 'region', 'revit_version']
                for key in required_keys:
                    if key not in model_data:
                        errors.append("Model '{}' missing: {}".format(model_name, key))
    
    # Check export section
    if 'export' in config:
        if 'output_base_path' not in config['export']:
            errors.append("Missing export.output_base_path")
    
    # Check email section
    if 'email' in config:
        if 'recipients' not in config['email'] or not config['email']['recipients']:
            errors.append("Missing or empty email.recipients")
    
    is_valid = len(errors) == 0
    return (is_valid, errors)


def validate_all_configs(config_paths, logger):
    """Validate all configs before processing
    
    Returns:
        (all_valid, validation_results)
    """
    logger.info("Validating {} config files...".format(len(config_paths)))
    
    validation_results = {}
    all_valid = True
    
    for config_path in config_paths:
        config_name = os.path.basename(config_path)
        is_valid, errors = validate_config(config_path)
        
        validation_results[config_name] = {
            'valid': is_valid,
            'errors': errors
        }
        
        if is_valid:
            logger.info("  [OK] {}".format(config_name))
        else:
            logger.error("  [FAIL] {}".format(config_name))
            for error in errors:
                logger.error("    - {}".format(error))
            all_valid = False
    
    return (all_valid, validation_results)


def parse_cli_args(argv=None):
    """Parse command-line arguments for orchestrator control."""
    parser = argparse.ArgumentParser(
        description="AutoExporter Orchestrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--sparc",
        action="store_true",
        help="Only run configs for SPARC (filters by filename/project metadata)"
    )
    return parser.parse_args(argv)


def filter_configs_by_flags(config_paths, cli_args, logger):
    """Filter discovered configs based on CLI flags."""
    filtered_paths = list(config_paths)
    
    if getattr(cli_args, "sparc", False):
        logger.info("SPARC flag detected - filtering configs to SPARC-only jobs")
        sparc_paths = []
        for path in filtered_paths:
            name = os.path.basename(path).lower()
            if "sparc" in name or "2412" in name:
                sparc_paths.append(path)
                continue
            
            # Inspect project metadata as fallback
            try:
                with open(path, 'r') as cfg_file:
                    cfg_data = json.load(cfg_file)
                project_name = cfg_data.get('project', {}).get('project_name', '')
                if project_name is None:
                    project_name = ''
                project_name_string = project_name if isinstance(project_name, str) else str(project_name)
                if "sparc" in project_name_string.lower():
                    sparc_paths.append(path)
            except Exception as cfg_error:
                logger.warning("  Could not inspect {} for SPARC metadata: {}".format(
                    os.path.basename(path),
                    cfg_error
                ))
        
        filtered_paths = sparc_paths
        logger.info("SPARC filter retained {} config(s)".format(len(filtered_paths)))
    
    return filtered_paths


# =============================================================================
# JOB EXECUTION
# =============================================================================

def write_payload(config_path, job_id, logger):
    """Write job payload file atomically"""
    payload = {
        "config_file": os.path.basename(config_path),
        "config_path": config_path,
        "job_id": job_id,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Write to temp file first
    temp_file = PAYLOAD_FILE + ".tmp"
    try:
        with open(temp_file, 'w') as f:
            json.dump(payload, f, indent=2)
        
        # Atomic rename
        if os.path.exists(PAYLOAD_FILE):
            os.remove(PAYLOAD_FILE)
        os.rename(temp_file, PAYLOAD_FILE)
        
        logger.info("Payload written: {}".format(job_id))
        return True
    except Exception as e:
        logger.error("Failed to write payload: {}".format(e))
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False


def get_revit_version_from_config(config_path):
    """Extract Revit version from config"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Get first model's Revit version
        models = config.get('models', {})
        if models:
            first_model = list(models.values())[0]
            return first_model.get('revit_version', '2026')
        return '2026'
    except:
        return '2026'


def get_timeout_from_config(config_path):
    """Extract timeout setting from config"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        orchestrator_settings = config.get('orchestrator', {})
        return orchestrator_settings.get('timeout_minutes', DEFAULT_TIMEOUT_MINUTES)
    except:
        return DEFAULT_TIMEOUT_MINUTES


def get_empty_doc_path(revit_version):
    """Get path to empty doc for given Revit version"""
    empty_doc = os.path.join(EMPTY_DOC_DIR, "empty_doc_{}.rvt".format(revit_version))
    
    if not os.path.exists(empty_doc):
        # Fallback to 2026
        empty_doc = os.path.join(EMPTY_DOC_DIR, "empty_doc_2026.rvt")
    
    return empty_doc


def launch_revit_job(config_path, job_id, logger):
    """Launch Revit with pyrevit to process the job
    
    Returns:
        (success, error_message, process) - process is None if failed
    """
    # Get Revit version from config
    revit_version = get_revit_version_from_config(config_path)
    logger.info("Revit version: {}".format(revit_version))
    write_orchestrator_heartbeat(job_id, "PREP", "Preparing to launch Revit {}".format(revit_version))
    
    # Get empty doc
    empty_doc = get_empty_doc_path(revit_version)
    if not os.path.exists(empty_doc):
        error_msg = "Empty doc not found: {}".format(empty_doc)
        write_orchestrator_heartbeat(job_id, "PREP_ERROR", error_msg, is_error=True)
        return (False, error_msg, None)
    
    logger.info("Empty doc: {}".format(empty_doc))
    
    # Build pyrevit command
    script_path = os.path.join(SCRIPT_DIR, "revit_auto_export_script.py")
    
    cmd = [
        'pyrevit', 'run',
        script_path,
        empty_doc,
        '--revit={}'.format(revit_version),
        '--purge',
        '--import={}'.format(IMPORT_PATH)
    ]
    
    logger.info("Launching Revit: {}".format(' '.join(cmd)))
    write_orchestrator_heartbeat(job_id, "LAUNCH", "Launching Revit {} via pyrevit CLI".format(revit_version))
    
    try:
        # Launch process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        
        write_orchestrator_heartbeat(job_id, "LAUNCHED", "Revit process started (PID: {}), waiting for script to run...".format(process.pid if hasattr(process, 'pid') else 'unknown'))
        logger.debug("Revit process PID: {}".format(process.pid if hasattr(process, 'pid') else 'unknown'))
        
        return (True, None, process)
    except Exception as e:
        error_msg = "Failed to launch pyrevit: {}".format(e)
        write_orchestrator_heartbeat(job_id, "LAUNCH_ERROR", error_msg, is_error=True)
        return (False, error_msg, None)


def get_latest_activity_time():
    """Get the most recent activity timestamp from status file or heartbeat logs
    
    Returns the latest modification time across monitored files, or None if no files exist
    """
    latest_time = None
    
    # Check status file
    if os.path.exists(STATUS_FILE):
        try:
            mtime = os.path.getmtime(STATUS_FILE)
            if latest_time is None or mtime > latest_time:
                latest_time = mtime
        except:
            pass
    
    # Check heartbeat log (today's file)
    heartbeat_dir = os.path.join(SCRIPT_DIR, "heartbeat")
    if os.path.exists(heartbeat_dir):
        try:
            date_stamp = datetime.now().strftime("%Y%m%d")
            heartbeat_file = os.path.join(heartbeat_dir, "heartbeat_{}.log".format(date_stamp))
            if os.path.exists(heartbeat_file):
                mtime = os.path.getmtime(heartbeat_file)
                if latest_time is None or mtime > latest_time:
                    latest_time = mtime
        except:
            pass
    
    return latest_time


def get_last_heartbeat_message():
    """Get the last heartbeat message from today's log file for debugging
    
    Returns the last line from the heartbeat log, or None if unavailable
    """
    heartbeat_dir = os.path.join(SCRIPT_DIR, "heartbeat")
    if not os.path.exists(heartbeat_dir):
        return None
    
    try:
        date_stamp = datetime.now().strftime("%Y%m%d")
        heartbeat_file = os.path.join(heartbeat_dir, "heartbeat_{}.log".format(date_stamp))
        
        if os.path.exists(heartbeat_file):
            with open(heartbeat_file, 'r') as f:
                lines = f.readlines()
                if lines:
                    return lines[-1].strip()
    except Exception as e:
        return "Error reading heartbeat: {}".format(e)
    
    return None


def wait_for_completion(process, config_path, job_id, logger):
    """Wait for job to complete with ACTIVITY-BASED timeout
    
    Timeout only triggers if there's NO progress (status/heartbeat updates) for the timeout duration.
    This allows long-running jobs to continue as long as they're making progress.
    
    Returns:
        (success, error_message, status_data)
    """
    timeout_minutes = get_timeout_from_config(config_path)
    timeout_seconds = timeout_minutes * 60
    start_time = time.time()
    
    logger.info("Waiting for completion (activity timeout: {} min)...".format(timeout_minutes))
    logger.info("Note: Timeout resets whenever progress is detected (status/heartbeat updates)")
    write_orchestrator_heartbeat(job_id, "WAIT_START", "Waiting for Revit process to complete (activity-based timeout: {} min idle)".format(timeout_minutes))
    
    check_interval = 5  # Check every 5 seconds
    heartbeat_interval = 30  # Write heartbeat every 30 seconds
    last_orchestrator_heartbeat_time = start_time
    
    # Track last activity time for intelligent timeout
    # IMPORTANT: Always start from job start time, NOT from old heartbeat files
    # This prevents inheriting stale timestamps from previous jobs
    last_activity_time = start_time
    last_reported_activity = start_time
    
    logger.debug("Activity tracking initialized to job start time (prevents stale timestamp bugs)")
    
    while True:
        current_time = time.time()
        total_elapsed = current_time - start_time
        
        # Check for new activity (status or heartbeat updates)
        latest_activity = get_latest_activity_time()
        if latest_activity is not None and latest_activity > last_activity_time:
            # Activity detected! Reset timeout
            idle_before = current_time - last_activity_time
            last_activity_time = latest_activity
            
            # Only log significant activity updates (more than 10 seconds since last report)
            if latest_activity > last_reported_activity + 10:
                logger.info("Progress detected - timeout timer reset (was idle for {:.0f}s)".format(idle_before))
                write_orchestrator_heartbeat(
                    job_id, 
                    "ACTIVITY", 
                    "Progress detected (status/heartbeat update) - timeout timer reset"
                )
                last_reported_activity = latest_activity
        
        # Calculate time since last activity
        idle_time = current_time - last_activity_time
        idle_minutes = idle_time / 60.0
        
        # Write periodic orchestrator heartbeat
        if current_time - last_orchestrator_heartbeat_time >= heartbeat_interval:
            total_minutes = total_elapsed / 60.0
            
            # Get last heartbeat message for better debugging
            last_msg = get_last_heartbeat_message()
            if last_msg and idle_minutes > 5:  # Show last activity if idle > 5 min
                logger.debug("Waiting... Total: {:.1f} min | Idle: {:.1f} min | Last: {}".format(
                    total_minutes, idle_minutes, last_msg[:80]))  # Truncate to 80 chars
            else:
                logger.debug("Waiting... Total: {:.1f} min | Idle: {:.1f} min".format(total_minutes, idle_minutes))
            
            write_orchestrator_heartbeat(
                job_id, 
                "WAIT_PROGRESS", 
                "Still waiting... Total: {:.1f} min | Idle: {:.1f} min / {} min timeout".format(
                    total_minutes, idle_minutes, timeout_minutes)
            )
            last_orchestrator_heartbeat_time = current_time
        
        # Check status file for terminal states (completed/failed) - allows moving to next job immediately
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, 'r') as f:
                    status_data = json.load(f)
                
                status = status_data.get('status')
                
                # Terminal states - return immediately without waiting for process exit
                if status in ['completed', 'failed']:
                    logger.info("Status '{}' detected in status file - proceeding to next job".format(status))
                    logger.info("Revit process will continue closing in background")
                    write_orchestrator_heartbeat(
                        job_id, 
                        "STATUS_COMPLETE", 
                        "Job marked '{}' in status file (Revit still closing) - moving to next job".format(status)
                    )
                    return (
                        status == 'completed', 
                        status_data.get('error') if status == 'failed' else None, 
                        status_data
                    )
            except Exception as e:
                # Ignore errors reading status file - will be caught by timeout or process check
                logger.debug("Could not read status file: {}".format(e))
                pass
        
        # Check ACTIVITY-BASED timeout (idle time, not total time)
        if idle_time > timeout_seconds:
            # Get last heartbeat for debugging
            last_msg = get_last_heartbeat_message()
            
            logger.error("Job timed out: No progress for {} minutes (total runtime: {:.1f} min)".format(
                timeout_minutes, total_elapsed / 60.0))
            
            if last_msg:
                logger.error("Last activity: {}".format(last_msg))
                write_orchestrator_heartbeat(
                    job_id, 
                    "TIMEOUT", 
                    "Job timed out after {} min idle - Last activity: {}".format(timeout_minutes, last_msg[:100]), 
                    is_error=True
                )
            else:
                write_orchestrator_heartbeat(
                    job_id, 
                    "TIMEOUT", 
                    "Job timed out: No activity (status/heartbeat updates) for {} minutes - process appears stuck".format(timeout_minutes), 
                    is_error=True
                )
            
            try:
                process.kill()
            except:
                pass
            return (False, "Timeout: No progress for {} minutes".format(timeout_minutes), None)
        
        # Check if process finished
        poll_result = process.poll()
        if poll_result is not None:
            # Process finished
            logger.info("Process exited with code: {} (total runtime: {:.1f} min)".format(
                poll_result, total_elapsed / 60.0))
            write_orchestrator_heartbeat(job_id, "PROCESS_EXIT", "Revit process exited with code: {}".format(poll_result))
            
            # Read status file
            if os.path.exists(STATUS_FILE):
                try:
                    with open(STATUS_FILE, 'r') as f:
                        status_data = json.load(f)
                    
                    if status_data.get('status') == 'completed':
                        write_orchestrator_heartbeat(job_id, "COMPLETED", "Job completed successfully")
                        return (True, None, status_data)
                    else:
                        error = status_data.get('error', 'Unknown error')
                        write_orchestrator_heartbeat(job_id, "FAILED", "Job failed: {}".format(error), is_error=True)
                        return (False, error, status_data)
                except Exception as e:
                    logger.error("Failed to read status file: {}".format(e))
                    write_orchestrator_heartbeat(job_id, "STATUS_ERROR", "Failed to read status file: {}".format(e), is_error=True)
                    return (False, "Failed to read status file", None)
            else:
                # No status file, check exit code
                if poll_result == 0:
                    write_orchestrator_heartbeat(job_id, "COMPLETED", "Process exited successfully (no status file)")
                    return (True, None, None)
                else:
                    write_orchestrator_heartbeat(job_id, "FAILED", "Process failed with exit code {}".format(poll_result), is_error=True)
                    return (False, "Process failed with exit code {}".format(poll_result), None)
        
        # Still running, wait and check again
        time.sleep(check_interval)


def process_job(config_path, logger):
    """Process a single config job
    
    Returns:
        (success, job_result_dict)
    """
    config_name = os.path.basename(config_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Extract project name from config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        project_name = config.get('project', {}).get('project_name', 'Unknown')
        # Also get model info for better debugging
        models = config.get('models', {})
        model_names = list(models.keys())
    except:
        project_name = 'Unknown'
        model_names = []
    
    job_id = "{}_{}".format(timestamp, project_name.replace(' ', '_'))
    
    logger.info("")
    logger.info("="*80)
    logger.info("Starting Job: {}".format(config_name))
    logger.info("Job ID: {}".format(job_id))
    logger.info("="*80)
    
    # Write initial orchestrator heartbeat
    write_orchestrator_heartbeat(job_id, "JOB_START", "Starting job: {} | Project: {} | Models: {}".format(
        config_name, project_name, ', '.join(model_names) if model_names else 'None'))
    
    start_time = time.time()
    
    # Write payload
    write_orchestrator_heartbeat(job_id, "PAYLOAD", "Writing job payload file")
    if not write_payload(config_path, job_id, logger):
        write_orchestrator_heartbeat(job_id, "PAYLOAD_ERROR", "Failed to write payload file", is_error=True)
        return (False, {
            'config': config_name,
            'job_id': job_id,
            'success': False,
            'error': 'Failed to write payload',
            'duration': 0
        })
    
    # Launch Revit job
    success, error, process = launch_revit_job(config_path, job_id, logger)
    if not success:
        return (False, {
            'config': config_name,
            'job_id': job_id,
            'success': False,
            'error': error,
            'duration': 0,
            'pid': None
        })
    
    # Track the PID for cleanup
    pid = process.pid if hasattr(process, 'pid') else None
    
    # Wait for completion
    success, error, status_data = wait_for_completion(process, config_path, job_id, logger)
    
    duration = time.time() - start_time
    
    job_result = {
        'config': config_name,
        'job_id': job_id,
        'success': success,
        'error': error,
        'duration': duration,
        'status_data': status_data,
        'pid': pid
    }
    
    if success:
        logger.success("Job completed successfully in {:.1f} seconds".format(duration))
        if status_data:
            exports = status_data.get('exports', {})
            logger.info("Exports: PDF={}, DWG={}, JPG={}".format(
                exports.get('pdf', 0),
                exports.get('dwg', 0),
                exports.get('jpg', 0)
            ))
    else:
        logger.error("Job failed: {}".format(error))
    
    return (success, job_result)


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def run_orchestrator(cli_args=None):
    """Main orchestrator function"""
    logger = OrchestratorLogger()
    if cli_args is None:
        cli_args = parse_cli_args()
    
    logger.info("AutoExporter Orchestrator Starting...")
    logger.info("Script directory: {}".format(SCRIPT_DIR))
    logger.info("Root path: {}".format(ROOT_PATH))
    
    # Check lock file
    if check_lock_file():
        logger.error("Another orchestrator instance is already running!")
        logger.error("If this is incorrect, delete: {}".format(LOCK_FILE))
        return 1
    
    create_lock_file()
    
    try:
        # Cleanup stale files
        logger.info("Cleaning up stale files...")
        cleanup_stale_files()
        
        # Pre-flight checks
        logger.info("Running pre-flight checks...")
        
        # Check disk space
        free_gb = check_disk_space()
        logger.info("Available disk space: {:.1f} GB".format(free_gb))
        if free_gb < MIN_DISK_SPACE_GB:
            logger.warning("Low disk space! ({:.1f} GB available)".format(free_gb))
        
        # Check pyrevit
        if not check_pyrevit_available():
            logger.error("pyrevit command not found in PATH!")
            logger.error("Please ensure pyrevit CLI is installed and in PATH")
            return 1
        logger.info("pyrevit command available")
        
        # Discover configs
        logger.info("Discovering config files...")
        config_paths = discover_configs()
        
        if not config_paths:
            logger.error("No config files found in: {}".format(CONFIGS_DIR))
            return 1
        
        logger.info("Found {} config file(s)".format(len(config_paths)))
        for config_path in config_paths:
            logger.info("  - {}".format(os.path.basename(config_path)))
        
        config_paths = filter_configs_by_flags(config_paths, cli_args, logger)
        if not config_paths:
            logger.error("No config files matched the requested filters/flags")
            return 1
        
        if getattr(cli_args, "sparc", False):
            logger.info("SPARC filter active - configs to process:")
            for config_path in config_paths:
                logger.info("  * {}".format(os.path.basename(config_path)))
        
        # Validate all configs
        all_valid, _ = validate_all_configs(config_paths, logger)
        if not all_valid:
            logger.error("Config validation failed! Fix errors before running.")
            return 1
        
        logger.success("All configs validated successfully")
        
        # Process each config
        logger.info("")
        logger.info("="*80)
        logger.info("Starting Job Processing")
        logger.info("="*80)
        
        job_results = []
        
        for i, config_path in enumerate(config_paths):
            # Process job
            _, job_result = process_job(config_path, logger)
            job_results.append(job_result)
            
            # Cleanup between jobs
            if i < len(config_paths) - 1:  # Not the last job
                logger.info("Cleaning up before next job...")
                
                # Kill only the specific Revit PID for this job (not all Revit instances)
                pid = job_result.get('pid')
                if pid:
                    kill_revit_processes(logger, specific_pid=pid)
                else:
                    # Fallback: kill all Revit if PID not tracked
                    logger.warning("PID not tracked, killing all Revit processes (fallback)")
                    kill_revit_processes(logger)
                
                cleanup_stale_files()
                cleanup_heartbeat_files()  # Remove heartbeat files to prevent timestamp pollution
                
                logger.info("Cooldown period ({} seconds)...".format(DEFAULT_COOLDOWN_SECONDS))
                time.sleep(DEFAULT_COOLDOWN_SECONDS)
        
        # Generate summary
        logger.info("")
        logger.info("="*80)
        logger.info("ORCHESTRATOR SUMMARY")
        logger.info("="*80)
        
        total_jobs = len(job_results)
        successful_jobs = sum(1 for r in job_results if r['success'])
        failed_jobs = total_jobs - successful_jobs
        
        logger.info("Total Jobs: {}".format(total_jobs))
        logger.info("Successful: {}".format(successful_jobs))
        logger.info("Failed: {}".format(failed_jobs))
        logger.info("")
        
        for result in job_results:
            status = "SUCCESS" if result['success'] else "FAILED"
            logger.info("[{}] {} ({:.1f}s)".format(
                status,
                result['config'],
                result['duration']
            ))
            if not result['success']:
                logger.info("  Error: {}".format(result['error']))
        
        logger.info("="*80)
        logger.info("Log file: {}".format(logger.get_log_file()))
        
        # Open log file
        try:
            os.startfile(logger.get_log_file())
        except:
            pass
        
        # Return exit code
        if failed_jobs > 0:
            return 1
        else:
            return 0
    
    finally:
        # Always remove lock file
        remove_lock_file()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    exit_code = run_orchestrator()
    sys.exit(exit_code)

