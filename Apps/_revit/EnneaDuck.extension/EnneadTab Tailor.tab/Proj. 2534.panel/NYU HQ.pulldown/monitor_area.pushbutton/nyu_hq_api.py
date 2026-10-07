#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Minimal NYU HQ webapp API client.

The NYU HQ website repo holds ZERO data: Postgres is the system of record and
the webapp's /api/* endpoints are the only gateway. Revit syncs through them:

  - GET  /api/targets    clean program targets (Revit READS)
  - POST /api/report     matched area report (Revit PUBLISHES)
  - POST /api/geometry   extracted model geometry (Revit PUBLISHES)

Auth is a bearer token sent as ``Authorization: Bearer <token>``. For
interactive Revit sessions no env vars are required: the first sync runs a
one-time EnneadTab-Home device flow (see home_auth.py) -- the browser opens
for the user to approve the device on enneadtab.com, and the token is then
cached DPAPI-protected on the machine. Set NYU_HQ_SERVICE_TOKEN only for
headless/CI use, where it acts as an override.

Python 2 / IronPython compatible (Revit).
"""

import json

import config
import home_auth

try:
    # Python 3
    import urllib.request as _request
    import urllib.error as _error
except ImportError:
    # Python 2 / IronPython
    import urllib2 as _request
    _error = _request


class NyuHqApiError(Exception):
    """Raised when the NYU HQ API cannot be reached or rejects a request."""
    pass


def _api_origin():
    origin = (config.NYU_HQ_API_URL or "").strip().rstrip("/")
    if not origin:
        raise NyuHqApiError(
            "NYU_HQ_API_URL is not set.\n"
            "Set the NYU_HQ_API_URL environment variable to the NYU HQ "
            "webapp origin (e.g. https://enneadtab.com/projects/nyu-hq) "
            "and run again.")
    return origin


def _auth_token():
    """Return (token, from_env).

    The NYU_HQ_SERVICE_TOKEN env var wins when set (headless/CI override);
    otherwise the token comes from the EnneadTab-Home device flow
    (home_auth.get_token()), which needs no configuration.
    """
    env_token = (config.NYU_HQ_SERVICE_TOKEN or "").strip()
    if env_token:
        return env_token, True
    return home_auth.get_token(), False


def _actor():
    return (config.NYU_HQ_ACTOR or "").strip() or "revit-monitor-area"


def _do_request(path, payload, timeout, token):
    """Single GET/POST attempt. Returns (http_status, decoded_body)."""
    url = _api_origin() + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = _request.Request(url, data=data)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("X-Actor", _actor())
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
        raise NyuHqApiError(
            "NYU HQ API request failed ({} {}): {}".format(
                "POST" if payload is not None else "GET", path, e))
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    return status, body


def _call(path, payload=None, timeout=90):
    """GET (payload None) or POST (payload given) a JSON API path.

    Returns the decoded JSON body. Raises NyuHqApiError on any failure.

    When the token came from EnneadTab-Home (not the env override) and the
    API answers 401, the cached token is forgotten and the request is
    retried once with a fresh device-flow token before giving up.
    """
    token, from_env = _auth_token()
    status, body = _do_request(path, payload, timeout, token)
    if status == 401 and not from_env:
        home_auth.forget_token()
        token, _ = _auth_token()
        status, body = _do_request(path, payload, timeout, token)
    if status >= 400:
        detail = ""
        if isinstance(body, dict) and body.get("error"):
            detail = ": {}".format(body["error"])
        raise NyuHqApiError(
            "NYU HQ API {} {} returned HTTP {}{}".format(
                "POST" if payload is not None else "GET",
                path, status, detail))
    return body


def get_targets():
    """Fetch the clean target program document (GET /api/targets)."""
    return _call("/api/targets")


def post_report(report_data):
    """Publish the matched area report (POST /api/report)."""
    return _call("/api/report", payload=report_data)


def post_geometry(geometry_data):
    """Publish the extracted model geometry (POST /api/geometry)."""
    return _call("/api/geometry", payload=geometry_data)
