"""End-to-end backtester tests on synthetic GBM prices.

No broker account, no market data, no network: anyone can run

    pytest -q

GBM has no edge by construction, which makes it a test of the ENGINE, not of a
strategy. These tests check that the backtester trades, charges and accounts
correctly - and that on a random walk it does not report an edge it could only
have found by looking ahead.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import (BacktestConfig, CostModel, HoldoutAlreadySpent, HoldoutLedger,
                             run, walk_forward)
from backtest.synthetic import gbm_panels
from core.base_breakout import BreakoutRules


@pytest.fixture(scope="module")
def panels():
    return gbm_panels(n_symbols=60, n_days=750, seed=0)


@pytest.fixture(scope="module")
def result(panels):
    return run(panels)


# ── it runs, end to end ───────────────────────────────────────────────────────

def test_the_backtest_runs_end_to_end_and_trades(result, panels):
    assert len(result.trades) >= 30
    assert len(result.equity) == len(panels["close"]) - 1
    assert np.isfinite(result.equity).all()
    assert set(result.trades["exit"]) <= {"time", "stop", "gap_stop"}


# ── the money adds up ─────────────────────────────────────────────────────────

def test_cash_plus_open_positions_equals_capital_plus_pnl(result, panels):
    """The ledger identity, on the final session."""
    cfg = BacktestConfig()
    last_close = panels["close"].iloc[-1]
    mtm = sum(p["qty"] * float(last_close[p["symbol"]]) for p in result.open_positions)
    cost_open = sum(p["qty"] * p["buy"] for p in result.open_positions)
    assert result.equity.iloc[-1] == pytest.approx(result.cash + mtm, abs=0.01)
    assert result.cash + cost_open == pytest.approx(cfg.capital + result.trades["net"].sum(), abs=0.01)


def test_every_trade_is_charged_and_net_is_gross_minus_charges(result):
    t = result.trades
    assert (t["charges"] > 0).all()
    assert np.allclose(t["net"], t["gross"] - t["charges"], atol=0.01)


def test_charges_follow_the_contract_note_schedule(result):
    """Delivery: STT on both legs and stamp duty on the buy leg dominate, so
    the round trip costs roughly 0.2-0.25% of turnover - never zero, never 2%."""
    t = result.trades
    pct = t["charges"] / (t["buy"] * t["qty"])
    assert pct.between(0.0015, 0.004).all(), pct.describe()


def test_slippage_is_paid_on_both_fills(panels, result):
    t = result.trades.iloc[0]
    open_px = panels["open"].loc[t["entry_date"], t["symbol"]]
    assert t["buy"] == pytest.approx(open_px * (1 + CostModel().slippage_bps / 1e4))


# ── no lookahead ──────────────────────────────────────────────────────────────

def test_a_signal_never_trades_on_its_own_bar(result, panels):
    t = result.trades
    assert (t["entry_date"] > t["signal_date"]).all()
    nxt = {d: panels["close"].index[i + 1] for i, d in enumerate(panels["close"].index[:-1])}
    assert all(nxt[s] == e for s, e in zip(t["signal_date"], t["entry_date"]))


def test_changing_the_future_does_not_change_the_past(panels):
    """Rescale every bar after a cutoff (one factor per symbol-day, applied to
    open/high/low/close alike so each bar stays a valid bar). Trades already
    closed by the cutoff must be identical - otherwise something read ahead."""
    base = run(panels)
    cut = panels["close"].index[450]
    after = panels["close"].index > cut
    rng = np.random.default_rng(99)
    f = rng.uniform(0.7, 1.3, panels["close"].loc[after].shape)
    scrambled = {k: v.copy() for k, v in panels.items()}
    for k in ("open", "high", "low", "close"):
        scrambled[k].loc[after] = panels[k].loc[after].values * f
    scrambled["volume"].loc[after] = panels["volume"].loc[after].values * rng.uniform(0.5, 2.0, f.shape)
    other = run(scrambled)
    done = lambda r: r.trades[r.trades["exit_date"] <= cut].reset_index(drop=True)
    assert len(done(base)) > 10
    pd.testing.assert_frame_equal(done(base), done(other))


# ── the sizing rule ───────────────────────────────────────────────────────────

def test_never_more_than_five_positions_at_once(result, panels):
    t = result.trades
    for d in panels["close"].index[::5]:
        live = ((t["entry_date"] <= d) & (t["exit_date"] > d)).sum()
        live += sum(1 for p in result.open_positions if p["entry_date"] <= d)
        assert live <= BacktestConfig().max_positions


def test_each_trade_commits_at_most_ten_percent_of_current_capital(result):
    cfg = BacktestConfig()
    t = result.trades.sort_values("entry_date")
    for _, row in t.iterrows():
        realised = t.loc[t["exit_date"] <= row["entry_date"], "net"].sum()
        assert row["buy"] * row["qty"] <= cfg.position_pct * (cfg.capital + realised) + 1e-6


# ── a random walk has no edge, and the engine must not invent one ────────────

def test_no_significant_edge_over_buy_and_hold_on_a_random_walk():
    """Per-trade excess over the equal-weight universe, pooled over 5 seeds.
    Anything near a significant positive t on GBM means the engine is leaking."""
    excess = []
    for seed in range(5):
        P = gbm_panels(seed=seed)
        r = run(P)
        bench = r.benchmark
        for _, t in r.trades.iterrows():
            ret = (t["sell"] * t["qty"] - t["charges"]) / (t["buy"] * t["qty"]) - 1
            b = bench.loc[t["exit_date"]] / bench.loc[t["entry_date"]] - 1
            excess.append(ret - b)
    e = np.asarray(excess)
    t_stat = e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))
    assert len(e) > 200
    assert t_stat < 2.0, f"engine found an 'edge' in a random walk: t={t_stat:.2f}"


# ── research guardrails ───────────────────────────────────────────────────────

def test_walk_forward_reports_out_of_sample_results_and_the_trial_count(panels):
    grid = [BacktestConfig(rules=BreakoutRules(vol_mult=v, depth_max=d))
            for v in (1.25, 1.5) for d in (0.25, 0.35)]
    wf = walk_forward(panels, grid, folds=4, holdout_frac=0.2)
    assert wf["trials"] == 4                    # best-of-4 is not a result without the 4
    assert len(wf["folds"]) == 3
    hold_start = pd.Timestamp(wf["holdout_starts"])
    for f in wf["folds"]:
        assert pd.Timestamp(f["test"][1]) < hold_start       # holdout never touched
        assert pd.Timestamp(f["train"][1]) < pd.Timestamp(f["test"][0])


def test_the_holdout_can_be_looked_at_exactly_once(panels, tmp_path):
    ledger = HoldoutLedger(str(tmp_path / "holdout_ledger.jsonl"))
    first = ledger.evaluate(panels, BacktestConfig(), label="final")
    assert first.summary["sessions"] > 0
    with pytest.raises(HoldoutAlreadySpent):
        ledger.evaluate(panels, BacktestConfig(), label="again")
    with pytest.raises(HoldoutAlreadySpent):          # a DIFFERENT config is refused too
        ledger.evaluate(panels, BacktestConfig(hold=10), label="tweaked")
