# -*- coding: utf-8 -*-
"""Client for the EnneadTab-EarthModel service -- real-world site context meshes.

The Rhino GetEarth button is a THIN CALLER. All tile fetching, cropping, and mesh
merging happens server-side behind one org-held credential, because end users can
neither install Grasshopper plugins nor hold their own Google Maps Platform key.
Same shape as the AI Render button -> RenderPolisher pairing.

Architecture ruling 2026-08-05 (see docs/plans/2026-08-05-getearth-earth-model-service.md):

  * NOT in Depot. Depot is a manifest of static, enumerable assets; this is a
    GENERATED resource keyed by (lat, lon, size, format). Wrong contract, so
    nothing here touches DEPOT/ROUTES, ASSET, or the manifest.
  * Transport is EnneadTab.AI._common -- the shared HTTP core that Depot itself
    reuses. It carries the one thing that actually matters in-process: .NET
    HttpWebRequest instead of urllib2, whose SSL is broken inside Revit/Rhino.
  * The service is its own repo + Vercel project, proxied at
    enneadtab.com/earth-model. Not a route inside EnneadTabHome (tile merging is
    a bad tenant in the portal that fronts everything else).
  * NOT a service-factory desktop product. There is no Electron/NSIS installer
    and nothing for electron-updater to ship. Do NOT add earth-model to
    DarkSide/publish/service_factory_products.json (listed under that file's
    _excluded on purpose; Wiki #517 / TODO-7264). Portal/wiki catalog visibility
    is owned by EnneadTab-Home (apps-config), not the ExeProducts mirror roster.

Control plane and data plane are split: POST returns JSON with a download URL and
a sha256, then the binary is fetched separately. That keeps a multi-megabyte GLB
off the JSON path, lets the server serve from blob storage, and leaves room to
turn the POST into a job-id + poll contract if merge times demand it.

IronPython 2.7 (loads inside Rhino): no f-strings, no type hints, no pathlib.
Fully-qualified sibling imports only -- a bare `import AUTH` resolves in an
editor and raises "No module named" at runtime under the package path.
"""

import os
import json
import hashlib

from EnneadTab import AUTH
from EnneadTab import FOLDER
from EnneadTab.AI import _common


# --- Contract ---------------------------------------------------------------

# Overridable per machine so a dev can point at a local stub without a code
# change -- and so a test can force "offline" by pointing at a refused address
# (http://127.0.0.1:9), the same trick the depot ship gate uses.
EARTH_MODEL_URL_ENV_VAR = "EA_EARTH_MODEL_URL"
EARTH_MODEL_URL_DEFAULT = "https://enneadtab.com/earth-model"

# Contract version this client speaks. Bump only on a breaking change; the
# server answers "client_too_old" when it can no longer serve this version.
CONTRACT_VERSION = "1"

HEADER_CLIENT = "X-EarthModel-Client"
HEADER_CLIENT_VERSION = "X-EarthModel-Client-Version"

# GLB is the ONLY format, decided by experiment 2026-08-05: Google serves
# glTF/GLB, and Rhino 8 imports GLB with textures intact as a Physically Based
# material -- which is what Enscape and Rhino Render consume. Any transcode step
# would add complexity and lose fidelity for no gain.
FORMAT_GLB = "glb"

CACHE_FOLDER_NAME = "earth_model_cache"

# Merging photogrammetric tiles is slow. This is deliberately generous and is
# PROVISIONAL -- it must be replaced by a measured value once real tile data
# flows. Setting it from a toy probe would be measuring the wrong workload.
DEFAULT_TIMEOUT_MS = 180000
DOWNLOAD_TIMEOUT_MS = 180000


class EarthModelError(Exception):
    """Raised for a protocol-level failure. Transport/offline failures do NOT
    raise -- they return None, so the button degrades instead of throwing a
    traceback at a designer."""

    def __init__(self, message, status_code=None):
        Exception.__init__(self, message)
        self.status_code = status_code


def get_base_url():
    override = os.environ.get(EARTH_MODEL_URL_ENV_VAR)
    if override:
        return override.rstrip("/")
    return EARTH_MODEL_URL_DEFAULT


def model_endpoint():
    return "{}/api/v{}/model".format(get_base_url(), CONTRACT_VERSION)


# --- Cache ------------------------------------------------------------------

def cache_dir():
    return FOLDER.get_local_dump_folder_folder(CACHE_FOLDER_NAME)


def cache_key(lat, lon, size_m, fmt=FORMAT_GLB, rotation_deg=0):
    """Stable key for an AOI request.

    Rounded to ~1e-6 deg (about 0.1 m) so that trivially different picks of the
    same spot reuse one cached model instead of re-billing a fresh server-side
    merge. Coarser than that would silently serve a neighbouring site.

    `rotation_deg` (senzhang-todo #4857, mirrors the server's own
    lib/model-cache.ts) is appended to the raw string ONLY when non-zero, so
    the key for rotation_deg=0 -- every request before this parameter existed,
    and every request that still doesn't ask for one -- is BYTE-IDENTICAL to
    what this function produced before. A local cache built before rotation
    existed stays a hit; DarkSide/tests/get_earth/rhino_l3_aoi_ironpython.py
    hardcodes the expected hash for the zero-rotation case across both Python
    runtimes and would catch a regression here.
    """
    rotation_part = "|r{:.1f}".format(float(rotation_deg)) if rotation_deg else ""
    raw = "{:.6f}|{:.6f}|{:.1f}|{}|{}{}".format(
        float(lat), float(lon), float(size_m), fmt, CONTRACT_VERSION, rotation_part)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cached_path(lat, lon, size_m, fmt=FORMAT_GLB, rotation_deg=0):
    """Local path for this AOI, whether or not it exists yet."""
    key = cache_key(lat, lon, size_m, fmt, rotation_deg)
    return os.path.join(cache_dir(), "{}.{}".format(key, fmt))


# --- Integrity + atomic write ----------------------------------------------

def sha256_of_file(path):
    h = hashlib.sha256()
    f = open(path, "rb")
    try:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    finally:
        f.close()
    return h.hexdigest()


def _atomic_download(url, dest_path, expected_sha256=None,
                     timeout_ms=DOWNLOAD_TIMEOUT_MS, on_progress=None):
    """Download to a temp file, verify, then rename into place.

    Restated here rather than imported from DEPOT._transport on purpose: the
    depot's version is bound to its manifest/ETag contract, and this is ~15
    dependency-free lines. Reaching into another subpackage's private module for
    it would couple GetEarth to Depot for no benefit.

    Without the temp-then-rename a killed Rhino leaves a half-written GLB at the
    real path, which imports as garbage and looks like a server bug.
    """
    tmp_path = dest_path + ".part"
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    _common.download_url_to_file(url, tmp_path, timeout_ms=timeout_ms,
                                 on_progress=on_progress)

    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
        raise EarthModelError("Downloaded model is empty: {}".format(url))

    if expected_sha256:
        actual = sha256_of_file(tmp_path)
        if actual.lower() != str(expected_sha256).lower():
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            raise EarthModelError(
                "Integrity check failed: expected {}, got {}".format(
                    expected_sha256, actual))

    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass
    os.rename(tmp_path, dest_path)
    return dest_path


# --- The call ---------------------------------------------------------------

def request_model_with_token(token, lat, lon, size_m, fmt=FORMAT_GLB,
                             source=None, force=False, rotation_deg=0,
                             on_progress=None, on_response=None):
    """Ask the service for an AOI and return a local path to the model.

    `source` selects the server-side backend ("google" | "osm3dep"); None lets
    the server choose its default. `force` bypasses the local cache.

    `rotation_deg` (#4857) is the compass bearing, clockwise from true north,
    to align the AOI square to -- e.g. Manhattan's grid runs ~29deg off. It is
    ADDITIVE on the wire: only sent when non-zero (same "only forward what
    was actually asked for" pattern as `source` two lines below), so a plain
    request looks byte-for-byte identical to one from before this parameter
    existed. The server (EnneadTab-EarthModel lib/contract.ts) defaults an
    absent rotation_deg to 0 and needs no CONTRACT_VERSION bump for it.
    Rhino needs no mesh-side change either -- the server returns geometry
    pre-rotated.

    The two optional callbacks exist because this call has TWO phases with
    very different progress available, and a caller drawing a UI has to be
    able to tell them apart:

      on_response(data)  -- fired once, with the parsed response dict, the
          moment the blocking POST has returned a usable answer. That is the
          only honest "generation finished, download starting" signal there
          is: the POST has no progress channel at all, so nothing can be
          reported between sending it and this callback.
      on_progress(done, total) -- fired per chunk while the GLB downloads.
          Real bytes, so a caller may draw a real percentage. `total` is None
          when the server sent no Content-Length.

    Both are wrapped: a caller's UI fault degrades the DISPLAY, never the
    download. This module stays Rhino-free and message-free -- composing text
    for a designer is the button's job, not the client's.

    Returns a local file path. Raises EarthModelError on a protocol failure.
    """
    dest = cached_path(lat, lon, size_m, fmt, rotation_deg)
    if not force and os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest

    payload = {
        "lat": float(lat),
        "lon": float(lon),
        "size_m": float(size_m),
        "format": fmt,
    }
    if source:
        payload["source"] = source
    if rotation_deg:
        payload["rotation_deg"] = float(rotation_deg)

    # NOTE: _common.post_json already returns a PARSED object (it ends in
    # `json.loads(result_text)`) -- do not decode it again. A non-JSON response
    # never reaches here at all: the decode fails inside _common and surfaces as
    # AIRequestError, which the caller handles alongside 401s and timeouts.
    data = _common.post_json(model_endpoint(), json.dumps(payload), token,
                             timeout_ms=DEFAULT_TIMEOUT_MS)

    if not isinstance(data, dict):
        raise EarthModelError(
            "Unexpected response type from earth-model service: {}".format(
                type(data).__name__))

    if data.get("error"):
        raise EarthModelError(str(data.get("error")))

    url = data.get("model_url")
    if not url:
        raise EarthModelError(
            "Response carried no model_url. Keys: {}".format(sorted(data.keys())))

    if on_response:
        try:
            on_response(data)
        except Exception as e:
            # The caller's status line broke. That is not a reason to abandon a
            # model the office has already paid to build.
            print("EARTH_MODEL: response callback failed: {}".format(e))

    _atomic_download(url, dest, expected_sha256=data.get("sha256"),
                     on_progress=on_progress)
    return dest


def request_model(lat, lon, size_m, fmt=FORMAT_GLB, source=None, force=False,
                  rotation_deg=0, on_progress=None, on_response=None):
    """Blocking-auth convenience wrapper. Returns a local path, or None.

    Degradation is deliberate and two-faced (global rule 13): the DESIGNER gets
    None and a caller-rendered message instead of a traceback, while the
    OPERATOR gets a printed reason -- never a silent swallow.

    A stale cached copy is served when the service is unreachable, so a designer
    mid-render is not blocked by an outage.

    `rotation_deg` -- see request_model_with_token's docstring (#4857).
    """
    token = AUTH.get_token_blocking()
    if not token:
        print("EARTH_MODEL: no desktop auth token; cannot reach the service.")
        return None

    # All-keyword past `force` deliberately, not positional: this file's own
    # request_model_with_token has grown params over time (rotation_deg is
    # the latest), and a positional call here is the one place in the module
    # a reordered/inserted parameter would silently misbind instead of
    # erroring -- caught while adding rotation_deg (senzhang-todo #4857).
    try:
        return request_model_with_token(
            token, lat, lon, size_m, fmt=fmt, source=source, force=force,
            rotation_deg=rotation_deg, on_progress=on_progress,
            on_response=on_response)
    except _common.AIRequestError as e:
        if getattr(e, "status_code", None) == 401:
            AUTH.clear_token()
            token = AUTH.get_token_blocking()
            if not token:
                print("EARTH_MODEL: re-auth failed after 401.")
                return None
            try:
                return request_model_with_token(
                    token, lat, lon, size_m, fmt=fmt, source=source,
                    force=force, rotation_deg=rotation_deg,
                    on_progress=on_progress, on_response=on_response)
            except Exception as e2:
                print("EARTH_MODEL: retry after re-auth failed: {}".format(e2))
                return _serve_stale(lat, lon, size_m, fmt, rotation_deg)
        print("EARTH_MODEL: request failed: {}".format(e))
        return _serve_stale(lat, lon, size_m, fmt, rotation_deg)
    except EarthModelError as e:
        print("EARTH_MODEL: {}".format(e))
        return _serve_stale(lat, lon, size_m, fmt, rotation_deg)
    except Exception as e:
        print("EARTH_MODEL: unexpected failure: {}".format(e))
        return _serve_stale(lat, lon, size_m, fmt, rotation_deg)


def _serve_stale(lat, lon, size_m, fmt, rotation_deg=0):
    """Offline fallback: a previously downloaded model beats nothing at all."""
    dest = cached_path(lat, lon, size_m, fmt, rotation_deg)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print("EARTH_MODEL: service unreachable; serving cached model {}".format(dest))
        return dest
    return None
