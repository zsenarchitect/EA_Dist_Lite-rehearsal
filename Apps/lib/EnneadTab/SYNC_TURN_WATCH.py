# -*- coding: utf-8 -*-
"""Local watch list + poll for 'your turn to sync' desktop toasts.

IronPython 2.7: no f-strings, no type hints. State is a dump-folder JSON so
pyRevit engines (startup vs hooks) share it.
"""

WATCH_FILE = "sync_turn_watch"
MAX_WATCHES = 8
POLL_SECONDS = 20

_poller_started = False


def _head_username(queue):
    if not queue:
        return ""
    entry = queue[0] or {}
    return (entry.get("username") or "").strip()


def _in_queue(queue, username):
    name = (username or "").strip()
    if not name:
        return False
    for entry in queue or []:
        if (entry.get("username") or "").strip() == name:
            return True
    return False


def evaluate_watch(watch, queue, username):
    """Return (action, watch). action is toast, keep, or drop."""
    watch = dict(watch or {})
    username = (username or "").strip()
    if not username or not _in_queue(queue, username):
        return "drop", watch
    head = _head_username(queue)
    if not head:
        watch["toasted_as_head"] = False
        return "keep", watch
    if head != username:
        watch["toasted_as_head"] = False
        return "keep", watch
    if watch.get("toasted_as_head"):
        return "keep", watch
    watch["toasted_as_head"] = True
    return "toast", watch


def build_toast_payload(watch):
    watch = watch or {}
    model_name = (watch.get("model_name") or "this model").strip() or "this model"
    dashboard_url = (watch.get("dashboard_url") or "").strip()
    actions = [{"id": "on_it", "label": "I'm on it", "type": "dismiss"}]
    if dashboard_url:
        actions.append({
            "id": "see_queue",
            "label": "See queue",
            "type": "open_url",
            "payload": dashboard_url,
        })
    return {
        "title": "Your turn to sync",
        "main_text": "{}\nGo sync in Revit.".format(model_name),
        "level": "warning",
        "sticky": True,
        "actions": actions,
    }


def load_state():
    try:
        import DATA_FILE
        data = DATA_FILE.get_data(WATCH_FILE, is_local=True) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    watches = data.get("watches") or []
    if not isinstance(watches, list):
        watches = []
    return {
        "username": data.get("username") or "",
        "watches": watches,
    }


def save_state(state):
    try:
        import DATA_FILE
        DATA_FILE.set_data({
            "username": (state or {}).get("username") or "",
            "watches": (state or {}).get("watches") or [],
        }, WATCH_FILE, is_local=True)
    except Exception:
        pass


def add_watch(model_guid, model_name, username, dashboard_url=None):
    guid = (model_guid or "").strip()
    user = (username or "").strip()
    if not guid or not user:
        return
    state = load_state()
    state["username"] = user
    remaining = [w for w in state["watches"] if (w.get("model_guid") or "") != guid]
    remaining.append({
        "model_guid": guid,
        "model_name": (model_name or "").strip() or guid,
        "dashboard_url": (dashboard_url or "").strip(),
        "toasted_as_head": False,
    })
    overflow = len(remaining) - MAX_WATCHES
    if overflow > 0:
        remaining = remaining[overflow:]
    state["watches"] = remaining
    save_state(state)


def remove_watch(model_guid):
    guid = (model_guid or "").strip()
    if not guid:
        return
    state = load_state()
    state["watches"] = [
        w for w in state["watches"] if (w.get("model_guid") or "") != guid
    ]
    save_state(state)


def poll_once(get_status, notify, username=None):
    """One pass over the watch list. Returns how many toasts were sent."""
    state = load_state()
    user = (username or state.get("username") or "").strip()
    if not user:
        return 0
    kept = []
    fired = 0
    for watch in state.get("watches") or []:
        guid = (watch.get("model_guid") or "").strip()
        if not guid:
            continue
        try:
            status = get_status(guid)
        except Exception:
            kept.append(watch)
            continue
        if status is None:
            kept.append(watch)
            continue
        queue = status.get("queue") or []
        url = (status.get("dashboard_url") or watch.get("dashboard_url") or "").strip()
        if url:
            watch["dashboard_url"] = url
        action, watch = evaluate_watch(watch, queue, user)
        if action == "drop":
            continue
        if action == "toast":
            try:
                notify(build_toast_payload(watch))
                fired += 1
            except Exception:
                watch["toasted_as_head"] = False
        kept.append(watch)
    state["username"] = user
    state["watches"] = kept
    save_state(state)
    return fired


def _default_get_status(model_guid):
    try:
        from EnneadTab.REVIT import REVIT_SYNC
        return REVIT_SYNC.api_get_status(model_guid)
    except Exception:
        try:
            import REVIT_SYNC
            return REVIT_SYNC.api_get_status(model_guid)
        except Exception:
            return None


def _default_notify(payload):
    import NOTIFICATION
    NOTIFICATION.messenger(
        main_text=payload.get("main_text") or "",
        title=payload.get("title"),
        level=payload.get("level") or "warning",
        sticky=bool(payload.get("sticky")),
        actions=payload.get("actions"),
    )


def start_poller():
    """Idempotent. Daemon thread, 20s interval. Revit startup engine only."""
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    import threading
    import time

    def _loop():
        while True:
            try:
                poll_once(_default_get_status, _default_notify)
            except Exception:
                pass
            time.sleep(POLL_SECONDS)

    thread = threading.Thread(target=_loop)
    thread.daemon = True
    thread.start()
