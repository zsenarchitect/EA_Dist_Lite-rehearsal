# -*- coding: utf-8 -*-
"""Show Room (EnneadTab-Presentation) - Revit sheet push skeleton (D5 / #3390).

Pushes sheet artifact *metadata* to:
  POST https://enneadtab.com/show-room/api/decks/{deckId}/push-artifact

Auth: desktop Bearer via EnneadTab.AUTH.get_token() (Home desktop OAuth).
Do NOT use D3 agent tokens here - those are minted for automated agents on a
deck scope; the Revit plugin is a desktop principal.

Transport: .NET HttpWebRequest under IronPython 2.7 (urllib2 SSL breaks in-host
on some office segments - #2429). AllowAutoRedirect=False + assert
Content-Type application/json + expected JSON keys (#2909). An SSO HTML login
must never read as success.

Composite sheet identity (Presentation spec sec 7 / #2463):
  model key + sheet_natural_key, corroborated by sheet_unique_id.
Wire JSON uses OpenAPI camelCase (modelGuid, sheetNaturalKey, ...).

Zero ACC dependency: export is a local path stub - no Autodesk Construction
Cloud credential (#3154 deliberately avoided).

SCHEDULE RISK
-------------
This module cannot be smoked without a machine running Revit. CI cannot host
that. Ship the skeleton + docs; a human with Revit must wire the button, run
a real export, and confirm a live push before calling D5 done end-to-end.

IronPython 2.7 safe: no f-strings, no type hints, no pathlib.
"""

from __future__ import print_function

import hashlib
import json
import os

from EnneadTab import AUTH, WEB_GUARD
from EnneadTab.AI import _common


SHOW_ROOM_ORIGIN = "https://enneadtab.com"
PUSH_PATH_TMPL = "/show-room/api/decks/{deck_id}/push-artifact"

# PushArtifactResponse keys - assert these so an HTML login page cannot pass.
_EXPECTED_RESPONSE_KEYS = ("artifact", "slot", "created")

# modelKeySource vocabulary (Presentation program plan sec 7 / #3243).
MODEL_KEY_CLOUD_GUID = "cloud_guid"
MODEL_KEY_WORKSHARING_GUID = "worksharing_guid"
MODEL_KEY_HASHED_PATH = "hashed_path"
MODEL_KEY_HASHED_TITLE = "hashed_title"


class ShowRoomPushError(Exception):
    """Raised when Show Room rejects or misroutes a push."""

    def __init__(self, message, status_code=None):
        self.status_code = status_code
        Exception.__init__(self, message)


def composite_sheet_source_key(sheet_natural_key):
    """Human-facing sourceKey prefix the server also derives: sheet:<number>.

    Pass the bare SheetNumber (e.g. 'A-101'); do not pre-prefix 'sheet:'.
    """
    natural = (sheet_natural_key or "").strip()
    if not natural:
        return None
    if natural.lower().startswith("sheet:"):
        natural = natural[6:].strip()
    return "sheet:{}".format(natural.lower())


def resolve_model_keys(doc):
    """Return modelGuid / rawModelKey / modelKeySource for a Revit Document.

    Mirrors REVIT_SYNC.get_model_guid priority but also reports *why* the key
    is trustworthy (#3243). When Revit APIs are unavailable (unit / CPython),
    returns a title-hash stub so the payload builder stays callable.
    """
    # 1. Cloud model GUID
    try:
        if hasattr(doc, "IsModelInCloud") and doc.IsModelInCloud:
            cloud_path = doc.GetCloudModelPath()
            if cloud_path:
                model_guid = str(cloud_path.GetModelGUID())
                if model_guid and model_guid != "00000000-0000-0000-0000-000000000000":
                    return {
                        "modelGuid": model_guid,
                        "rawModelKey": model_guid,
                        "modelKeySource": MODEL_KEY_CLOUD_GUID,
                    }
    except Exception:
        pass

    # 2. Worksharing central GUID
    try:
        guid = doc.WorksharingCentralGUID
        if guid and str(guid) != "00000000-0000-0000-0000-000000000000":
            g = str(guid)
            return {
                "modelGuid": g,
                "rawModelKey": g,
                "modelKeySource": MODEL_KEY_WORKSHARING_GUID,
            }
    except Exception:
        pass

    # 3. Hash of central path (local workshared)
    try:
        central_path = doc.GetWorksharingCentralModelPath()
        if central_path:
            from Autodesk.Revit.DB import ModelPathUtils
            path_str = ModelPathUtils.ConvertModelPathToUserVisiblePath(central_path)
            if path_str:
                hashed = _hash_path_to_guid(path_str)
                return {
                    "modelGuid": hashed,
                    "rawModelKey": hashed,
                    "modelKeySource": MODEL_KEY_HASHED_PATH,
                }
    except Exception:
        pass

    # 4. Title hash (non-workshared / stub)
    title = getattr(doc, "Title", None) or "untitled"
    hashed = _hash_path_to_guid(title)
    return {
        "modelGuid": hashed,
        "rawModelKey": hashed,
        "modelKeySource": MODEL_KEY_HASHED_TITLE,
    }


def _hash_path_to_guid(path_str):
    """Deterministic path/title id - same spirit as REVIT_SYNC._hash_path_to_guid."""
    try:
        from EnneadTab.REVIT import REVIT_SYNC
        return REVIT_SYNC._hash_path_to_guid(path_str)
    except Exception:
        digest = hashlib.sha1((path_str or "").encode("utf-8")).hexdigest()[:32]
        return "path-{}".format(digest)


def local_export_stub(sheet, export_dir=None):
    """Local sheet export placeholder - no ACC.

    Returns (local_path, content_type, byte_length, content_hash).
    A human with Revit wires real PDF/PNG export here; v1 only needs the
    metadata contract to be correct.
    """
    number = ""
    name = ""
    try:
        number = str(sheet.SheetNumber)
    except Exception:
        number = "unknown"
    try:
        name = str(sheet.Name)
    except Exception:
        name = ""

    directory = export_dir or os.path.join(
        os.environ.get("TEMP", os.environ.get("TMP", ".")),
        "enneadtab_show_room",
    )
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
    except Exception:
        directory = "."

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in number)[:40]
    path = os.path.join(directory, "sheet_{}.png".format(safe or "stub"))
    # Tiny placeholder PNG is not written here - just hash the identity string
    # so dry runs without Revit still produce a stable contentHash.
    payload = "show-room-stub:{0}:{1}".format(number, name).encode("utf-8")
    content_hash = hashlib.sha256(payload).hexdigest()
    return path, "image/png", len(payload), content_hash


def build_push_payload(
    model_guid,
    raw_model_key,
    model_key_source,
    sheet_natural_key,
    sheet_unique_id,
    issued,
    content_hash,
    content_type,
    byte_length,
    confirm_issued_replace=False,
):
    """OpenAPI PushArtifactRequest (camelCase) from Revit-side fields."""
    body = {
        "contentType": content_type,
        "contentHash": content_hash,
        "byteLength": int(byte_length),
        "modelGuid": model_guid,
        "rawModelKey": raw_model_key,
        "modelKeySource": model_key_source,
        "sheetNaturalKey": (sheet_natural_key or "").strip(),
        "sheetUniqueId": (sheet_unique_id or "").strip(),
        "issued": bool(issued),
    }
    if confirm_issued_replace:
        body["confirmIssuedReplace"] = True
    return body


def push_artifact(deck_id, payload, token=None, timeout_ms=60000):
    """POST push-artifact. Returns parsed JSON dict on success.

    Asserts Content-Type application/json and expected response keys (#2909).
    """
    if not deck_id:
        raise ShowRoomPushError("deck_id is required")

    auth_token = token
    if auth_token is None:
        auth_token = AUTH.get_token()
    if not auth_token:
        raise ShowRoomPushError(
            "No desktop Bearer token - sign in via AUTH.request_auth() first "
            "(D3 agent tokens are not used by this plugin)",
            status_code=401,
        )

    url = SHOW_ROOM_ORIGIN + PUSH_PATH_TMPL.format(deck_id=deck_id)
    body_str = json.dumps(payload)

    if _common._USE_DOTNET:
        status, content_type, text = _post_dotnet(url, body_str, auth_token, timeout_ms)
    else:
        status, content_type, text = _post_urllib(url, body_str, auth_token, timeout_ms)

    if WEB_GUARD.is_redirect(status):
        raise ShowRoomPushError(
            WEB_GUARD.describe(status) or "API redirected to login",
            status_code=status,
        )

    if status != 200:
        raise ShowRoomPushError(
            "Show Room push failed: HTTP {0}".format(status),
            status_code=status,
        )

    if not content_type or "application/json" not in content_type.lower():
        raise ShowRoomPushError(
            "Expected Content-Type application/json, got {!r} - likely an SSO "
            "HTML page (#2909)".format(content_type),
            status_code=status,
        )

    try:
        parsed = json.loads(text) if text else None
    except Exception:
        parsed = None

    if not WEB_GUARD.is_delivered(status, parsed):
        raise ShowRoomPushError(
            "Response body is not JSON - SSO bounce disguised as 200 (#2909)",
            status_code=status,
        )

    if not isinstance(parsed, dict):
        raise ShowRoomPushError("JSON body was not an object", status_code=status)

    missing = [k for k in _EXPECTED_RESPONSE_KEYS if k not in parsed]
    if missing:
        raise ShowRoomPushError(
            "JSON missing expected keys {0} (#2909)".format(missing),
            status_code=status,
        )

    return parsed


def push_sheet_from_revit(doc, sheet, deck_id, export_dir=None, confirm_issued_replace=False):
    """High-level: resolve model keys, stub-export, push. Needs live Revit for sheet APIs."""
    keys = resolve_model_keys(doc)
    path, content_type, byte_length, content_hash = local_export_stub(sheet, export_dir)

    sheet_number = ""
    sheet_uid = ""
    issued = False
    try:
        sheet_number = str(sheet.SheetNumber).strip()
    except Exception:
        pass
    try:
        sheet_uid = str(sheet.UniqueId)
    except Exception:
        pass
    try:
        # Best-effort issued flag - real wiring inspects Revision.Issued / GetAllRevisionIds.
        issued = bool(getattr(sheet, "Issued", False))
    except Exception:
        issued = False

    payload = build_push_payload(
        model_guid=keys["modelGuid"],
        raw_model_key=keys["rawModelKey"],
        model_key_source=keys["modelKeySource"],
        sheet_natural_key=sheet_number,
        sheet_unique_id=sheet_uid,
        issued=issued,
        content_hash=content_hash,
        content_type=content_type,
        byte_length=byte_length,
        confirm_issued_replace=confirm_issued_replace,
    )
    result = push_artifact(deck_id, payload)
    # Stub path is for the human wiring a real exporter - not on the wire.
    result["_localExportPathStub"] = path
    return result


def _post_dotnet(url, body_str, token, timeout_ms):
    from System.Net import WebRequest, ServicePointManager, SecurityProtocolType  # pyright: ignore
    from System.IO import StreamReader  # pyright: ignore
    from System.Text import Encoding  # pyright: ignore

    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
    except Exception:
        pass

    request = WebRequest.Create(url)
    request.Method = "POST"
    request.ContentType = "application/json"
    request.Timeout = timeout_ms
    WEB_GUARD.harden_dotnet_request(request)
    request.Headers.Add(
        "Authorization",
        "Bearer {}".format(_common._safe_token(token)),
    )

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
            content_type = ""
            try:
                content_type = str(response.ContentType or "")
            except Exception:
                content_type = ""
            reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
            text = reader.ReadToEnd()
            reader.Close()
        finally:
            response.Close()
        return status, content_type, text
    except Exception as err:
        status = _common._status_from_exception(err) or 0
        text = str(err)
        return status, "", text


def _post_urllib(url, body_str, token, timeout_ms):
    try:
        from urllib.request import Request
        from urllib.error import HTTPError
    except ImportError:
        from urllib2 import Request, HTTPError

    req = Request(url, data=body_str.encode("utf-8"))
    req.add_header("Content-Type", "application/json")
    req.add_header(
        "Authorization",
        "Bearer {}".format(_common._safe_token(token)),
    )
    timeout_sec = max(1, int(timeout_ms / 1000.0))
    try:
        response = WEB_GUARD.urlopen_no_redirect(req, timeout_sec)
        status = getattr(response, "code", None) or getattr(response, "status", 200) or 200
        content_type = ""
        try:
            content_type = response.headers.get("Content-Type") or ""
        except Exception:
            content_type = ""
        raw = response.read()
        if not isinstance(raw, type(u"")):
            raw = raw.decode("utf-8")
        return int(status), content_type, raw
    except HTTPError as err:
        status = int(getattr(err, "code", 0) or 0)
        content_type = ""
        try:
            content_type = err.headers.get("Content-Type") or ""
        except Exception:
            pass
        raw = ""
        try:
            raw = err.read()
            if raw and not isinstance(raw, type(u"")):
                raw = raw.decode("utf-8")
        except Exception:
            raw = str(err)
        return status, content_type, raw


def unit_test():
    """Pure-Python checks - no Revit required."""
    assert composite_sheet_source_key("A-101") == "sheet:a-101"
    assert composite_sheet_source_key("sheet:A-101") == "sheet:a-101"
    assert composite_sheet_source_key("") is None

    class _Doc(object):
        Title = "Stub Model"
        IsModelInCloud = False

    keys = resolve_model_keys(_Doc())
    assert keys["modelKeySource"] == MODEL_KEY_HASHED_TITLE
    assert keys["modelGuid"] and keys["rawModelKey"]

    body = build_push_payload(
        model_guid=keys["modelGuid"],
        raw_model_key=keys["rawModelKey"],
        model_key_source=keys["modelKeySource"],
        sheet_natural_key="A-101",
        sheet_unique_id="uid-1",
        issued=False,
        content_hash="abc",
        content_type="image/png",
        byte_length=3,
    )
    for required in (
        "contentType",
        "contentHash",
        "byteLength",
        "modelGuid",
        "rawModelKey",
        "modelKeySource",
        "sheetNaturalKey",
        "sheetUniqueId",
        "issued",
    ):
        assert required in body, required

    print("SHOW_ROOM_PUSH unit_test OK")


if __name__ == "__main__":
    unit_test()
