from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

import requests


OAUTH_AUTHORIZE_URL = "https://developer.api.autodesk.com/authentication/v2/authorize"
OAUTH_TOKEN_URL = "https://developer.api.autodesk.com/authentication/v2/token"


def _get_oauth_config(config_dir: Path) -> dict:
    cfg = {
        "client_id": None,
        "client_secret": None,
        "redirect_uri": "http://127.0.0.1:8765/callback",
        "scope": "data:read data:write account:read",
    }
    # Prefer credentials.json for client data
    cred_file = config_dir / "credentials.json"
    if cred_file.exists():
        try:
            with open(cred_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                cfg["client_id"] = d.get("client_id") or cfg["client_id"]
                cfg["client_secret"] = d.get("client_secret") or cfg["client_secret"]
        except Exception:
            pass
    # Allow override in oauth file
    oauth_file = config_dir / "user_oauth.json"
    if oauth_file.exists():
        try:
            with open(oauth_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                for k in ("client_id", "client_secret", "redirect_uri", "scope"):
                    if d.get(k):
                        cfg[k] = d.get(k)
        except Exception:
            pass
    return cfg


def _load_tokens(config_dir: Path) -> Optional[dict]:
    p = config_dir / "user_oauth.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("tokens")
    except Exception:
        return None


def _save_tokens(config_dir: Path, tokens: dict) -> None:
    p = config_dir / "user_oauth.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    obj = {}
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            obj = {}
    obj["tokens"] = tokens
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _now() -> float:
    return time.time()


def get_user_access_token(config_dir: Path) -> Optional[str]:
    """Return a valid user access token if available, refreshing as needed.

    Requires user_oauth.json with tokens and client details (or credentials.json).
    """
    cfg = _get_oauth_config(config_dir)
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not client_id or not client_secret:
        return None

    tokens = _load_tokens(config_dir)
    if not tokens:
        return None

    access_token = tokens.get("access_token")
    expires_at = tokens.get("expires_at", 0)
    refresh_token = tokens.get("refresh_token")

    if access_token and _now() < float(expires_at) - 120:
        return access_token

    if not refresh_token:
        return None

    # Refresh
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    try:
        resp = requests.post(OAUTH_TOKEN_URL, data=data, timeout=30)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        access_token = payload.get("access_token")
        expires_in = float(payload.get("expires_in", 3600))
        refresh_token = payload.get("refresh_token", refresh_token)
        tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": _now() + expires_in,
        }
        _save_tokens(config_dir, tokens)
        return access_token
    except Exception:
        return None


class _CallbackHandler(BaseHTTPRequestHandler):
    code_value: Optional[str] = None

    def do_GET(self):  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            self.__class__.code_value = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"You can close this window.")
        except Exception:
            pass


def interactive_login(config_dir: Path) -> Optional[str]:
    """Start local server, open browser to authorize, exchange code, save tokens.

    Note: The app's callback URI must be registered in APS portal (default
    http://127.0.0.1:8765/callback). Returns access token or None.
    """
    cfg = _get_oauth_config(config_dir)
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    redirect_uri = cfg.get("redirect_uri")
    scope = cfg.get("scope")
    if not client_id or not client_secret or not redirect_uri:
        return None

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
    }
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    # Start local server
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    server = HTTPServer((host, port), _CallbackHandler)

    import webbrowser
    webbrowser.open(auth_url)

    # Wait for one request with code
    server.handle_request()
    code = _CallbackHandler.code_value
    server.server_close()
    if not code:
        return None

    # Exchange code for tokens
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    try:
        resp = requests.post(OAUTH_TOKEN_URL, data=data, timeout=30)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = float(payload.get("expires_in", 3600))
        tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": _now() + expires_in,
        }
        _save_tokens(config_dir, tokens)
        return access_token
    except Exception:
        return None


