"""core/base_breakout.py — a base-breakout detector for NSE equities.

THE PATTERN
-----------
    a LEADER in an uptrend  ->  consolidates in a BASE near its highs
        ->  the right side TIGHTENS into a short-term pivot (handle / flag /
            line of lower highs)  ->  price CLOSES through the pivot on
            above-average VOLUME

Every rule below is the textbook form of that shape (Minervini's trend
template; O'Neil's base depth and volume rules). The thresholds are fixed
constants, chosen before any test, so a backtest of them is not a search.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
* No "tightness / VCP contraction" threshold. It is the most fit-prone part of
  the pattern (small changes to the cut-off move individual charts in or out),
  so it is reported as a feature, never used as a gate.
* No intraday logic: this works on daily bars.
* IPO bases need a different rule - there is no 52-week history to define a
  leader - so `min_history` excludes them.

ONE IMPLEMENTATION FOR RESEARCH AND LIVE
----------------------------------------
Everything works on wide panels (rows = sessions, columns = symbols) and uses
only data up to and including the signal bar. The research test and the daily
scanner call the same `evaluate()`, so a backtest and a live scan cannot drift
apart.

PAPER. Nothing here places an order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BreakoutRules:
    # ── the base ──────────────────────────────────────────────────────────
    base_len: int = 40            # 8 weeks of bars before the signal
    depth_min: float = 0.08       # shallower is a drift, not a base
    depth_max: float = 0.35       # deeper is a broken chart (O'Neil: <33%)
    pivot_len: int = 5            # the short-term pivot: handle / flag top
    pivot_near_rim: float = 0.90  # pivot must sit in the top 10% of the base
    # ── the trend template (leader) ───────────────────────────────────────
    lo_252_mult: float = 1.30     # >=30% above the 52-week low
    hi_252_mult: float = 0.75     # within 25% of the 52-week high
    # ── the trigger ───────────────────────────────────────────────────────
    vol_mult: float = 1.25        # breakout volume vs 50-day average
    vol_len: int = 50
    close_loc_min: float = 0.50   # close in the upper half of the day's range
    # ── tradeability ──────────────────────────────────────────────────────
    min_turnover: float = 5e7     # Rs 5 Cr/day median: Rs 1L is 0.2% of it
    min_price: float = 20.0
    min_history: int = 250        # IPO bases are a different rule
    # ── bookkeeping ───────────────────────────────────────────────────────
    dedupe_bars: int = 10         # one signal per base, not one per day
    max_stop_pct: float = 0.08    # stop under the pivot low, capped at 8%

    def to_dict(self) -> Dict:
        return asdict(self)


def _ema(x: pd.DataFrame, span: int) -> pd.DataFrame:
    return x.ewm(span=span, adjust=False, min_periods=span).mean()


def evaluate(o: pd.DataFrame, h: pd.DataFrame, l: pd.DataFrame,
             c: pd.DataFrame, v: pd.DataFrame,
             rules: BreakoutRules = BreakoutRules()) -> Dict[str, pd.DataFrame]:
    """Every condition of the pattern, as panels. Point-in-time throughout:
    each value at row t uses rows <= t only.

    Returns the boolean `signal` panel plus the panels a trader needs to act
    on it (`pivot`, `rim`, `stop`, `depth`, `vol_ratio`) and the component
    conditions, so a near-miss can be explained rather than just dropped.
    """
    r = rules
    from core.corporate_actions import flag_panel

    # a split or bonus inside the window fakes both depth and a breakout
    ca = flag_panel(c)
    ca_recent = ca.astype(float).rolling(r.base_len + 1, min_periods=1).max() > 0

    hist = c.notna().cumsum()
    turnover = (c * v).rolling(20, min_periods=15).median()
    tradeable = ((turnover >= r.min_turnover) & (c >= r.min_price)
                 & (hist >= r.min_history) & ~ca_recent)

    # 1. a leader: Minervini's trend template, reduced to what daily bars say
    ema21, ema50 = _ema(c, 21), _ema(c, 50)
    lo252 = l.rolling(252, min_periods=200).min()
    hi252 = h.rolling(252, min_periods=200).max()
    trend = ((c > ema50) & (ema21 > ema50) & (ema50 > ema50.shift(10))
             & (c >= r.lo_252_mult * lo252) & (c >= r.hi_252_mult * hi252))

    # 2. a base: the 8 weeks BEFORE today, 8-35% deep
    rim = h.shift(1).rolling(r.base_len, min_periods=r.base_len).max()
    base_low = l.shift(1).rolling(r.base_len, min_periods=r.base_len).min()
    depth = 1.0 - base_low / rim
    base = (depth >= r.depth_min) & (depth <= r.depth_max)

    # 3. the pivot: the short-term high the right side tightened into
    pivot = h.shift(1).rolling(r.pivot_len, min_periods=r.pivot_len).max()
    near_rim = pivot >= r.pivot_near_rim * rim

    # 4. the trigger: a fresh CLOSE through the pivot, on volume, closing strong
    vol_avg = v.shift(1).rolling(r.vol_len, min_periods=int(r.vol_len * 0.8)).mean()
    vol_ratio = v / vol_avg
    rng = (h - l)
    close_loc = ((c - l) / rng.where(rng > 0)).fillna(1.0)   # locked bar = at high
    fresh = (c > pivot) & ~(c.shift(1) > pivot.shift(1))
    trigger = (fresh & (vol_ratio >= r.vol_mult) & (close_loc >= r.close_loc_min))

    raw = (tradeable & trend & base & near_rim & trigger).fillna(False)
    # one signal per base: drop a signal if another fired in the prior N bars
    prior = raw.astype(float).shift(1).rolling(r.dedupe_bars, min_periods=1).max() > 0
    signal = raw & ~prior

    # the stop sits under the pivot's own low, never more than 8% away
    pivot_low = l.rolling(r.pivot_len + 1, min_periods=r.pivot_len + 1).min()
    stop = np.maximum(pivot_low, c * (1.0 - r.max_stop_pct))

    # contraction is REPORTED, never gated (see module docstring)
    right_range = (h.shift(1).rolling(10, min_periods=10).max()
                   - l.shift(1).rolling(10, min_periods=10).min()) / rim
    contraction = right_range / depth

    return {"signal": signal, "pivot": pivot, "rim": rim, "stop": stop,
            "depth": depth, "vol_ratio": vol_ratio, "close_loc": close_loc,
            "contraction": contraction, "turnover": turnover,
            "tradeable": tradeable, "trend": trend, "base": base,
            "near_rim": near_rim, "trigger": trigger}


def setups_on(panels: Dict[str, pd.DataFrame], ev: Dict[str, pd.DataFrame],
              when: Optional[pd.Timestamp] = None,
              watch_within: float = 0.05) -> Dict[str, List[Dict]]:
    """What a trader acts on for one session.

    `breakouts`: the signal fired on this bar's close.
    `watchlist`: everything except the trigger holds, and the close is within
    `watch_within` of the pivot - a setup that has not broken out yet.
    """
    c = panels["close"]
    when = when if when is not None else c.index[-1]
    row = {k: v.loc[when] for k, v in ev.items()}
    close = c.loc[when]

    def card(sym: str, kind: str) -> Dict:
        entry = float(close[sym])
        stop = float(row["stop"][sym])
        return {
            "symbol": sym, "kind": kind, "date": str(pd.Timestamp(when).date()),
            "close": round(entry, 2), "pivot": round(float(row["pivot"][sym]), 2),
            "rim": round(float(row["rim"][sym]), 2),
            "stop": round(stop, 2), "risk_pct": round(100 * (1 - stop / entry), 2),
            "depth_pct": round(100 * float(row["depth"][sym]), 1),
            "vol_ratio": round(float(row["vol_ratio"][sym]), 2),
            "contraction": round(float(row["contraction"][sym]), 2),
            "turnover_cr": round(float(row["turnover"][sym]) / 1e7, 1),
        }

    sig = row["signal"].fillna(False)
    breakouts = [card(s, "breakout") for s in sig.index[sig]]

    ready = (row["tradeable"] & row["trend"] & row["base"] & row["near_rim"]
             & ~sig).fillna(False)
    dist = (row["pivot"] / close - 1.0)
    near = ready & (dist >= 0) & (dist <= watch_within)
    watch = [card(s, "watch") for s in near.index[near.fillna(False)]]

    breakouts.sort(key=lambda x: -x["vol_ratio"])
    watch.sort(key=lambda x: (x["pivot"] / x["close"]))
    return {"breakouts": breakouts, "watchlist": watch}
