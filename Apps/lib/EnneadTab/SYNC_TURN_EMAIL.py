# -*- coding: utf-8 -*-
"""Gateway payload for the Revit 'Your Turn To Sync' mail.

IronPython 2.7: no f-strings, no type hints. Blocks match enneadtab-email's
schema so the meme is a cid: image Resend actually inlines.
"""

import os
import json

MEME_CID = "meme_you_sync_first"
# Direct gateway origin. Home's /email rewrite returns 200 HTML (login
# page) for this static file, so a fetch of enneadtab.com/email/... would
# attach a webpage as the "jpeg".
MEME_URL = "https://enneadtab-email.vercel.app/sync-turn/you-sync-first.jpg"
QUEUE_URL_PREFIX = "https://enneadtab.com/sync/queue/"
SUBJECT = "Your Turn To Sync!"


def _text(value):
    if value is None:
        return ""
    return str(value)


def build_blocks(model_title, just_finished, next_user, remaining_after, queue_url):
    """Return gateway blocks for one sync-turn mail."""
    title = _text(model_title).strip() or "this model"
    finished = _text(just_finished).strip() or "A colleague"
    you = _text(next_user).strip()
    waiters = [_text(name).strip() for name in (remaining_after or []) if _text(name).strip()]
    if waiters:
        still_waiting = ", ".join(waiters[:8])
        if len(waiters) > 8:
            still_waiting = still_waiting + ", and more"
    else:
        still_waiting = "You are the last in line."

    blocks = [
        {"type": "heading", "text": "Your turn to sync"},
        {
            "type": "image",
            "src": "cid:{}".format(MEME_CID),
            "alt": "You sync first",
        },
        {
            "type": "paragraph",
            "text": "{} just finished. It is your turn to sync {}.".format(finished, title),
        },
        {
            "type": "keyValue",
            "pairs": [
                {"key": "Just finished", "value": finished},
                {"key": "You", "value": you or "(you)"},
                {"key": "Still waiting", "value": still_waiting},
            ],
        },
    ]
    if queue_url:
        blocks.append({
            "type": "button",
            "label": "Open the queue",
            "href": queue_url,
        })
    return blocks


def build_attachments():
    return [{
        "url": MEME_URL,
        "filename": "you-sync-first.jpg",
        "contentType": "image/jpeg",
        "contentId": MEME_CID,
    }]


def queue_url_for(model_guid):
    guid = _text(model_guid).strip()
    if not guid:
        return None
    return QUEUE_URL_PREFIX + guid


def idempotency_key(model_guid, next_user, just_finished):
    return "enneadtab-os:sync-turn:{}:{}:{}".format(
        _text(model_guid).strip() or "unknown",
        _text(next_user).strip() or "unknown",
        _text(just_finished).strip() or "unknown",
    )[:256]


def _send_via_emailer(to_addr, model_title):
    """Signed-out fallback: launch Emailer.exe so the nag still leaves.

    The meme still will not inline (local img src) - this path exists only so a
    colleague without a desktop token still gets the one-liner. Do not use it
    after a gateway 5xx (mayHaveSent).
    """
    try:
        import DATA_FILE
        import EXE
        import IMAGE
    except Exception as err:
        return {
            "id": "",
            "status": "failed",
            "reason": "emailer import failed: {}".format(err),
            "mayHaveSent": False,
        }
    body = "Hi there, it is your turn to sync <{}>!".format(_text(model_title))
    meme = IMAGE.get_image_path_by_name("meme_you_sync_first.jpg")
    data = {
        "receiver_email_list": [to_addr],
        "subject": SUBJECT,
        "body": body.replace("\n", "<br>"),
        "body_folder_link_list": None,
        "body_image_link_list": [meme] if meme else None,
        "attachment_list": None,
        "logo_image_path": IMAGE.get_image_path_by_name("logo.png"),
    }
    DATA_FILE.set_data(data, "email_data")
    opened = EXE.try_open_app("Emailer")
    if not opened:
        return {
            "id": "",
            "status": "failed",
            "reason": "emailer not launched",
            "mayHaveSent": False,
        }
    return {
        "id": "",
        "status": "queued",
        "reason": "emailer-fallback",
        "mayHaveSent": True,
    }


def send(model_title, just_finished, next_user, remaining_after, model_guid=None):
    """POST the designed mail. Emailer.exe only if there is no desktop token."""
    next_user = _text(next_user).strip()
    if not next_user:
        return {"id": "", "status": "failed", "reason": "empty next_user", "mayHaveSent": False}

    import AUTH
    import EMAIL
    import USER

    to_addr = "{}@ennead.com".format(next_user)
    if to_addr.startswith("@") or " " in next_user:
        next_user = next_user.replace(" ", "")
        to_addr = "{}@ennead.com".format(next_user)
        if not next_user:
            return {"id": "", "status": "failed", "reason": "invalid next_user", "mayHaveSent": False}

    if not AUTH.get_token():
        return _send_via_emailer(to_addr, model_title)

    queue_url = queue_url_for(model_guid)
    blocks = build_blocks(
        model_title, just_finished, next_user, remaining_after, queue_url)
    result = EMAIL.send_blocks(
        to_list=[to_addr],
        subject=SUBJECT,
        blocks=blocks,
        attachments=build_attachments(),
        reply_to=USER.get_company_email_address(),
        idempotency_key=idempotency_key(model_guid, next_user, just_finished),
        tags={"kind": "sync-turn"},
    )
    if result.get("status") == "failed":
        reason = str(result.get("reason") or "")
        if "401" in reason or "not signed in" in reason:
            return _send_via_emailer(to_addr, model_title)
    return result


if __name__ == "__main__":
    preview_blocks = build_blocks(
        "2534_A_EA_NYU HQ",
        "bshapiro",
        "szhang",
        [],
        queue_url_for("00000000-0000-0000-0000-000000000001"),
    )
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_turn_preview.json")
    handle = open(out_path, "w")
    json.dump({"blocks": preview_blocks, "attachments": build_attachments()}, handle, indent=2)
    handle.close()
    print("preview payload: {}".format(out_path))
