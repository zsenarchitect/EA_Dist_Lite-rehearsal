__title__ = ["LibraryDryRun"]
__doc__ = """Preview a catalog refresh without writing anything.

Key Features:
- Reports what a refresh would do: reuse / reindex / drop / error previews
- Scans the configured roots read-only (no Rhino open, no index write)
- Flags missing or unreadable roots before a real refresh hits them"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc

import hashlib
import os
import sys

from EnneadTab import LOG, ERROR_HANDLE, ENVIRONMENT

_LIBRARY_DIR = os.path.join(ENVIRONMENT.RHINO_FOLDER, "Library")
if _LIBRARY_DIR not in sys.path:
    sys.path.append(_LIBRARY_DIR)

try:
    import catalog as CATALOG  # Apps/_rhino/Library/catalog.py (shared lib)
except ImportError:
    CATALOG = None


try:
    _STRING_TYPES = basestring  # IronPython 2.7
except NameError:
    _STRING_TYPES = str  # CPython 3 (test/dev only)


_DEFINITION_EXTS = (".gh", ".ghx")
# Mirrors LibraryFileFingerprint.ContentHashMaxBytes: above this size the
# fingerprint falls back to an mtime+size token instead of hashing content.
_CONTENT_HASH_MAX = 32 * 1024 * 1024
_MTIME_PREFIX = "mtime:"


def _ci_get(mapping, name):
    if not isinstance(mapping, dict):
        return None
    if name in mapping:
        return mapping[name]
    lowered = name.lower()
    for key in mapping:
        try:
            if key.lower() == lowered:
                return mapping[key]
        except Exception:
            continue
    return None


def _mtime_token(path, size):
    # Mirrors LibraryFileFingerprint.FromMtimeAndSize: mtime:{unixMs}:{length}.
    try:
        unix_ms = int(os.path.getmtime(path) * 1000)
    except Exception:
        return None
    return "{0}{1}:{2}".format(_MTIME_PREFIX, unix_ms, size)


def _fingerprint(path):
    # Mirrors LibraryFileFingerprint.TryCompute: lowercase hex SHA-256 of the
    # file bytes (read-only), mtime token fallback for large/unreadable files.
    try:
        size = os.path.getsize(path)
    except Exception:
        return None
    if size > _CONTENT_HASH_MAX:
        return _mtime_token(path, size)
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except Exception:
        return _mtime_token(path, size)


def _scan_definition_files(roots):
    """Returns (discovered, error_previews).

    discovered: [(path, root)]. error_previews: [(kind, path, message)].
    Read-only walk; per-directory errors are collected, never abort the root.
    Mirrors the dry-run enumeration policy of LibraryRefreshPlanner.PlanDryRun.
    """
    discovered = []
    error_previews = []
    for raw_root in roots or []:
        root = str(raw_root).strip() if raw_root is not None else ""
        if not root:
            error_previews.append(("RootNotFound", "(empty)", "Scan root is empty."))
            continue
        if not os.path.isdir(root):
            error_previews.append(("RootNotFound", root,
                                   "Scan root not found or unreachable."))
            continue
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                names = os.listdir(directory)
            except Exception as ex:
                error_previews.append(("EnumerationFailed", directory, str(ex)))
                continue
            for name in names:
                full = os.path.join(directory, name)
                try:
                    is_dir = os.path.isdir(full)
                except Exception as ex:
                    error_previews.append(("FileAccessDenied", full, str(ex)))
                    continue
                if is_dir:
                    stack.append(full)
                    continue
                try:
                    is_file = os.path.isfile(full)
                except Exception:
                    continue
                if is_file and os.path.splitext(name)[1].lower() in _DEFINITION_EXTS:
                    discovered.append((full, root))
    return discovered, error_previews


def _norm(path):
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return path


def _plan(previous_entries, discovered):
    """Returns (reuse, reindex, drop).

    reuse: previous entries whose fingerprint is unchanged (kept as-is).
    reindex: (path, root, fingerprint) tuples that are new or changed --
    the expensive part of a refresh. drop: previous entries whose source file
    is no longer under any root.
    """
    prev_by_path = {}
    for entry in previous_entries or []:
        if isinstance(entry, dict) and entry.get("path"):
            prev_by_path[_norm(entry.get("path"))] = entry
    reuse = []
    reindex = []
    seen = set()
    for path, root in discovered:
        key = _norm(path)
        seen.add(key)
        fingerprint = _fingerprint(path)
        previous = prev_by_path.get(key)
        if previous is not None and fingerprint and previous.get("fileHash") == fingerprint:
            reuse.append(previous)
        else:
            reindex.append((path, root, fingerprint))
    drop = [entry for key, entry in prev_by_path.items() if key not in seen]
    return reuse, reindex, drop


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_dry_run():
    if CATALOG is None:
        rs.MessageBox("Shared catalog library not found (Apps/_rhino/Library/catalog.py). "
                      "Merge the shared-lib PR first.")
        return
    index_path, settings_path = CATALOG.find_catalog_paths()
    if not index_path:
        rs.MessageBox("No catalog index found. Refresh the Grasshopper library first.")
        return
    index = CATALOG.load_index(index_path)
    settings = CATALOG.load_settings(settings_path) if settings_path else {}
    roots = _ci_get(settings, "scanRoots") or _ci_get(index, "scanRoots") or []
    if isinstance(roots, _STRING_TYPES):
        roots = [roots]
    roots = [r for r in roots if isinstance(r, _STRING_TYPES)]

    previous_entries = CATALOG.iter_entries(index)
    discovered, error_previews = _scan_definition_files(roots)
    reuse, reindex, drop = _plan(previous_entries, discovered)

    summary = "dry run: scanned {0}, reuse {1}, reindex {2}, drop {3}, error previews {4}".format(
        len(discovered), len(reuse), len(reindex), len(drop), len(error_previews))

    lines = ["Nothing was written -- this is a preview only.", ""]
    for path, root, _fp in sorted(reindex):
        lines.append("REINDEX  {0}".format(path))
    for entry in sorted(reuse, key=lambda e: e.get("title") or ""):
        lines.append("REUSE    {0}".format(entry.get("path") or entry.get("title")))
    for entry in sorted(drop, key=lambda e: e.get("title") or ""):
        lines.append("DROP     {0}".format(entry.get("path") or entry.get("title")))
    for kind, path, message in error_previews:
        lines.append("ERROR [{0}] {1}: {2}".format(kind, path, message))
    lines.append("")
    lines.append("A real refresh may still hit file-open failures no dry run can predict.")

    rs.ListBox(lines, "Library - Dry Run Refresh", summary)
    print(summary)


if __name__ == "__main__":
    library_dry_run()
