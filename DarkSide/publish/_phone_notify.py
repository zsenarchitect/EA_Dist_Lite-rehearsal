"""Send a push notification to phone via ntfy.sh (subscribe in ntfy app first)."""

import os
import sys
import urllib.error
import urllib.request

DARKSIDE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _load_ntfy_topic():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        return topic
    env_path = os.path.join(DARKSIDE_DIR, ".env")
    if not os.path.isfile(env_path):
        return ""
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "NTFY_TOPIC":
                return value.strip().strip('"').strip("'")
    return ""


def send_ntfy(title, message, click_url=None, tags=None):
    topic = _load_ntfy_topic()
    if not topic:
        print("NTFY_TOPIC not set. Add to DarkSide/.env, e.g. NTFY_TOPIC=your-secret-topic")
        print("Phone: install ntfy app -> Subscribe to topic -> use same name in .env")
        return False

    url = "https://ntfy.sh/{}".format(topic)
    headers = {"Title": title[:250], "Priority": "default", "Tags": tags or "bell"}
    if click_url:
        headers["Click"] = click_url

    data = message.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        print("Phone notification sent (ntfy topic: {})".format(topic))
        return True
    except urllib.error.HTTPError as e:
        print("ntfy failed HTTP {}: {}".format(e.code, e.read().decode("utf-8", errors="replace")))
        return False
    except Exception as e:
        print("ntfy failed: {}".format(e))
        return False


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "EnneadTab Publish"
    body = sys.argv[2] if len(sys.argv) > 2 else "Reminder"
    click = sys.argv[3] if len(sys.argv) > 3 else ""
    ok = send_ntfy(title, body, click or None)
    sys.exit(0 if ok else 1)
