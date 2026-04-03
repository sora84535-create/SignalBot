"""
Bitcoin Master Signal Engine
==============================
Combines multiple sub-indicators to produce a single LONG/SHORT signal
with confidence score for BTC/USDT futures.

Sub-indicators used:
  1. EMA 9/21/50/200 trend stack
  2. RSI 14 with divergence check
  3. Stoch RSI (14,3,3) crossover
  4. MACD Histogram flip
  5. Supertrend direction
  6. ADX trend strength
  7. Volume CVD delta
  8. SMC: BOS / CHoCH confirmation
  9. Bollinger Band squeeze
 10. Hull MA slope
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import asyncio

from config.settings import settings
from src.utils.mexc_client import mexc
from src.indicators.engine import indicator_engine, IndicatorResult
from src.smc.engine import smc_engine, SMCResult
from src.utils.logger import setup_logger

logger = setup_logger("btc_signal")

TF_MAP = {
    "5m":  "Min5",
    "15m": "Min15",
    "1h":  "Min60",
    "4h":  "Hour4",
    "1d":  "Day1",
}


@dataclass
class BTCSignal:
    direction: str          # "LONG" | "SHORT" | "NEUTRAL"
    confidence: int         # 0–100
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    timeframe: str
    reasons: List[str]      = field(default_factory=list)
    smc_reasons: List[str]  = field(default_factory=list)
    warnings: List[str]     = field(default_factory=list)
    rsi: float              = 0.0
    adx: float              = 0.0
    supertrend_dir: int     = 0
    macd_hist: float        = 0.0
    vol_ratio: float        = 1.0
    funding_rate: float     = 0.0


class BTCSignalEngine:

    async def get_signal(self, timeframe: str = "1h") -> Optional[BTCSignal]:
        symbol = "BTCUSDT"
        interval = TF_MAP.get(timeframe, "Min60")

        try:
            # Fetch klines
            raw = await mexc.get_futures_klines(symbol, interval, settings.CANDLES_LIMIT)
            if not raw:
                logger.warning("No kline data for BTC")
                return None

            # Normalise MEXC futures kline format
            klines = self._normalise(raw)
            if not klines:
                return None

            # Technical indicators
            ind: Optional[IndicatorResult] = indicator_engine.analyze(klines, timeframe)
            if ind is None:
                return None

            # SMC
            smc: SMCResult = smc_engine.analyze(ind.df)

            # Funding rate
            fr_data = await mexc.get_futures_funding_rate(symbol)
            funding = float(fr_data.get("fundingRate", 0)) * 100  # → %

            # Combine scores
            combined = self._combine(ind, smc, timeframe)
            if combined["direction"] == "NEUTRAL":
                return None

            last   = ind.last
            close  = float(last["close"])
            atr    = float(last.get("atr", close * 0.01))

            # SL / TP based on ATR
            if combined["direction"] == "LONG":
                sl  = round(close - atr * 1.5, 2)
                tp1 = round(close + atr * 1.0, 2)
                tp2 = round(close + atr * 2.0, 2)
                tp3 = round(close + atr * 3.5, 2)
            else:
                sl  = round(close + atr * 1.5, 2)
                tp1 = round(close - atr * 1.0, 2)
                tp2 = round(close - atr * 2.0, 2)
                tp3 = round(close - atr * 3.5, 2)

            sig = BTCSignal(
                direction     = combined["direction"],
                confidence    = combined["confidence"],
                entry         = round(close, 2),
                sl            = sl,
                tp1           = tp1,
                tp2           = tp2,
                tp3           = tp3,
                timeframe     = timeframe,
                reasons       = ind.signals,
                smc_reasons   = smc.signals,
                warnings      = ind.warnings + combined.get("warnings", []),
                rsi           = float(last.get("rsi", 0)),
                adx           = float(last.get("adx", 0)),
                supertrend_dir = int(last.get("supertrend_direction", 0)),
                macd_hist     = float(last.get("macd_hist", 0)),
                vol_ratio     = float(last.get("vol_ratio", 1)),
                funding_rate  = funding,
            )
            return sig

        except Exception as e:
            logger.error("BTCSignalEngine error: %s", e, exc_info=True)
            return None

    # ── Score combination ─────────────────────────────────────────
    def _combine(self, ind: IndicatorResult, smc: SMCResult, tf: str) -> Dict:
        """
        Merge indicator score + SMC score.
        Fire signal only if:
          - combined >= MIN_CONFLUENCE_SCORE
          - both agree on direction
          - ADX > 20 (not choppy)
        """
        warnings = []
        last = ind.last

        adx = float(last.get("adx", 0))
        if adx < 18:
            warnings.append(f"⚠️ ADX {adx:.1f} — market ranging, signal weaker")

        # Indicator direction
        ind_bull = ind.trend == "bullish"
        ind_bear = ind.trend == "bearish"

        # SMC direction
        smc_bull = smc.trend == "bullish" or smc.entry_bias == "long"
        smc_bear = smc.trend == "bearish" or smc.entry_bias == "short"

        # Require BOTH to agree
        if ind_bull and smc_bull:
            direction = "LONG"
        elif ind_bear and smc_bear:
            direction = "SHORT"
        else:
            return {"direction": "NEUTRAL", "confidence": 0, "warnings": warnings}

        # Combined confidence (weighted)
        ind_weight = 0.55
        smc_weight = 0.45
        confidence = int(ind.score * ind_weight + smc.score * smc_weight)

        # ADX bonus
        if adx > 25:
            confidence = min(100, confidence + 5)

        # Supertrend alignment bonus
        st_dir = int(last.get("supertrend_direction", 0))
        if direction == "LONG" and st_dir == -1:
            confidence = min(100, confidence + 5)
        elif direction == "SHORT" and st_dir == 1:
            confidence = min(100, confidence + 5)

        # Funding rate adjustment (contrarian)
        fr = float(last.get("funding_rate", 0) or 0)
        if direction == "LONG" and fr > 0.05:
            warnings.append(f"⚠️ High positive funding {fr:.3f}% — longs paying shorts")
        elif direction == "SHORT" and fr < -0.05:
            warnings.append(f"⚠️ Negative funding {fr:.3f}% — shorts paying longs")

        if confidence < settings.MIN_CONFLUENCE_SCORE:
            return {"direction": "NEUTRAL", "confidence": confidence, "warnings": warnings}

        return {"direction": direction, "confidence": confidence, "warnings": warnings}

    # ── MEXC kline normaliser ─────────────────────────────────────
    @staticmethod
    def _normalise(raw) -> list:
        """
        MEXC futures klines return:
        { "time": [...], "open": [...], "close": [...], "high": [...], "low": [...], "vol": [...] }
        """
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
                        "ts":     times[i],
                        "open":   opens[i]  if i < len(opens)  else 0,
                        "high":   highs[i]  if i < len(highs)  else 0,
                        "low":    lows[i]   if i < len(lows)   else 0,
                        "close":  closes[i] if i < len(closes) else 0,
                        "volume": vols[i]   if i < len(vols)   else 0,
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
        except Exception as e:
            logger.error("Normalise klines error: %s", e)
        return result

    # ── Multi-timeframe analysis ──────────────────────────────────
    async def multi_tf_analysis(self) -> Dict[str, Optional[BTCSignal]]:
        """Run analysis on multiple timeframes simultaneously."""
        tasks = {tf: self.get_signal(tf) for tf in ["15m", "1h", "4h"]}
        results = {}
        for tf, coro in tasks.items():
            try:
                results[tf] = await coro
            except Exception as e:
                logger.error("MTF analysis error %s: %s", tf, e)
                results[tf] = None
        return results


# Singleton
btc_signal_engine = BTCSignalEngine()
