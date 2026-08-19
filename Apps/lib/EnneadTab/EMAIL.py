# -*- coding: utf-8 -*-
"""Desktop email via enneadtab-email. No Outlook. No Emailer.exe.

Posts through Home ``https://enneadtab.com/email/api/send`` with a Bearer token.
Identity is always ``enneadtab-os``. The gateway derives From; Reply-To is the
signed-in colleague so "Your Turn To Sync!" still reads as a person (R6).

Never put SERVICE_KEY on a workstation. Never call AUTH.get_token_blocking()
from this module -- a sync hook or crash-adjacent caller must not open a browser.
"""

import os
import re
import json
import time
import base64

import USER
import ENVIRONMENT
import SPEAK
import AUTH
import FOLDER
import NOTIFICATION

GATEWAY_SEND_URL = "https://enneadtab.com/email/api/send"
IDENTITY_SLUG = "enneadtab-os"
INLINE_MAX_SOURCE_BYTES = 3 * 1024 * 1024
_CID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

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
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
    except ImportError:
        from urllib2 import urlopen, Request, HTTPError  # pyright: ignore


def _failed_result(reason, may_have_sent=False):
    return {
        "id": "",
        "status": "failed",
        "reason": reason,
        "mayHaveSent": bool(may_have_sent),
        "receiptUrl": "",
    }


def _accepted_result(body):
    return {
        "id": str(body.get("id") or ""),
        "status": str(body.get("status") or "failed"),
        "reason": body.get("error") or body.get("message") or body.get("reason"),
        "mayHaveSent": bool(body.get("mayHaveSent")),
        "receiptUrl": str(body.get("receiptUrl") or ""),
    }


def _cid_from_path(path):
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    cleaned = _CID_SAFE.sub("_", stem).strip("._-")
    return cleaned or "inline"


def _write_draft(to_list, subject, blocks, reason):
    """R5 without Outlook: keep a local copy when the gateway cannot send."""
    try:
        html_path = FOLDER.get_local_dump_folder_file("failed_email_draft.html")
        meta_path = FOLDER.get_local_dump_folder_file("failed_email_draft_meta.json")
        lines = ["<!DOCTYPE html><html><body>"]
        for block in blocks or []:
            btype = block.get("type")
            if btype == "heading":
                lines.append("<h2>{}</h2>".format(_esc(block.get("text"))))
            elif btype == "paragraph":
                lines.append("<p>{}</p>".format(_esc(block.get("text")).replace("\n", "<br>")))
            elif btype == "button":
                lines.append('<p><a href="{0}">{1}</a></p>'.format(
                    _esc(block.get("href")), _esc(block.get("label"))))
            elif btype == "image":
                lines.append("<p>[image {0}]</p>".format(_esc(block.get("src"))))
            elif btype == "keyValue":
                for pair in block.get("pairs") or []:
                    lines.append("<p>{0}: {1}</p>".format(
                        _esc(pair.get("key")), _esc(pair.get("value"))))
            elif btype == "folderLink":
                lines.append("<p>{0}: {1}</p>".format(
                    _esc(block.get("label")), _esc(block.get("href"))))
        lines.append("</body></html>")
        with open(html_path, "w") as handle:
            handle.write("".join(lines))
        meta = {
            "To": to_list,
            "Subject": subject,
            "reason": reason,
            "instructions": "Gateway send failed. Open failed_email_draft.html and send from Outlook manually if needed.",
        }
        with open(meta_path, "w") as handle:
            json.dump(meta, handle, indent=2)
        print("Email draft saved: {} ({})".format(html_path, reason))
        return html_path
    except Exception as err:
        print("Could not save email draft: {}".format(err))
        return None


def _esc(text):
    return (
        str(text if text is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _notify_failure(reason):
    try:
        NOTIFICATION.messenger("Email not sent: {}".format(reason))
    except Exception:
        pass


def _http_post_json(url, payload, token, timeout_ms):
    """POST JSON. Returns (http_status, parsed_dict). Never raises on 4xx/5xx."""
    body = json.dumps(payload)
    if _USE_DOTNET:
        return _http_post_dotnet(url, body, token, timeout_ms)
    return _http_post_urllib(url, body, token, timeout_ms)


def _http_post_dotnet(url, body, token, timeout_ms):
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        request = WebRequest.Create(url)
        request.Method = "POST"
        request.ContentType = "application/json"
        request.Headers.Add("Authorization", "Bearer {}".format(token))
        request.Timeout = timeout_ms
        body_bytes = Encoding.UTF8.GetBytes(body)
        request.ContentLength = body_bytes.Length
        stream = request.GetRequestStream()
        stream.Write(body_bytes, 0, body_bytes.Length)
        stream.Close()
        response = request.GetResponse()
        status = int(response.StatusCode)
        reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
        text = reader.ReadToEnd()
        reader.Close()
        response.Close()
        return status, json.loads(text) if text else {}
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
        return status, parsed


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
    if not status:
        try:
            match = re.search(r"\((\d{3})\)", str(err))
            if match:
                status = int(match.group(1))
        except Exception:
            pass
    return status, text


def _http_post_urllib(url, body, token, timeout_ms):
    req = Request(url)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer {}".format(token))
    encoded = body.encode("utf-8")
    try:
        response = urlopen(req, encoded, timeout=timeout_ms // 1000)
        status = getattr(response, "code", 200) or 200
        raw = response.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return status, json.loads(raw) if raw else {}
    except HTTPError as err:
        raw = ""
        try:
            raw = err.read()
            if isinstance(raw, bytes):
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
        return int(err.code), parsed
    except Exception as err:
        return 0, {"message": str(err)}


def send_blocks(
    to_list,
    subject,
    blocks,
    attachments=None,
    reply_to=None,
    idempotency_key=None,
    tags=None,
):
    """Send gateway blocks. Returns a status dict, never a boolean.

    On 5xx / unknown fate the result includes mayHaveSent=True -- do not retry.
    """
    if isinstance(to_list, str):
        to_list = [part.strip() for part in to_list.replace(";", ",").split(",") if part.strip()]
    to_list = [addr.strip() for addr in (to_list or []) if addr and addr.strip()]
    if not to_list:
        return _failed_result("missing recipients")
    if not blocks:
        return _failed_result("missing blocks")
    if not subject:
        return _failed_result("missing subject")

    token = AUTH.get_token()
    if not token:
        reason = "not signed in to EnneadTab (no desktop token)"
        _write_draft(to_list, subject, blocks, reason)
        _notify_failure(reason)
        return _failed_result(reason)

    if not reply_to:
        reply_to = USER.get_company_email_address()
    if not idempotency_key:
        idempotency_key = "enneadtab-os:{}:{}".format(
            USER.USER_NAME, int(time.time() * 1000)
        )

    payload = {
        "identity": IDENTITY_SLUG,
        "to": to_list,
        "subject": subject,
        "blocks": blocks,
        "idempotencyKey": idempotency_key[:256],
        "replyTo": reply_to,
    }
    if attachments:
        payload["attachments"] = attachments
    if tags:
        payload["tags"] = tags

    try:
        http_status, body = _http_post_json(GATEWAY_SEND_URL, payload, token, 30000)
    except Exception as err:
        # Unknown fate: the request may have reached Resend. Do not retry.
        reason = "gateway unreachable: {}".format(err)
        _write_draft(to_list, subject, blocks, reason)
        _notify_failure(reason)
        return _failed_result(reason, may_have_sent=True)

    result = _accepted_result(body if isinstance(body, dict) else {})
    if http_status >= 500:
        result["status"] = "failed"
        result["mayHaveSent"] = True if result["mayHaveSent"] or http_status >= 500 else False
        result["reason"] = result["reason"] or "gateway {}".format(http_status)
        _write_draft(to_list, subject, blocks, result["reason"])
        _notify_failure(result["reason"])
        return result

    if http_status == 0 or (http_status >= 400 and result["status"] not in ("accepted", "queued", "delivered")):
        result["status"] = "failed"
        result["reason"] = result["reason"] or "gateway {}".format(http_status)
        _write_draft(to_list, subject, blocks, result["reason"])
        _notify_failure(result["reason"])
        return result

    if result["status"] in ("accepted", "queued", "delivered"):
        try:
            SPEAK.speak(
                "enni-ed tab email is sent out. Subject line: {}".format(
                    subject.lower().replace("ennead", "enni-ed ")
                )
            )
        except Exception:
            pass
        return result

    result["status"] = "failed"
    result["reason"] = result["reason"] or "gateway {}".format(http_status)
    _write_draft(to_list, subject, blocks, result["reason"])
    _notify_failure(result["reason"])
    return result


def _file_attachment(path, as_inline_image=False):
    """Local file -> inline base64 attachment, or None if missing/too big."""
    if not path or not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
    except Exception:
        return None
    if size > INLINE_MAX_SOURCE_BYTES:
        print(
            "Skipping attachment {} ({} bytes over inline cap)".format(path, size)
        )
        return None
    try:
        handle = open(path, "rb")
        raw = handle.read()
        handle.close()
    except Exception as err:
        print("Could not read attachment {}: {}".format(path, err))
        return None
    encoded = base64.b64encode(raw)
    if not isinstance(encoded, str):
        encoded = encoded.decode("ascii")
    item = {
        "content": encoded,
        "filename": os.path.basename(path),
    }
    lower = path.lower()
    if lower.endswith(".png"):
        item["contentType"] = "image/png"
    elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
        item["contentType"] = "image/jpeg"
    elif lower.endswith(".gif"):
        item["contentType"] = "image/gif"
    if as_inline_image:
        item["contentId"] = _cid_from_path(path)
    return item


def email(
    receiver_email_list,
    body,
    subject=ENVIRONMENT.PLUGIN_NAME + " Auto Email",
    body_folder_link_list=None,
    body_image_link_list=None,
    attachment_list=None,
):
    """Send email through the gateway. Compatibility wrapper around send_blocks.

    Args:
        receiver_email_list (list): List of email addresses.
        body (str): Body of the email (plain text; newlines stay newlines).
        subject (str, optional): Subject of the email.
        body_folder_link_list (list, optional): Folder links as folderLink blocks.
        body_image_link_list (list, optional): Local image paths, CID-inlined when under 3 MB.
        attachment_list (list, optional): Local files attached when under 3 MB.
    """
    if not body:
        print("Missing body of the email.....")
        return _failed_result("missing body")

    if not receiver_email_list:
        print("missing email receivers....")
        return _failed_result("missing recipients")

    if isinstance(receiver_email_list, str):
        print("Prefer list but ok.")
        print(receiver_email_list)
        receiver_email_list = receiver_email_list.rstrip().split(";")

    blocks = [{"type": "paragraph", "text": body}]
    attachments = []

    if body_folder_link_list:
        for link in body_folder_link_list:
            if not link:
                continue
            blocks.append({
                "type": "folderLink",
                "href": link,
                "label": "Open folder",
            })

    if body_image_link_list:
        for path in body_image_link_list:
            item = _file_attachment(path, as_inline_image=True)
            if not item:
                continue
            attachments.append(item)
            blocks.append({
                "type": "image",
                "src": "cid:{}".format(item["contentId"]),
                "alt": item["filename"],
            })

    if attachment_list:
        for path in attachment_list:
            item = _file_attachment(path, as_inline_image=False)
            if item:
                attachments.append(item)

    return send_blocks(
        to_list=receiver_email_list,
        subject=subject,
        blocks=blocks,
        attachments=attachments or None,
        reply_to=USER.get_company_email_address(),
    )


def email_error(
    traceback, tool_name, error_from_user, subject_line=ENVIRONMENT.PLUGIN_NAME + " Auto Email Error Log"
):
    """Do not send crash traces through Resend.

    A storm on @try_catch_error would consume the shared 10 req/s team limit and
    take every identity dark. Crash reports go to ErrorDump only.
    """
    print(
        "email_error suppressed (crash mail does not go to Resend): {} / {}".format(
            tool_name, error_from_user
        )
    )
    return _failed_result("crash email suppressed")


def email_to_self(
    subject=ENVIRONMENT.PLUGIN_NAME + " Auto Email to Self",
    body=None,
    body_folder_link_list=None,
    body_image_link_list=None,
    attachment_list=None,
):
    """Send email to self."""
    return email(
        receiver_email_list=[USER.get_company_email_address()],
        subject=subject,
        body=body,
        body_folder_link_list=body_folder_link_list,
        body_image_link_list=body_image_link_list,
        attachment_list=attachment_list,
    )


def unit_test():
    email_to_self(
        subject="Test Email for compiler",
        body="Happy Howdy. This is a quick email test to see if the base communication still working",
    )


if __name__ == "__main__":
    unit_test()
