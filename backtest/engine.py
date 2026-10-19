"""backtest/engine.py — a portfolio backtester with an Indian cost model.

WHAT IT SIMULATES
-----------------
One pot of capital, walked forward session by session:

  1. EXITS first, against the session's bar. A stop is gap-honest: if the bar
     OPENS through the stop the fill is the open, not the stop price (booking
     the stop level on a gap manufactures a fake edge). Otherwise a position
     exits at the close once it has been held `hold` sessions.
  2. ENTRIES second, from signals computed on the PREVIOUS session's close and
     filled at THIS session's open. A signal can never trade on the bar that
     produced it.
  3. SIZING: each trade commits `position_pct` of the account's current value
     (capital + realised P&L), at most `max_positions` open at once, and only
     with cash that is actually there.
  4. COSTS: every round trip is charged the itemised NSE/SEBI schedule from
     core/charges.py (brokerage, STT, exchange fee, SEBI fee, stamp duty, GST)
     plus slippage on both fills.

WHAT IT REFUSES TO DO
---------------------
* Evaluate the final holdout segment twice (`HoldoutLedger`).
* Report a walk-forward result without the number of parameter sets tried,
  which is what a multiple-testing correction needs.

The signal function is pluggable; the default is core.base_breakout.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from core import charges as ch
from core.base_breakout import BreakoutRules, evaluate

Panels = Dict[str, pd.DataFrame]          # open/high/low/close/volume, dates x symbols


@dataclass(frozen=True)
class CostModel:
    segment: str = "delivery"              # core.charges segment for the round trip
    slippage_bps: float = 5.0              # per fill, applied against you

    def fill(self, price: float, side: str) -> float:
        s = self.slippage_bps / 1e4
        return price * (1 + s) if side == "buy" else price * (1 - s)

    def charges(self, buy_price: float, sell_price: float, qty: int) -> float:
        return ch.round_trip(buy_price, sell_price, qty, self.segment).total


@dataclass(frozen=True)
class BacktestConfig:
    capital: float = 1_000_000.0
    position_pct: float = 0.10             # of current capital, per trade
    max_positions: int = 5
    hold: int = 20                         # sessions before the time exit
    rules: BreakoutRules = field(default_factory=BreakoutRules)

    def fingerprint(self) -> str:
        d = asdict(self)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    benchmark: pd.Series                   # equal-weight buy-and-hold of the tradeable universe
    summary: Dict[str, float]
    open_positions: List[Dict] = field(default_factory=list)   # still held at the end
    cash: float = 0.0


def _signals(panels: Panels, rules: BreakoutRules) -> Dict[str, pd.DataFrame]:
    return evaluate(panels["open"], panels["high"], panels["low"], panels["close"],
                    panels["volume"], rules)


def run(panels: Panels, config: BacktestConfig = BacktestConfig(),
        costs: CostModel = CostModel(), start=None, end=None,
        signal_fn: Optional[Callable[[Panels, BreakoutRules], Dict[str, pd.DataFrame]]] = None
        ) -> BacktestResult:
    """Walk the book forward over [start, end]. Signals are computed on the
    FULL panel (they only ever look backwards) and then traded inside the
    window, so a window's first trades can use history from before it."""
    ev = (signal_fn or _signals)(panels, config.rules)
    o, h, l, c = (panels[k] for k in ("open", "high", "low", "close"))
    dates = c.index
    lo = 0 if start is None else int(dates.searchsorted(pd.Timestamp(start)))
    hi = len(dates) if end is None else int(dates.searchsorted(pd.Timestamp(end), side="right"))
    sig, stop_px, rank = ev["signal"], ev["stop"], ev["vol_ratio"]

    cash, realised = config.capital, 0.0
    open_pos: List[Dict] = []
    trades: List[Dict] = []
    curve = []

    for i in range(max(lo, 1), hi):
        d = dates[i]
        # 1. exits
        still = []
        for p in open_pos:
            sym = p["symbol"]
            op, lw, cl = o.iat[i, p["col"]], l.iat[i, p["col"]], c.iat[i, p["col"]]
            exit_px, how = None, None
            if np.isfinite(op) and op <= p["stop"]:
                exit_px, how = op, "gap_stop"
            elif np.isfinite(lw) and lw <= p["stop"]:
                exit_px, how = p["stop"], "stop"
            elif i - p["entry_i"] >= config.hold and np.isfinite(cl):
                exit_px, how = cl, "time"
            if exit_px is None:
                still.append(p)
                continue
            sell = costs.fill(float(exit_px), "sell")
            fees = costs.charges(p["buy"], sell, p["qty"])
            gross = (sell - p["buy"]) * p["qty"]
            net = gross - fees
            cash += sell * p["qty"] - fees
            realised += net
            trades.append({**{k: p[k] for k in ("symbol", "signal_date", "entry_date", "qty", "buy", "stop")},
                           "exit_date": d, "sell": sell, "exit": how, "gross": gross,
                           "charges": fees, "net": net, "held": i - p["entry_i"]})
        open_pos = still

        # 2. entries: yesterday's signals, today's open
        held = {p["symbol"] for p in open_pos}
        prev = sig.iloc[i - 1]
        cands = [s for s in prev.index[prev.fillna(False).values] if s not in held]
        cands.sort(key=lambda s: -float(rank.iloc[i - 1][s]) if pd.notna(rank.iloc[i - 1][s]) else 0.0)
        for sym in cands:
            if len(open_pos) >= config.max_positions:
                break
            j = c.columns.get_loc(sym)
            op = o.iat[i, j]
            st = stop_px.iat[i - 1, j]
            if not (np.isfinite(op) and np.isfinite(st)) or op <= st:
                continue                     # opened at/below its own stop: not entered
            allot = config.position_pct * (config.capital + realised)
            buy = costs.fill(float(op), "buy")
            qty = int(min(allot, cash) // buy)
            if qty < 1:
                continue
            cash -= buy * qty
            open_pos.append({"symbol": sym, "col": j, "signal_date": dates[i - 1], "entry_date": d,
                             "entry_i": i, "qty": qty, "buy": buy, "stop": float(st)})

        mtm = sum(p["qty"] * (c.iat[i, p["col"]] if np.isfinite(c.iat[i, p["col"]]) else p["buy"])
                  for p in open_pos)
        curve.append((d, cash + mtm))

    equity = pd.Series(dict(curve), name="equity", dtype=float)
    tr = pd.DataFrame(trades)

    # benchmark: equal-weight buy-and-hold of the names tradeable on each day
    rets = (c / c.shift(1) - 1).where(ev["tradeable"].shift(1, fill_value=False))
    bench_r = rets.mean(axis=1).fillna(0.0).loc[equity.index]
    benchmark = config.capital * (1 + bench_r).cumprod()

    days = len(equity)
    years = days / 252.0 if days else float("nan")
    end_eq = float(equity.iloc[-1]) if days else config.capital
    summary = {
        "sessions": days, "trades": int(len(tr)),
        "open_at_end": len(open_pos),
        "total_return": end_eq / config.capital - 1,
        "benchmark_return": float(benchmark.iloc[-1] / config.capital - 1) if days else 0.0,
        "charges_paid": float(tr["charges"].sum()) if len(tr) else 0.0,
        "cagr": (end_eq / config.capital) ** (1 / years) - 1 if days and years > 0 else float("nan"),
        "max_drawdown": float((equity / equity.cummax() - 1).min()) if days else 0.0,
        "realised": realised,
    }
    held = [{k: p[k] for k in ("symbol", "signal_date", "entry_date", "qty", "buy", "stop")}
            for p in open_pos]
    return BacktestResult(tr, equity, benchmark, summary, held, cash)


# ── walk-forward ─────────────────────────────────────────────────────────────

def _score(res: BacktestResult) -> float:
    """What the walk-forward selects on: return in excess of buy-and-hold."""
    return res.summary["total_return"] - res.summary["benchmark_return"]


def walk_forward(panels: Panels, grid: Iterable[BacktestConfig], folds: int = 4,
                 holdout_frac: float = 0.2, costs: CostModel = CostModel()) -> Dict:
    """Expanding-window walk-forward over the NON-holdout part of the sample.

    For fold k (k >= 1) every configuration in `grid` is scored on folds 0..k-1
    and the best one is then run, unseen, on fold k. The final `holdout_frac`
    of sessions is never touched here - see HoldoutLedger.

    Returns the out-of-sample results AND `trials` (how many configurations
    were tried), because a best-of-N result means nothing without N.
    """
    grid = list(grid)
    dates = panels["close"].index
    cut = int(len(dates) * (1 - holdout_frac))
    edges = np.linspace(0, cut, folds + 1, dtype=int)
    oos = []
    for k in range(1, folds):
        tr_start, tr_end = dates[edges[0]], dates[edges[k] - 1]
        te_start, te_end = dates[edges[k]], dates[edges[k + 1] - 1]
        scored = [(_score(run(panels, cfg, costs, tr_start, tr_end)), n) for n, cfg in enumerate(grid)]
        best_score, best = max(scored)
        res = run(panels, grid[best], costs, te_start, te_end)
        oos.append({"fold": k, "train": (str(tr_start.date()), str(tr_end.date())),
                    "test": (str(te_start.date()), str(te_end.date())),
                    "chosen": best, "train_excess": best_score,
                    "oos_excess": _score(res), "oos_trades": res.summary["trades"]})
    return {"folds": oos, "trials": len(grid),
            "holdout_starts": str(dates[cut].date()) if cut < len(dates) else None}


# ── one-shot holdout ─────────────────────────────────────────────────────────

class HoldoutAlreadySpent(RuntimeError):
    pass


class HoldoutLedger:
    """Records every configuration evaluated on the holdout. A second look at
    the same holdout - with the same configuration or a different one - is
    refused: a holdout you can retry is just more training data."""

    def __init__(self, path: str):
        self.path = path

    def _spent(self) -> List[Dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def evaluate(self, panels: Panels, config: BacktestConfig, holdout_frac: float = 0.2,
                 costs: CostModel = CostModel(), label: str = "") -> BacktestResult:
        dates = panels["close"].index
        start = dates[int(len(dates) * (1 - holdout_frac))]
        key = f"{dates[0].date()}|{start.date()}|{dates[-1].date()}"
        prior = [r for r in self._spent() if r["holdout"] == key]
        if prior:
            raise HoldoutAlreadySpent(
                f"holdout {key} was already evaluated ({prior[0]['config']}, {prior[0]['label']!r}); "
                "re-testing on it would turn it into training data")
        res = run(panels, config, costs, start, dates[-1])
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"holdout": key, "config": config.fingerprint(),
                                 "label": label}) + "\n")
        return res
