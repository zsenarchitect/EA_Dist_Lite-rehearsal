#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Upload the most recent closed Revit journal to Crash Detective and open the diagnosis.

Finds the latest closed-session journal under %LOCALAPPDATA%\\Autodesk\\Revit, asks for confirm,
then submits it for automatic analysis and opens the investigation result page. If upload is not
possible (file too large, network, or API unavailable), copies the journal path to the clipboard
and opens the Crash Detective site so you can drop the file manually.

Features:
- Prefers the prior closed session over the live Revit journal when distinguishable
- Confirm dialog before any upload (Cancel does nothing)
- Graceful clipboard fallback when the journal is oversized or upload fails
- Works with no document open (zero-doc)"""
__title__ = "Report\nLast Crash"
__context__ = "zero-doc"
__tip__ = True
import proDUCKtion # pyright: ignore
proDUCKtion.validify()

import os
import time
import webbrowser
from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, CLIPBOARD, CRASH_DETECTIVE
from EnneadTab.REVIT import REVIT_FORMS

UPLOAD_OPTION = "Upload & Open Diagnosis"
COPY_PATH_OPTION = "Copy path & open site"
CANCEL_OPTION = "Cancel"


def _format_size(nbytes):
    """Human-readable file size for the confirm dialog."""
    try:
        n = float(nbytes)
    except Exception:
        return "?"
    if n < 1024:
        return "{} B".format(int(n))
    if n < 1024 * 1024:
        return "{:.1f} KB".format(n / 1024.0)
    return "{:.1f} MB".format(n / (1024.0 * 1024.0))


def _display_path(path):
    """Shorten %LOCALAPPDATA% prefix when present; otherwise return full path."""
    local = os.environ.get("LOCALAPPDATA", "")
    if local and path.startswith(local):
        return "%LOCALAPPDATA%" + path[len(local):]
    return path


def _journal_confirm_details(journal_path):
    """Build main/sub text for the confirm dialog (name, path, size, mtime)."""
    file_name = os.path.basename(journal_path)
    display = _display_path(journal_path)
    try:
        size_str = _format_size(os.path.getsize(journal_path))
    except Exception:
        size_str = "?"
    try:
        mtime_str = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(os.path.getmtime(journal_path)))
    except Exception:
        mtime_str = "?"

    main_text = "Upload this journal to Crash Detective?"
    sub_text = (
        "File: {}\n"
        "Path: {}\n"
        "Size: {}\n"
        "Modified: {}"
    ).format(file_name, display, size_str, mtime_str)
    return main_text, sub_text


def _confirm_upload(journal_path):
    """Ask before POST. Returns UPLOAD_OPTION, COPY_PATH_OPTION, or CANCEL_OPTION."""
    main_text, sub_text = _journal_confirm_details(journal_path)
    res = REVIT_FORMS.dialogue(
        title="EnneadTab Crash Reporter",
        main_text=main_text,
        sub_text=sub_text,
        options=[
            [UPLOAD_OPTION, "Submit journal and open the diagnosis page"],
            [COPY_PATH_OPTION, "No upload -- copy path and open Crash Detective"],
            CANCEL_OPTION,
        ],
        icon="info")
    if isinstance(res, (tuple, list)):
        res = res[0]
    if res in (UPLOAD_OPTION, COPY_PATH_OPTION):
        return res
    return CANCEL_OPTION


def _fallback_open_site(journal_path, main_text, sub_text):
    if journal_path and os.path.exists(journal_path):
        try:
            CLIPBOARD.copy_to_clipboard(journal_path)
        except Exception:
            pass
    NOTIFICATION.messenger(
        main_text=main_text,
        sub_text=sub_text,
        window_title="EnneadTab Crash Reporter"
    )
    webbrowser.open(CRASH_DETECTIVE.CRASH_DETECTIVE_HOME)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def report_last_crash():
    latest_journal = CRASH_DETECTIVE.pick_report_journal()

    if not latest_journal or not os.path.exists(latest_journal):
        NOTIFICATION.messenger(
            main_text="Could not automatically locate a Revit journal file.",
            sub_text="Opening Revit Crash Detective...",
            window_title="EnneadTab Crash Reporter"
        )
        webbrowser.open(CRASH_DETECTIVE.CRASH_DETECTIVE_HOME)
        return

    choice = _confirm_upload(latest_journal)
    if choice == CANCEL_OPTION:
        return

    file_name = os.path.basename(latest_journal)

    if choice == COPY_PATH_OPTION:
        _fallback_open_site(
            latest_journal,
            "Journal path copied:\n{}\n\nDrop it into Crash Detective.".format(file_name),
            "Opening Revit Crash Detective...")
        return

    NOTIFICATION.messenger(
        main_text="Uploading journal to Crash Detective:\n{}".format(file_name),
        sub_text="Submitting for automatic diagnosis...",
        window_title="EnneadTab Crash Reporter"
    )

    result = CRASH_DETECTIVE.submit_journal_file(latest_journal)
    if result.get("ok") and result.get("url"):
        NOTIFICATION.messenger(
            main_text="Journal submitted:\n{}".format(file_name),
            sub_text="Opening diagnosis...",
            window_title="EnneadTab Crash Reporter"
        )
        webbrowser.open(result["url"])
        return

    reason = result.get("reason")
    if reason == "too_large":
        main = (
            "Journal is too large to auto-upload:\n{}\n\n"
            "Path copied to clipboard -- drop it into Crash Detective."
        ).format(file_name)
        sub = "Opening Revit Crash Detective..."
    elif reason in ("redirect", "auth"):
        main = (
            "Could not auto-submit (sign-in or API gate):\n{}\n\n"
            "Path copied to clipboard -- drop it into Crash Detective."
        ).format(file_name)
        sub = "Opening Revit Crash Detective..."
    elif reason == "transport":
        main = (
            "Could not reach Crash Detective:\n{}\n\n"
            "Path copied to clipboard -- drop it into Crash Detective when online."
        ).format(file_name)
        sub = "Opening Revit Crash Detective..."
    else:
        main = (
            "Auto-upload did not complete for:\n{}\n\n"
            "Path copied to clipboard -- drop it into Crash Detective."
        ).format(file_name)
        sub = "Opening Revit Crash Detective..."

    _fallback_open_site(latest_journal, main, sub)


if __name__ == "__main__":
    report_last_crash()
