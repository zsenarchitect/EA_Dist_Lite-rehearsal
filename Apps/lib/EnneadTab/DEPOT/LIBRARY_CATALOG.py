# -*- coding: utf-8 -*-
"""EnneadTab-Library catalog client -- unauthenticated REST reads of the
digital-asset catalog webapp (GET /api/v1/assets) and file downloads served
directly from Library's own host.

DECISION (senzhang-todo #5447, 2026-09-05): Library owns the catalog metadata
(category/tags/versioning/changelog/compatibility); each asset still ships as
one opaque file per version (senzhang-todo #5766) -- Library does not publish
a separate per-channel manifest.

CORRECTED 2026-09-05 (same day, later): earlier versions of this module and
family_browser_script.py's _resolve_depot_key() assumed versionHistory[].
downloadUrl was meant to become an EnneadTab-Depot asset KEY, resolved via
EnneadTab.DEPOT.ASSET.get_asset_path(). That does not match Library's actual
shipped code -- read directly (EnneadTab-Library/app/api/v1/assets/route.ts,
lib/catalog.ts): downloadUrl is a path relative to LIBRARY'S OWN host (e.g.
"/files/enscape/Materials/Foo.mat"), served by Library itself. Library has
zero Depot/Postgres/Blob dependencies in its package.json. Treat downloadUrl
exactly like previewUrl -- resolve_media_url() then a plain GET -- not as an
opaque key for a different service's client. "Depot delivers asset bytes"
was an architectural recommendation on top of #5447, never Library's
implemented contract; do not resurrect the depot-key resolution this module
used to do.

CORRECTED 2026-09-10: the "Library takes no auth" premise above was never
actually true in production -- live probing found `/library/api/v1/assets`
302-redirects to Home's SSO `/login` for an unauthenticated caller (Home's
middleware.ts gates every non-public path except EARTH_MODEL/Depot/Bank-style
soft-public routes, and `/library/*` was never added to PUBLIC_ROUTES). This
module's own WEB_GUARD hardening (below) already stops that redirect from
being silently followed and misread as a 200 -- so the bug never corrupted
data -- but every call was still failing closed to an empty catalog.

Still deliberately does NOT reuse EnneadTab.DEPOT._transport's
_headers_with_auth wholesale (that also attaches a Depot-specific
X-Depot-Service-Key fallback that has no meaning for Library, a separate
service per senzhang-todo #5447). Instead, every function here now accepts an
optional `token` (from EnneadTab.AUTH.get_token(), the same desktop-auth
token already accepted by Home's middleware for /depot/api/* and
/bank/api/events -- see middleware.ts's global "Desktop token auth" Bearer
branch, which runs for every path before route-specific gating) and attaches
it as `Authorization: Bearer <token>` when present. `token=None` still works
exactly as before (whatever the route allows for an anonymous caller).

Never raises: any transport or protocol failure returns None/(None, None) so
a caller degrades to an empty/"unavailable" catalog, matching ASSET.py's
existing offline-degradation philosophy (a stale or empty list beats a dead
button).

Fully-qualified imports only (repo rule: never bare "import ENVIRONMENT").
IronPython 2.7 safe: no f-strings, no type hints, no pathlib.
"""

import json
import os

try:
    from urllib import quote_plus as _quote_plus          # Py2 / IronPython 2.7
except ImportError:
    from urllib.parse import quote_plus as _quote_plus     # Py3 / Rhino 8 CPython

from EnneadTab import ENVIRONMENT, WEB_GUARD
from EnneadTab.AI import _common


# --- Base URL -----------------------------------------------------------

# Overridable per machine via the EA_LIBRARY_URL env var, mirroring
# DEPOT/ROUTES.py's EA_DEPOT_URL escape hatch -- point at a local dev server
# or a different host without a code change.
LIBRARY_BASE_URL_DEFAULT = "https://enneadtab.com/library"


def get_base_url():
    """Resolve the Library base URL: EA_LIBRARY_URL override, else the default."""
    override = os.environ.get(ENVIRONMENT.EA_LIBRARY_URL_ENV_VAR)
    if override:
        return override.rstrip("/")
    return LIBRARY_BASE_URL_DEFAULT


# --- Catalog read ---------------------------------------------------------

def list_assets(query=None, category=None, asset_format=None, software=None, tag=None, token=None):
    """Fetch the Library catalog, optionally filtered server-side.

    `token` is a desktop-auth token from EnneadTab.AUTH.get_token() -- pass it
    so an SSO-gated deployment lets the request through instead of 302-ing to
    /login (see module docstring). None still works wherever the route allows
    an anonymous caller.

    Returns (assets, categories) -- both plain lists straight off the JSON
    response -- on success. Returns (None, None) when Library is unreachable,
    errors, or returns something unparseable. Never raises.
    """
    params = {}
    if query:
        params["q"] = query
    if category:
        params["category"] = category
    if asset_format:
        params["format"] = asset_format
    if software:
        params["software"] = software
    if tag:
        params["tag"] = tag

    status, body = _get(_assets_url(params), timeout_ms=10000, token=token)
    if status != 200:
        return None, None

    payload = _parse_json(body)
    if payload is None:
        return None, None

    return payload.get("assets") or [], payload.get("categories") or []


def resolve_media_url(path_or_url):
    """Join a possibly-relative media/download path (previewUrl, downloadUrl)
    from the catalog onto the Library base URL. Already-absolute URLs are
    allowed through only when their host matches Library's own configured
    host -- these values come straight from Library's JSON response, and
    with a second live consumer of download_asset() as of senzhang-todo
    #5511 (Rhino's place_asset.button, downloading straight to disk and
    inserting the result as a block), fetching whatever absolute URL a
    response happens to contain is not a risk worth carrying. Library's
    documented job is to serve its own bytes (EnneadTab-Library/CLAUDE.md)
    -- there is no legitimate case today for a different host. Returns None
    for an empty/missing input, or for an absolute URL on a foreign host."""
    if not path_or_url:
        return None
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not _is_allowed_absolute_url(path_or_url):
            return None
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = "/" + path_or_url
    return "{0}{1}".format(get_base_url(), path_or_url)


def _is_allowed_absolute_url(url):
    base_host = _host_of(get_base_url())
    return base_host is not None and _host_of(url) == base_host


def _host_of(url):
    # Minimal "scheme://host[:port][/path]" host extraction -- deliberately
    # not using urlparse here so this stays a two-line, easy-to-audit check
    # rather than pulling in a general-purpose URL parser for one field.
    try:
        after_scheme = url.split("://", 1)[1]
    except IndexError:
        return None
    return after_scheme.split("/", 1)[0].lower() or None


def get_download_folder():
    """Local destination for files pulled from Library. Deliberately separate
    from DEPOT.ASSET's cache (_cache.py) -- that cache is keyed by Depot asset
    keys with sha256/manifest bookkeeping that does not apply to Library's own
    content."""
    folder = os.path.join(ENVIRONMENT.ECO_SYS_FOLDER, "LibraryDownloads")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def download_asset(download_url, dest_filename=None, timeout_ms=60000, token=None):
    """Download a Library-hosted file (typically versionHistory[0].downloadUrl)
    into get_download_folder(). `token` is a desktop-auth token, same contract
    as list_assets(). Returns the local path on success, or None on any
    failure (bad/missing url, unreachable host, write error) -- never
    raises."""
    full_url = resolve_media_url(download_url)
    if not full_url:
        return None
    if not dest_filename:
        dest_filename = full_url.rstrip("/").split("/")[-1] or "library_download"
    dest_path = os.path.join(get_download_folder(), dest_filename)
    return dest_path if _download(full_url, dest_path, timeout_ms, token=token) else None


def _assets_url(params):
    base = "{0}/api/v1/assets".format(get_base_url())
    if not params:
        return base
    pairs = ["{0}={1}".format(k, _quote_plus(str(v))) for k, v in sorted(params.items())]
    return "{0}?{1}".format(base, "&".join(pairs))


def _parse_json(body):
    if body is None:
        return None
    try:
        text = body.decode("utf-8") if hasattr(body, "decode") else body
        return json.loads(text)
    except Exception:
        return None


# --- HTTP (optional Bearer token; see module docstring for why this doesn't
# reuse DEPOT._transport wholesale) ------------------------------------------

def _auth_headers(token):
    return {"Authorization": "Bearer {0}".format(token)} if token else {}


def _get(url, timeout_ms, token=None):
    """Small in-memory GET for the catalog JSON. Returns (status, body_bytes);
    (None, None) on a transport failure that never reached a server."""
    if _common._USE_DOTNET:
        return _get_dotnet(url, timeout_ms, token=token)
    return _get_urllib(url, timeout_ms, token=token)


def _get_dotnet(url, timeout_ms, token=None):
    from System.Net import WebRequest, WebException, ServicePointManager, SecurityProtocolType  # pyright: ignore
    from System.IO import StreamReader  # pyright: ignore
    from System.Text import Encoding  # pyright: ignore
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "GET"
        WEB_GUARD.harden_dotnet_request(request)
        request.Timeout = timeout_ms
        for k, v in _auth_headers(token).items():
            request.Headers.Add(k, v)
        response = request.GetResponse()
        try:
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            try:
                text = reader.ReadToEnd()
            finally:
                reader.Close()
            body = text.encode("utf-8") if hasattr(text, "encode") else text
            return 200, body
        finally:
            response.Close()
    except WebException as e:
        return _common._status_from_exception(e), None
    except Exception:
        return None, None


def _urllib_mods():
    try:
        from urllib.request import urlopen, Request  # Py3
        from urllib.error import HTTPError, URLError
    except ImportError:
        from urllib2 import urlopen, Request, HTTPError, URLError  # Py2
    return urlopen, Request, HTTPError, URLError


def _get_urllib(url, timeout_ms, token=None):
    urlopen, Request, HTTPError, URLError = _urllib_mods()
    try:
        req = Request(url)
        for k, v in _auth_headers(token).items():
            req.add_header(k, v)
        resp = WEB_GUARD.urlopen_no_redirect(req, timeout_ms / 1000.0)
        try:
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read()
        finally:
            resp.close()
        return status or 200, body
    except HTTPError as e:
        return e.code, None
    except URLError:
        return None, None
    except Exception:
        return None, None


def _download(url, dest_path, timeout_ms, token=None):
    """Stream url to dest_path atomically (temp file + os.rename). Returns
    True/False -- never raises, never leaves a partial file at dest_path."""
    tmp = dest_path + ".part"
    ok = (_download_dotnet(url, tmp, timeout_ms, token=token) if _common._USE_DOTNET
          else _download_urllib(url, tmp, timeout_ms, token=token))
    if not ok:
        _safe_remove(tmp)
        return False
    try:
        if os.path.exists(dest_path):
            os.remove(dest_path)  # Windows rename won't overwrite
        os.rename(tmp, dest_path)
        return True
    except Exception:
        _safe_remove(tmp)
        return False


def _safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _download_dotnet(url, tmp_path, timeout_ms, token=None):
    import System  # pyright: ignore
    from System.Net import WebRequest, ServicePointManager, SecurityProtocolType  # pyright: ignore
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "GET"
        WEB_GUARD.harden_dotnet_request(request)
        request.Timeout = timeout_ms
        for k, v in _auth_headers(token).items():
            request.Headers.Add(k, v)
        response = request.GetResponse()
        try:
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
            return True
        finally:
            response.Close()
    except Exception:
        return False


def _download_urllib(url, tmp_path, timeout_ms, token=None):
    urlopen, Request, HTTPError, URLError = _urllib_mods()
    try:
        req = Request(url)
        for k, v in _auth_headers(token).items():
            req.add_header(k, v)
        resp = WEB_GUARD.urlopen_no_redirect(req, timeout_ms / 1000.0)
        try:
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
        return True
    except Exception:
        return False
