"""Dump-folder inbox: discover, parse, consume notification JSON files."""

from __future__ import print_function

import json
import os
import shutil
import time

INBOX_SUBDIR = "messenger_inbox"
FILE_PREFIX = "notif_"
FILE_SUFFIX = ".sexyDuck"
POISON_SUBDIR = "_poison"
MAX_QUEUE = 50
TTL_SECONDS = 3600  # drop unread older than 1h on drain


def get_dump_folder():
    """Resolve EnneadTab Dump folder (same as _Exe_Util / ENVIRONMENT)."""
    eco = os.path.join(
        os.environ.get("USERPROFILE", ""),
        "Documents",
        "EnneadTab Ecosystem",
    )
    dump = os.path.join(eco, "Dump")
    if not os.path.exists(dump):
        try:
            os.makedirs(dump)
        except OSError:
            pass
    return dump


def get_inbox_dir():
    path = os.path.join(get_dump_folder(), INBOX_SUBDIR)
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def get_poison_dir():
    path = os.path.join(get_inbox_dir(), POISON_SUBDIR)
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def list_ready_files():
    """Return sorted paths of complete inbox files (ignore .tmp)."""
    inbox = get_inbox_dir()
    if not os.path.isdir(inbox):
        return []
    files = []
    for name in os.listdir(inbox):
        if name.startswith(".") or name == POISON_SUBDIR:
            continue
        if name.endswith(".tmp") or name.endswith(".partial"):
            continue
        if not name.startswith(FILE_PREFIX):
            continue
        if not name.endswith(FILE_SUFFIX):
            continue
        path = os.path.join(inbox, name)
        if os.path.isfile(path):
            files.append(path)
    files.sort(key=lambda p: os.path.getmtime(p))
    return files


def _quarantine(path, reason):
    try:
        dest_dir = get_poison_dir()
        base = os.path.basename(path)
        dest = os.path.join(dest_dir, "{}_{}".format(int(time.time()), base))
        shutil.move(path, dest)
        print("Quarantined poison inbox file ({}): {}".format(reason, dest))
    except Exception as e:
        print("Failed to quarantine {}: {}".format(path, e))
        try:
            os.remove(path)
        except Exception:
            pass


def read_and_consume(path):
    """Parse one inbox file and delete it. Returns dict or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        if not raw.strip():
            _quarantine(path, "empty")
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or "main_text" not in data:
            _quarantine(path, "bad_shape")
            return None
        try:
            os.remove(path)
        except OSError:
            pass
        return data
    except (ValueError, json.JSONDecodeError) as e:
        _quarantine(path, "json:{}".format(e))
        return None
    except Exception as e:
        print("Error reading inbox {}: {}".format(path, e))
        return None


def drain(max_items=MAX_QUEUE):
    """Consume ready files into a list of payload dicts (oldest first).

    Drops TTL-expired files. Caps at max_items (keeps newest if over).
    """
    ready = list_ready_files()
    now = time.time()
    kept = []
    for path in ready:
        try:
            age = now - os.path.getmtime(path)
            if age > TTL_SECONDS:
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
        except OSError:
            continue
        kept.append(path)

    if len(kept) > max_items:
        drop = kept[:-max_items]
        kept = kept[-max_items:]
        for path in drop:
            try:
                os.remove(path)
            except OSError:
                pass

    payloads = []
    for path in kept:
        data = read_and_consume(path)
        if data:
            payloads.append(data)
    return payloads
