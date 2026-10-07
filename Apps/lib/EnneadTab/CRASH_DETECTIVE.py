# -*- coding: utf-8 -*-
"""Client helpers for EnneadTab Crash Detective (enneadtab.com/crash).

IronPython 2.7 safe (Revit/Rhino) and CPython 3.x safe. Finds the best Revit
journal to report, POSTs it to CrashDetective, and builds the investigation
result URL. The Revit ribbon button is the primary caller; keep this module
free of UI so a future desktop host can reuse the same contract.
"""

from __future__ import print_function

import glob
import json
import os
import shutil
import tempfile
import time

import AUTH
import WEB_GUARD

CRASH_DETECTIVE_HOME = "https://enneadtab.com/crash/"
INVESTIGATIONS_API = "https://enneadtab.com/crash/api/v1/investigations"
INVESTIGATION_VIEW_TMPL = "https://enneadtab.com/crash/investigation/{0}"

# Client-side cap: JSON-encoding a huge journal doubles memory in IronPython
# and can freeze Revit. Larger files fall back to clipboard + open site.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB
READ_CHUNK_BYTES = 1024 * 1024
POST_TIMEOUT_MS = 45000

# If the newest journal was touched this recently, treat it as the live
# session and prefer the previous closed journal when one exists.
LIVE_JOURNAL_MTIME_SEC = 90

_USE_DOTNET = False
try:
    from System.Net import WebRequest, ServicePointManager, SecurityProtocolType  # pyright: ignore
    from System.IO import StreamReader  # pyright: ignore
    from System.Text import Encoding  # pyright: ignore
    _USE_DOTNET = True
except ImportError:
    pass

if not _USE_DOTNET:
    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
    except ImportError:
        from urllib2 import Request, urlopen, HTTPError  # pyright: ignore


def list_journal_paths():
    """Return journal.*.txt paths under %LOCALAPPDATA%\\Autodesk\\Revit."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return []

    revit_dir = os.path.join(local_app_data, "Autodesk", "Revit")
    if not os.path.isdir(revit_dir):
        return []

    pattern = os.path.join(revit_dir, "Autodesk Revit *", "Journals", "journal.*.txt")
    journal_files = glob.glob(pattern)
    if not journal_files:
        pattern_fallback = os.path.join(revit_dir, "*", "Journals", "journal.*.txt")
        journal_files = glob.glob(pattern_fallback)

    return [p for p in journal_files if os.path.isfile(p)]


def pick_report_journal(paths=None, now=None):
    """Pick the journal most likely to be the last closed / crash session.

    Hypothesis (verified against common Revit behavior): while Revit is open,
    the newest journal by mtime is the live session. After a crash + restart,
    the prior session journal is the second-newest and stopped receiving
    writes. When only one journal exists, return it.
    """
    if paths is None:
        paths = list_journal_paths()
    if not paths:
        return None

    ranked = sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)
    if len(ranked) == 1:
        return ranked[0]

    if now is None:
        now = time.time()
    newest = ranked[0]
    try:
        age = now - os.path.getmtime(newest)
    except Exception:
        return newest

    if age < LIVE_JOURNAL_MTIME_SEC:
        return ranked[1]
    return newest


def read_journal_text(path, max_bytes=MAX_UPLOAD_BYTES):
    """Read journal content as unicode text.

    Returns (text, None) on success, or (None, reason) when the file is missing,
    too large, or unreadable. Size is checked before a full read so oversized
    journals fail fast without loading into memory.
    """
    if not path or not os.path.isfile(path):
        return None, "missing"
    try:
        size = os.path.getsize(path)
    except Exception:
        return None, "unreadable"
    if size > max_bytes:
        return None, "too_large"

    chunks = []
    total = 0
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return None, "too_large"
                chunks.append(chunk)
    except Exception:
        return None, "unreadable"

    # Py3 rb -> bytes; Py2/IronPython rb -> str. Join with matching type.
    if chunks and isinstance(chunks[0], bytes):
        raw = b"".join(chunks)
    else:
        raw = "".join(chunks)
    # Normalize to text (unicode on Py2, str on Py3).
    if not isinstance(raw, type(u"")):
        try:
            return raw.decode("utf-8"), None
        except Exception:
            try:
                return raw.decode("utf-8", "replace"), None
            except Exception:
                return raw.decode("latin-1", "replace"), None
    return raw, None


def investigation_url(investigation_id):
    """Build the diagnostic result page URL for a submitted investigation."""
    return INVESTIGATION_VIEW_TMPL.format(investigation_id)


def parse_investigation_response(status, payload):
    """Return investigation id from a successful create response, else None.

    Contract: HTTP 202 (or 200) with JSON containing ``id``.
    """
    if status not in (200, 202):
        return None
    if not isinstance(payload, dict):
        return None
    inv_id = payload.get("id")
    if inv_id is None:
        return None
    inv_id = str(inv_id).strip()
    return inv_id or None


def _auth_token():
    try:
        return AUTH.get_token()
    except Exception:
        return None


def _dotnet_error_body(err):
    status = 0
    text = ""
    try:
        response = getattr(err, "Response", None)
        if response is not None:
            try:
                status = int(response.StatusCode)
            except Exception:
                status = 0
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            text = reader.ReadToEnd()
            reader.Close()
    except Exception:
        pass
    return status, text


def _post_json_dotnet(url, body_str, token, timeout_ms):
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
    except Exception:
        pass

    request = WebRequest.Create(url)
    request.Method = "POST"
    request.ContentType = "application/json"
    request.Timeout = timeout_ms
    WEB_GUARD.harden_dotnet_request(request)
    if token:
        request.Headers.Add("Authorization", "Bearer {0}".format(token))

    body_bytes = Encoding.UTF8.GetBytes(body_str)
    request.ContentLength = body_bytes.Length
    stream = request.GetRequestStream()
    try:
        stream.Write(body_bytes, 0, body_bytes.Length)
    finally:
        stream.Close()

    try:
        response = request.GetResponse()
        try:
            status = int(response.StatusCode)
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            text = reader.ReadToEnd()
            reader.Close()
        finally:
            response.Close()
        parsed = json.loads(text) if text else {}
        return status, parsed if isinstance(parsed, dict) else {}
    except Exception as err:
        status, text = _dotnet_error_body(err)
        parsed = {}
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {"message": text[:500]}
        if not parsed:
            parsed = {"message": str(err)}
        return status, parsed if isinstance(parsed, dict) else {"message": str(err)}


def _post_json_urllib(url, body_str, token, timeout_ms):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer {0}".format(token)
    encoded = body_str.encode("utf-8")
    timeout_sec = max(1, int(timeout_ms / 1000.0))

    req = Request(url, data=encoded)
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        response = WEB_GUARD.urlopen_no_redirect(req, timeout_sec)
        status = getattr(response, "code", None) or getattr(response, "status", 200) or 200
        raw = response.read()
        if not isinstance(raw, type(u"")):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw) if raw else {}
        return int(status), parsed if isinstance(parsed, dict) else {}
    except HTTPError as err:
        raw = ""
        try:
            raw = err.read()
            if raw and not isinstance(raw, type(u"")):
                raw = raw.decode("utf-8")
        except Exception:
            pass
        parsed = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"message": raw[:500]}
        if not parsed:
            parsed = {"message": str(err)}
        return int(getattr(err, "code", 0) or 0), parsed if isinstance(parsed, dict) else {}
    except Exception as err:
        return 0, {"message": str(err)}


def post_investigation(journal_content, timeout_ms=POST_TIMEOUT_MS, token=None):
    """POST journal text to CrashDetective. Returns (http_status, parsed_dict).

    Never raises for HTTP/transport failures. Prefer .NET HttpWebRequest under
    IronPython (urllib TLS is unreliable inside Revit on some office networks).
    """
    payload = {"journal_content": journal_content}
    body_str = json.dumps(payload)
    if token is None:
        token = _auth_token()

    if _USE_DOTNET:
        return _post_json_dotnet(INVESTIGATIONS_API, body_str, token, timeout_ms)
    return _post_json_urllib(INVESTIGATIONS_API, body_str, token, timeout_ms)


def submit_journal_file(path, max_bytes=MAX_UPLOAD_BYTES, timeout_ms=POST_TIMEOUT_MS):
    """Read ``path`` and create an investigation.

    Returns a result dict:
      ok (bool)
      investigation_id (str|None)
      url (str|None) -- investigation page when ok
      reason (str|None) -- missing|too_large|unreadable|http|auth|redirect|transport|no_id
      status (int)
      detail (dict|str|None)
      path (str)
    """
    result = {
        "ok": False,
        "investigation_id": None,
        "url": None,
        "reason": None,
        "status": 0,
        "detail": None,
        "path": path,
    }
    text, read_err = read_journal_text(path, max_bytes=max_bytes)
    if read_err:
        result["reason"] = read_err
        return result

    status, payload = post_investigation(text, timeout_ms=timeout_ms)
    result["status"] = status
    result["detail"] = payload
    inv_id = parse_investigation_response(status, payload)
    if inv_id:
        result["ok"] = True
        result["investigation_id"] = inv_id
        result["url"] = investigation_url(inv_id)
        return result

    if WEB_GUARD.is_redirect(status):
        result["reason"] = "redirect"
    elif status in (401, 403):
        result["reason"] = "auth"
    elif status == 0:
        result["reason"] = "transport"
    elif status:
        result["reason"] = "http"
    else:
        result["reason"] = "no_id"
    return result


def unit_test():
    """Lightweight CPython checks for selection + response parsing."""
    root = tempfile.mkdtemp(prefix="crash_detective_")
    try:
        a = os.path.join(root, "journal.0001.txt")
        b = os.path.join(root, "journal.0002.txt")
        with open(a, "wb") as handle:
            handle.write(b"old session\n")
        with open(b, "wb") as handle:
            handle.write(b"live session\n")
        now = time.time()
        os.utime(a, (now - 3600, now - 3600))
        os.utime(b, (now - 5, now - 5))
        picked = pick_report_journal([a, b], now=now)
        assert picked == a, "should prefer prior closed journal over live"

        os.utime(b, (now - 600, now - 600))
        picked = pick_report_journal([a, b], now=now)
        assert picked == b, "newest closed journal wins when not live"

        text, err = read_journal_text(a)
        assert err is None and "old session" in text

        huge = os.path.join(root, "journal.huge.txt")
        with open(huge, "wb") as handle:
            handle.write(b"x" * 100)
        text, err = read_journal_text(huge, max_bytes=50)
        assert text is None and err == "too_large"

        assert parse_investigation_response(
            202, {"id": "abc-123", "status": "queued"}
        ) == "abc-123"
        assert parse_investigation_response(200, {"id": "xyz"}) == "xyz"
        assert parse_investigation_response(500, {"id": "nope"}) is None
        assert parse_investigation_response(202, {}) is None
        assert investigation_url("abc-123").endswith("/crash/investigation/abc-123")
        print("CRASH_DETECTIVE unit_test OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unit_test()
