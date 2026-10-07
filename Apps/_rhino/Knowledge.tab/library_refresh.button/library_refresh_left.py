__title__ = ["LibraryRefresh"]
__doc__ = """Refresh the Grasshopper definition catalog (throttled).

Key Features:
- Re-scans the configured roots and rebuilds the catalog index
- Throttled: skips the re-scan while the last refresh is still fresh
- Interval is configurable in the library settings; 0 disables throttling"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc

import datetime
import hashlib
import json
import os
import sys

from EnneadTab import LOG, ERROR_HANDLE, ENVIRONMENT
from EnneadTab.RHINO import RHINO_FORMS

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
_CONTENT_HASH_MAX = 32 * 1024 * 1024
_MTIME_PREFIX = "mtime:"

_DEFAULT_THROTTLE_SECONDS = 30.0
_STICKY_LAST = "EnneadTab_Library_LastRefreshUtc"
_STICKY_SUMMARY = "EnneadTab_Library_LastRefreshSummary"


def should_refresh(last_run, interval_seconds):
    """Decide whether a catalog refresh should run now.

    Ports the throttle rule of the GH LibraryIndexRefreshService
    (EnneadTab-For-Grasshopper PR #25): when a refresh completed less than
    ``interval_seconds`` ago, the re-scan is skipped and the cached result is
    reused. ``last_run`` is the completion time of the last successful refresh
    (naive UTC datetime) or None. An interval <= 0 disables throttling.

    NOTE: this helper is intentionally defined here so the button ships
    standalone; it should be hoisted into Apps/_rhino/Library/catalog.py
    (shared lib) at merge time and imported from there instead.
    """
    try:
        interval = float(interval_seconds)
    except Exception:
        interval = _DEFAULT_THROTTLE_SECONDS
    if interval <= 0:
        return True
    if last_run is None:
        return True
    try:
        now = datetime.datetime.utcnow()
        return (now - last_run).total_seconds() >= interval
    except Exception:
        return True


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


def _parse_iso(text):
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _last_successful_refresh():
    return _parse_iso(sc.sticky.get(_STICKY_LAST))


def _remember_successful_refresh(summary):
    now = datetime.datetime.utcnow()
    sc.sticky[_STICKY_LAST] = now.isoformat()
    sc.sticky[_STICKY_SUMMARY] = summary


def _throttle_interval_seconds(settings):
    raw = _ci_get(settings, "refreshThrottleSeconds")
    if raw is None:
        raw = _ci_get(settings, "refresh_throttle_seconds")
    if raw is None:
        return _DEFAULT_THROTTLE_SECONDS
    try:
        return float(raw)
    except Exception:
        return _DEFAULT_THROTTLE_SECONDS


def _mtime_token(path, size):
    try:
        unix_ms = int(os.path.getmtime(path) * 1000)
    except Exception:
        return None
    return "{0}{1}:{2}".format(_MTIME_PREFIX, unix_ms, size)


def _fingerprint(path):
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
    discovered = []
    errors = []
    for raw_root in roots or []:
        root = str(raw_root).strip() if raw_root is not None else ""
        if not root:
            errors.append(("RootNotFound", "(empty)", "Scan root is empty."))
            continue
        if not os.path.isdir(root):
            errors.append(("RootNotFound", root, "Scan root not found or unreachable."))
            continue
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                names = os.listdir(directory)
            except Exception as ex:
                errors.append(("EnumerationFailed", directory, str(ex)))
                continue
            for name in names:
                full = os.path.join(directory, name)
                try:
                    if os.path.isdir(full):
                        stack.append(full)
                        continue
                    if os.path.isfile(full) and os.path.splitext(name)[1].lower() in _DEFINITION_EXTS:
                        discovered.append((full, root))
                except Exception as ex:
                    errors.append(("FileAccessDenied", full, str(ex)))
    return discovered, errors


def _norm(path):
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return path


def _new_id(path, root):
    # Stable, root-scoped id for newly discovered files. Previous entries keep
    # their own ids; this only fills the gap for files the index never saw.
    try:
        digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:8]
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        return "root-{0}/{1}".format(digest, rel)
    except Exception:
        return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]


def _apply_sidecar_overrides(raw_entry, path):
    # Mirrors the GH indexer: the *.ennead.json sidecar overrides the curated
    # fields of the generated entry.
    try:
        sidecar = CATALOG.load_sidecar({"path": path})
    except Exception:
        sidecar = {}
    for key in ("title", "description", "tags", "category", "curated"):
        value = _ci_get(sidecar, key)
        if value is not None:
            raw_entry[key] = value
    return raw_entry


def _refresh(index, index_path, roots):
    """Rebuild the index entries in place. Returns (counts, errors)."""
    raw_entries = _ci_get(index, "entries")
    if not isinstance(raw_entries, (list, tuple)):
        raw_entries = []
    prev_by_path = {}
    for raw in raw_entries:
        if isinstance(raw, dict):
            path = _ci_get(raw, "sourcePath") or _ci_get(raw, "path")
            if path:
                prev_by_path[_norm(path)] = raw

    discovered, errors = _scan_definition_files(roots)
    now_iso = datetime.datetime.utcnow().isoformat()
    new_entries = []
    seen = set()
    reused = 0
    reindexed = 0
    for path, root in sorted(discovered):
        key = _norm(path)
        seen.add(key)
        previous = prev_by_path.get(key)
        fingerprint = _fingerprint(path)
        prev_hash = _ci_get(previous, "fileHash") if previous else None
        if previous is not None and fingerprint and prev_hash == fingerprint:
            new_entries.append(previous)
            reused += 1
            continue
        raw = {
            "id": _ci_get(previous, "id") if previous else _new_id(path, root),
            "title": os.path.splitext(os.path.basename(path))[0],
            "description": "",
            "tags": [],
            "category": "",
            "sourcePath": os.path.abspath(path),
            "scanRoot": root,
            "fileHash": fingerprint or "",
            "pluginsRequired": [],
            "pluginsKnown": False,
            "conventionOk": True,
            "conventionNotes": "",
            "parameters": _ci_get(previous, "parameters") or [],
            "indexedAt": now_iso,
            "curated": bool(_ci_get(previous, "curated")) if previous else False,
        }
        new_entries.append(_apply_sidecar_overrides(raw, path))
        reindexed += 1
    dropped = sum(1 for key in prev_by_path if key not in seen)

    index["entries"] = new_entries
    index["scanRoots"] = list(roots)
    index["lastIndexedAt"] = now_iso
    with open(index_path, "w") as handle:
        json.dump(index, handle, indent=2)
    counts = {"scanned": len(discovered), "reused": reused,
              "reindexed": reindexed, "dropped": dropped}
    return counts, errors


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_refresh():
    if CATALOG is None:
        rs.MessageBox("Shared catalog library not found (Apps/_rhino/Library/catalog.py). "
                      "Merge the shared-lib PR first.")
        return
    index_path, settings_path = CATALOG.find_catalog_paths()
    if not index_path:
        rs.MessageBox("No catalog index found. Nothing to refresh yet.")
        return
    settings = CATALOG.load_settings(settings_path) if settings_path else {}
    interval = _throttle_interval_seconds(settings)
    last_run = _last_successful_refresh()

    if not should_refresh(last_run, interval):
        cached = sc.sticky.get(_STICKY_SUMMARY) or "no cached summary"
        RHINO_FORMS.notification(
            title="Library - Refresh Throttled",
            main_text="Refresh throttled (last scan < {0:g}s ago).".format(interval),
            sub_text="Cached: {0}".format(cached))
        return

    index = CATALOG.load_index(index_path)
    roots = _ci_get(settings, "scanRoots") or _ci_get(index, "scanRoots") or []
    if isinstance(roots, _STRING_TYPES):
        roots = [roots]
    roots = [r for r in roots if isinstance(r, _STRING_TYPES)]
    if not roots:
        rs.MessageBox("No scan roots configured in the library settings.")
        return

    try:
        counts, errors = _refresh(index, index_path, roots)
    except Exception as ex:
        rs.MessageBox("Refresh failed: {0}".format(ex))
        return

    summary = "scanned {0}, reused {1}, reindexed {2}, dropped {3}, errors {4}".format(
        counts["scanned"], counts["reused"], counts["reindexed"],
        counts["dropped"], len(errors))
    _remember_successful_refresh(summary)
    detail = "Refresh complete: {0}.".format(summary)
    if errors:
        detail += " First errors: " + "; ".join(
            "[{0}] {1}".format(kind, path) for kind, path, _m in errors[:5])
    RHINO_FORMS.notification(title="Library - Refresh",
                             main_text=detail,
                             sub_text=index_path)
    print(detail)


if __name__ == "__main__":
    library_refresh()
