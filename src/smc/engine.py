"""
Smart Money Concepts (SMC / ICT) Engine
========================================
Detects:
  • Market Structure: BOS (Break of Structure), CHoCH (Change of Character)
  • FVG (Fair Value Gap / imbalance)
  • Order Blocks (OB) — bullish and bearish
  • Liquidity Sweeps (false breakouts)
  • POI zones (Points of Interest)
  • Multi-timeframe structure bias

All logic mirrors the approach seen in the charts:
  - BOS confirmed on body close only (no wicks)
  - CHoCH = first counter-structural BOS = reversal signal
  - FVG = 3-candle imbalance gap
  - OB = last opposing candle before displacement
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import settings
from src.utils.logger import setup_logger

logger = setup_logger("smc")


# ──────────────────────────────────────────────────────────────────
#  Data structures
# ──────────────────────────────────────────────────────────────────
@dataclass
class StructureLevel:
    idx: int
    price: float
    kind: str      # "high" | "low"
    is_external: bool

@dataclass
class BOS:
    idx: int
    level: float
    direction: str     # "bullish" | "bearish"
    is_choch: bool
    strength: float    # how far price broke through (ATR units)

@dataclass
class FVG:
    idx: int
    top: float
    bottom: float
    direction: str     # "bullish" | "bearish"
    filled: bool = False
    fill_pct: float = 0.0

@dataclass
class OrderBlock:
    idx: int
    top: float
    bottom: float
    direction: str     # "bullish" | "bearish"
    tested: bool = False
    broken: bool = False

@dataclass
class LiquiditySweep:
    idx: int
    level: float
    direction: str     # "buy_side" | "sell_side"
    reversal: bool = False

@dataclass
class SMCResult:
    structure_levels: List[StructureLevel] = field(default_factory=list)
    bos_list:         List[BOS]            = field(default_factory=list)
    fvg_list:         List[FVG]            = field(default_factory=list)
    ob_list:          List[OrderBlock]     = field(default_factory=list)
    sweeps:           List[LiquiditySweep] = field(default_factory=list)

    # Summary
    trend:       str = "neutral"   # "bullish" | "bearish" | "neutral"
    last_bos:    Optional[BOS]   = None
    last_fvg:    Optional[FVG]   = None
    last_ob:     Optional[OrderBlock] = None
    last_sweep:  Optional[LiquiditySweep] = None

    # Confluences
    entry_bias:  str = "none"     # "long" | "short" | "none"
    poi_zone:    Optional[Tuple[float, float]] = None   # (low, high)
    score:       int = 0          # 0-100
    signals:     List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
#  SMC Engine
# ──────────────────────────────────────────────────────────────────
class SMCEngine:

    # ── Pivot detection ───────────────────────────────────────────
    @staticmethod
    def _find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> List[StructureLevel]:
        """
        Finds swing highs and lows.
        Only external (significant) pivots are used for BOS.
        """
        pivots = []
        n = len(df)
        for i in range(left, n - right):
            hi = df["high"].iloc[i]
            lo = df["low"].iloc[i]

            is_swing_high = all(hi >= df["high"].iloc[i - j] for j in range(1, left + 1)) and \
                            all(hi >= df["high"].iloc[i + j] for j in range(1, right + 1))
            is_swing_low  = all(lo <= df["low"].iloc[i - j] for j in range(1, left + 1)) and \
                            all(lo <= df["low"].iloc[i + j] for j in range(1, right + 1))

            if is_swing_high:
                pivots.append(StructureLevel(i, hi, "high", True))
            if is_swing_low:
                pivots.append(StructureLevel(i, lo, "low", True))

        return sorted(pivots, key=lambda x: x.idx)

    # ── BOS / CHoCH detection ─────────────────────────────────────
    @staticmethod
    def _detect_structure(df: pd.DataFrame, pivots: List[StructureLevel], atr: float) -> List[BOS]:
        """
        BOS: body close beyond last external swing high/low.
        CHoCH: first BOS counter to current structure direction.
        """
        bos_events = []
        structure_trend = "neutral"

        highs = [p for p in pivots if p.kind == "high"]
        lows  = [p for p in pivots if p.kind == "low"]

        if len(highs) < 2 or len(lows) < 2:
            return bos_events

        # Use body close (not wicks) for confirmation
        close = df["close"]
        n     = len(df)

        # Track last external high and low
        last_high = highs[-2].price if len(highs) >= 2 else None
        last_low  = lows[-2].price  if len(lows) >= 2 else None

        for i in range(len(df) - 5, len(df)):
            if i < 0:
                continue
            c = close.iloc[i]

            # Bullish BOS: body close > last external high
            if last_high and c > last_high:
                is_choch = structure_trend == "bearish"
                strength = (c - last_high) / atr if atr > 0 else 0
                bos_events.append(BOS(i, last_high, "bullish", is_choch, strength))
                structure_trend = "bullish"
                # Update last_high
                for h in reversed(highs):
                    if h.idx < i:
                        last_high = h.price
                        break

            # Bearish BOS: body close < last external low
            elif last_low and c < last_low:
                is_choch = structure_trend == "bullish"
                strength = (last_low - c) / atr if atr > 0 else 0
                bos_events.append(BOS(i, last_low, "bearish", is_choch, strength))
                structure_trend = "bearish"
                for l in reversed(lows):
                    if l.idx < i:
                        last_low = l.price
                        break

        return bos_events

    # ── FVG detection ─────────────────────────────────────────────
    @staticmethod
    def _detect_fvg(df: pd.DataFrame) -> List[FVG]:
        """
        Bullish FVG:  low[i] > high[i-2]  (gap above — price likely returns)
        Bearish FVG:  high[i] < low[i-2]  (gap below)
        """
        fvgs = []
        min_size = settings.FVG_MIN_SIZE_PCT / 100

        for i in range(2, len(df)):
            low_i    = df["low"].iloc[i]
            high_i   = df["high"].iloc[i]
            high_im2 = df["high"].iloc[i - 2]
            low_im2  = df["low"].iloc[i - 2]
            mid      = df["close"].iloc[i - 1]

            # Bullish FVG
            if low_i > high_im2:
                gap_pct = (low_i - high_im2) / mid
                if gap_pct >= min_size:
                    # Check if filled by later candles
                    filled = False
                    for j in range(i + 1, len(df)):
                        if df["low"].iloc[j] <= high_im2:
                            filled = True
                            break
                    fvgs.append(FVG(i, low_i, high_im2, "bullish", filled))

            # Bearish FVG
            elif high_i < low_im2:
                gap_pct = (low_im2 - high_i) / mid
                if gap_pct >= min_size:
                    filled = False
                    for j in range(i + 1, len(df)):
                        if df["high"].iloc[j] >= low_im2:
                            filled = True
                            break
                    fvgs.append(FVG(i, low_im2, high_i, "bearish", filled))

        return fvgs

    # ── Order Block detection ─────────────────────────────────────
    @staticmethod
    def _detect_order_blocks(df: pd.DataFrame, bos_list: List[BOS]) -> List[OrderBlock]:
        """
        Order Block = last opposing candle BEFORE displacement (BOS).
        Bullish OB: last bearish candle before bullish BOS.
        Bearish OB: last bullish candle before bearish BOS.
        """
        obs = []
        for bos in bos_list:
            idx = bos.idx
            if bos.direction == "bullish":
                # Find last bearish candle before BOS
                for j in range(idx - 1, max(0, idx - settings.OB_LOOKBACK), -1):
                    if df["close"].iloc[j] < df["open"].iloc[j]:
                        top    = max(df["open"].iloc[j], df["close"].iloc[j])
                        bottom = min(df["open"].iloc[j], df["close"].iloc[j])
                        # Check if tested
                        tested = any(
                            df["low"].iloc[k] <= top and df["high"].iloc[k] >= bottom
                            for k in range(j + 1, min(j + 20, len(df)))
                        )
                        obs.append(OrderBlock(j, top, bottom, "bullish", tested))
                        break
            else:
                for j in range(idx - 1, max(0, idx - settings.OB_LOOKBACK), -1):
                    if df["close"].iloc[j] > df["open"].iloc[j]:
                        top    = max(df["open"].iloc[j], df["close"].iloc[j])
                        bottom = min(df["open"].iloc[j], df["close"].iloc[j])
                        tested = any(
                            df["high"].iloc[k] >= bottom and df["low"].iloc[k] <= top
                            for k in range(j + 1, min(j + 20, len(df)))
                        )
                        obs.append(OrderBlock(j, top, bottom, "bearish", tested))
                        break
        return obs

    # ── Liquidity sweep detection ─────────────────────────────────
    @staticmethod
    def _detect_sweeps(df: pd.DataFrame, pivots: List[StructureLevel]) -> List[LiquiditySweep]:
        """
        Sweep = price goes beyond a swing level (wick) but closes back.
        Indicates stop-hunt / liquidity grab before reversal.
        """
        sweeps = []
        lookback = 30
        if len(df) < lookback:
            return sweeps

        recent = df.iloc[-lookback:]
        swing_highs = [p.price for p in pivots if p.kind == "high"]
        swing_lows  = [p.price for p in pivots if p.kind == "low"]

        for i in range(2, len(recent) - 1):
            c  = recent.iloc[i]
            cn = recent.iloc[i + 1]

            # Buy-side sweep (sweep of highs, then reversal)
            for h in swing_highs[-5:]:
                if c["high"] > h and c["close"] < h:
                    reversal = cn["close"] < c["close"]
                    sweeps.append(LiquiditySweep(
                        len(df) - lookback + i, h, "buy_side", reversal
                    ))
                    break

            # Sell-side sweep (sweep of lows, then bounce)
            for l in swing_lows[-5:]:
                if c["low"] < l and c["close"] > l:
                    reversal = cn["close"] > c["close"]
                    sweeps.append(LiquiditySweep(
                        len(df) - lookback + i, l, "sell_side", reversal
                    ))
                    break

        return sweeps

    # ── POI zone from FVG + OB ────────────────────────────────────
    @staticmethod
    def _build_poi(fvgs: List[FVG], obs: List[OrderBlock], direction: str) -> Optional[Tuple[float, float]]:
        """Find the most recent relevant POI zone."""
        zones = []
        for fvg in reversed(fvgs):
            if fvg.direction == direction and not fvg.filled:
                zones.append((fvg.bottom, fvg.top))
        for ob in reversed(obs):
            if ob.direction == direction and not ob.broken:
                zones.append((ob.bottom, ob.top))
        return zones[0] if zones else None

    # ══════════════════════════════════════════════════════════════
    #  Full analysis
    # ══════════════════════════════════════════════════════════════
    def analyze(self, df: pd.DataFrame) -> SMCResult:
        result = SMCResult()

        if len(df) < 30:
            return result

        # ATR for strength calculation
        atr = df["atr"].iloc[-1] if "atr" in df.columns else (
            (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
        )

        # Pivots
        pivots = self._find_pivots(df)
        result.structure_levels = pivots

        # BOS / CHoCH
        bos_list = self._detect_structure(df, pivots, atr)
        result.bos_list  = bos_list
        result.last_bos  = bos_list[-1] if bos_list else None

        # FVG
        fvgs = self._detect_fvg(df)
        result.fvg_list = fvgs
        # Most recent unfilled FVG
        unfilled = [f for f in reversed(fvgs) if not f.filled]
        result.last_fvg = unfilled[0] if unfilled else (fvgs[-1] if fvgs else None)

        # Order Blocks
        obs = self._detect_order_blocks(df, bos_list)
        result.ob_list  = obs
        result.last_ob  = obs[-1] if obs else None

        # Sweeps
        sweeps = self._detect_sweeps(df, pivots)
        result.sweeps     = sweeps
        result.last_sweep = sweeps[-1] if sweeps else None

        # Determine trend from last few BOS
        recent_bos = [b for b in bos_list[-5:]]
        if recent_bos:
            bull_count = sum(1 for b in recent_bos if b.direction == "bullish")
            bear_count = len(recent_bos) - bull_count
            if bull_count > bear_count:
                result.trend = "bullish"
            elif bear_count > bull_count:
                result.trend = "bearish"

        # POI
        result.poi_zone = self._build_poi(fvgs, obs, result.trend)

        # Scoring
        self._score(result, df)
        return result

    def _score(self, res: SMCResult, df: pd.DataFrame):
        score   = 0
        signals = []
        last    = df.iloc[-1]
        close   = last["close"]

        # BOS scoring
        if res.last_bos:
            bos = res.last_bos
            if bos.is_choch:
                score += 25
                signals.append(
                    f"{'🔼' if bos.direction == 'bullish' else '🔽'} "
                    f"CHoCH {bos.direction.upper()} @ {bos.level:.4f} — reversal signal!"
                )
            else:
                score += 15
                signals.append(
                    f"{'📈' if bos.direction == 'bullish' else '📉'} "
                    f"BOS {bos.direction.upper()} @ {bos.level:.4f} — continuation"
                )

        # FVG scoring
        if res.last_fvg:
            fvg = res.last_fvg
            if not fvg.filled:
                score += 15
                mid = (fvg.top + fvg.bottom) / 2
                pct = abs(close - mid) / close * 100
                signals.append(
                    f"📊 Open FVG ({fvg.direction}) "
                    f"[{fvg.bottom:.4f}–{fvg.top:.4f}] "
                    f"{pct:.1f}% from current price"
                )
                # Price approaching FVG = strong signal
                if pct < 0.5:
                    score += 10
                    signals.append("⚡ Price AT FVG — high-probability entry zone!")

        # Order Block scoring
        if res.last_ob:
            ob = res.last_ob
            if not ob.broken:
                score += 12
                mid   = (ob.top + ob.bottom) / 2
                pct   = abs(close - mid) / close * 100
                if pct < 0.3:
                    score += 8
                    signals.append(
                        f"🏦 Price inside OB ({ob.direction}) "
                        f"[{ob.bottom:.4f}–{ob.top:.4f}] — premium entry!"
                    )

        # Liquidity sweep scoring
        if res.last_sweep:
            sw = res.last_sweep
            if sw.reversal:
                score += 15
                signals.append(
                    f"💧 Liquidity sweep {sw.direction.replace('_', ' ')} "
                    f"@ {sw.level:.4f} with reversal confirmed"
                )
            else:
                score += 8
                signals.append(
                    f"💧 Liquidity sweep {sw.direction.replace('_', ' ')} "
                    f"@ {sw.level:.4f} (reversal pending)"
                )

        # POI zone
        if res.poi_zone:
            low, high = res.poi_zone
            if low <= close <= high:
                score += 20
                signals.append(
                    f"🎯 Price INSIDE POI zone [{low:.4f}–{high:.4f}] — prime entry!"
                )

        # Trend alignment bonus
        if res.trend != "neutral":
            score = min(100, score + 5)

        res.score   = min(100, score)
        res.signals = signals

        # Entry bias
        if res.trend == "bullish" and res.last_bos and not (res.last_bos.is_choch and res.last_bos.direction == "bearish"):
            res.entry_bias = "long"
        elif res.trend == "bearish" and res.last_bos and not (res.last_bos.is_choch and res.last_bos.direction == "bullish"):
            res.entry_bias = "short"
        else:
            res.entry_bias = "none"


# Singleton
smc_engine = SMCEngine()
