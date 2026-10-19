"""Live order placement is not part of the public version.

These pin it so a future edit cannot quietly bring it back.
"""
from __future__ import annotations

import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.api_dhan as api
import core.execution as ex


def test_the_flag_is_a_false_constant_not_configuration():
    assert api.LIVE_TRADING_ENABLED is False
    src = inspect.getsource(api)
    assert re.search(r"^LIVE_TRADING_ENABLED = False$", src, re.M)
    assert not re.search(r"LIVE_TRADING_ENABLED\s*=.*(getenv|environ|config)", src)


@pytest.mark.parametrize("method,args", [
    ("place_order", ("RELIANCE", "NSE_EQ", "BUY", 1)),
    ("modify_order", ("ORDER1",)),
    ("cancel_order", ("ORDER1",)),
])
def test_every_order_method_raises(method, args):
    with pytest.raises(api.LiveTradingDisabled):
        getattr(api.DhanAPI, method)(object(), *args)


def test_no_order_sending_request_remains_in_the_adapter():
    """Static check: no method sends PUT/DELETE, and no method that POSTs
    touches the /orders endpoint (only data endpoints - charts, quotes,
    option chains - are POSTed to)."""
    src = inspect.getsource(api)
    assert '_request("PUT"' not in src and '_request("DELETE"' not in src
    for name, fn in inspect.getmembers(api.DhanAPI, inspect.isfunction):
        body = inspect.getsource(fn)
        if '_request("POST"' in body:
            assert '"/orders' not in body, f"{name} POSTs to /orders"


def test_the_execution_layer_is_always_paper():
    assert ex._paper_mode() is True
