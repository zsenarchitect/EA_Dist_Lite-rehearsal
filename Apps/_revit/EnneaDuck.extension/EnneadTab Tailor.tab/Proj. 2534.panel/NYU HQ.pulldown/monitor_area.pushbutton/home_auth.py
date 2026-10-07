#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
EnneadTab-Home device auth for the NYU HQ Revit panel.

Interactive Revit sessions authenticate to the NYU HQ API through the user's
EnneadTab-Home sign-in -- no NYU_HQ_SERVICE_TOKEN env var needed:

  1. POST https://enneadtab.com/api/desktop-auth/start  {"app": "revit"}
     -> {"sessionId", "authUrl", "app"}
  2. The authUrl is opened in the browser. The user is already SSO'd on
     enneadtab.com in the common case (otherwise they sign in there) and
     approves the device.
  3. Poll GET https://enneadtab.com/api/desktop-auth/poll?session=<id>
     every 2 s until {"status": "ready", "token": ...} (HTTP 202 while
     pending, 404 when the session is gone).

The bearer token is cached at %APPDATA%/EnneadTab/nyu_hq_home_token.json,
DPAPI-protected (Windows, CurrentUser scope) via clr +
System.Security.Cryptography.ProtectedData. The cache holds
{"token": ..., "exp": ...}; get_token() returns the cached token while it
is still valid (60 s leeway) and only runs the browser flow otherwise.

On machines without DPAPI (non-Windows) the token cannot be stored
securely -- get_token() raises a clear error telling the user to set
NYU_HQ_SERVICE_TOKEN instead. The cache is never written as plaintext.

Python 2 / IronPython compatible (Revit). _protect/_unprotect are
module-level so CPython tests can monkeypatch them.
"""

import base64
import json
import os
import time
import webbrowser

try:
    # Python 3
    import urllib.request as _request
    import urllib.error as _error
    from urllib.parse import quote as _quote
except ImportError:
    # Python 2 / IronPython
    import urllib2 as _request
    _error = _request
    from urllib import quote as _quote

try:
    import clr
    clr.AddReference("System.Security")
    from System.Security.Cryptography import ProtectedData, DataProtectionScope
    from System import Array, Byte
    _HAVE_DPAPI = True
except Exception:
    _HAVE_DPAPI = False


HOME_ORIGIN = "https://enneadtab.com"
_AUTH_START_URL = HOME_ORIGIN + "/api/desktop-auth/start"
_AUTH_POLL_URL = HOME_ORIGIN + "/api/desktop-auth/poll"
_TOKEN_FILENAME = "nyu_hq_home_token.json"
_EXP_LEEWAY_SECONDS = 60
_POLL_INTERVAL_SECONDS = 2
_POLL_TIMEOUT_SECONDS = 180


def _fail(message):
    """Raise NyuHqApiError. Imported lazily to avoid an import cycle:
    nyu_hq_api imports this module, so a top-level import would be
    circular."""
    from nyu_hq_api import NyuHqApiError
    raise NyuHqApiError(message)


# ---------------------------------------------------------------------------
# DPAPI protection
# ---------------------------------------------------------------------------

def _protect(data):
    """DPAPI-protect bytes for the current Windows user.

    Raises NyuHqApiError when DPAPI is unavailable (non-Windows): the
    token must never be stored as plaintext.
    """
    if not _HAVE_DPAPI:
        _fail(
            "Cannot store the EnneadTab sign-in token securely on this "
            "machine (Windows DPAPI is unavailable).\n"
            "Set the NYU_HQ_SERVICE_TOKEN environment variable instead, "
            "or sign in from a Windows machine.")
    net_in = Array[Byte](bytearray(data))
    net_out = ProtectedData.Protect(net_in, None,
                                    DataProtectionScope.CurrentUser)
    return bytes(bytearray(net_out))


def _unprotect(data):
    """Reverse _protect. Raises NyuHqApiError when DPAPI is unavailable."""
    if not _HAVE_DPAPI:
        _fail(
            "Cannot read the cached EnneadTab sign-in token on this "
            "machine (Windows DPAPI is unavailable).\n"
            "Set the NYU_HQ_SERVICE_TOKEN environment variable instead, "
            "or sign in from a Windows machine.")
    net_in = Array[Byte](bytearray(data))
    net_out = ProtectedData.Unprotect(net_in, None,
                                      DataProtectionScope.CurrentUser)
    return bytes(bytearray(net_out))


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------

def _cache_path():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "EnneadTab", _TOKEN_FILENAME)


def _read_cached_token():
    """Return the cached token string, or None when there is no cache."""
    path = _cache_path()
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        blob = f.read()
    try:
        payload = json.loads(_unprotect(blob).decode("utf-8"))
    except Exception:
        # Corrupt cache: treat as missing; the device flow will rewrite it.
        return None
    token = payload.get("token") if isinstance(payload, dict) else None
    return token or None


def _write_cached_token(token):
    path = _cache_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    payload = json.dumps({"token": token,
                          "exp": _token_exp(token)}).encode("utf-8")
    with open(path, "wb") as f:
        f.write(_protect(payload))


def forget_token():
    """Delete the cached token (used when the API rejects it with 401)."""
    try:
        os.remove(_cache_path())
    except OSError:
        pass


# ---------------------------------------------------------------------------
# JWT exp helpers (no signature verification -- client-side freshness only)
# ---------------------------------------------------------------------------

def _b64url_decode(segment):
    if isinstance(segment, bytes):
        segment = segment.decode("ascii")
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _token_exp(token):
    """Return the token's exp claim (epoch seconds), or None."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def token_expired(token):
    """True when the token is missing its exp or expires within the leeway."""
    exp = _token_exp(token)
    if exp is None:
        return True
    return exp <= time.time() + _EXP_LEEWAY_SECONDS


# ---------------------------------------------------------------------------
# Device flow HTTP
# ---------------------------------------------------------------------------

def _http_post_json(url, payload, timeout=30):
    """POST JSON, return the decoded JSON body. Raises NyuHqApiError."""
    data = json.dumps(payload).encode("utf-8")
    req = _request.Request(url, data=data)
    req.add_header("Content-Type", "application/json")
    try:
        resp = _request.urlopen(req, timeout=timeout)
        raw = resp.read()
    except _error.HTTPError as e:
        _fail("EnneadTab sign-in request failed (HTTP {}). Please try "
              "again.".format(e.code))
    except Exception as e:
        _fail("Could not reach {} for EnneadTab sign-in: {}".format(
            HOME_ORIGIN, e))
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except ValueError:
        _fail("EnneadTab sign-in returned an unexpected response. "
              "Please try again.")


def _http_get_json(url, timeout=30):
    """GET JSON. Returns (http_status, decoded_body_or_None)."""
    req = _request.Request(url)
    req.add_header("Accept", "application/json")
    try:
        resp = _request.urlopen(req, timeout=timeout)
        status = resp.getcode()
        raw = resp.read()
    except _error.HTTPError as e:
        status = e.code
        try:
            raw = e.read()
        except Exception:
            raw = ""
    except Exception as e:
        _fail("Could not reach {} for EnneadTab sign-in: {}".format(
            HOME_ORIGIN, e))
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    return status, body


def _device_flow():
    """Run the browser device flow. Returns the bearer token."""
    started = _http_post_json(_AUTH_START_URL, {"app": "revit"})
    if not isinstance(started, dict):
        _fail("EnneadTab sign-in returned an unexpected response. "
              "Please try again.")
    session_id = started.get("sessionId")
    auth_url = started.get("authUrl")
    if not session_id or not auth_url:
        _fail("EnneadTab sign-in did not return a device session. "
              "Please try again.")
    webbrowser.open(auth_url)
    token = _poll_for_token(session_id)
    _write_cached_token(token)
    return token


def _poll_for_token(session_id):
    """Poll until the user approves the device. Returns the bearer token."""
    url = _AUTH_POLL_URL + "?session=" + _quote(session_id)
    deadline = time.time() + _POLL_TIMEOUT_SECONDS
    while True:
        if time.time() >= deadline:
            _fail("EnneadTab sign-in timed out after {} seconds without "
                  "approval. Please run the sync again and approve the "
                  "device in your browser.".format(_POLL_TIMEOUT_SECONDS))
        status, body = _http_get_json(url)
        if status == 404:
            _fail("The EnneadTab sign-in session expired before it was "
                  "approved. Please run the sync again.")
        if status >= 400:
            _fail("EnneadTab sign-in failed (HTTP {}). Please try "
                  "again.".format(status))
        if isinstance(body, dict) and body.get("status") == "ready" \
                and body.get("token"):
            return body["token"]
        # Pending (HTTP 202) or any other non-ready answer: keep waiting.
        time.sleep(_POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_token():
    """Return a valid NYU HQ API bearer token.

    Uses the cached token while it is still valid; otherwise runs the
    one-time browser device flow against EnneadTab-Home and caches the
    result. Raises NyuHqApiError with a human-readable message.
    """
    token = _read_cached_token()
    if token and not token_expired(token):
        return token
    # Fail fast when the token cannot be cached securely. _protect raises
    # NyuHqApiError on machines without DPAPI (never store plaintext); it
    # is a no-op probe everywhere else, and CPython tests monkeypatch it.
    _protect(b"enneadtab-home-auth-probe")
    return _device_flow()
