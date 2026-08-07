# -*- coding: utf-8 -*-
"""Stop a login page from being mistaken for a successful API call.

THE FAILURE THIS EXISTS TO PREVENT
----------------------------------
On 2026-08-07, probing production found that EnneadTab-Home's middleware
redirects several service API prefixes to an SSO login page -- `/bank/api/*`,
`/wiki/api/*` and `/depot/api/*` -- and does so even when the request carries an
`Authorization: Bearer` header, so the service behind it never sees the request.

That alone would be a visible outage. What made it invisible is the second half:
EVERY HTTP client here followed redirects by default. urllib3, urllib2,
urllib.request and .NET `HttpWebRequest` (`AllowAutoRedirect` defaults to True)
all chase the 302, land on the login page, and hand back **HTTP 200 with an HTML
body**. Any client whose success test is `status == 200` then reports success:

  * LEADER_BOARD deleted the queued event and incremented its "sent" count.
  * DEPOT's `STATE.write_state` returned True, so all 39 shared-state call sites
    behind `DATA_FILE.set_data(..., is_local=False)` silently wrote nothing.

No exception, no alarm, no log line. The one client that survived --
`AI/_common.py` -- did so because it explicitly checks `300 <= status < 400` and
converts it to an auth failure instead of following it. This module generalizes
that.

THE RULE
--------
A 3xx from our own infrastructure is a CONFIGURATION ERROR, not a route to
follow. Nothing here should ever chase one: an API that answers with a redirect
is an API that did not answer. Surfacing the 3xx makes a proxy misconfiguration
look like what it is, instead of like a delivery.

Body-consuming callers should additionally refuse a 200 whose body will not
parse -- see `is_delivered`. That is defence in depth: even if some future proxy
returns 200 directly rather than redirecting, an HTML body is still not an API
response.

IronPython 2.7 SAFE. No f-strings, no type hints, no pathlib. Loaded inside both
Revit and Rhino.
"""


REDIRECT_MIN = 300
REDIRECT_MAX = 400


def is_redirect(status):
    """True for any 3xx. Treat as a misrouted request, never as a retry-later."""
    if status is None:
        return False
    try:
        return REDIRECT_MIN <= int(status) < REDIRECT_MAX
    except Exception:
        return False


def is_delivered(status, parsed_payload):
    """True only when the service itself answered.

    For callers that consume a JSON body. `parsed_payload` is whatever the
    caller's JSON decode produced -- None when it could not be parsed, which is
    exactly what an HTML login page yields. A 200 with an unparseable body is
    NOT a delivery, however encouraging the status line looks.
    """
    if status is None:
        return False
    try:
        if int(status) != 200:
            return False
    except Exception:
        return False
    return parsed_payload is not None


def describe(status):
    """One-line explanation for a log note, or None when nothing is wrong.

    Kept here so every client words this failure the same way -- someone reading
    a log should be able to search one phrase across the whole fleet.
    """
    if is_redirect(status):
        return ("HTTP {} redirect from an API endpoint -- the request was routed "
                "to a login page and never reached the service. This is a proxy "
                "configuration problem, not an auth or network problem.".format(status))
    return None


# --------------------------------------------------------------- urllib

def no_redirect_opener():
    """A urllib opener that raises on 3xx instead of following it.

    Works on both Python 2 (`urllib2`) and Python 3 (`urllib.request`). Returning
    None from `redirect_request` makes urllib raise `HTTPError` carrying the real
    3xx code, which callers already handle -- they read `e.code`, so the redirect
    arrives as a status rather than as a fake 200.

    Returns None when neither module is importable; callers then fall back to
    their normal opener, which is no worse than today.
    """
    try:
        import urllib.request as _u          # Py3
        request_mod = _u
        redirect_base = _u.HTTPRedirectHandler
    except ImportError:
        try:
            import urllib2 as _u2            # Py2 / IronPython
            request_mod = _u2
            redirect_base = _u2.HTTPRedirectHandler
        except ImportError:
            return None

    class _NoRedirect(redirect_base):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        return request_mod.build_opener(_NoRedirect())
    except Exception:
        return None


def urlopen_no_redirect(request, timeout):
    """`urlopen` that surfaces a 3xx as an HTTPError rather than following it.

    Falls back to the plain `urlopen` if a no-redirect opener cannot be built --
    degraded, but never broken.
    """
    opener = no_redirect_opener()
    if opener is not None:
        return opener.open(request, timeout=timeout)
    try:
        import urllib.request as _u
        return _u.urlopen(request, timeout=timeout)
    except ImportError:
        import urllib2 as _u2
        return _u2.urlopen(request, timeout=timeout)


# --------------------------------------------------------------- .NET

def harden_dotnet_request(request):
    """Turn off `AllowAutoRedirect` on a .NET HttpWebRequest.

    `WebRequest.Create` is typed as WebRequest, but for http/https it really is
    an HttpWebRequest, which carries this property; IronPython resolves it at
    runtime. Best-effort and silent on failure -- a transport that cannot be
    hardened must still be usable.

    Returns True when the property was set.
    """
    try:
        request.AllowAutoRedirect = False
        return True
    except Exception:
        return False


def unit_test():
    assert is_redirect(302) and is_redirect(301) and is_redirect(308)
    assert not is_redirect(200) and not is_redirect(401) and not is_redirect(None)
    assert is_delivered(200, {"ok": True})
    assert not is_delivered(200, None), "an HTML login page must not read as delivered"
    assert not is_delivered(302, {"ok": True})
    assert describe(302) and describe(200) is None
    print("WEB_GUARD unit_test OK")


if __name__ == "__main__":
    unit_test()
