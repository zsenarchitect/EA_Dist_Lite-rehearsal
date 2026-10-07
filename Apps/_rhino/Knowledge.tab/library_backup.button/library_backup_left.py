__title__ = "LibraryBackup"
__doc__ = """Back up the catalog's sidecar/metadata files to a timestamped zip on demand.

Key Features:
- Snapshots every *.ennead.json sidecar under each catalog scan root
- Stores a backup-interval preference in library-settings.json (backupIntervalMinutes)
- Offers 'back up now' when the newest backup is older than the interval
- Prunes old backups, keeps the newest 10

Ports EnneadTab-For-Grasshopper#57 (interval auto-backup of sidecars/metadata)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, sys, json, shutil, zipfile, time
import fnmatch
from collections import OrderedDict
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path: sys.path.append(_library_dir)
try:
    import catalog
except ImportError:
    catalog = None
from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE
_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")

# Mirrors the Grasshopper LibraryAutoBackup defaults (GH PR #57):
# DefaultIntervalMinutes = 10, DefaultMaxSnapshots = 10, SidecarSearchPattern = "*.ennead.json".
_BACKUP_INTERVAL_KEY = "backupIntervalMinutes"
_DEFAULT_INTERVAL_MINUTES = 10
_MAX_BACKUPS = 10
_SIDECAR_PATTERN = "*.ennead.json"


def _settings_write_path(index_path, settings_path):
    # find_catalog_paths() returns None for a settings file that does not
    # exist yet; fall back to the catalog default layout where the settings
    # live next to the index (%LOCALAPPDATA%/EnneadTab/Grasshopper).
    if settings_path:
        return settings_path
    return os.path.join(os.path.dirname(index_path), "library-settings.json")


def _load_settings(settings_path):
    try:
        with open(settings_path, "r") as f:
            return json.load(f, object_pairs_hook=OrderedDict)
    except (IOError, OSError, ValueError):
        return OrderedDict()


def _save_settings(settings_path, settings):
    folder = os.path.dirname(settings_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def _get_interval(settings):
    try:
        interval = int(settings.get(_BACKUP_INTERVAL_KEY, _DEFAULT_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        interval = _DEFAULT_INTERVAL_MINUTES
    return max(1, interval)


def _scan_roots(index, settings):
    # Mirrors GH RunAutoBackup: snapshot every scan root known to the store.
    roots = []
    for raw in (index.get("scanRoots") or settings.get("scanRoots") or []):
        root = raw.strip() if isinstance(raw, basestring) else ""
        if root and os.path.isdir(root) and root not in roots:
            roots.append(root)
    return roots


def _iter_sidecars(scan_root):
    # Tolerant recursive sidecar enumeration; mirrors GH EnumerateSidecars —
    # one unreadable folder must not fail the whole snapshot.
    stack = [scan_root]
    while stack:
        current = stack.pop()
        try:
            names = os.listdir(current)
        except (OSError, IOError):
            continue
        for name in names:
            full = os.path.join(current, name)
            if os.path.isdir(full):
                stack.append(full)
            elif fnmatch.fnmatch(name.lower(), _SIDECAR_PATTERN):
                yield full


def _backups_dir(index_path):
    # Co-located with the catalog store: <catalog_dir>/LibraryBackups/sidecar-snapshots.
    return os.path.join(os.path.dirname(index_path), "LibraryBackups", "sidecar-snapshots")


def _list_backups(backups_dir):
    try:
        names = os.listdir(backups_dir)
    except (OSError, IOError):
        return []
    zips = [n for n in names if n.lower().endswith(".zip")]
    zips.sort()
    return [os.path.join(backups_dir, n) for n in zips]


def _newest_backup_age_minutes(backups_dir):
    backups = _list_backups(backups_dir)
    if not backups:
        return None
    try:
        mtime = os.path.getmtime(backups[-1])
    except (OSError, IOError):
        return None
    return max(0, int((time.time() - mtime) / 60))


def _unique_zip_path(backups_dir):
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    name = "sidecar-backup-{0}.zip".format(stamp)
    path = os.path.join(backups_dir, name)
    n = 1
    while os.path.exists(path):
        name = "sidecar-backup-{0}-{1}.zip".format(stamp, n)
        path = os.path.join(backups_dir, name)
        n += 1
    return path


def _prune_oldest(backups_dir, keep):
    # Mirrors GH PruneOldest: delete oldest timestamped zips beyond keep.
    backups = _list_backups(backups_dir)
    removed = 0
    while len(backups) > max(1, keep):
        oldest = backups.pop(0)
        try:
            os.remove(oldest)
            removed += 1
        except (OSError, IOError):
            pass
    return removed


def _do_backup(scan_roots, backups_dir):
    if not os.path.isdir(backups_dir):
        os.makedirs(backups_dir)
    zip_path = _unique_zip_path(backups_dir)
    copied = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, root in enumerate(scan_roots):
            label = os.path.basename(os.path.normpath(root)) or "root{0}".format(i)
            label = "root{0}-{1}".format(i, label)
            for sidecar in _iter_sidecars(root):
                try:
                    rel = os.path.relpath(sidecar, root)
                    archive.write(sidecar, os.path.join(label, rel))
                    copied += 1
                except (OSError, IOError):
                    # Best-effort: one unreadable sidecar must not fail the snapshot.
                    pass
    pruned = _prune_oldest(backups_dir, _MAX_BACKUPS)
    return zip_path, copied, pruned


def _change_interval(settings, settings_path, current):
    get_string = getattr(rs, "GetString", None)
    if get_string is None:
        rs.MessageBox("Cannot prompt for a new interval in this environment.",
                      buttons=0, title=__title__)
        return
    answer = get_string("Backup interval in minutes", str(current))
    if answer is None:
        return
    try:
        new_value = int(answer.strip())
    except (TypeError, ValueError, AttributeError):
        rs.MessageBox("Not a whole number: {0}".format(answer),
                      buttons=0, title=__title__)
        return
    if new_value < 1:
        rs.MessageBox("Interval must be at least 1 minute.",
                      buttons=0, title=__title__)
        return
    settings[_BACKUP_INTERVAL_KEY] = new_value
    _save_settings(settings_path, settings)
    rs.MessageBox("Backup interval set to {0} min.\nStored in library-settings.json.".format(new_value),
                  buttons=0, title=__title__)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_backup():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT); return
    index_path, settings_path = catalog.find_catalog_paths()
    if not index_path or not os.path.isfile(index_path):
        rs.MessageBox("No catalog index found yet.\n"
                      "Refresh the Grasshopper library first, then try again.",
                      buttons=0, title=__title__)
        return

    settings_path = _settings_write_path(index_path, settings_path)
    settings = _load_settings(settings_path)
    index = catalog.load_index(index_path)
    scan_roots = _scan_roots(index, settings)
    if not scan_roots:
        rs.MessageBox("No catalog scan roots found.\n"
                      "Set scan roots in the Grasshopper library first.",
                      buttons=0, title=__title__)
        return

    interval = _get_interval(settings)
    backups_dir = _backups_dir(index_path)
    age = _newest_backup_age_minutes(backups_dir)
    if age is None:
        last_line = "No backups yet."
        hint = "Create the first backup now."
    elif age < interval:
        last_line = "Newest backup is {0} min old.".format(age)
        hint = "That is within the {0}-min interval — a fresh backup is optional.".format(interval)
    else:
        last_line = "Newest backup is {0} min old.".format(age)
        hint = "That is older than the {0}-min interval — a backup is recommended.".format(interval)

    action = RHINO_FORMS.select_from_list(
        ["Back up now", "Change backup interval..."],
        title="EnneadTab Library Backup",
        message="{0}\n{1}\n\nInterval: {2} min (stored in library-settings.json).".format(
            last_line, hint, interval),
        button_names=["Go"],
        multi_select=False)
    if not action:
        return

    if action == "Change backup interval...":
        _change_interval(settings, settings_path, interval)
        return

    zip_path, copied, pruned = _do_backup(scan_roots, backups_dir)
    if copied == 0:
        try:
            os.remove(zip_path)
        except (OSError, IOError):
            pass
        rs.MessageBox("No *.ennead.json sidecars found under the scan roots.\n"
                      "Nothing was backed up.",
                      buttons=0, title=__title__)
        return

    settings[_BACKUP_INTERVAL_KEY] = interval
    _save_settings(settings_path, settings)
    rs.MessageBox("Backed up {0} sidecar(s) to:\n{1}\n\nPruned {2} old backup(s); keeping the newest {3}.".format(
        copied, zip_path, pruned, _MAX_BACKUPS),
        buttons=0, title=__title__)

library_backup()
