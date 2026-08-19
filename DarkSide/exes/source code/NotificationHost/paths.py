"""Shared Dump-folder resolution for the NotificationHost package.

`get_dump_folder()` was independently duplicated in inbox.py, mute.py and
NotificationHost.py. progress_jobs.py would have been the fourth copy, so the
resolver lives here instead. The existing three are intentionally left alone in
this change -- migrating them is a separate, behaviour-neutral cleanup, and
mixing it into a feature commit would widen the blast radius for no benefit.

The path is resolved the same way ENVIRONMENT / _Exe_Util do it, and is
deliberately NOT the shell's Documents location: EnneadTab pins the literal
%USERPROFILE%\\Documents so the Dump folder stays OUT of OneDrive.
"""

from __future__ import print_function

import os


def get_eco_folder():
    return os.path.join(
        os.environ.get("USERPROFILE", ""),
        "Documents",
        "EnneadTab Ecosystem",
    )


def get_dump_folder():
    """Resolve the EnneadTab Dump folder, creating it if absent."""
    dump = os.path.join(get_eco_folder(), "Dump")
    if not os.path.exists(dump):
        try:
            os.makedirs(dump)
        except OSError:
            # Another process won the race. Harmless -- we only need it to exist.
            pass
    return dump


def get_dump_subdir(name):
    """Resolve (and create) a subdirectory of the Dump folder.

    The makedirs is guarded rather than exists-then-create: two Revit sessions
    starting a job at the same moment race this, and an unguarded call raises
    OSError on the loser. FOLDER.secure_folder on the library side has exactly
    that bug (senzhang-todo #3898); do not copy it.
    """
    path = os.path.join(get_dump_folder(), name)
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path
