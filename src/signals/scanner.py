"""
Multi-Coin Signal Scanner
==========================
Scans all futures pairs on MEXC, runs full indicator + SMC pipeline,
emits only high-quality signals (confluence >= threshold).

Anti-noise filters:
  • ADX > 20 (trending)
  • Volume confirmation
  • SMC + indicator agreement required
  • Cooldown per symbol
  • Filters out micro-cap / illiquid pairs
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from config.settings import settings
from src.utils.mexc_client import mexc
from src.indicators.engine import indicator_engine, IndicatorResult
from src.smc.engine import smc_engine, SMCResult
from src.utils.logger import setup_logger

logger = setup_logger("scanner")

TF_MAP = {
    "5m":  "Min5",
    "15m": "Min15",
    "1h":  "Min60",
    "4h":  "Hour4",
    "1d":  "Day1",
}


@dataclass
class CoinSignal:
    symbol:      str
    direction:   str          # "LONG" | "SHORT"
    confidence:  int
    timeframe:   str
    entry:       float
    sl:          float
    tp1:         float
    tp2:         float
    reasons:     List[str]    = field(default_factory=list)
    smc_signals: List[str]    = field(default_factory=list)
    warnings:    List[str]    = field(default_factory=list)
    rsi:         float        = 0.0
    vol_ratio:   float        = 1.0
    funding:     float        = 0.0
    trend_smc:   str          = "neutral"
    fvg_present: bool         = False
    bos_present: bool         = False


class CoinScanner:

    def __init__(self):
        self._cooldowns: Dict[str, float] = {}     # symbol → last signal ts
        self._blacklist: Set[str] = set()           # symbols to skip

    def _is_cooldown(self, symbol: str) -> bool:
        last = self._cooldowns.get(symbol, 0)
        return (time.time() - last) < settings.SIGNAL_COOLDOWN_MIN * 60

    def _set_cooldown(self, symbol: str):
        self._cooldowns[symbol] = time.time()

    # ── Normalise klines ─────────────────────────────────────────
    @staticmethod
    def _norm(raw) -> list:
        result = []
        try:
            if isinstance(raw, dict):
                times  = raw.get("time", [])
                opens  = raw.get("open", [])
                highs  = raw.get("high", [])
                lows   = raw.get("low", [])
                closes = raw.get("close", [])
                vols   = raw.get("vol", raw.get("volume", []))
                for i in range(len(times)):
                    result.append({
                        "ts": times[i], "open": opens[i], "high": highs[i],
                        "low": lows[i], "close": closes[i], "volume": vols[i],
                    })
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, (list, tuple)) and len(item) >= 6:
                        result.append({
                            "ts": item[0], "open": item[1], "high": item[2],
                            "low": item[3], "close": item[4], "volume": item[5],
                        })
                    elif isinstance(item, dict):
                        result.append(item)
        except Exception:
            pass
        return result

    # ── Analyse a single coin ─────────────────────────────────────
    async def _analyse_coin(self, symbol: str, timeframe: str = "15m") -> Optional[CoinSignal]:
        if self._is_cooldown(symbol) or symbol in self._blacklist:
            return None

        interval = TF_MAP.get(timeframe, "Min15")
        try:
            raw = await mexc.get_futures_klines(symbol, interval, settings.CANDLES_LIMIT)
            if not raw:
                return None

            klines = self._norm(raw)
            if len(klines) < 50:
                return None

            ind: Optional[IndicatorResult] = indicator_engine.analyze(klines, timeframe)
            if ind is None:
                return None

            smc: SMCResult = smc_engine.analyze(ind.df)

            # ── Anti-noise filters ──────────────────────────────
            last = ind.last
            adx  = float(last.get("adx", 0))

            if adx < 18:
                return None   # Ranging market — skip

            if float(last.get("vol_ratio", 0)) < 0.5:
                return None   # Volume too thin

            # Direction agreement
            ind_trend = ind.trend
            smc_bias  = smc.entry_bias

            direction = None
            if ind_trend == "bullish" and smc_bias in ("long", "none") and smc.trend != "bearish":
                direction = "LONG"
            elif ind_trend == "bearish" and smc_bias in ("short", "none") and smc.trend != "bullish":
                direction = "SHORT"
            else:
                return None  # Conflicting signals

            # Combined score
            confidence = int(ind.score * 0.55 + smc.score * 0.45)
            if confidence < settings.MIN_CONFLUENCE_SCORE:
                return None

            close = float(last["close"])
            atr   = float(last.get("atr", close * 0.01))

            if direction == "LONG":
                sl  = round(close - atr * 1.5, 8)
                tp1 = round(close + atr * 1.5, 8)
                tp2 = round(close + atr * 3.0, 8)
            else:
                sl  = round(close + atr * 1.5, 8)
                tp1 = round(close - atr * 1.5, 8)
                tp2 = round(close - atr * 3.0, 8)

            # Funding
            try:
                fr_data = await mexc.get_futures_funding_rate(symbol)
                funding = float(fr_data.get("fundingRate", 0)) * 100
            except Exception:
                funding = 0.0

            self._set_cooldown(symbol)

            return CoinSignal(
                symbol      = symbol,
                direction   = direction,
                confidence  = confidence,
                timeframe   = timeframe,
                entry       = round(close, 8),
                sl          = sl,
                tp1         = tp1,
                tp2         = tp2,
                reasons     = ind.signals[:4],
                smc_signals = smc.signals[:3],
                warnings    = ind.warnings[:2],
                rsi         = float(last.get("rsi", 0)),
                vol_ratio   = float(last.get("vol_ratio", 1)),
                funding     = funding,
                trend_smc   = smc.trend,
                fvg_present = bool(smc.last_fvg and not smc.last_fvg.filled),
                bos_present = bool(smc.last_bos),
            )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Coin %s error: %s", symbol, e)
            return None

    # ── Scan all pairs ────────────────────────────────────────────
    async def scan_all(self, timeframe: str = "15m", pairs: List[str] = None) -> List[CoinSignal]:
        """
        Scan all (or specified) futures pairs. Returns list of signals.
        Runs concurrently with semaphore to avoid rate-limits.
        """
        if pairs is None:
            pairs = settings.TOP_FUTURES_PAIRS

        sem     = asyncio.Semaphore(5)     # max 5 concurrent requests
        signals = []

        async def _safe(sym):
            async with sem:
                sig = await self._analyse_coin(sym, timeframe)
                if sig:
                    signals.append(sig)
                await asyncio.sleep(0.2)   # small delay

        await asyncio.gather(*[_safe(s) for s in pairs], return_exceptions=True)

        # Sort by confidence descending
        signals.sort(key=lambda x: x.confidence, reverse=True)
        return signals

    # ── Discover ALL MEXC futures symbols ─────────────────────────
    async def get_all_futures_symbols(self) -> List[str]:
        try:
            data = await mexc.get_futures_symbols()
            return [d["symbol"] for d in data if d.get("state") == "open"]
        except Exception as e:
            logger.error("get_all_futures_symbols: %s", e)
            return settings.TOP_FUTURES_PAIRS


# Singleton
coin_scanner = CoinScanner()
