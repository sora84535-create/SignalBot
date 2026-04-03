"""
Configuration — all settings from environment variables
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    # ── Telegram ──────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str   = os.getenv("TELEGRAM_CHAT_ID", "")
    ADMIN_IDS: List[int]    = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ])

    # ── MEXC API ──────────────────────────────────────────────────
    MEXC_API_KEY:    str = os.getenv("MEXC_API_KEY", "")
    MEXC_API_SECRET: str = os.getenv("MEXC_API_SECRET", "")
    MEXC_BASE_URL:   str = "https://contract.mexc.com"
    MEXC_SPOT_URL:   str = "https://api.mexc.com"

    # ── Groq AI ───────────────────────────────────────────────────
    GROQ_API_KEY:   str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL:     str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ── News APIs ─────────────────────────────────────────────────
    NEWS_API_KEY:       str = os.getenv("NEWS_API_KEY", "")
    CRYPTOPANIC_KEY:    str = os.getenv("CRYPTOPANIC_KEY", "")

    # ── Signal settings ───────────────────────────────────────────
    # Timeframes to analyze (minutes)
    TIMEFRAMES: List[str] = field(default_factory=lambda: ["5m", "15m", "1h", "4h", "1d"])

    # Minimum confluence score (0–100) to fire a signal
    MIN_CONFLUENCE_SCORE: int   = int(os.getenv("MIN_CONFLUENCE_SCORE", "65"))
    SIGNAL_COOLDOWN_MIN:  int   = int(os.getenv("SIGNAL_COOLDOWN_MIN", "15"))   # minutes

    # How many candles to load for analysis
    CANDLES_LIMIT: int = 200

    # ── Spread settings ───────────────────────────────────────────
    MIN_SPREAD_PCT:    float = float(os.getenv("MIN_SPREAD_PCT", "10.0"))        # %
    SPREAD_SCAN_SEC:   int   = int(os.getenv("SPREAD_SCAN_SEC", "60"))           # every N seconds
    DEX_PROVIDERS: List[str] = field(default_factory=lambda: [
        "dexscreener", "coingecko"
    ])

    # ── SMC / ICT ─────────────────────────────────────────────────
    FVG_MIN_SIZE_PCT:    float = 0.15   # % imbalance to count as FVG
    OB_LOOKBACK:         int   = 50     # candles for order block search
    STRUCTURE_LOOKBACK:  int   = 100

    # ── Indicators ────────────────────────────────────────────────
    EMA_FAST:       int = 9
    EMA_SLOW:       int = 21
    EMA_200:        int = 200
    RSI_PERIOD:     int = 14
    STOCH_K:        int = 14
    STOCH_D:        int = 3
    STOCH_SMOOTH:   int = 3
    MACD_FAST:      int = 8
    MACD_SLOW:      int = 17
    MACD_SIGNAL:    int = 9
    ATR_PERIOD:     int = 14
    ADX_PERIOD:     int = 14
    SUPERTREND_ATR: int = 10
    SUPERTREND_FAC: float = 3.0
    BB_PERIOD:      int = 20
    BB_STD:         float = 2.0
    VOLUME_SMA:     int = 20
    VOLUME_SPIKE:   float = 2.0         # × SMA to count as spike

    # ── Bitcoin Indicator thresholds ──────────────────────────────
    BTC_RSI_OB:        float = 70.0
    BTC_RSI_OS:        float = 30.0
    BTC_STRONG_SIGNAL: int   = 4        # how many sub-indicators agree

    # ── Scheduler intervals ───────────────────────────────────────
    SIGNAL_SCAN_INTERVAL:  int = 300    # 5 min
    NEWS_SCAN_INTERVAL:    int = 600    # 10 min
    MARKET_UPDATE_INTERVAL: int = 3600  # 1 hour

    # ── Top pairs to monitor ──────────────────────────────────────
    TOP_FUTURES_PAIRS: List[str] = field(default_factory=lambda: [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT",
        "DOGE_USDT", "ADA_USDT", "AVAX_USDT", "MATIC_USDT", "DOT_USDT",
        "LINK_USDT", "UNI_USDT", "ATOM_USDT", "LTC_USDT", "NEAR_USDT",
        "FIL_USDT", "APT_USDT", "ARB_USDT", "OP_USDT", "INJ_USDT",
        "DUSK_USDT", "SUI_USDT", "TIA_USDT", "MANTA_USDT", "JUP_USDT",
    ])

    # ── Risk defaults ─────────────────────────────────────────────
    DEFAULT_LEVERAGE:   int   = 10
    DEFAULT_RISK_PCT:   float = 1.0
    DEFAULT_RR:         float = 2.0     # risk:reward

    # ── Misc ──────────────────────────────────────────────────────
    DEBUG:    bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    TIMEZONE:  str = os.getenv("TIMEZONE", "UTC")


settings = Settings()
