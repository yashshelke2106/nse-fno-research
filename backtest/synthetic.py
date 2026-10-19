"""backtest/synthetic.py — geometric-Brownian-motion OHLCV panels.

GBM has no edge by construction: tomorrow's return is independent of every
pattern in the past. That makes it the right fixture for a backtester. It can
run end to end with no broker account and no market data, and a correct
engine run on it must NOT report a significant edge over buy-and-hold. If it
does, the engine is leaking the future or mis-charging costs.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def gbm_panels(n_symbols: int = 60, n_days: int = 750, mu: float = 0.10,
               sigma: float = 0.32, seed: int = 0, start: str = "2020-01-01",
               volume_mean: float = 600_000) -> Dict[str, pd.DataFrame]:
    """OHLCV panels (rows = sessions, columns = symbols) from daily GBM.

    `mu`/`sigma` are annualised. Opens gap from the prior close with a slice of
    the day's variance, highs/lows bracket open and close, and volume is
    lognormal so some sessions clear a volume-confirmation threshold.
    """
    rng = np.random.default_rng(seed)
    dt = 1 / 252.0
    idx = pd.bdate_range(start, periods=n_days)
    cols = [f"SYN{i:03d}" for i in range(n_symbols)]
    s0 = rng.uniform(150, 1500, n_symbols)
    shocks = rng.standard_normal((n_days, n_symbols))
    log_r = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * shocks
    close = s0 * np.exp(np.cumsum(log_r, axis=0))
    prev = np.vstack([s0, close[:-1]])
    # the overnight gap takes ~30% of the day's variance, the session the rest
    gap = np.exp(0.3 * sigma * np.sqrt(dt) * rng.standard_normal((n_days, n_symbols)))
    open_ = prev * gap
    span = np.abs(rng.normal(0, sigma * np.sqrt(dt), (n_days, n_symbols))) * close
    high = np.maximum(open_, close) + span * rng.uniform(0.2, 1.0, (n_days, n_symbols))
    low = np.minimum(open_, close) - span * rng.uniform(0.2, 1.0, (n_days, n_symbols))
    low = np.maximum(low, 0.01)
    volume = rng.lognormal(np.log(volume_mean), 0.45, (n_days, n_symbols)).round()
    mk = lambda a: pd.DataFrame(a, index=idx, columns=cols)
    return {"open": mk(open_), "high": mk(high), "low": mk(low), "close": mk(close),
            "volume": mk(volume)}
