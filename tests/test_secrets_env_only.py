"""Credentials come from the environment and are never written anywhere."""
from __future__ import annotations

import base64
import inspect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.secrets as sec


def _jwt(exp: float) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc({'exp': int(exp)})}.sig"


def test_values_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", "TESTCLIENT")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "eyJ.test.token")
    assert sec.get_client_id() == "TESTCLIENT"
    assert sec.get_access_token() == "eyJ.test.token"


def test_missing_credentials_are_none_not_an_error(monkeypatch):
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(sec, "ENV_FILE", os.path.join(os.path.dirname(__file__), "no.env"))
    assert sec.get_access_token() is None
    assert sec.token_health().valid is False


def test_the_module_has_no_write_path():
    src = inspect.getsource(sec)
    assert "open(" in src and ', "w"' not in src and "'w'" not in src
    assert "keyring" not in src.split('"""', 2)[-1]   # no OS keyring in the code


def test_token_health_reads_the_expiry():
    assert sec.token_health(_jwt(time.time() + 3600 * 12)).valid is True
    expired = sec.token_health(_jwt(time.time() - 3600))
    assert expired.valid is False and "EXPIRED" in expired.message
