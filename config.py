"""config.py — runtime configuration for the public version.

Credentials are NOT here: they come from the environment / a git-ignored
`.env` via core/secrets.py (see .env.example). Nothing in this file is secret.

Safety: PAPER_TRADE is True and live order placement is not included in this
repository at all (core/api_dhan.py: LIVE_TRADING_ENABLED, LiveTradingDisabled).
"""
import os

# ── credentials: read from the environment, never committed ──────────────
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")
NSE_API_KEY = os.getenv("NSE_API_KEY", "")
NSE_API_SECRET = os.getenv("NSE_API_SECRET", "")

# ── safety ────────────────────────────────────────────────────────────────
PAPER_TRADE = True               # the execution layer is paper-only in this version
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "0") == "1"
INSTRUMENT_MODE = os.getenv("INSTRUMENT_MODE", "futures").lower()
ENFORCE_LIQUIDITY_TIER = True

# ── market hours (IST) ────────────────────────────────────────────────────
MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30

# ── cost model overrides ──────────────────────────────────────────────────
# core/charges.py ships the default NSE/SEBI schedule. Rates are revised by the
# exchanges and brokerage differs per broker: override per segment here, e.g.
#   CHARGE_RATES = {"delivery": {..., "stt_buy": 0.001}}
CHARGE_RATES = None

# ── strategy / risk / execution parameters ────────────────────────────────
# Lot sizes change every few months; the code prefers the live scrip master
# (core/scrip_master.py) and treats this table only as a fallback.

RISK_CONFIG = {   'max_risk_per_trade': 0.012,
    'sl_pct': 0.05,
    'atr_sl_multiplier': 1.2,
    'min_sl_pct': 0.01,
    'max_sl_pct': 0.025,
    'max_daily_loss': 0.04,
    'max_consecutive_losses': 2,
    'max_trades_per_day': 3,
    'min_risk_reward': 1.5,
    'max_per_sector': 2,
    'max_drawdown_halt': 0.08,
    'max_concurrent_positions': 5,
    'max_per_expiry': 3}

EXECUTION_CONFIG = {   'order_type': 'LIMIT',
    'slippage_tolerance': 0.001,
    'retry_attempts': 3,
    'retry_delay': 2}

SIGNAL_CONFIG = {   'atr_period': 14,
    'atr_multiplier': 1.5,
    'volume_multiplier': 1.5,
    'range_period': 20,
    'ema_fast': 9,
    'ema_slow': 21,
    'rsi_period': 14,
    'rsi_oversold': 38,
    'rsi_overbought': 70,
    'supertrend_period': 10,
    'supertrend_multiplier': 3.0,
    'nr7_lookback': 7,
    'min_votes': 5,
    'min_vote_lead': 3,
    'vol_surge_threshold': 1.5,
    'rsi_extreme_oversold': 30,
    'rsi_extreme_overbought': 75,
    'min_strength': 55,
    'rsi_long_momentum_min': 62,
    'rsi_short_floor': 30,
    'disable_shorts': False,
    'rr_ratio': 4.0,
    'block_after_hour': 12,
    'skip_first_minutes': 15,
    'best_hours': [10, 11],
    'blacklisted_patterns': ['range_squeeze_down'],
    'max_volume_ratio': 3.0}

STRIKE_CONFIG = {'itm_delta': 0.3, 'otm_delta': 0.15, 'spot_otm_multiplier': 0.02}

VOLUME_EXIT_CONFIG = {   'entry_min_vol_ratio': 2.0,
    'exit_vol_threshold': 0.5,
    'profit_required_pct': 0.015,
    'vol_surge_lookback': 20}

PAPER_FILL_COST_BPS = {'equity': 5, 'futures': 5, 'option': 50}

NSE_LOT_SIZES = {   'NIFTY': 75,
    'BANKNIFTY': 35,
    'FINNIFTY': 65,
    'MIDCPNIFTY': 120,
    'RELIANCE': 250,
    'TCS': 150,
    'INFY': 300,
    'HDFCBANK': 550,
    'ICICIBANK': 700,
    'SBIN': 1500,
    'BHARTIARTL': 500,
    'KOTAKBANK': 400,
    'BAJFINANCE': 125,
    'HINDUNILVR': 300,
    'ITC': 1600,
    'LT': 150,
    'AXISBANK': 625,
    'MARUTI': 100,
    'ASIANPAINT': 200,
    'WIPRO': 1000,
    'HCLTECH': 350,
    'TITAN': 175,
    'SUNPHARMA': 350,
    'TATAMOTORS': 1425,
    'ADANIENT': 250,
    'NTPC': 2250,
    'POWERGRID': 2700,
    'ULTRACEMCO': 100,
    'JSWSTEEL': 675,
    'ONGC': 1925,
    'COALINDIA': 2100,
    'BPCL': 1800,
    'HEROMOTOCO': 150,
    'EICHERMOT': 50,
    'TATASTEEL': 1425,
    'HINDALCO': 700,
    'GRASIM': 175,
    'CIPLA': 650,
    'DRREDDY': 125,
    'DEEPAKNT': 200,
    'BAJAJ-AUTO': 75,
    'FORCEMOT': 150,
    'KPIT': 400,
    'KPITTECH': 400,
    'BOSCH': 50,
    'MOTHERSON': 5000,
    'BHEL': 3200,
    'BEL': 3500,
    'HAL': 150,
    'NALCO': 7200,
    'VEDANTA': 2000,
    'VEDL': 2000,
    'ADANIGREEN': 350,
    'TATAPOWER': 3375,
    'WAAREE': 50,
    'CHOLAFIN': 1000,
    'MUTHOOTFIN': 400,
    'MOTILALOFS': 280,
    'ANGELONE': 300,
    'ICICISEC': 350,
    'SAMMAAN': 5000,
    'SAMMAANCAP': 5000}
