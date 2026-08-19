#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
INTEGRITY
---------
Verifies that a deployed EnneadTab install is INTERNALLY CONSISTENT -- that the
lib half and the extension half came from the same publish.

WHY THIS EXISTS
---------------
The installer exe copies the new distribution file-by-file straight into the
LIVE EA_Dist folder. Any mid-way failure -- Revit holding a .py or .dll open,
a network blip, a permission denial -- stops the copy partway and leaves a
TORN install: some files from the new publish, some from the old one.

A torn install is invisible to every static check in this repo. The repo itself is
internally consistent (a helper and its caller land in the same commit), so
check_ironpython.py / check_artifact_freshness.py are green while a user's machine
is running a spliced tree. The only place the skew exists is the deployed folder,
so the only thing that can see it is a runtime assertion at the distribution
boundary. That is this module.

The live example that motivated it:
    AttributeError: 'module' object has no attribute 'get_subcategory_signatures'
    at EnneaDuck.extension/hooks/family-loaded.py -- NEW hook file calling into an
    OLD REVIT_CATEGORY.py. 94 of 100 recent production ErrorDump events.

WHAT IT NEEDS
-------------
A manifest -- Installation/dist_manifest.json -- written by the publisher
(DarkSide/publish/________publish.py::_write_dist_manifest) into the distribution
copy. It maps every shipped .py file under Apps/lib/EnneadTab and
Apps/_revit/EnneaDuck.extension to its SHA-256 at publish time.

A developer/source tree has NO manifest. That is not an error: verify() reports
"no manifest, nothing to check" and every caller treats it as a pass. Absence of a
manifest must never be louder than a real skew.

Compatible with IronPython 2.7 and CPython 3.
"""

import os
import json
import hashlib
import threading
import time
import traceback

import ENVIRONMENT
import ERROR_HANDLE
import NOTIFICATION
import DATA_FILE
import USER


MANIFEST_NAME = "dist_manifest.json"

# Trees the manifest covers. Kept in ONE place so the publisher (writer) and this
# module (reader) can never drift on scope. Forward slashes; joined per-OS below.
MANIFEST_TREES = [
    "Apps/lib/EnneadTab",
    "Apps/_revit/EnneaDuck.extension",
]

# Only source files are covered. Hashing exes/pyc/images would make the manifest
# enormous and would false-positive on locally-regenerated .pyc files.
MANIFEST_EXTENSIONS = (".py",)

# How many skewed files to name in a report before truncating. A fully failed copy
# would otherwise produce a multi-megabyte ErrorDump payload.
MAX_REPORTED_FILES = 25

_TORN_REPORT_GATE_HOURS = 6.0


def get_manifest_path(root=None):
    """Absolute path to the manifest of a deployed tree.

    Args:
        root (str, optional): Root of the tree to inspect. Defaults to the
            currently-running install (ENVIRONMENT.ROOT).

    Returns:
        str: Path to Installation/dist_manifest.json inside that tree.
    """
    if root is None:
        root = ENVIRONMENT.ROOT
    return os.path.join(root, "Installation", MANIFEST_NAME)


def hash_file(file_path):
    """SHA-256 of a file, or None if it cannot be read.

    Args:
        file_path (str): Absolute path to the file.

    Returns:
        str or None: Lowercase hex digest, None on any read failure.
    """
    try:
        digest = hashlib.sha256()
        f = open(file_path, "rb")
        try:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
        finally:
            f.close()
        return digest.hexdigest()
    except Exception:
        return None


def iter_manifest_files(root):
    """Yield (relative_posix_path, absolute_path) for every file the manifest covers.

    Shared by the publisher and the verifier so the two can never disagree about
    which files are in scope.

    Args:
        root (str): Root of the tree to walk.

    Returns:
        list: List of (rel_path, abs_path) tuples, sorted by rel_path.
    """
    results = []
    for tree in MANIFEST_TREES:
        tree_root = os.path.join(root, *tree.split("/"))
        if not os.path.isdir(tree_root):
            continue
        for current_dir, dirs, files in os.walk(tree_root):
            # Never hash caches or VCS metadata -- they are machine-local noise.
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
            for name in files:
                if not name.endswith(MANIFEST_EXTENSIONS):
                    continue
                abs_path = os.path.join(current_dir, name)
                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                results.append((rel_path, abs_path))
    results.sort()
    return results


def build_manifest_files(root):
    """Build the {relative_path: sha256} map for a tree.

    Args:
        root (str): Root of the tree to hash.

    Returns:
        dict: Mapping of relative posix path to hex digest. Unreadable files are
            omitted rather than recorded with a fake hash.
    """
    files = {}
    for rel_path, abs_path in iter_manifest_files(root):
        digest = hash_file(abs_path)
        if digest is not None:
            files[rel_path] = digest
    return files


def get_manifest(root=None):
    """Load the manifest of a deployed tree.

    Returns:
        dict or None: Parsed manifest, or None when absent/corrupt. A dev tree has
            no manifest and that is a normal, silent condition.
    """
    path = get_manifest_path(root)
    try:
        if not os.path.exists(path):
            return None
        f = open(path, "r")
        try:
            return json.load(f)
        finally:
            f.close()
    except Exception:
        ERROR_HANDLE.print_note(
            "INTEGRITY: manifest unreadable at {}\n{}".format(path, traceback.format_exc()))
        return None


def verify(root=None):
    """Compare a deployed tree against its own manifest.

    Args:
        root (str, optional): Tree to verify. Defaults to the running install.

    Returns:
        tuple: (is_ok, skewed, checked_count)
            is_ok (bool): True when the tree matches the manifest, OR when there is
                no manifest to check against (dev tree / pre-manifest publish).
            skewed (list): Human-readable "path (reason)" strings, capped at
                MAX_REPORTED_FILES + 1 summary line.
            checked_count (int): Number of files compared.
    """
    if root is None:
        root = ENVIRONMENT.ROOT

    manifest = get_manifest(root)
    if not manifest:
        # No manifest: a source checkout, or a publish predating this feature.
        # Silent pass -- absence of evidence is not evidence of a torn install.
        return True, [], 0

    expected = manifest.get("files") or {}
    if not expected:
        return True, [], 0

    skewed = []
    checked = 0
    for rel_path in sorted(expected.keys()):
        checked += 1
        abs_path = os.path.join(root, *rel_path.split("/"))
        if not os.path.exists(abs_path):
            reason = "MISSING"
        else:
            actual = hash_file(abs_path)
            if actual is None:
                reason = "UNREADABLE"
            elif actual != expected[rel_path]:
                reason = "STALE_OR_MODIFIED"
            else:
                continue
        if len(skewed) < MAX_REPORTED_FILES:
            skewed.append("{} ({})".format(rel_path, reason))
        elif len(skewed) == MAX_REPORTED_FILES:
            skewed.append("...and more (report truncated)")

    return (len(skewed) == 0), skewed, checked


def _should_report_torn(gate_key):
    """Once-per-window gate so a permanently torn machine cannot flood ErrorDump."""
    try:
        data = DATA_FILE.get_data("integrity_report_gate") or {}
        if (time.time() - data.get(gate_key, 0)) < (_TORN_REPORT_GATE_HOURS * 3600.0):
            return False
        data[gate_key] = time.time()
        DATA_FILE.set_data(data, "integrity_report_gate")
        return True
    except Exception:
        # A gate failure must never silence a real report.
        return True


def report_torn_install(skewed, source, root=None, notify_user=True):
    """Make a torn install LOUD: ErrorDump for the dev team, plain English for the user.

    The send runs on a daemon thread -- send_error_to_error_dump can burn up to
    ~20s of transport timeouts on exactly the broken-network machines most likely
    to be torn, and this is reached from the startup/save path.

    Args:
        skewed (list): Output of verify().
        source (str): Where the detection happened ("post_update", "hook_guard", ...).
        root (str, optional): Tree that was verified.
        notify_user (bool): Show the user the re-run-the-installer message.
    """
    if root is None:
        root = ENVIRONMENT.ROOT

    message = "\n".join([
        "EnneadTab TORN INSTALL detected ({})".format(source),
        "root: {}".format(root),
        "dist version: {}".format(ENVIRONMENT.get_dist_version()),
        "skewed files:",
    ] + ["  - {}".format(item) for item in skewed])

    ERROR_HANDLE.print_note(message)

    if notify_user:
        try:
            NOTIFICATION.messenger(
                "Your EnneadTab install is INCOMPLETE or OUT OF DATE.\n"
                "Some files updated, some did not.\n"
                "Please re-run the EnneadTab installer to repair it.",
                sticky=True)
        except Exception:
            pass

    if not _should_report_torn(source):
        return

    def _send():
        try:
            ERROR_HANDLE.send_error_to_error_dump(
                error_message=message,
                func_name="integrity_torn_install:{}".format(source),
                user_name=USER.USER_NAME,
                is_silent=not notify_user)
        except Exception:
            pass

    worker = threading.Thread(target=_send)
    worker.daemon = True
    worker.start()


def verify_and_report(root=None, source="post_update", notify_user=True):
    """Verify a tree and, on skew, report it. Returns True when the tree is intact.

    This is the function the updater calls after a copy. It is the ONLY thing
    entitled to declare an update successful.
    """
    try:
        is_ok, skewed, checked = verify(root)
    except Exception:
        # Verification itself failing must not be mistaken for a torn install --
        # that would tell every user to reinstall over a bug in this module.
        ERROR_HANDLE.print_note(
            "INTEGRITY: verification crashed\n{}".format(traceback.format_exc()))
        return True

    if is_ok:
        ERROR_HANDLE.print_note(
            "INTEGRITY: verified {} files against manifest -- install is consistent.".format(checked))
        return True

    report_torn_install(skewed, source, root=root, notify_user=notify_user)
    return False


def unit_test():
    """Verify the running install and print the outcome."""
    is_ok, skewed, checked = verify()
    print("manifest: {}".format(get_manifest_path()))
    print("checked : {}".format(checked))
    print("intact  : {}".format(is_ok))
    for item in skewed:
        print("  skew: {}".format(item))


if __name__ == "__main__":
    unit_test()
