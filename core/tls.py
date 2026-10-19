"""
tls.py - one switch for certificate verification, defaulting to ON.

WHY THIS EXISTS
---------------
Five modules each carried their own copy of "skip TLS verification unless
DHAN_SSL_STRICT=1". Importing core.api_dhan monkey-patched requests so that
EVERY https call in the process defaulted to verify=False, and swapped the
stdlib default context for an unverified one. The comment blamed a corporate
proxy; the sandbox these sessions used to run in did intercept TLS.

The desk machine does not. Measured 2026-09-25 with certifi: api.dhan.co,
images.dhan.co, www.nseindia.com, nsearchives.nseindia.com and Yahoo all
verify cleanly. So the bypass protected nothing, and it sent the Dhan
Access-Token (a JWT that can place real orders, whatever PAPER_TRADE says),
the api-secret and the Telegram bot token over connections that would accept
any certificate from anyone on the network path.

RULE
----
Verification is on. Set DHAN_SSL_INSECURE=1 to turn it off for a machine that
really does sit behind an intercepting proxy - a deliberate, visible choice
rather than the silent default. DHAN_SSL_STRICT is still accepted and is now
redundant.
"""
from __future__ import annotations

import os

_TRUE = ("1", "true", "yes")


def insecure_requested() -> bool:
    """True only when the operator has explicitly asked to skip verification."""
    if os.environ.get("DHAN_SSL_STRICT", "").strip().lower() in _TRUE:
        return False
    return os.environ.get("DHAN_SSL_INSECURE", "").strip().lower() in _TRUE


def verify_arg():
    """Value for requests' `verify=`: the certifi bundle, or False on opt-out."""
    if insecure_requested():
        return False
    try:
        import certifi
        return certifi.where()
    except ImportError:          # pragma: no cover - requests depends on certifi
        return True
