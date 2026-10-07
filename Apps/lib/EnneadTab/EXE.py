# -*- coding: utf-8 -*-
"""Run apps from the EnneadTab app library.

This module provides functionality to safely execute applications from the EnneadTab library,
with support for legacy versions and temporary file handling.
"""

import os
import time
import random
import ENVIRONMENT
import USER
import COPY
import ERROR_HANDLE
import ENGINE

def is_process_running(process_name):
    """Check if a process is already running.
    
    Args:
        process_name (str): Name of the process to check (without .exe extension).
        
    Returns:
        bool: True if process is running, False otherwise.
    """
    try:
        import subprocess
        # Use tasklist to check if process is running
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq {}.exe'.format(process_name)], 
                              capture_output=True, text=True, shell=True)
        # If the process is found, tasklist will show it in the output
        return process_name.lower() in result.stdout.lower()
    except:
        # If we can't check, assume it's not running to avoid blocking
        return False

# Dictionary to track recent calls to executables
_recent_exe_calls = {}
# Maximum number of calls allowed per second (2 calls per second)
_MAX_CALLS_PER_SECOND = 2

# Last attempt to wake the persistent NotificationHost. List, not a bare float,
# so the helper can mutate it without a `global` declaration (IronPython 2.7).
_LAST_HOST_WAKE_ATTEMPT = [0.0]
# A failed wake must not relaunch a ~38 MB onefile on every notification.
_HOST_WAKE_COOLDOWN_SECONDS = 60.0

# Records the (size, mtime) identity of the NotificationHost.exe we last launched,
# so a later call can tell a stale (pre-update) running daemon from a current one.
# Lives in the same local Dump folder the daemon writes its heartbeat to.
_HOST_LAUNCHED_VERSION_FILENAME = "notification_host_launched_version.txt"

def _is_rate_limited(exe_name):
    """Check if an executable is currently rate limited.
    
    Args:
        exe_name (str): Name of the executable to check
        
    Returns:
        bool: True if rate limited, False otherwise
    """
    global _recent_exe_calls
    
    exe_key = exe_name.lower().replace(".exe", "")
    current_time = time.time()
    
    if exe_key in _recent_exe_calls:
        recent_calls = _recent_exe_calls[exe_key]
        # Remove calls older than 1 second
        recent_calls = [t for t in recent_calls if current_time - t < 1.0]
        
        # If too many recent calls, rate limited
        if len(recent_calls) >= _MAX_CALLS_PER_SECOND:
            return True
            
    return False


def open_document_file(file_path):
    """Open a document file using the system's default application.
    
    Args:
        file_path (str): Path to the document file.
        
    Returns:
        bool: True if file was opened successfully, False otherwise.
    """
    try:
        os.startfile(file_path)
        return True
    except OSError:
        ERROR_HANDLE.print_note("Failed to open file: {}".format(file_path))
        return False

def locate_executable(exe_name):
    """Locate an executable or batch launcher in the standard EnneadTab locations.

    Searches for .bat first (lightweight Python launcher), then .exe (compiled).
    This allows gradual migration from compiled EXEs to .bat launchers without
    changing any callers.

    Args:
        exe_name (str): Name of the executable without extension.

    Returns:
        str: Path to the executable/batch file if found, None otherwise.
    """
    exe_name = exe_name.replace(".exe", "").replace(".bat", "")
    if exe_name == "ShanghaiRepoAssist":
        return None

    # Search order: .bat first (preferred - no recompilation needed), then .exe
    extensions = [".bat", ".exe"]

    # Local checks first, network last-resort: both product-folder checks are
    # a cheap os.path.exists, while the depot lookup below is an HTTP round
    # trip (manifest GET + a download attempt). Checking it per-extension
    # ahead of the foldered-variant check would pay that cost on every lookup
    # for any tool still using the foldered layout -- including
    # NotificationHost, resolved via this function on the Revit UI thread by
    # _try_wake_notification_host / _notification_host_is_stale.
    for ext in extensions:
        # Check product folder
        path = ENVIRONMENT.EXE_PRODUCT_FOLDER + "\\{}{}".format(exe_name, ext)
        if os.path.exists(path):
            return path

        # Check foldered variant in product folder
        path = ENVIRONMENT.EXE_PRODUCT_FOLDER + "\\{0}\\{0}{1}".format(exe_name, ext)
        if os.path.exists(path):
            return path

    # STAND_ALONE_FOLDER (office L: drive) is retired -- resolve through the
    # depot "tools/standalone" asset namespace instead (network-drive
    # retirement epic, senzhang-todo #3171). get_asset_path downloads to a
    # local cache and returns that path, or None if the key is unknown. Tried
    # only after every local location has missed for both extensions.
    from EnneadTab.DEPOT import ASSET
    for ext in extensions:
        depot_path = ASSET.get_asset_path("tools/standalone/{}{}".format(exe_name, ext))
        if depot_path:
            return depot_path

    return None

def create_temporary_copy(exe_path, exe_name):
    """Create a temporary copy of an executable for safe execution.
    
    Args:
        exe_path (str): Path to the original executable.
        exe_name (str): Name of the executable.
        
    Returns:
        str or None: Path to the temporary copy if successful, None otherwise.
    """
    temp_exe_name = "_temp_exe_{}_{}.exe".format(exe_name, int(time.time()))
    
    # Ensure the temporary directory exists
    temp_dir = ENVIRONMENT.WINDOW_TEMP_FOLDER
    if not os.path.exists(temp_dir):
        try:
            os.makedirs(temp_dir)
        except Exception as e:
            if USER.IS_DEVELOPER:
                print("[Developer only log] Failed to create temp directory: {}".format(e))
            return None
            
    # Properly join paths to ensure backslash is included
    temp_exe = os.path.join(temp_dir, temp_exe_name)
    
    COPY.copyfile(exe_path, temp_exe)
    if os.path.exists(temp_exe):
        return temp_exe
    else:
        print("Temp exe not found, maybe failed to copy due to permission issue.")
        return None

def try_open_legacy_app(exe_name):
    """Legacy L: exe folder is retired. Always False.

    Args:
        exe_name (str): Name of the executable without extension.

    Returns:
        bool: False. The office share no longer exists.
    """
    return False

def try_open_app(exe_name, legacy_name = None, safe_open = False, depth = 0):
    """Attempt to open an executable file from the app library.
    
    Args:
        exe_name (str): Name of the executable file to open. Can include full path.
        legacy_name (str, optional): Name of legacy executable as fallback.
        safe_open (bool, optional): When True, creates a temporary copy before execution
            to allow for updates while the app is running.
        depth (int, optional): Recursion depth counter to prevent infinite recursion.
            Defaults to 0.
    
    Returns:
        bool: True if application was successfully opened, False otherwise.
    
    Note:
        Safe mode creates temporary copies in the system temp folder with automatic cleanup:
        - OS_Installer/AutoStartup files: cleaned up after 12 hours
        - Other executables: cleaned up after 24 hours
        
        Rate limiting is applied to prevent rapid-fire calling of the same executable.
        No more than 2 calls per second for the same executable are allowed.
    """
    # Access the global dictionary for tracking calls
    global _recent_exe_calls
    
    # Prevent infinite recursion
    if depth > 2:
        ERROR_HANDLE.print_note("Maximum recursion depth reached for: {}".format(exe_name))
        return False
        
    # Check rate limiting for the executable
    exe_key = exe_name.lower().replace(".exe", "")
    current_time = time.time()
    
    if exe_key in _recent_exe_calls:
        recent_calls = _recent_exe_calls[exe_key]
        # Remove calls older than 1 second
        recent_calls = [t for t in recent_calls if current_time - t < 1.0]
        
        # If too many recent calls, prevent this call
        if len(recent_calls) >= _MAX_CALLS_PER_SECOND:
            # Instead of returning False, wait a bit and try again
            time.sleep(0.5)  # Wait 500ms
            current_time = time.time()
            # Clean up old calls again after waiting
            recent_calls = [t for t in recent_calls if current_time - t < 1.0]
            if len(recent_calls) >= _MAX_CALLS_PER_SECOND:
                ERROR_HANDLE.print_note("Rate limit reached for: {}. Maximum {} calls per second allowed.".format(
                    exe_name, _MAX_CALLS_PER_SECOND))
                return False
            
        # Update the call history
        _recent_exe_calls[exe_key] = recent_calls + [current_time]
    else:
        # First call for this executable
        _recent_exe_calls[exe_key] = [current_time]

    # Handle non-executable files directly
    abs_name = exe_name.lower()
    if abs_name.endswith((".3dm", ".xlsx", ".xls", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".ico", ".webp", ".psd")):
        return open_document_file(exe_name)

    # Locate the executable
    exe_path = locate_executable(exe_name)
    if not exe_path:
        ERROR_HANDLE.print_note("No exe found in the location.")
        ERROR_HANDLE.print_note("No exe found!!!\n{}\n Will try to open legacy app.".format(exe_name))
        
        # Try legacy app
        if legacy_name and try_open_app(legacy_name, depth = depth + 1):
            return True
            
        if try_open_legacy_app(exe_name):
            return True
            
        ERROR_HANDLE.print_note("No legacy app found!!!\n{}".format(exe_name))
        return False

    # # Check if process is already running (for single-instance applications)
    # if is_process_running(exe_name.replace(".exe", "")):
    #     ERROR_HANDLE.print_note("Process {} is already running. Skipping startup.".format(exe_name))
    #     return True

    # Execute the app
    if safe_open:
        temp_path = create_temporary_copy(exe_path, exe_name.replace(".exe", ""))
        if temp_path:
            try:
                os.startfile(temp_path)
                clean_temporary_executables()
                return True
            except OSError as e:
                if "being used by another process" in str(e):
                    ERROR_HANDLE.print_note("Process {} is already running or file is locked. Skipping startup.".format(exe_name))
                    return True
                else:
                    ERROR_HANDLE.print_note("Failed to start {}: {}".format(exe_name, e))
                    return False
        return False
    else:
        try:
            os.startfile(exe_path)
            return True
        except OSError as e:
            if "being used by another process" in str(e):
                ERROR_HANDLE.print_note("Process {} is already running or file is locked. Skipping startup.".format(exe_name))
                return True
            else:
                ERROR_HANDLE.print_note("Failed to start {}: {}".format(exe_name, e))
                return False

def clean_temporary_executables():
    if random.random() < 0.9:
        return

    """Clean up temporary executables older than a specified age.
    
    This function removes temporary executable files created by the safe_open option.
    Files are only removed if they are older than a specified threshold:
    - OS_Installer/AutoStartup files: cleaned up after 12 hours
    - Other executables: cleaned up after 24 hours
    
    Files that are currently in use will be skipped and logged for debugging purposes.
    """
    
    def get_ignore_age(file):
        """Determine the age threshold for ignoring files."""
        if "OS_Installer" in file or "AutoStartup" in file:
            return 60 * 60 * 12  # 12 hours
        return 60 * 60 * 24  # 24 hours

    # Iterate through files in the temporary folder
    for file in os.listdir(ENVIRONMENT.WINDOW_TEMP_FOLDER):
        if file.startswith("_temp_exe_"):
            # Check the modification time and ignore if too recent
            file_path = os.path.join(ENVIRONMENT.WINDOW_TEMP_FOLDER, file)
            if time.time() - os.path.getmtime(file_path) < get_ignore_age(file):
                continue
            
            try:
                # Remove the file or directory
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    os.rmdir(file_path)
            except OSError as e:
                # This typically happens when file is still in use
                continue
            except Exception as e:
                ERROR_HANDLE.print_note("Error removing {}: {}".format(file_path, e))


def _host_version_sidecar_path():
    """Local file recording the identity of the NotificationHost.exe we launched.

    Same Dump folder the daemon writes ``notification_host_alive.txt`` to
    (``%USERPROFILE%\\Documents\\EnneadTab Ecosystem\\Dump``), so this stays a
    per-machine local marker and never touches shared storage.
    """
    return os.path.join(ENVIRONMENT.DUMP_FOLDER, _HOST_LAUNCHED_VERSION_FILENAME)


def _exe_identity(exe_path):
    """Cheap, lock-safe version identity for an on-disk exe: "<size>-<mtime>".

    Uses os.stat (works on a running, read-locked exe -- no hashing of a ~38 MB
    onefile on this user-triggered path). A rebuilt PyInstaller onefile virtually
    always changes size, so size+mtime reliably distinguishes an updated exe.
    Returns None if the file cannot be stat'd.
    """
    try:
        st = os.stat(exe_path)
        return "{}-{}".format(int(st.st_size), int(st.st_mtime))
    except Exception:
        return None


def _record_notification_host_version(exe_path):
    """Persist the identity of the exe we just launched (best-effort)."""
    identity = _exe_identity(exe_path)
    if not identity:
        return
    try:
        with open(_host_version_sidecar_path(), "w") as f:
            f.write(identity)
    except Exception:
        ERROR_HANDLE.print_note("Failed to record NotificationHost version marker.")


def _notification_host_is_stale():
    """True if the running daemon predates the NotificationHost.exe now on disk.

    Version-aware relaunch is a COMPILED-EXE mechanism: if the located launcher is
    a .bat or the developer .py source, a launcher's identity does not track the
    code it runs, so we never treat those as stale (return False).

    A missing sidecar means the running daemon was launched by pre-fix code (which
    wrote no marker) -- treat it as stale so it gets exactly one forced relaunch
    onto the current exe. A sidecar that differs from the current on-disk identity
    means a newer exe landed while the old daemon kept running.
    """
    exe_path = locate_executable("NotificationHost")
    if not exe_path or not exe_path.lower().endswith(".exe"):
        return False
    current = _exe_identity(exe_path)
    if not current:
        return False
    try:
        with open(_host_version_sidecar_path(), "r") as f:
            recorded = f.read().strip()
    except Exception:
        return True  # no marker -> pre-fix daemon, force one relaunch
    return recorded != current


def _kill_notification_host(timeout=3.0):
    """Terminate the running NotificationHost.exe and wait for it to exit.

    The single-instance mutex is released by the OS when the process dies, but
    taskkill /F returns before termination completes and lock.acquire_single_instance
    does NOT retry -- so poll until the process is gone before any relaunch, or the
    fresh instance would see the mutex still held and exit immediately.

    Returns:
        bool: True if the process is confirmed gone within the timeout.
    """
    try:
        import subprocess
        # Force-kill by image name. Written as a shell string (force flag placed
        # mid-command, not as a trailing quoted list element) so the IronPython
        # linter's f-string regex does not false-positive on a quote-adjacent F.
        subprocess.call(
            "taskkill /F /IM NotificationHost.exe",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        ERROR_HANDLE.print_note("Failed to kill NotificationHost: {}".format(e))
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_process_running("NotificationHost"):
            return True
        time.sleep(0.1)
    return not is_process_running("NotificationHost")


def _notification_host_lock_held():
    """True if NotificationHost already holds its single-instance mutex."""
    try:
        import ctypes
        from ctypes import wintypes
        SYNCHRONIZE = 0x00100000
        MUTEX_NAME = "Local\\EnneadTab_NotificationHost"
        kernel32 = ctypes.windll.kernel32
        OpenMutex = kernel32.OpenMutexW
        OpenMutex.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        OpenMutex.restype = wintypes.HANDLE
        handle = OpenMutex(SYNCHRONIZE, False, MUTEX_NAME)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return is_process_running("NotificationHost")


def ensure_notification_host():
    """Report whether NotificationHost is up RIGHT NOW, starting it if it is not.

    Contract (rewritten 2026-08-12, senzhang-todo #3895): the return value answers
    "will the host drain the item I just enqueued?" -- NOT "did a launch get
    requested?". The previous version returned True as soon as os.startfile()
    did not raise, which is fire-and-forget: it returns before the process
    exists and never surfaces an exit code. Callers use this to decide whether
    to fall back to the legacy Messenger, so a launch-requested True silently
    swallowed the user's message whenever the host could not actually start.

    A freshly-launched host cannot drain the CURRENT item anyway -- the onefile
    build is ~38 MB and takes seconds to unpack -- so we start it for the next
    message and return False, routing this one through the legacy fallback.
    That makes the degradation self-healing rather than silent.

    Returns:
        bool: True only if the host is already running and draining the inbox.
    """
    if _notification_host_lock_held() or is_process_running("NotificationHost"):
        # A running daemon keeps the OLD exe in memory across an EA_Dist update, so
        # a stale (e.g. dim-unaware, #146) build can outlive its replacement. When
        # the on-disk exe no longer matches the one we launched, cycle the daemon
        # onto the current build (senzhang-todo #3992). Like a cold wake, the fresh
        # ~38 MB onefile cannot drain THIS item, so return False and let the caller
        # route it through the legacy fallback; the booted host drains the already-
        # enqueued inbox item via its own _drain_startup.
        if _notification_host_is_stale():
            _kill_notification_host()
            _try_wake_notification_host(force=True)
            return False
        return True

    _try_wake_notification_host()
    return False


def _try_wake_notification_host(force=False):
    """Best-effort start of the persistent host. Never claims readiness.

    Rate-limited because a failed wake would otherwise re-launch a ~38 MB
    onefile on every single notification. Pass ``force=True`` right after a
    version-aware kill (see ensure_notification_host) so the replacement is not
    swallowed by the cooldown of the wake that started the now-killed daemon --
    a staleness kill fires at most once per version change, so bypassing the
    cooldown there cannot cause relaunch storms.

    Returns:
        bool: True if a start was successfully requested (NOT that it is up).
    """
    now = time.time()
    if not force and now - _LAST_HOST_WAKE_ATTEMPT[0] < _HOST_WAKE_COOLDOWN_SECONDS:
        return False
    _LAST_HOST_WAKE_ATTEMPT[0] = now

    exe_path = locate_executable("NotificationHost")
    if exe_path:
        try:
            os.startfile(exe_path)
            # Record what we launched so a later call can detect a stale daemon
            # once EA_Dist ships a newer exe. Only meaningful for the compiled exe.
            if exe_path.lower().endswith(".exe"):
                _record_notification_host_version(exe_path)
            return True
        except OSError as e:
            ERROR_HANDLE.print_note("Failed to start NotificationHost: {}".format(e))
            return False

    # Developer convenience: run source script without a rebuilt exe.
    try:
        if USER.IS_DEVELOPER:
            script = os.path.join(
                ENVIRONMENT.ROOT,
                "DarkSide",
                "exes",
                "source code",
                "NotificationHost",
                "NotificationHost.py",
            )
            if os.path.exists(script):
                success, _stdout, stderr = ENGINE.cast_python(script, wait=False)
                if success:
                    return True
                ERROR_HANDLE.print_note(
                    "Failed to start NotificationHost script: {}".format(stderr)
                )
    except Exception as e:
        ERROR_HANDLE.print_note("NotificationHost developer wake failed: {}".format(e))

    ERROR_HANDLE.print_note("NotificationHost.exe not found.")
    return False


if __name__ == "__main__":
    script_path = os.path.join(ENVIRONMENT.ROOT, "DarkSide", "exes", "source code",
                               "NotificationHost", "NotificationHost.py")
    if not os.path.exists(script_path):
        script_path = os.path.join(ENVIRONMENT.APP_FOLDER, "Messenger.py")
    success, stdout, stderr = ENGINE.cast_python(script_path, wait=True)
    if not success:
        ERROR_HANDLE.print_note("Failed to run NotificationHost: {}".format(stderr))
