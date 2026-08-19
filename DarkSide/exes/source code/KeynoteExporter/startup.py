#!/usr/bin/env python3
"""
Startup helpers for KeynoteExporter.

Kept deliberately dependency-light (stdlib only) so it can run BEFORE the heavy
imports in ``src`` (pandas/openpyxl). Two concerns:

1. Splash screen - the PyInstaller onefile splash shows instantly on double-click
   while the bootloader unpacks ~95MB and the interpreter starts, so the user is
   never staring at an empty screen. The ``update_splash``/``close_splash`` calls
   are safe no-ops when not running as a frozen ``--splash`` build.

   NOTE: the build uses PyInstaller's CLI ``--splash`` which renders a STATIC
   image only (CLI templates ``text_pos=None``, so live status text is not drawn).
   The loading text is therefore baked into the image; the update_splash() calls
   below stay in place so live text starts working automatically if the build is
   ever switched to a .spec that sets text_pos.

2. Single-instance lock - a user must never open more than one KeynoteExporter at
   once. Uses an OS-level exclusive byte-range lock on a per-user temp file. The
   lock is bound to the open file handle and the OS releases it automatically when
   the process exits or crashes, so there is never a stale lock to clean up.
"""

import os
import tempfile

# Hold the lock file handle for the whole process lifetime. If it were garbage
# collected the OS would release the lock and a second instance could start.
_LOCK_HANDLE = None


def update_splash(text):
    """Update the splash status line (no-op unless running as a --splash build)."""
    try:
        import pyi_splash  # only present inside a frozen onefile built with --splash
        if pyi_splash.is_alive():
            pyi_splash.update_text(text)
    except Exception:
        pass


def close_splash():
    """Close the splash screen if it is showing."""
    try:
        import pyi_splash
        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass


def acquire_single_instance(app_id="EnneadTab_KeynoteExporter"):
    """Try to become the single running instance for this user session.

    Returns True if this process acquired the lock (it is the only instance),
    False if another instance already holds it.

    The lock is an exclusive 1-byte region lock on a per-user temp file, released
    by the OS on process exit/crash - so a crash never leaves a stale lock behind.
    On platforms without ``msvcrt`` (non-Windows dev) this is a no-op that allows
    launch, since this is a Windows-only tool.
    """
    global _LOCK_HANDLE
    try:
        import msvcrt
    except ImportError:
        return True  # not Windows -> do not block

    lock_path = os.path.join(tempfile.gettempdir(), app_id + ".lock")
    try:
        handle = open(lock_path, "a+")
    except OSError:
        # Cannot open the lock file (perms/disk) -> fail open rather than block.
        return True

    try:
        handle.seek(0)
        # Both instances contend for the same byte 0; the second one raises.
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return False  # another instance holds the lock

    _LOCK_HANDLE = handle  # keep alive for the process lifetime
    return True


def set_app_user_model_id(app_id="EnneadTab.KeynoteExporter"):
    """Give the process its own taskbar identity.

    Without an explicit AppUserModelID, Windows groups a frozen Python GUI under
    the host interpreter and shows a generic icon on the taskbar instead of the
    app's own icon. Must be called BEFORE the first window is created. No-op off
    Windows.
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def notify_already_running(app_name="EnneadTab Keynote Exporter"):
    """Tell the user another instance is already open, via a native dialog."""
    msg = "{} is already running.\n\nLook for the window that is already open.".format(app_name)
    try:
        import ctypes
        # MB_ICONINFORMATION (0x40) | MB_SETFOREGROUND (0x10000) | MB_TOPMOST (0x40000)
        ctypes.windll.user32.MessageBoxW(0, msg, app_name, 0x40 | 0x10000 | 0x40000)
        return
    except Exception:
        pass
    try:
        print(msg)
    except Exception:
        pass
