"""Resolve YouTube URLs to a cached thumbnail + watch link.

No iframe / WebEngine — fetch i.ytimg.com jpg into Dump cache.
"""

from __future__ import print_function

import os
import re

try:
    from urllib.request import urlopen, Request
except ImportError:
    from urllib2 import urlopen, Request  # type: ignore

import inbox
import error_report

# Standard YouTube video id length.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_WATCH_RE = re.compile(
    r"(?:youtube\.com/watch\?(?:[^#]*&)?v=|youtu\.be/|youtube\.com/embed/|"
    r"youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)
_THUMB_TEMPLATES = (
    "https://i.ytimg.com/vi/{}/hqdefault.jpg",
    "https://i.ytimg.com/vi/{}/mqdefault.jpg",
    "https://i.ytimg.com/vi/{}/default.jpg",
)
CACHE_SUBDIR = "notification_yt_thumbs"
FETCH_TIMEOUT_SEC = 8


def looks_like_youtube(value):
    if not value:
        return False
    text = str(value).strip()
    if _ID_RE.match(text):
        return True
    lower = text.lower()
    return "youtube.com" in lower or "youtu.be" in lower


def parse_video_id(value):
    """Return 11-char video id or None."""
    if not value:
        return None
    text = str(value).strip()
    if _ID_RE.match(text):
        return text
    match = _WATCH_RE.search(text)
    if match:
        return match.group(1)
    return None


def watch_url(video_id):
    return "https://www.youtube.com/watch?v={}".format(video_id)


def _cache_dir():
    path = os.path.join(inbox.get_dump_folder(), CACHE_SUBDIR)
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def _cache_path(video_id):
    return os.path.join(_cache_dir(), "{}.jpg".format(video_id))


def fetch_thumbnail(video_id):
    """Download thumbnail to Dump cache. Returns local path or None."""
    if not video_id:
        return None
    dest = _cache_path(video_id)
    if os.path.isfile(dest) and os.path.getsize(dest) > 500:
        return dest

    last_err = None
    for template in _THUMB_TEMPLATES:
        url = template.format(video_id)
        try:
            req = Request(
                url,
                headers={"User-Agent": "EnneadTab-NotificationHost/1.0"},
            )
            resp = urlopen(req, timeout=FETCH_TIMEOUT_SEC)
            try:
                data = resp.read()
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            if not data or len(data) < 500:
                continue
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            if os.path.isfile(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            os.rename(tmp, dest)
            return dest
        except Exception as e:
            last_err = e
            continue

    if last_err is not None:
        try:
            error_report.report(
                "YouTube thumb fetch failed for {}: {}".format(
                    video_id, last_err
                ),
                func_name="youtube_thumb.fetch_thumbnail",
            )
        except Exception:
            pass
    return None


def needs_network_fetch(payload):
    """True if payload references YouTube and the thumb is not cached yet."""
    if not isinstance(payload, dict):
        return False
    raw = payload.get("youtube") or payload.get("youtube_url")
    image = payload.get("image")
    if not raw and looks_like_youtube(image):
        raw = image
    video_id = parse_video_id(raw)
    if not video_id:
        return False
    path = _cache_path(video_id)
    return not (os.path.isfile(path) and os.path.getsize(path) > 500)


def enrich_payload(payload, allow_network=True):
    """If payload has a YouTube URL, attach thumbnail image + Open action.

    Accepts:
      - payload['youtube'] / payload['youtube_url']
      - payload['image'] that is itself a YouTube URL or bare video id

    When allow_network is False, only a cached thumb is used (never blocks).
    """
    if not isinstance(payload, dict):
        return payload

    raw = payload.get("youtube") or payload.get("youtube_url")
    image = payload.get("image")
    if not raw and looks_like_youtube(image):
        raw = image
        # Do not treat the URL as a local image path.
        payload.pop("image", None)

    video_id = parse_video_id(raw)
    if not video_id:
        return payload

    watch = watch_url(video_id)
    payload["youtube_url"] = watch

    if not payload.get("image"):
        dest = _cache_path(video_id)
        if os.path.isfile(dest) and os.path.getsize(dest) > 500:
            payload["image"] = dest
        elif allow_network:
            thumb = fetch_thumbnail(video_id)
            if thumb:
                payload["image"] = thumb

    actions = payload.get("actions")
    if actions is None:
        actions = []
    else:
        actions = list(actions)

    already = False
    for action in actions:
        if not isinstance(action, dict):
            continue
        if (action.get("type") or "").lower() != "open_url":
            continue
        payload_url = str(action.get("payload") or "")
        if parse_video_id(payload_url) == video_id or payload_url == watch:
            already = True
            break

    if not already and len(actions) < 2:
        actions.insert(
            0,
            {
                "id": "youtube_open",
                "label": "Open",
                "type": "open_url",
                "payload": watch,
            },
        )
        payload["actions"] = actions

    return payload
