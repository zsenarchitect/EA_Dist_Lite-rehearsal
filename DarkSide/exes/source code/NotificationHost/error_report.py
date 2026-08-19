"""Fire-and-forget ErrorDump reporter for NotificationHost.

Standalone stdlib POST so the frozen exe does not need EnneadTab imports.
Payload shape matches ERROR_HANDLE.send_error_to_error_dump /
infrawatch_common.report_error (source_app EnneadTab-OS).
"""

from __future__ import print_function

import json
import os
import socket
import sys
import traceback
import urllib.request

_INGEST_URL = "https://error-dump-ennead-projects.vercel.app/error-dump/api/ingest"
_TIMEOUT = 5


def report(error_message, func_name="NotificationHost", is_silent=True):
    """POST to EnneadTab-ErrorDump. Never raises."""
    try:
        msg = str(error_message) if error_message is not None else "unknown"
        payload = {
            "source_app": "EnneadTab-OS",
            "environment": "terminal",
            "error_message": msg[:5000],
            "stack_trace": msg[:10000],
            "function_name": str(func_name),
            "user_name": os.environ.get("USERNAME")
            or os.environ.get("USER", "unknown"),
            "machine_name": os.environ.get("COMPUTERNAME")
            or socket.gethostname(),
            "context": {
                "is_silent": bool(is_silent),
                "component": "NotificationHost",
                "frozen": bool(getattr(sys, "frozen", False)),
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _INGEST_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=_TIMEOUT)
    except Exception:
        pass


def report_exc(func_name="NotificationHost", is_silent=True):
    """Report the current exception (call from an except block)."""
    report(traceback.format_exc(), func_name=func_name, is_silent=is_silent)


def install_excepthook():
    """Send uncaught exceptions to ErrorDump, then chain to previous hook."""
    previous = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            report(
                "".join(traceback.format_exception(exc_type, exc, tb)),
                func_name="NotificationHost.excepthook",
                is_silent=False,
            )
        except Exception:
            pass
        try:
            previous(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook
