"""The base-breakout detector (core/base_breakout.py) - the properties that
make a backtest of it mean anything.

No network: synthetic panels only.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_breakout import BreakoutRules, evaluate, setups_on


def _base_then_breakout(n_advance=260, n_base=40, seed=3, vol_spike=3.0):
    """One stock: a long advance (a leader), an 8-week base ~15% deep near
    the highs, then a breakout bar on heavy volume. Plus a flat filler stock so
    the panel has a cross-section."""
    rng = np.random.default_rng(seed)
    adv = np.linspace(100, 200, n_advance) * (1 + rng.normal(0, 0.003, n_advance))
    base = 190 + 10 * np.sin(np.linspace(0, 3 * np.pi, n_base)) * np.linspace(1, 0.4, n_base)
    close = np.r_[adv, base, [215.0]]
    n = len(close)
    idx = pd.bdate_range("2023-01-02", periods=n)
    hi = close * 1.01
    lo = close * 0.99
    op = close * 0.998
    vol = np.full(n, 1_000_000.0)
    vol[-1] = vol_spike * 1_000_000.0
    lo[-1], hi[-1] = 204.0, 216.0               # close in the upper half
    mk = lambda x, f: pd.DataFrame({"LEAD": x, "FLAT": np.full(n, f)}, index=idx)
    return {"open": mk(op, 100.0), "high": mk(hi, 100.5), "low": mk(lo, 99.5),
            "close": mk(close, 100.0), "volume": mk(vol, 1_000_000.0)}


def _ev(P, rules=BreakoutRules()):
    return evaluate(P["open"], P["high"], P["low"], P["close"], P["volume"], rules)


def test_the_textbook_breakout_fires_on_its_own_bar():
    P = _base_then_breakout()
    ev = _ev(P)
    last = P["close"].index[-1]
    assert bool(ev["signal"].loc[last, "LEAD"])
    assert not bool(ev["signal"].loc[last, "FLAT"])       # no trend, no base


def test_no_lookahead_a_signal_does_not_change_when_the_future_is_removed():
    """The property a backtest stands on: the value at bar t must be computable
    from bars <= t. Truncating the panel after t must not change bar t."""
    P = _base_then_breakout()
    full = _ev(P)
    for cut in (5, 20, 60):
        part = _ev({k: v.iloc[:-cut] for k, v in P.items()})
        # every panel the scanner prints, not just the (mostly False) signal
        for name in ("signal", "pivot", "rim", "stop", "depth", "vol_ratio",
                     "trend", "base", "tradeable"):
            a, b = part[name], full[name].loc[part[name].index]
            pd.testing.assert_frame_equal(a, b, check_names=False,
                                          obj=f"{name} with the last {cut} bars removed")


def test_light_volume_is_not_a_breakout():
    P = _base_then_breakout(vol_spike=1.0)
    ev = _ev(P)
    assert not bool(ev["signal"].iloc[-1]["LEAD"])
    assert not bool(ev["trigger"].iloc[-1]["LEAD"])


def test_an_ipo_without_a_year_of_history_is_excluded():
    """A recent listing has no 52-week history to define a leader, so it is
    excluded rather than silently scored."""
    P = _base_then_breakout()
    short = {k: v.iloc[-120:] for k, v in P.items()}
    ev = _ev(short)
    assert not ev["signal"]["LEAD"].any()
    assert not bool(ev["tradeable"].iloc[-1]["LEAD"])


def test_illiquid_names_are_not_tradeable():
    P = _base_then_breakout()
    P["volume"] = P["volume"] / 1000.0          # ~Rs 20 lakh/day
    ev = _ev(P)
    assert not bool(ev["tradeable"].iloc[-1]["LEAD"])
    assert not ev["signal"]["LEAD"].any()


def test_a_split_inside_the_base_cannot_fake_a_breakout():
    """A 1:2 split halves the price; unmasked, the base would read 50% deep and
    the next recovery as a breakout. The corporate-action mask must kill it."""
    P = _base_then_breakout()
    k = len(P["close"]) - 20
    for f in ("open", "high", "low", "close"):
        P[f].iloc[k:, 0] = P[f].iloc[k:, 0] / 2.0
    ev = _ev(P)
    assert not ev["signal"]["LEAD"].iloc[k:].any()


def test_the_stop_is_never_more_than_eight_percent_away():
    P = _base_then_breakout()
    ev = _ev(P)
    c = P["close"].iloc[-1]["LEAD"]
    assert ev["stop"].iloc[-1]["LEAD"] >= c * 0.92 - 1e-9
    assert ev["stop"].iloc[-1]["LEAD"] < c


def test_one_signal_per_base_not_one_per_day():
    P = _base_then_breakout()
    # make the two bars after the breakout also close at new highs on volume
    for i, px in ((1, 218.0), (2, 221.0)):
        row = P["close"].index[-1] + pd.offsets.BDay(i)
        for f, val in (("open", px - 1), ("high", px + 1), ("low", px - 3), ("close", px)):
            P[f].loc[row] = [val, 100.0]
        P["volume"].loc[row] = [4_000_000.0, 1_000_000.0]
    ev = _ev(P)
    assert int(ev["signal"]["LEAD"].iloc[-3:].sum()) == 1


def test_setups_on_reports_the_levels_a_trader_needs():
    P = _base_then_breakout()
    ev = _ev(P)
    out = setups_on(P, ev)
    assert [b["symbol"] for b in out["breakouts"]] == ["LEAD"]
    b = out["breakouts"][0]
    for k in ("close", "pivot", "rim", "stop", "risk_pct", "depth_pct", "vol_ratio"):
        assert k in b
    assert b["close"] > b["pivot"]
    assert 0 < b["risk_pct"] <= 8.0
