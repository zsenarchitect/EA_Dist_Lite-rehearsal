# -*- coding: utf-8 -*-
"""ARVR client module for EnneadTab.

Provides model staging, uploading, and room pairing to EnneadTab-ARVR (https://enneadtab.com/arvr).
Supports IronPython 2.7 (.NET WebRequest) and CPython 3.x (urllib).
"""

import os
import random
import time
import json
import webbrowser
from EnneadTab import NOTIFICATION, FOLDER

ARVR_URL_BASE = "https://enneadtab.com/arvr"
SUBDIR_STAGING = "ARVR_Exports"
# The only non-model type the room upload-token route accepts (see put_blob_file).
OCTET_STREAM = "application/octet-stream"

# Content types for files staged/uploaded to ARVR rooms.
_CONTENT_TYPES = {
    ".usdz": "model/vnd.usdz+zip",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
}

def content_type_for(filename):
    """Return the upload content type for a filename, by extension."""
    ext = os.path.splitext(filename)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")

# Model formats the web viewer (<model-viewer>) can actually render.
VIEWABLE_MODEL_EXTENSIONS = (".glb", ".gltf", ".usdz")

def unsupported_model_reason(filename):
    """Return an error string if filename is not a viewer-renderable model, else None.

    The web viewer only renders glTF/GLB (plus USDZ for iOS Quick Look).
    Uploading anything else (e.g. .obj) would report success on the desktop
    and show a blank model on the phone.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in VIEWABLE_MODEL_EXTENSIONS:
        return None
    return "Unsupported model format '{}'. The AR/VR viewer only renders .glb, .gltf or .usdz. Export as GLB and try again.".format(ext or filename)

def generate_room_id():
    """Generate a friendly 6-char alphanumeric room code."""
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.choice(chars) for _ in range(6))

def get_staging_directory():
    """Get or create local temp staging directory for exported 3D assets."""
    staging_dir = FOLDER.get_local_dump_folder_folder(SUBDIR_STAGING)
    if not os.path.exists(staging_dir):
        try:
            os.makedirs(staging_dir)
        except Exception:
            pass
    return staging_dir

def stage_and_upload(filepath, room_id=None, timeout_ms=90000, auto_open_browser=True):
    """Perform complete staging validation, cloud upload, and web pairing.

    Args:
        filepath (str): Local path to .glb, .gltf, or .usdz file.
        room_id (str, optional): Target room code. If None, auto-generates.
        timeout_ms (int): Network timeout in milliseconds.
        auto_open_browser (bool): Automatically open paired desktop hub in browser.

    Returns:
        tuple: (success, room_id, web_url, error_message)
    """
    if not filepath or not os.path.exists(filepath):
        msg = "File does not exist: {}".format(filepath)
        NOTIFICATION.messenger(msg)
        return False, None, None, msg

    bad_format = unsupported_model_reason(os.path.basename(filepath))
    if bad_format:
        NOTIFICATION.messenger(bad_format)
        return False, None, None, bad_format

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        msg = "Exported file is empty (0 bytes): {}".format(os.path.basename(filepath))
        NOTIFICATION.messenger(msg)
        return False, None, None, msg

    if not room_id:
        room_id = generate_room_id()
    else:
        room_id = room_id.upper().strip()

    filename = os.path.basename(filepath)
    NOTIFICATION.messenger("Staging & uploading [{}] ({:.1f} MB) to AR/VR room {}...".format(
        filename, file_size / (1024.0 * 1024.0), room_id))

    ok, final_room, web_url, err = upload_model_file(filepath, room_id=room_id, timeout_ms=timeout_ms)
    if ok:
        NOTIFICATION.messenger(
            "3D Model successfully staged & beamed to Room {}!\nOpening mobile pairing hub...".format(final_room))
        if auto_open_browser:
            webbrowser.open(web_url)
        return True, final_room, web_url, None
    else:
        NOTIFICATION.messenger("Upload failed: {}\nOpening default web hub instead.".format(err))
        if auto_open_browser:
            open_web_hub()
        return False, room_id, None, err

def _http_post_json(url, json_body, timeout_ms):
    """POST a JSON string body. Returns (ok, response_text, error_message)."""
    try:
        from System.Net import WebRequest, ServicePointManager, SecurityProtocolType # pyright: ignore
        from System.IO import StreamReader # pyright: ignore
        import System # pyright: ignore
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "POST"
        request.ContentType = "application/json"
        request.Timeout = timeout_ms

        body_bytes = System.Text.Encoding.UTF8.GetBytes(json_body)
        request.ContentLength = body_bytes.Length
        stream = request.GetRequestStream()
        stream.Write(body_bytes, 0, body_bytes.Length)
        stream.Close()

        response = request.GetResponse()
        reader = StreamReader(response.GetResponseStream())
        text = reader.ReadToEnd()
        reader.Close()
        response.Close()
        return True, text, None
    except ImportError:
        import urllib.request
        req = urllib.request.Request(
            url, data=json_body.encode("utf-8"), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_ms // 1000) as resp:
                return True, resp.read().decode("utf-8"), None
        except Exception as e:
            return False, None, str(e)
    except Exception as e:
        return False, None, str(e)

def _http_put_bytes(url, body_bytes, headers, timeout_ms):
    """PUT raw bytes with custom headers. Returns (ok, response_text, error_message)."""
    try:
        from System.Net import WebRequest, ServicePointManager, SecurityProtocolType # pyright: ignore
        from System.IO import StreamReader # pyright: ignore
        import System # pyright: ignore
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "PUT"
        request.Timeout = timeout_ms
        for key, value in headers.items():
            if key.lower() == "content-type":
                request.ContentType = value
            else:
                request.Headers.Add(key, value)

        dotnet_bytes = System.Array[System.Byte](bytearray(body_bytes))
        request.ContentLength = dotnet_bytes.Length
        stream = request.GetRequestStream()
        stream.Write(dotnet_bytes, 0, dotnet_bytes.Length)
        stream.Close()

        response = request.GetResponse()
        reader = StreamReader(response.GetResponseStream())
        text = reader.ReadToEnd()
        reader.Close()
        response.Close()
        return True, text, None
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=timeout_ms // 1000) as resp:
                return True, resp.read().decode("utf-8"), None
        except Exception as e:
            return False, None, str(e)
    except Exception as e:
        return False, None, str(e)

def put_blob_file(filepath, room_id, blob_pathname, timeout_ms=60000, content_type=None):
    """PUT a file's bytes directly to Vercel Blob storage (no room registration).

    Steps 1-2 of the two-step direct-to-Blob protocol: request a short-lived
    client token, then PUT the bytes straight to Blob, bypassing the web app's
    serverless function (which has a hard ~4.5MB request-body cap). Wire
    protocol (endpoint, headers, x-api-version) verified against
    @vercel/blob's own installed package source in EnneadTab-ARVR
    (node_modules/@vercel/blob/dist/chunk-*.js), not guessed.

    Args:
        filepath (str): Absolute path to the local file.
        room_id (str): Target room code (used for the upload-token request).
        blob_pathname (str): Destination pathname in the blob store, e.g.
            "rooms/AB12CD/drawings/A101/A101.glb".
        timeout_ms (int): Network timeout in milliseconds.
        content_type (str, optional): Override the content type sent to Blob. The room
            upload-token route only allows model types and application/octet-stream, so
            non-model files (sheet PNGs, JSON) must pass "application/octet-stream";
            the web app serves them with a type derived from the file extension.

    Returns:
        tuple: (success, blob_url, error_message)
    """
    if not os.path.exists(filepath):
        return False, None, "File does not exist: " + str(filepath)

    if not room_id:
        room_id = generate_room_id()
    else:
        room_id = room_id.upper().strip()

    try:
        with open(filepath, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        return False, None, "Failed to read file: " + str(e)

    if len(file_bytes) == 0:
        return False, None, "File is empty (0 bytes): " + str(filepath)

    filename = os.path.basename(filepath)
    content_type = content_type or content_type_for(filename)

    # Step 1: request a short-lived client token. Request shape matches
    # exactly what @vercel/blob/client's upload() sends to a handleUpload()
    # route (EnneadTab-ARVR app/api/room/[roomId]/upload-token/route.ts).
    token_url = "{}/api/room/{}/upload-token".format(ARVR_URL_BASE, room_id)
    token_payload = json.dumps({
        "type": "blob.generate-client-token",
        "payload": {
            "pathname": blob_pathname,
            "multipart": False,
            "clientPayload": None,
        },
    })
    ok, token_response, err = _http_post_json(token_url, token_payload, timeout_ms)
    if not ok:
        return False, None, "Failed to get upload token: " + str(err)

    try:
        token_data = json.loads(token_response)
        client_token = token_data["clientToken"]
        store_id = token_data["storeId"]
    except Exception as e:
        return False, None, "Malformed upload-token response: " + str(e)

    # Step 2: PUT the bytes directly to Vercel Blob storage.
    request_id = "{}:{}:{:x}".format(store_id, int(time.time() * 1000), random.randint(0, 0xFFFFFF))
    blob_headers = {
        "authorization": "Bearer " + client_token,
        "x-vercel-blob-store-id": store_id,
        "x-api-version": "12",
        "x-api-blob-request-id": request_id,
        "x-api-blob-request-attempt": "0",
        "x-vercel-blob-access": "private",
        "x-content-type": content_type,
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
    }
    blob_put_url = "https://vercel.com/api/blob/?pathname=" + _url_quote(blob_pathname)
    ok, put_response, err = _http_put_bytes(blob_put_url, file_bytes, blob_headers, timeout_ms)
    if not ok:
        return False, None, "Blob upload failed: " + str(err)

    try:
        blob_data = json.loads(put_response)
        blob_url = blob_data["url"]
    except Exception as e:
        return False, None, "Malformed blob upload response: " + str(e)

    return True, blob_url, None


def register_room(room_id, blob_url, filename, content_type, size, extra=None, timeout_ms=60000):
    """Register a room with the ARVR web app (a few bytes of metadata).

    Extra payload fields (e.g. manifestUrl, kind) are passed through to the
    room API; the current route ignores fields it does not know, so this is
    forward-compatible with the drawing-set viewer (epic TODO-6999).

    Returns:
        tuple: (success, web_url, error_message)
    """
    if not room_id:
        room_id = generate_room_id()
    else:
        room_id = room_id.upper().strip()

    register_url = "{}/api/room/{}".format(ARVR_URL_BASE, room_id)
    register_payload = {
        "blobUrl": blob_url,
        "filename": filename,
        "contentType": content_type,
        "size": size,
    }
    if extra:
        register_payload.update(extra)
    ok, _, err = _http_post_json(register_url, json.dumps(register_payload), timeout_ms)
    if not ok:
        return False, None, "Room registration failed: " + str(err)

    web_url = "{}?room={}".format(ARVR_URL_BASE, room_id)
    return True, web_url, None


def upload_model_file(filepath, room_id=None, timeout_ms=60000):
    """Upload a 3D model (.glb / .gltf / .usdz) to the ARVR room session.

    Uploads directly to Vercel Blob storage in two steps (request a
    short-lived client token, then PUT the bytes straight to Blob),
    bypassing the web app's own serverless function for the upload
    itself. A single POST straight to the room API hit Vercel's hard,
    non-configurable ~4.5MB request-body cap on any real architectural
    model; only the small token-request and room-registration calls still
    go through that function now. Wire protocol (endpoint, headers,
    x-api-version) verified against @vercel/blob's own installed package
    source in EnneadTab-ARVR (node_modules/@vercel/blob/dist/chunk-*.js),
    not guessed -- there is no JS runtime here to run the SDK itself.

    Args:
        filepath (str): Absolute path to model file.
        room_id (str, optional): Target room id. If None, a new one is generated.
        timeout_ms (int): Network timeout in milliseconds.

    Returns:
        tuple: (success, room_id, web_url, error_message)
    """
    if not os.path.exists(filepath):
        return False, None, None, "File does not exist: " + str(filepath)

    bad_format = unsupported_model_reason(os.path.basename(filepath))
    if bad_format:
        return False, None, None, bad_format

    if not room_id:
        room_id = generate_room_id()
    else:
        room_id = room_id.upper().strip()

    filename = os.path.basename(filepath)
    content_type = content_type_for(filename)
    pathname = "rooms/{}/{}".format(room_id, filename)

    # Steps 1-2: direct-to-Blob upload via the shared helper.
    ok, blob_url, err = put_blob_file(filepath, room_id, pathname, timeout_ms)
    if not ok:
        return False, room_id, None, err

    # Step 3: register the room with the resulting blob URL -- a few bytes
    # of metadata, never the model itself.
    size = os.path.getsize(filepath)
    ok, web_url, err = register_room(
        room_id, blob_url, filename, content_type, size, timeout_ms=timeout_ms)
    if not ok:
        return False, room_id, None, err

    return True, room_id, web_url, None


def upload_composition(model_path, sheet_png_path, plan_ext, paper, origin_mm,
                       north_yaw_deg, scale_den, room_id=None, set_name=None, timeout_ms=90000):
    """Upload a model plus its composed site-plan sheet as a one-sheet drawing set.

    The sheet PNG (from ARVR_COMPOSE.render_sheet_png) and the model go to the
    drawing-set paths the server validates. The model is also staged as the
    room's main model so the desktop hub preview and plain AR view keep working.

    Returns:
        tuple: (success, room_id, drawings_url, error_message)
    """
    from EnneadTab import ARVR_COMPOSE as compose
    if not model_path or not model_path.lower().endswith(".glb"):
        return False, None, None, "Composed sheets need a .glb model (the drawing-set viewer reads GLB only)."
    if not os.path.exists(model_path):
        return False, None, None, "File does not exist: " + str(model_path)
    if not sheet_png_path or not os.path.exists(sheet_png_path):
        return False, None, None, "Composed sheet image is missing."
    room_id = (room_id or generate_room_id()).upper().strip()
    model_size = os.path.getsize(model_path)
    try:
        manifest = compose.build_manifest(set_name, model_size, plan_ext, paper, origin_mm,
                                          north_yaw_deg, scale_den, created_at_ms=int(time.time() * 1000))
    except ValueError as e:
        return False, room_id, None, str(e)
    plan_path, sheet_model_path = compose.sheet_blob_paths(room_id, plan_ext)
    manifest["sheets"][0]["planBlobPath"] = plan_path
    manifest["sheets"][0]["modelBlobPath"] = sheet_model_path

    ok, _, err = put_blob_file(sheet_png_path, room_id, plan_path, timeout_ms,
                               content_type=OCTET_STREAM)
    if not ok:
        return False, room_id, None, err
    ok, _, err = put_blob_file(model_path, room_id, sheet_model_path, timeout_ms)
    if not ok:
        return False, room_id, None, err
    filename = os.path.basename(model_path)
    ok, main_url, err = put_blob_file(model_path, room_id, "rooms/{}/{}".format(room_id, filename), timeout_ms)
    if not ok:
        return False, room_id, None, err
    ok, _, err = register_room(room_id, main_url, filename, content_type_for(filename), model_size,
                               extra={"drawingSet": manifest}, timeout_ms=timeout_ms)
    if not ok:
        return False, room_id, None, err
    return True, room_id, "{}/view/{}/drawings".format(ARVR_URL_BASE, room_id), None


def upload_sequence(room_id, manifest, timeout_ms=60000):
    """Upload an exploded-axon / construction-sequence manifest to an existing room.

    The file goes to rooms/<id>/sequence/sequence.json (a subfolder, so the
    room's model lookup never mistakes it for the model) as octet-stream, the
    only non-model type the upload-token route accepts.

    Returns:
        tuple: (success, error_message)
    """
    if not room_id:
        return False, "No room yet: send the model to a room first."
    room_id = room_id.upper().strip()
    path = os.path.join(get_staging_directory(), "arvr_sequence.json")
    try:
        with open(path, "w") as f:
            json.dump(manifest, f)
    except Exception as e:
        return False, "Could not write the sequence file: " + str(e)
    ok, _, err = put_blob_file(path, room_id, "rooms/{}/sequence/sequence.json".format(room_id),
                               timeout_ms, content_type=OCTET_STREAM)
    return ok, err


def _url_quote(text):
    """Percent-encode a URL for embedding in a query string, across Py2/Py3."""
    try:
        import urllib
        return urllib.quote(text, safe="")
    except AttributeError:
        from urllib.parse import quote
        return quote(text, safe="")

def download_qr_code(data_url, size=220):
    """Fetch a QR code PNG (encoding data_url) from a public QR image API and
    save it locally, so Rhino/Revit can display it inline in the dialog
    instead of sending the user to a browser page to see the code.

    Args:
        data_url (str): the URL the QR code should encode (the room's web_url).
        size (int): QR image edge length in pixels.

    Returns:
        str or None: local PNG file path, or None if the fetch failed.
    """
    if not data_url:
        return None

    try:
        import uuid
        qr_api_url = "https://api.qrserver.com/v1/create-qr-code/?size={0}x{0}&data={1}".format(
            size, _url_quote(data_url))
        staging_dir = get_staging_directory()
        out_path = os.path.join(staging_dir, "arvr_qr_{}_{}.png".format(size, uuid.uuid4().hex[:8]))

        # Clean up stale QR files older than 5 minutes in staging dir
        try:
            now_t = time.time()
            for fname in os.listdir(staging_dir):
                if fname.startswith("arvr_qr_") and fname.endswith(".png"):
                    fpath = os.path.join(staging_dir, fname)
                    try:
                        if now_t - os.path.getmtime(fpath) > 300:
                            os.remove(fpath)
                    except:
                        pass
        except:
            pass

        downloaded = False
        # Try .NET WebClient first if in IronPython
        try:
            from System.Net import WebClient, ServicePointManager, SecurityProtocolType # pyright: ignore
            try:
                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            except:
                pass
            client = WebClient()
            client.DownloadFile(qr_api_url, out_path)
            downloaded = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        except:
            pass

        if not downloaded:
            try:
                try:
                    import urllib.request as urllib_req
                    urllib_req.urlretrieve(qr_api_url, out_path)
                except ImportError:
                    import urllib
                    urllib.urlretrieve(qr_api_url, out_path)
                downloaded = os.path.exists(out_path) and os.path.getsize(out_path) > 0
            except:
                pass

        if downloaded:
            return out_path
    except:
        return None

    return None

def get_mobile_viewer_url(room_id):
    """Return the direct mobile AR viewer URL for a room (the big QR target)."""
    return "{}/view/{}".format(ARVR_URL_BASE, room_id.upper().strip())

def download_qr_code_pair(room_id, hub_url):
    """Download both QR codes needed for the share dialog:
      - Large QR  (240px) -> mobile AR viewer URL  (https://enneadtab.com/arvr/view/<room>)
      - Small QR  (80px)  -> desktop hub room URL   (https://enneadtab.com/arvr?room=<room>)

    Args:
        room_id (str): The room code.
        hub_url (str): The desktop hub URL (already computed by stage_and_upload).

    Returns:
        tuple: (large_qr_path, small_qr_path) - either may be None if fetch failed.
    """
    mobile_url = get_mobile_viewer_url(room_id)
    large_path = download_qr_code(mobile_url, size=240)
    small_path = download_qr_code(hub_url, size=80)
    return large_path, small_path

def open_web_hub(room_id=None):
    """Open the ARVR web app in default browser."""
    if room_id:
        url = "{}?room={}".format(ARVR_URL_BASE, room_id.upper().strip())
    else:
        url = ARVR_URL_BASE
    webbrowser.open(url)
    return url
