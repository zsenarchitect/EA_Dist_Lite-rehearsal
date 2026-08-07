from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import requests


class TokenCache:
    def __init__(self) -> None:
        self.access_token: Optional[str] = None
        self.expires_at: float = 0.0

    def valid(self, buffer_seconds: int = 120) -> bool:
        return bool(self.access_token) and (time.time() < self.expires_at - buffer_seconds)


_TOKEN_CACHE = TokenCache()


def _load_borrowed_credentials() -> Optional[Tuple[str, str]]:
    """Attempt to borrow credentials from known sibling app locations.

    Returns (client_id, client_secret) or None.
    """
    candidates = [
        Path("DarkSide/exes/source code/RevitSlave-3.0/config/aps_credentials.json"),
        # Add more known app credential paths here if needed
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cid = data.get("client_id")
                    csec = data.get("client_secret")
                    if cid and csec:
                        return cid, csec
            except Exception:
                continue
    return None


def _load_local_credentials(config_dir: Path) -> Optional[Tuple[str, str]]:
    creds_file = config_dir / "credentials.json"
    if creds_file.exists():
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                cid = data.get("client_id")
                csec = data.get("client_secret")
                if cid and csec:
                    return cid, csec
        except Exception:
            return None
    return None


def get_credentials(config_dir: Path) -> Optional[Tuple[str, str]]:
    # 1) Environment variables
    cid = os.environ.get("APS_CLIENT_ID")
    csec = os.environ.get("APS_CLIENT_SECRET")
    if cid and csec:
        return cid, csec

    # 2) Local file
    creds = _load_local_credentials(config_dir)
    if creds:
        return creds

    # 3) Borrowed credentials from sibling apps
    creds = _load_borrowed_credentials()
    if creds:
        return creds

    return None


def get_access_token(config_dir: Path, scopes: str = "data:read data:write account:read") -> Optional[str]:
    if _TOKEN_CACHE.valid():
        return _TOKEN_CACHE.access_token

    creds = get_credentials(config_dir)
    if not creds:
        return None
    client_id, client_secret = creds

    token_url = "https://developer.api.autodesk.com/authentication/v2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": scopes,
    }
    try:
        resp = requests.post(token_url, headers=headers, data=data, timeout=30)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        _TOKEN_CACHE.access_token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        _TOKEN_CACHE.expires_at = time.time() + float(expires_in)
        return _TOKEN_CACHE.access_token
    except Exception:
        return None


def get_impersonation_headers(config_dir: Path) -> dict:
    """Return headers for two-legged impersonation if configured.

    Supports env vars APS_IMPERSONATE_EMAIL / APS_IMPERSONATE_USER_ID or
    fields in configs/config.json: impersonate_user_email / impersonate_user_id.
    """
    # 1) Environment variables
    email = os.environ.get("APS_IMPERSONATE_EMAIL")
    user_id = os.environ.get("APS_IMPERSONATE_USER_ID")
    if email:
        return {"x-user-email": email, "x-ads-user-email": email}
    if user_id:
        return {"x-user-id": user_id, "x-ads-user-id": user_id}

    # 2) configs/config.json
    cfg = config_dir / "config.json"
    if cfg.exists():
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if data.get("impersonate_user_email"):
                        em = data.get("impersonate_user_email")
                        return {"x-user-email": em, "x-ads-user-email": em}
                    if data.get("impersonate_user_id"):
                        uid = data.get("impersonate_user_id")
                        return {"x-user-id": uid, "x-ads-user-id": uid}
        except Exception:
            pass
    return {}


