# -*- coding: utf-8 -*-
"""Depot HTTP transport -- conditional GET (ETag/304) and atomic download.

Dual runtime: IronPython 2.7 (.NET HttpWebRequest, because urllib2 SSL is broken
inside Revit/Rhino) and CPython 3.x (urllib). See plan 5.2.

C14 (reuse, don't fork): the drift-prone primitives -- error classification,
Bearer-token hygiene, encoding -- are REUSED from EnneadTab.AI._common
(_status_from_exception, _safe_token, to_unicode, _USE_DOTNET). Only the request
LOOP differs, because the depot needs things AI does not: an If-None-Match
conditional GET that reports 304, response ETag capture, and an atomic
download-to-temp-then-rename. Those are genuinely new capability, not a second
copy of the transport. (A fuller extraction of _common's request loop into one
shared core is a possible follow-up; the anti-drift goal -- one classifier, one
auth path -- is already met by importing them here.)

C15 (offline classifier): a connection-refused / DNS failure / timeout is a
transport failure -> Result.transport_failed = True (offline). A protocol
response (any HTTP status) is NOT a transport failure; the ROUTE-level policy
"a 404/410 on the manifest or asset route means offline" is applied by the
caller (ASSET), which knows the route -- see is_route_offline().

The .NET branch of this file cannot be exercised under CPython; per plan 13 the
unit tests cover the urllib branch and the IronPython branch is validated on a
live Rhino 7 / Revit host. Keep the two branches structurally identical.
"""

import os

# Fully-qualified sibling imports (repo rule: never bare "import _common").
from EnneadTab import WEB_GUARD
from EnneadTab.AI import _common


class Result(object):
    """Outcome of a depot transport call.

    transport_failed=True means offline (refused / DNS / timeout) -- the caller
    should serve cache or alarm, never raise. Otherwise `status` is the HTTP
    status: 200 (body + etag present), 304 (not modified; body is None, reuse
    cache), or any 4xx/5xx the caller maps to a domain result.
    """
    __slots__ = ("status", "body", "etag", "transport_failed", "error")

    def __init__(self, status=None, body=None, etag=None,
                 transport_failed=False, error=None):
        self.status = status
        self.body = body                 # bytes on 200, else None
        self.etag = etag                 # str or None
        self.transport_failed = transport_failed
        self.error = error               # str, for logging only

    def ok(self):
        """200 means the DEPOT answered -- which is only true because this
        transport no longer follows redirects.

        Home's middleware answers a gated API path with a 302 to an SSO login
        page. Followed, that becomes a 200 with an HTML body, and this method
        returned True for it: STATE.write_state then reported success for a write
        that never happened, across all 39 DATA_FILE(is_local=False) call sites,
        with no alarm because nothing looked like a failure. Every request path
        here now sets AllowAutoRedirect=False / uses a no-redirect opener, so a
        redirect stays a 3xx, ok() stays False, and write_state falls through to
        _alarm.announce_depot_unreachable. See WEB_GUARD.
        """
        return self.status == 200

    def not_modified(self):
        return self.status == 304


def is_route_offline(result):
    """C15 route-level policy: an unreachable transport OR a whole-route 404/410
    (the manifest/asset route itself does not exist) both mean 'offline'. A 404
    on a single known state key is NOT offline -- callers that read one key pass
    the status through instead of calling this."""
    if result.transport_failed:
        return True
    return result.status in (404, 410)


def _headers_with_auth(headers, token, if_none_match):
    out = dict(headers or {})
    if token:
        out["Authorization"] = "Bearer {0}".format(_common._safe_token(token))
    if if_none_match:
        # ETags are quoted per RFC; store/compare verbatim.
        out["If-None-Match"] = if_none_match
    return out


def get(url, token=None, headers=None, if_none_match=None, timeout_ms=15000):
    """Conditional GET. Returns a Result. Never raises for a transport failure
    (returns transport_failed=True); an HTTP status is reported in Result."""
    full_headers = _headers_with_auth(headers, token, if_none_match)
    if _common._USE_DOTNET:
        return _get_dotnet(url, full_headers, timeout_ms)
    return _get_urllib(url, full_headers, timeout_ms)


def put_json(url, body_str, token=None, headers=None, timeout_ms=30000):
    """PUT a JSON body. Returns a Result: 200/201 on success (body may carry the
    server doc), 409 for a rev conflict (body carries the winning doc), or
    transport_failed when offline. Never raises for a transport failure."""
    full_headers = _headers_with_auth(headers, token, None)
    if _common._USE_DOTNET:
        return _put_dotnet(url, body_str, full_headers, timeout_ms)
    return _put_urllib(url, body_str, full_headers, timeout_ms)


def download(url, dest_path, token=None, headers=None, timeout_ms=30000):
    """Download to `dest_path` atomically (temp file + os.rename). Returns a
    Result whose `etag` is the server ETag when present. Transport failures set
    transport_failed=True and leave no partial file behind."""
    full_headers = _headers_with_auth(headers, token, None)
    tmp = dest_path + ".part"
    if _common._USE_DOTNET:
        result = _download_dotnet(url, tmp, full_headers, timeout_ms)
    else:
        result = _download_urllib(url, tmp, full_headers, timeout_ms)
    if result.ok():
        # Atomic publish: rename only after a complete write. os.rename is
        # atomic within a volume on both Windows and POSIX.
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)      # Windows rename won't overwrite
            os.rename(tmp, dest_path)
        except Exception as e:
            _safe_remove(tmp)
            return Result(transport_failed=False, error="atomic rename failed: {0}".format(e))
    else:
        _safe_remove(tmp)
    return result


def _safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# --- .NET (IronPython 2.7) branch -------------------------------------------

def _get_dotnet(url, headers, timeout_ms):
    from System.Net import (WebRequest, WebException,  # pyright: ignore
                            ServicePointManager, SecurityProtocolType, HttpStatusCode)
    from System.IO import StreamReader  # pyright: ignore
    from System.Text import Encoding  # pyright: ignore
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "GET"
        WEB_GUARD.harden_dotnet_request(request)
        request.Timeout = timeout_ms
        for k, v in headers.items():
            _dotnet_set_header(request, k, v)
        response = request.GetResponse()
        try:
            etag = response.Headers["ETag"]
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            try:
                text = reader.ReadToEnd()
            finally:
                reader.Close()
            body = text.encode("utf-8") if hasattr(text, "encode") else text
            return Result(status=200, body=body, etag=etag)
        finally:
            response.Close()
    except WebException as e:
        status = _common._status_from_exception(e)
        if status == 304:
            etag = _dotnet_etag_from_exception(e)
            return Result(status=304, etag=etag)
        if status is None:
            # No HTTP response reached us at all -> transport failure (offline).
            return Result(transport_failed=True, error=str(e))
        return Result(status=status, error=str(e))
    except Exception as e:
        return Result(transport_failed=True, error=str(e))


def _dotnet_set_header(request, key, value):
    # Authorization and most keys go through Headers.Add; a few are restricted
    # .NET properties. Depot only sets Authorization / X-Depot-* / If-None-Match,
    # none of which are restricted, so Headers.Add is safe.
    request.Headers.Add(key, value)


def _dotnet_etag_from_exception(e):
    try:
        resp = e.Response
        if resp is not None:
            return resp.Headers["ETag"]
    except Exception:
        pass
    return None


def _download_dotnet(url, tmp_path, headers, timeout_ms):
    import System  # pyright: ignore
    from System.Net import (WebRequest, WebException,  # pyright: ignore
                            ServicePointManager, SecurityProtocolType)
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "GET"
        WEB_GUARD.harden_dotnet_request(request)
        request.Timeout = timeout_ms
        for k, v in headers.items():
            request.Headers.Add(k, v)
        response = request.GetResponse()
        try:
            etag = response.Headers["ETag"]
            stream = response.GetResponseStream()
            fs = System.IO.FileStream(tmp_path, System.IO.FileMode.Create)
            try:
                buf = System.Array[System.Byte](bytearray(8192))
                while True:
                    n = stream.Read(buf, 0, buf.Length)
                    if n <= 0:
                        break
                    fs.Write(buf, 0, n)
            finally:
                fs.Close()
                stream.Close()
            return Result(status=200, etag=etag)
        finally:
            response.Close()
    except WebException as e:
        status = _common._status_from_exception(e)
        if status is None:
            return Result(transport_failed=True, error=str(e))
        return Result(status=status, error=str(e))
    except Exception as e:
        return Result(transport_failed=True, error=str(e))


# --- CPython (urllib) branch ------------------------------------------------

def _urllib_mods():
    try:
        from urllib.request import urlopen, Request  # Py3
        from urllib.error import HTTPError, URLError
    except ImportError:
        from urllib2 import urlopen, Request, HTTPError, URLError  # Py2
    return urlopen, Request, HTTPError, URLError


def _get_urllib(url, headers, timeout_ms):
    urlopen, Request, HTTPError, URLError = _urllib_mods()
    try:
        req = Request(url)
        for k, v in headers.items():
            req.add_header(k, v)
        resp = WEB_GUARD.urlopen_no_redirect(req, timeout_ms / 1000.0)
        try:
            etag = resp.headers.get("ETag")
            # urllib does not always RAISE for 304 (no default 304 handler); it
            # can return the response with status 304 and an empty body. Read the
            # real status instead of assuming 200.
            status = getattr(resp, "status", None)
            if status is None:
                status = resp.getcode()
            body = resp.read()
        finally:
            resp.close()
        if status == 304:
            return Result(status=304, etag=etag)
        return Result(status=status or 200, body=body, etag=etag)
    except HTTPError as e:
        if e.code == 304:
            etag = None
            try:
                etag = e.headers.get("ETag")
            except Exception:
                pass
            return Result(status=304, etag=etag)
        return Result(status=e.code, error=str(e))
    except URLError as e:
        # DNS failure / connection refused / timeout -> offline.
        return Result(transport_failed=True, error=str(e))
    except Exception as e:
        return Result(transport_failed=True, error=str(e))


def _download_urllib(url, tmp_path, headers, timeout_ms):
    urlopen, Request, HTTPError, URLError = _urllib_mods()
    try:
        req = Request(url)
        for k, v in headers.items():
            req.add_header(k, v)
        resp = WEB_GUARD.urlopen_no_redirect(req, timeout_ms / 1000.0)
        try:
            etag = resp.headers.get("ETag")
            f = open(tmp_path, "wb")
            try:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
            finally:
                f.close()
        finally:
            resp.close()
        return Result(status=200, etag=etag)
    except HTTPError as e:
        return Result(status=e.code, error=str(e))
    except URLError as e:
        return Result(transport_failed=True, error=str(e))
    except Exception as e:
        return Result(transport_failed=True, error=str(e))


# --- PUT (state writes) -----------------------------------------------------

def _dotnet_response_body(web_exception):
    """Read the body of a .NET WebException's response (e.g. the 409 winning
    doc). Returns bytes or None."""
    try:
        from System.IO import StreamReader  # pyright: ignore
        from System.Text import Encoding  # pyright: ignore
        resp = web_exception.Response
        if resp is None:
            return None
        reader = StreamReader(resp.GetResponseStream(), Encoding.UTF8)
        try:
            text = reader.ReadToEnd()
        finally:
            reader.Close()
        return text.encode("utf-8") if hasattr(text, "encode") else text
    except Exception:
        return None


def _put_dotnet(url, body_str, headers, timeout_ms):
    from System.Net import (WebRequest, WebException,  # pyright: ignore
                            ServicePointManager, SecurityProtocolType)
    from System.IO import StreamReader  # pyright: ignore
    from System.Text import Encoding  # pyright: ignore
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "PUT"
        WEB_GUARD.harden_dotnet_request(request)
        request.Timeout = timeout_ms
        request.ContentType = "application/json"
        for k, v in headers.items():
            if k.lower() == "content-type":
                continue  # set via the property above
            request.Headers.Add(k, v)
        data = Encoding.UTF8.GetBytes(body_str)
        request.ContentLength = data.Length
        stream = request.GetRequestStream()
        try:
            stream.Write(data, 0, data.Length)
        finally:
            stream.Close()
        response = request.GetResponse()
        try:
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            try:
                text = reader.ReadToEnd()
            finally:
                reader.Close()
            body = text.encode("utf-8") if hasattr(text, "encode") else text
            return Result(status=200, body=body)
        finally:
            response.Close()
    except WebException as e:
        status = _common._status_from_exception(e)
        if status is None:
            return Result(transport_failed=True, error=str(e))
        # A protocol status (e.g. 409) carries a body -- the winning doc.
        return Result(status=status, body=_dotnet_response_body(e), error=str(e))
    except Exception as e:
        return Result(transport_failed=True, error=str(e))


def _put_urllib(url, body_str, headers, timeout_ms):
    urlopen, Request, HTTPError, URLError = _urllib_mods()
    body_bytes = body_str.encode("utf-8")
    try:
        req = Request(url, data=body_bytes)
        for k, v in headers.items():
            req.add_header(k, v)
        req.get_method = lambda: "PUT"   # Py2 + Py3
        resp = WEB_GUARD.urlopen_no_redirect(req, timeout_ms / 1000.0)
        try:
            status = getattr(resp, "status", None)
            if status is None:
                status = resp.getcode()
            rbody = resp.read()
        finally:
            resp.close()
        return Result(status=status or 200, body=rbody)
    except HTTPError as e:
        rbody = None
        try:
            rbody = e.read()   # 409 winning doc / error envelope
        except Exception:
            pass
        return Result(status=e.code, body=rbody, error=str(e))
    except URLError as e:
        return Result(transport_failed=True, error=str(e))
    except Exception as e:
        return Result(transport_failed=True, error=str(e))
