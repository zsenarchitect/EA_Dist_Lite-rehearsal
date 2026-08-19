"""Machine-local enrollment for the EnneadTab publisher.

WHY THIS REPLACES A HOSTNAME LIST
---------------------------------
Publisher eligibility used to be a hostname allowlist committed to the repo:

    _schedule_publish.py        ALLOWED_COMPUTERS = ["EANY-1X8MWP3"]
    _register_..._task.bat      ALLOWED_PC=EANY-1X8MWP3
    _register_shcedule_...py    COMPUTERNAME != 'SZHANG'      (a THIRD, different name)

That shape has four problems, all of which actually bit:

  1. Moving the publisher means editing and committing source, so the machine
     identity of an operations decision lives in version control forever.
  2. The names drift. Three pins disagreed with each other, and the 'SZHANG' one
     matched no machine that still exists -- so that registrar was dead and
     nobody noticed, because a pin that matches nothing just silently does nothing.
  3. They read the hostname from two different sources (socket.gethostname() vs
     %COMPUTERNAME%), which are not guaranteed to agree under a service account.
     Repointing one and not the other yields a box that pulls but does not
     publish -- green either way.
  4. It cannot express "not right now". Disabling meant editing code.

Enrollment is instead an explicit, machine-local, reversible opt-in: a marker file
outside the repo. Setup writes it, teardown removes it, and the publisher asks.
Nothing about which machine publishes is committed to git, so moving the publisher
is an operation, not a code change.

The marker lives OUTSIDE the working tree on purpose. Inside it, it would be
either committed (making every clone think it is the publisher) or gitignored
(making a dirty tree, which the publish now refuses).
"""

import json
import os
import socket

MARKER_DIR = os.path.join(os.path.expanduser("~"), ".enneadtab")
MARKER_PATH = os.path.join(MARKER_DIR, "publisher-enrollment.json")
SCHEMA_VERSION = 1


def _machine_name():
    """One source of truth for this machine's identity.

    Everything here goes through this function. The previous code mixed
    socket.gethostname() and %COMPUTERNAME%, which can disagree.
    """
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "").upper()


def read_enrollment():
    """Return the enrollment record for this machine, or None if not enrolled."""
    try:
        with open(MARKER_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError):
        return None


def is_enrolled():
    """True when this machine has been explicitly enrolled as the publisher.

    Fail-CLOSED: anything unreadable, malformed, or enrolled under a different
    machine name means "not the publisher". The safe default for "may I overwrite
    the firm's distribution" is no.
    """
    record = read_enrollment()
    if not record:
        return False
    if record.get("schema_version") != SCHEMA_VERSION:
        return False
    return record.get("machine", "").upper() == _machine_name()


def enable(repo_path, note=None, timestamp=None):
    """Enroll THIS machine as the publisher. Returns the record written.

    `timestamp` is injected rather than read from the clock so callers can record
    a meaningful time and so this stays testable.
    """
    if not os.path.isdir(MARKER_DIR):
        os.makedirs(MARKER_DIR)
    record = {
        "schema_version": SCHEMA_VERSION,
        "machine": _machine_name(),
        "repo_path": os.path.abspath(repo_path),
        "enrolled_at": timestamp,
        "note": note,
    }
    with open(MARKER_PATH, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    return record


def disable():
    """Un-enroll this machine. Returns True if a marker was removed."""
    if os.path.exists(MARKER_PATH):
        os.remove(MARKER_PATH)
        return True
    return False


def describe():
    """One-line human status, for setup/teardown output and for the run log."""
    record = read_enrollment()
    if not record:
        return "NOT enrolled as publisher (no marker at {})".format(MARKER_PATH)
    if record.get("machine", "").upper() != _machine_name():
        return ("marker at {} is enrolled for machine {!r}, but this machine is {!r} "
                "-> NOT the publisher".format(MARKER_PATH, record.get("machine"), _machine_name()))
    return "ENROLLED as publisher (machine {}, repo {}, since {})".format(
        record.get("machine"), record.get("repo_path"), record.get("enrolled_at"))


if __name__ == "__main__":
    print(describe())
    print("machine: {}".format(_machine_name()))
    print("enrolled: {}".format(is_enrolled()))
