#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Shared HTTP transport for the EnneadTab.AI submodules.

IronPython 2.7 (Revit/Rhino) -- uses .NET HttpWebRequest because urllib2's SSL
is broken inside the host process. CPython 3.x -- uses urllib.

All AI calls are proxied through enneadtab.com or ennead-ai.com. The desktop
Bearer token (issued by EnneadTabHome / .desktop_auth_token.sexyDuck) is
injected via the Authorization header. Trust boundary lives in middleware on
the Vercel side.
"""

import binascii
import json
import os
import re


# Public service URLs.
ENNEADTAB_URL = "https://enneadtab.com"   # Chat, translate, auth.
RENDER_URL = "https://enneadtab.com/rendering"  # Image/video render, gallery, prompts, demo-images, quota. Re-homed from ennead-ai.com 2026-07-27 (behind enneadtab.com gate).


# --- Runtime detection ---
_USE_DOTNET = False
try:
    from System.Net import WebRequest, WebException, ServicePointManager, SecurityProtocolType # pyright: ignore
    from System.IO import StreamReader # pyright: ignore
    from System.Text import Encoding # pyright: ignore
    _USE_DOTNET = True
except ImportError:
    WebException = None  # sentinel for CPython branches

if not _USE_DOTNET:
    try:
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
    except ImportError:
        from urllib2 import urlopen, Request, HTTPError


class AIRequestError(Exception):
    """Raised when an AI proxy request fails."""
    def __init__(self, message, status_code=None):
        self.status_code = status_code
        Exception.__init__(self, message)


# --- Helpers ---

def _rand_hex(n=8):
    """Return 2n-char ASCII hex. IronPython 2.7 + CPython safe.

    os.urandom returns str on IP27 (no .hex() method); binascii.hexlify works
    on both runtimes regardless of bytes-vs-str semantics.
    """
    return binascii.hexlify(os.urandom(n)).decode("ascii")


def _safe_token(token):
    """Strip whitespace/newlines off a Bearer token before .NET header injection.

    .NET WebHeaderCollection raises ArgumentException on \\r or \\n in values.
    Defensive against the env-var-trailing-newline class of bug.
    """
    return (token or "").strip()


def to_unicode(s):
    """Coerce input to a Python unicode string for safe json.dumps on IP27.

    On IronPython 2.7 / Windows, json.dumps of a `str` containing non-ASCII
    bytes triggers an implicit str.decode('ascii') and dies with
    "'unknown' codec can't decode byte 0xNN" (the Lengthen / Shorten failure
    mode reported 2026-04-22). Cause: prompts arrive from clipboard paste,
    file load (cp1252 default per Windows-encoding memory), or stale persisted
    state and carry mojibake bytes. Normalize at the API boundary so every
    AI endpoint is encoding-safe regardless of caller hygiene.
    """
    if s is None:
        return u""
    if isinstance(s, bytes):
        try:
            return s.decode("utf-8")
        except (UnicodeDecodeError, UnicodeError):
            try:
                return s.decode("cp1252", "replace")
            except Exception:
                return s.decode("latin-1", "replace")
    return s


_DOTNET_STATUS_RE = re.compile(r"\((\d{3})\)\s+[A-Z]")


def _status_from_exception(e):
    """Extract a typed HTTP status code from a .NET WebException or urllib HTTPError.

    Locale- and substring-safe: only matches the .NET WebException message
    template `"The remote server returned an error: (NNN) <Description>."`,
    which is well-defined and locale-stable (.NET emits this English string
    regardless of OS locale -- verified across Win10/11 Revit hosts). Will
    NOT match arbitrary "401" tokens elsewhere in the message body. Per
    feedback_error_signature_matching memory: substring matching is safe
    when the substring is a typed structured token, not free text.
    """
    if WebException is not None and isinstance(e, WebException):
        try:
            resp = e.Response
            if resp is not None:
                return int(resp.StatusCode)
        except Exception:
            pass
    code = getattr(e, "code", None)
    if isinstance(code, int):
        return code
    # Fallback: parse status from the .NET WebException message itself.
    # Many WebException variants have no parseable .Response (DNS failure,
    # SSL handshake fail, certain proxy responses) but still embed the
    # upstream HTTP status in the message. 2026-04-27: Gemini 429 was
    # returning status=None and tripping the circuit breaker instead of
    # the proper 429 wait+retry path.
    try:
        msg = str(e)
        m = _DOTNET_STATUS_RE.search(msg)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


# --- HTTP POST: JSON body ---

def post_json(url, payload_str, token, timeout_ms=120000):
    if _USE_DOTNET:
        return _post_json_dotnet(url, payload_str, token, timeout_ms)
    return _post_json_urllib(url, payload_str, token, timeout_ms)


def _post_json_dotnet(url, payload_str, token, timeout_ms):
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "POST"
        request.ContentType = "application/json"
        request.Headers.Add("Authorization", "Bearer {}".format(_safe_token(token)))
        request.Timeout = timeout_ms

        body_bytes = Encoding.UTF8.GetBytes(payload_str)
        request.ContentLength = body_bytes.Length
        req_stream = request.GetRequestStream()
        req_stream.Write(body_bytes, 0, body_bytes.Length)
        req_stream.Close()

        response = request.GetResponse()
        # StreamReader without an explicit encoding uses Encoding.Default, which
        # on .NET Framework (IronPython's host) is the Windows ANSI code page --
        # any non-Latin-1 byte (UTF-8 multibyte sequences for e-acute, c-cedilla, Chinese chars, etc.)
        # then triggers IronPython's "'unknown' codec can't decode byte 0xNN".
        # Always pass Encoding.UTF8 explicitly. (2026-04-21 Shorten failure.)
        reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
        result_text = reader.ReadToEnd()
        reader.Close()
        response.Close()

        return json.loads(result_text)
    except Exception as e:
        raise AIRequestError(str(e), status_code=_status_from_exception(e))


def _post_json_urllib(url, payload_str, token, timeout_ms):
    try:
        req = Request(url)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer {}".format(_safe_token(token)))
        response = urlopen(req, payload_str.encode("utf-8"), timeout=timeout_ms // 1000)
        resp_body = response.read()
        if isinstance(resp_body, bytes):
            resp_body = resp_body.decode("utf-8")
        return json.loads(resp_body)
    except HTTPError as e:
        raise AIRequestError(str(e), status_code=e.code)
    except Exception as e:
        raise AIRequestError(str(e))


# --- HTTP GET: JSON body ---

def get_json(url, token=None, timeout_ms=15000):
    if _USE_DOTNET:
        try:
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            request = WebRequest.Create(url)
            request.Method = "GET"
            request.Timeout = timeout_ms
            if token:
                request.Headers.Add("Authorization", "Bearer {}".format(_safe_token(token)))
            response = request.GetResponse()
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            try:
                text = reader.ReadToEnd()
            finally:
                reader.Close()
                response.Close()
            return json.loads(text)
        except Exception as e:
            raise AIRequestError(str(e), status_code=_status_from_exception(e))
    else:
        try:
            req = Request(url)
            if token:
                req.add_header("Authorization", "Bearer {}".format(_safe_token(token)))
            resp = urlopen(req, timeout=timeout_ms // 1000)
            try:
                text = resp.read()
                if isinstance(text, bytes):
                    text = text.decode("utf-8")
            finally:
                resp.close()
            return json.loads(text)
        except HTTPError as e:
            raise AIRequestError(str(e), status_code=e.code)
        except Exception as e:
            raise AIRequestError(str(e))


# --- HTTP POST: multipart/form-data, JSON response ---

def post_multipart(url, fields, files, token, timeout_ms=120000):
    """fields: dict of {name: value}.
       files: list of (field_name, filename, file_bytes, content_type).
    """
    boundary = "----EnneadTabBoundary{}".format(_rand_hex(16))
    body_parts = []
    for name, value in fields.items():
        body_parts.append("--{}".format(boundary).encode("utf-8"))
        body_parts.append('Content-Disposition: form-data; name="{}"'.format(name).encode("utf-8"))
        body_parts.append(b"")
        if isinstance(value, bytes):
            body_parts.append(value)
        else:
            body_parts.append(str(value).encode("utf-8"))
    for field_name, filename, file_bytes, content_type in files:
        body_parts.append("--{}".format(boundary).encode("utf-8"))
        body_parts.append('Content-Disposition: form-data; name="{}"; filename="{}"'.format(field_name, filename).encode("utf-8"))
        body_parts.append("Content-Type: {}".format(content_type).encode("utf-8"))
        body_parts.append(b"")
        body_parts.append(file_bytes)
    body_parts.append("--{}--".format(boundary).encode("utf-8"))
    body_parts.append(b"")
    body = b"\r\n".join(body_parts)
    content_type = "multipart/form-data; boundary={}".format(boundary)

    if _USE_DOTNET:
        return _post_multipart_dotnet(url, body, content_type, token, timeout_ms)
    return _post_multipart_urllib(url, body, content_type, token, timeout_ms)


def _post_multipart_dotnet(url, body, content_type, token, timeout_ms):
    try:
        import System # pyright: ignore
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "POST"
        request.ContentType = content_type
        request.Headers.Add("Authorization", "Bearer {}".format(_safe_token(token)))
        request.Timeout = timeout_ms
        dotnet_bytes = System.Array[System.Byte](bytearray(body))
        request.ContentLength = dotnet_bytes.Length
        req_stream = request.GetRequestStream()
        req_stream.Write(dotnet_bytes, 0, dotnet_bytes.Length)
        req_stream.Close()
        response = request.GetResponse()
        reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
        result_text = reader.ReadToEnd()
        reader.Close()
        response.Close()
        return json.loads(result_text)
    except Exception as e:
        raise AIRequestError(str(e), status_code=_status_from_exception(e))


def _post_multipart_urllib(url, body, content_type, token, timeout_ms):
    try:
        req = Request(url)
        req.add_header("Content-Type", content_type)
        req.add_header("Authorization", "Bearer {}".format(_safe_token(token)))
        response = urlopen(req, body, timeout=timeout_ms // 1000)
        resp_body = response.read()
        if isinstance(resp_body, bytes):
            resp_body = resp_body.decode("utf-8")
        return json.loads(resp_body)
    except HTTPError as e:
        raise AIRequestError(str(e), status_code=e.code)
    except Exception as e:
        raise AIRequestError(str(e))


# --- HTTP POST: multipart/form-data, raw text response (for SSE streams) ---

def post_multipart_raw(url, fields, files, token, timeout_ms=180000, progress_callback=None):
    """Returns the raw response text. Used for SSE streaming endpoints
    (image render). 3xx redirects are mapped to status_code=401 so the
    caller's auth-recovery path fires.
    """
    boundary = "----EnneadTabBoundary{}".format(_rand_hex(16))
    body_parts = []
    for name, value in fields.items():
        body_parts.append("--{}".format(boundary).encode("utf-8"))
        body_parts.append('Content-Disposition: form-data; name="{}"'.format(name).encode("utf-8"))
        body_parts.append(b"")
        body_parts.append(str(value).encode("utf-8") if not isinstance(value, bytes) else value)
    for field_name, filename, file_bytes, ct in files:
        body_parts.append("--{}".format(boundary).encode("utf-8"))
        body_parts.append('Content-Disposition: form-data; name="{}"; filename="{}"'.format(field_name, filename).encode("utf-8"))
        body_parts.append("Content-Type: {}".format(ct).encode("utf-8"))
        body_parts.append(b"")
        body_parts.append(file_bytes)
    body_parts.append("--{}--".format(boundary).encode("utf-8"))
    body_parts.append(b"")
    body = b"\r\n".join(body_parts)
    content_type_header = "multipart/form-data; boundary={}".format(boundary)

    if progress_callback:
        progress_callback("Uploading image...")

    if _USE_DOTNET:
        try:
            import System # pyright: ignore
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            request = WebRequest.Create(url)
            request.Method = "POST"
            request.ContentType = content_type_header
            request.Headers.Add("Authorization", "Bearer {}".format(_safe_token(token)))
            request.Timeout = timeout_ms
            request.ReadWriteTimeout = timeout_ms
            request.AllowAutoRedirect = False  # 307 to login page would mask 401

            dotnet_bytes = System.Array[System.Byte](bytearray(body))
            request.ContentLength = dotnet_bytes.Length
            req_stream = request.GetRequestStream()
            req_stream.Write(dotnet_bytes, 0, dotnet_bytes.Length)
            req_stream.Close()

            if progress_callback:
                progress_callback("AI is generating your image...")

            response = request.GetResponse()
            try:
                status_code = int(response.StatusCode)
            except Exception:
                status_code = 200
            if 300 <= status_code < 400:
                try:
                    response.Close()
                except Exception:
                    pass
                raise AIRequestError(
                    "Auth redirect ({}) -- token likely expired".format(status_code),
                    status_code=401)

            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            try:
                result_text = reader.ReadToEnd()
            finally:
                reader.Close()
                response.Close()

            if not result_text or len(result_text) < 10:
                raise AIRequestError(
                    "Empty response from server (got {} bytes). Check auth token and server logs.".format(
                        len(result_text or "")))
            return result_text
        except AIRequestError:
            raise
        except Exception as e:
            raise AIRequestError(str(e), status_code=_status_from_exception(e))
    else:
        try:
            req = Request(url)
            req.add_header("Content-Type", content_type_header)
            req.add_header("Authorization", "Bearer {}".format(_safe_token(token)))
            if progress_callback:
                progress_callback("AI is generating your image...")
            response = urlopen(req, body, timeout=timeout_ms // 1000)
            resp_body = response.read()
            if isinstance(resp_body, bytes):
                resp_body = resp_body.decode("utf-8")
            return resp_body
        except HTTPError as e:
            raise AIRequestError(str(e), status_code=e.code)
        except Exception as e:
            raise AIRequestError(str(e))


# --- File downloader ---

# Bytes per read. Both download branches have always streamed in chunks; the
# size is named here because it is now also the CADENCE of the on_progress
# callback, which makes it a UI-facing number rather than a private detail.
DOWNLOAD_CHUNK_BYTES = 8192


def _content_length_or_none(value):
    """Normalise a Content-Length into a positive int, or None when unknown.

    .NET's HttpWebResponse.ContentLength is -1 when the header is absent;
    urllib hands back None. Both mean "no total", and a caller must render
    that as a bare byte count with NO percentage rather than inventing one --
    the same honesty rule the generation phase follows.
    """
    try:
        total = int(value)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return total


def _header_value(resp, name):
    """One response header, or None. Tolerant of both urllib generations.

    Python 3's email.message.Message exposes .get(); Python 2's rfc822.Message
    exposes .getheader() (and aliases .get to it). Neither is guaranteed on a
    caller-supplied stand-in, so both are probed and a miss is None.
    """
    try:
        headers = resp.info()
    except Exception:
        return None
    if headers is None:
        return None
    for accessor in ("get", "getheader"):
        fn = getattr(headers, accessor, None)
        if fn is None:
            continue
        try:
            return fn(name)
        except Exception:
            continue
    return None


def _progress_reporter(on_progress):
    """Wrap a caller's callback so a fault in IT cannot kill the download.

    Two-faced degradation (rule 13): the download still completes, and the
    operator gets exactly ONE printed reason -- reporting is then switched off
    rather than printing once per 8 KB chunk for the rest of an 8 MB file.

    Returns None when there is nothing to report to, so the hot loop can skip
    the call entirely.
    """
    if on_progress is None:
        return None

    state = {"dead": False}

    def report(done, total):
        if state["dead"]:
            return
        try:
            on_progress(done, total)
        except Exception as e:
            state["dead"] = True
            print("download progress callback failed; continuing without "
                  "progress: {}".format(e))

    return report


def download_url_to_file(url, dest_path, timeout_ms=30000, on_progress=None):
    """Download a URL to a local file. No auth header (used for public assets
    like the Ennead style-reference library). Returns dest_path on success.

    on_progress, when given, is called after every chunk as
    ``on_progress(bytes_done, total_bytes)``. `bytes_done` accumulates and the
    last call always carries the full size. `total_bytes` is None when the
    server sent no Content-Length, and a caller MUST then draw a byte count
    without a percentage instead of guessing at one.

    Note the name: `progress_callback` in post_multipart_raw above takes a
    TEXT message, which is a different contract. Two-argument byte progress is
    `on_progress` throughout, so the two can never be passed to each other by
    mistake.

    Default None leaves both branches byte-for-byte the behaviour they had
    before -- the existing AI_RENDER callers are untouched.
    """
    if _USE_DOTNET:
        try:
            import System # pyright: ignore
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            request = WebRequest.Create(url)
            request.Method = "GET"
            request.Timeout = timeout_ms
            response = request.GetResponse()
            try:
                total = _content_length_or_none(
                    getattr(response, "ContentLength", None))
                report = _progress_reporter(on_progress)
                stream = response.GetResponseStream()
                fs = System.IO.FileStream(dest_path, System.IO.FileMode.Create)
                try:
                    buf = System.Array[System.Byte](
                        bytearray(DOWNLOAD_CHUNK_BYTES))
                    done = 0
                    while True:
                        n = stream.Read(buf, 0, buf.Length)
                        if n <= 0:
                            break
                        fs.Write(buf, 0, n)
                        done += n
                        if report:
                            report(done, total)
                finally:
                    fs.Close()
                    stream.Close()
            finally:
                response.Close()
            return dest_path
        except Exception as e:
            raise AIRequestError(str(e), status_code=_status_from_exception(e))
    else:
        try:
            resp = urlopen(url, timeout=timeout_ms // 1000)
            try:
                total = _content_length_or_none(
                    _header_value(resp, "Content-Length"))
                report = _progress_reporter(on_progress)
                f = open(dest_path, "wb")
                try:
                    done = 0
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if report:
                            report(done, total)
                finally:
                    f.close()
            finally:
                resp.close()
            return dest_path
        except HTTPError as e:
            raise AIRequestError(str(e), status_code=e.code)
        except Exception as e:
            raise AIRequestError(str(e))
