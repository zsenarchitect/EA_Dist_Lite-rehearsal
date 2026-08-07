#!/usr/bin/env python3
"""
Interactive 3-legged OAuth login helper.

Opens a browser, captures the authorization code via a local callback,
exchanges it for tokens, and stores them in configs/user_oauth.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from oauth3 import interactive_login


def main() -> int:
    config_dir = BASE_DIR / "configs"
    token = interactive_login(config_dir)
    if token:
        print("Login successful. Token saved.")
        return 0
    print("Login failed. Check client_id/secret and redirect URI in APS app.")
    return 1


if __name__ == "__main__":
    sys.exit(main())


