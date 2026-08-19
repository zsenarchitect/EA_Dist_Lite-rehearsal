"""Single-instance guard for NotificationHost (Win32 named mutex).

msvcrt file locks are unreliable across PyInstaller onefile parent/child
lifetimes; a named mutex is held for the process lifetime and is the
standard Windows single-instance pattern.
"""

from __future__ import print_function

import ctypes
from ctypes import wintypes

MUTEX_NAME = "Local\\EnneadTab_NotificationHost"
_MUTEX_HANDLE = None

ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000


def acquire_single_instance():
    """Become the only NotificationHost instance.

    Returns True if this process owns the mutex, False if another instance
    already owns it. OS releases the mutex when the process exits/crashes.
    """
    global _MUTEX_HANDLE
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, wintypes.BOOL(True), MUTEX_NAME)
        if not handle:
            return True  # fail open rather than block notifications
        last_error = kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:
        return True


def is_host_lock_held():
    """Return True if another process currently owns the NotificationHost mutex."""
    try:
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
        return False
