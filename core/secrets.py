"""core/secrets.py — broker credentials, read from the environment only.

The public version keeps one rule: credentials live in the environment (or a
local, git-ignored `.env`), never in code, never in a tracked file, and this
module never WRITES them anywhere. Copy `.env.example` to `.env` and fill it
in; the data feed and the WebSocket read from here.

    DHAN_CLIENT_ID          broker client id
    DHAN_ACCESS_TOKEN       trading-API JWT (expires daily)
    DHAN_DATA_TOKEN         data-API token, if your plan issues one
    DHAN_DATA_API_KEY       data-API key
    DHAN_DATA_API_SECRET    data-API secret

Nothing here is needed to run the tests or the backtester: both run on
synthetic data with no broker account.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(_PROJECT_ROOT, ".env")

# Kept for callers that log where a token "would" live. Nothing writes here.
TOKEN_FILE = ENV_FILE


def _load_dotenv_once() -> None:
    """Minimal .env reader (KEY=VALUE lines). Real environment variables win."""
    if getattr(_load_dotenv_once, "_done", False):
        return
    _load_dotenv_once._done = True
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _get(name: str) -> Optional[str]:
    _load_dotenv_once()
    v = os.environ.get(name, "").strip()
    return v or None


def get_client_id() -> Optional[str]:
    return _get("DHAN_CLIENT_ID")


def get_access_token() -> Optional[str]:
    return _get("DHAN_ACCESS_TOKEN")


def get_data_token() -> Optional[str]:
    return _get("DHAN_DATA_TOKEN")


def get_data_api_key() -> Optional[str]:
    return _get("DHAN_DATA_API_KEY")


def get_data_api_secret() -> Optional[str]:
    return _get("DHAN_DATA_API_SECRET")


@dataclass
class TokenHealth:
    valid: bool
    expires_at: Optional[datetime]
    hours_left: Optional[float]
    needs_refresh: bool
    message: str


def token_health(token: Optional[str] = None) -> TokenHealth:
    """Decode the JWT's `exp` claim (no signature check - this only reports)."""
    t = token if token is not None else get_access_token()
    if not t:
        return TokenHealth(False, None, None, True, "No token configured (see .env.example)")
    parts = t.split(".")
    if len(parts) != 3:
        return TokenHealth(False, None, None, True, "Token is not a JWT")
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    except Exception as e:
        return TokenHealth(False, None, None, True, f"Decode error: {e}")
    exp = payload.get("exp")
    if not exp:
        return TokenHealth(True, None, None, False, "Token decoded, no exp claim")
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    hrs = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600.0
    if hrs <= 0:
        return TokenHealth(False, exp_dt, hrs, True, f"EXPIRED {abs(hrs):.1f}h ago")
    return TokenHealth(True, exp_dt, hrs, hrs <= 6,
                       f"Valid for {hrs:.1f}h (until {exp_dt:%Y-%m-%d %H:%M} UTC)")
