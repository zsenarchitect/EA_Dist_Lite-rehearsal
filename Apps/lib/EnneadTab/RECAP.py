"""Show the pending usage digest inside Revit and Rhino.

IronPython 2.7 SAFE. No f-strings, no type hints, no pathlib. This module is
imported by both hosts, so it must stay parseable by the oldest runtime.

This side COMPUTES NOTHING. The scheduled CPython producer
(Apps/lib/DumpScripts/recap/recap_main.py) does all reading, math, claim
selection and copywriting, then leaves a small handoff file. Here we only
read it, check it is fresh, and hand it to NOTIFICATION.

Two reasons that split matters beyond tidiness:
  * A full log parse must never run on the Revit UI thread at startup.
  * Revit and Rhino call the identical function, so there is no per-framework
    logic that CAN drift. The CLAUDE.md Rhino<->Revit parity rule is satisfied
    by construction rather than by remembering to mirror an edit.
"""

import os
import time

import CONFIG
import DATA_FILE
import ERROR_HANDLE
import FOLDER
import NOTIFICATION

try:
    import ENVIRONMENT
    PLUGIN_EXTENSION = ENVIRONMENT.PLUGIN_EXTENSION
except Exception:
    PLUGIN_EXTENSION = ".sexyDuck"


PENDING_FILE = "recap_pending_digest"
PENDING_SCHEMA = 1

SETTING_DIGEST = "checkbox_recap_digest_weekly"
SETTING_EMAIL = "checkbox_recap_email_monthly"

# Absent or older than this and we show NOTHING. Stale numbers presented as
# current are worse than silence, and staleness is the COMMON failure here
# (task never enrolled, machine off for a fortnight), not the rare one.
MAX_AGE_DAYS = 21


def is_digest_enabled():
    """Weekly in-app digest opt-in. Defaults on."""
    return CONFIG.get_setting(SETTING_DIGEST, True)


def is_email_enabled():
    """Monthly recap email opt-in. Defaults on. Read by the producer."""
    return CONFIG.get_setting(SETTING_EMAIL, True)


def _parse_date(text):
    """'YYYY-MM-DD' -> epoch seconds, or None."""
    if not text:
        return None
    try:
        return time.mktime(time.strptime(str(text), "%Y-%m-%d"))
    except Exception:
        return None


def _read_pending():
    try:
        data = DATA_FILE.get_data(PENDING_FILE)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _is_showable(data):
    """Every reason we would rather show nothing at all."""
    if not data:
        return False
    if data.get("consumed"):
        return False
    if data.get("schema") != PENDING_SCHEMA:
        return False
    if not data.get("surface_text"):
        return False

    now = time.time()
    expires = _parse_date(data.get("expires_at"))
    if expires is not None and now > expires:
        return False

    generated = _parse_date(data.get("generated_at"))
    if generated is not None and (now - generated) > (MAX_AGE_DAYS * 86400):
        return False
    return True


def _mark_consumed(data):
    """One-shot consume. Written BEFORE the toast fires so a crash mid-show
    cannot produce a duplicate on the next startup."""
    try:
        data["consumed"] = True
        DATA_FILE.set_data(data, PENDING_FILE)
        return True
    except Exception:
        return False


def _build_actions(data):
    """The curiosity-gap resolver.

    The toast withholds WHICH tool; this action is where the reader gets the
    answer. A gap with no way to resolve it is the failure mode that costs a
    permanent opt-out, so the action is only offered when the target exists.
    """
    html_path = data.get("html_path")
    if not html_path:
        return None
    try:
        if not os.path.exists(html_path):
            return None
    except Exception:
        return None
    return [{
        "id": "recap_open",
        "label": "Show me",
        "type": "open_path",
        "payload": html_path,
    }]


@ERROR_HANDLE.try_catch_error(is_pass=True)
def show_pending_digest():
    """Show the weekly digest toast if one is pending, fresh and wanted.

    `is_pass` rather than `is_silent`: is_silent still SENDS an error email.
    This runs on every Revit and Rhino launch fleet-wide, so a persistent
    failure here would mail the whole office on every startup. A digest that
    fails to appear is a nicety not delivered, not an incident.
    """
    if not is_digest_enabled():
        return False

    data = _read_pending()
    if not _is_showable(data):
        return False

    # Consume first. A duplicate digest is more annoying than a missed one.
    _mark_consumed(data)

    chart = data.get("chart")
    kwargs = {
        "main_text": data.get("surface_text"),
        "level": "info",
        "sticky": True,
    }
    actions = _build_actions(data)
    if actions:
        kwargs["actions"] = actions
    if chart:
        # Declarative payload: NotificationHost renders it. Nothing is
        # rasterized here, which is what keeps this file IronPython safe.
        kwargs["chart"] = chart

    try:
        NOTIFICATION.messenger(**kwargs)
    except TypeError:
        # An older NotificationHost/NOTIFICATION without chart support. Show
        # the text rather than nothing -- a missing chart must never suppress
        # the message.
        kwargs.pop("chart", None)
        NOTIFICATION.messenger(**kwargs)
    return True


def peek():
    """Diagnostic: what the consumer currently sees. Never shows a toast."""
    data = _read_pending()
    return {
        "found": bool(data),
        "showable": _is_showable(data),
        "enabled": is_digest_enabled(),
        "surface_text": (data or {}).get("surface_text"),
        "generated_at": (data or {}).get("generated_at"),
        "expires_at": (data or {}).get("expires_at"),
        "consumed": (data or {}).get("consumed"),
        "path": FOLDER.get_local_dump_folder_file(
            PENDING_FILE + PLUGIN_EXTENSION),
    }
