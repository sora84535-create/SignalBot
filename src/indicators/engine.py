"""
Technical Indicators Engine
All calculations are pure numpy/pandas — no TA-Lib dependency required.
Covers: EMA, RSI, Stoch RSI, MACD, ATR, ADX, Bollinger Bands,
        Supertrend, Volume analysis, OBV, CVD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import math

import numpy as np
import pandas as pd

from config.settings import settings
from src.utils.logger import setup_logger

logger = setup_logger("indicators")


# ──────────────────────────────────────────────────────────────────
#  Data class for a fully-decorated OHLCV dataframe
# ──────────────────────────────────────────────────────────────────
@dataclass
class IndicatorResult:
    df: pd.DataFrame                    # enriched OHLCV
    last: pd.Series                     # last (most recent) row
    trend: str = "neutral"              # "bullish" | "bearish" | "neutral"
    score: int = 0                      # 0-100 confluence
    signals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
#  Low-level helpers
# ──────────────────────────────────────────────────────────────────
def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (used by RSI, ATR)."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


# ──────────────────────────────────────────────────────────────────
#  Main indicator engine
# ──────────────────────────────────────────────────────────────────
class IndicatorEngine:

    # ── Build DataFrame from raw kline data ───────────────────────
    @staticmethod
    def build_df(raw: list) -> pd.DataFrame:
        """
        Accepts lists of [ts, open, high, low, close, volume]
        or dicts with those keys.
        Returns a clean pd.DataFrame.
        """
        if not raw:
            return pd.DataFrame()

        if isinstance(raw[0], (list, tuple)):
            df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        elif isinstance(raw[0], dict):
            df = pd.DataFrame(raw)
            rename = {}
            for col in ["open", "high", "low", "close", "volume"]:
                for key in [col, col.upper(), col.capitalize()]:
                    if key in df.columns:
                        rename[key] = col
                        break
            df.rename(columns=rename, inplace=True)
        else:
            return pd.DataFrame()

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["open", "high", "low", "close"], inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    # ── EMA ───────────────────────────────────────────────────────
    @staticmethod
    def add_ema(df: pd.DataFrame) -> pd.DataFrame:
        df["ema9"]  = _ema(df["close"], settings.EMA_FAST)
        df["ema21"] = _ema(df["close"], settings.EMA_SLOW)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], settings.EMA_200)
        return df

    # ── RSI ───────────────────────────────────────────────────────
    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
        period = period or settings.RSI_PERIOD
        delta = df["close"].diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_gain = _rma(gain, period)
        avg_loss = _rma(loss, period)
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    # ── Stochastic RSI ────────────────────────────────────────────
    @staticmethod
    def add_stoch_rsi(df: pd.DataFrame) -> pd.DataFrame:
        if "rsi" not in df.columns:
            IndicatorEngine.add_rsi(df)
        k_period = settings.STOCH_K
        d_period = settings.STOCH_D
        smooth   = settings.STOCH_SMOOTH

        rsi_min = df["rsi"].rolling(k_period).min()
        rsi_max = df["rsi"].rolling(k_period).max()
        stoch   = (df["rsi"] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
        k       = stoch.rolling(smooth).mean() * 100
        d       = k.rolling(d_period).mean()
        df["stoch_k"] = k
        df["stoch_d"] = d
        return df

    # ── MACD (Raschke 8/17/9) ─────────────────────────────────────
    @staticmethod
    def add_macd(df: pd.DataFrame) -> pd.DataFrame:
        fast   = _ema(df["close"], settings.MACD_FAST)
        slow   = _ema(df["close"], settings.MACD_SLOW)
        macd   = fast - slow
        signal = _ema(macd, settings.MACD_SIGNAL)
        hist   = macd - signal
        df["macd"]        = macd
        df["macd_signal"] = signal
        df["macd_hist"]   = hist
        return df

    # ── ATR ───────────────────────────────────────────────────────
    @staticmethod
    def add_atr(df: pd.DataFrame) -> pd.DataFrame:
        tr = _true_range(df["high"], df["low"], df["close"])
        df["atr"] = _rma(tr, settings.ATR_PERIOD)
        return df

    # ── ADX ───────────────────────────────────────────────────────
    @staticmethod
    def add_adx(df: pd.DataFrame) -> pd.DataFrame:
        period = settings.ADX_PERIOD
        tr     = _true_range(df["high"], df["low"], df["close"])
        up     = df["high"].diff()
        down   = -df["low"].diff()
        plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)

        atr    = _rma(tr, period)
        plus_  = _rma(pd.Series(plus_dm,  index=df.index), period) / atr * 100
        minus_ = _rma(pd.Series(minus_dm, index=df.index), period) / atr * 100
        dx     = (plus_ - minus_).abs() / (plus_ + minus_).replace(0, np.nan) * 100
        df["adx"]      = _rma(dx, period)
        df["plus_di"]  = plus_
        df["minus_di"] = minus_
        return df

    # ── Bollinger Bands ───────────────────────────────────────────
    @staticmethod
    def add_bollinger(df: pd.DataFrame) -> pd.DataFrame:
        mid = df["close"].rolling(settings.BB_PERIOD).mean()
        std = df["close"].rolling(settings.BB_PERIOD).std()
        df["bb_upper"] = mid + settings.BB_STD * std
        df["bb_mid"]   = mid
        df["bb_lower"] = mid - settings.BB_STD * std
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / mid
        df["bb_pct_b"] = (df["close"] - df["bb_lower"]) / (
            df["bb_upper"] - df["bb_lower"]
        ).replace(0, np.nan)
        return df

    # ── Supertrend ────────────────────────────────────────────────
    @staticmethod
    def add_supertrend(df: pd.DataFrame) -> pd.DataFrame:
        if "atr" not in df.columns:
            IndicatorEngine.add_atr(df)

        factor = settings.SUPERTREND_FAC
        atr    = df["atr"]
        hl2    = (df["high"] + df["low"]) / 2

        upper_band = hl2 + factor * atr
        lower_band = hl2 - factor * atr

        final_upper = upper_band.copy()
        final_lower = lower_band.copy()
        supertrend  = pd.Series(index=df.index, dtype=float)
        direction   = pd.Series(index=df.index, dtype=int)   # 1=up, -1=down

        close = df["close"]

        for i in range(1, len(df)):
            # Upper band
            if upper_band.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1]:
                final_upper.iloc[i] = upper_band.iloc[i]
            else:
                final_upper.iloc[i] = final_upper.iloc[i - 1]

            # Lower band
            if lower_band.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1]:
                final_lower.iloc[i] = lower_band.iloc[i]
            else:
                final_lower.iloc[i] = final_lower.iloc[i - 1]

            # Direction
            if supertrend.iloc[i - 1] == final_upper.iloc[i - 1]:
                direction.iloc[i] = -1 if close.iloc[i] > final_upper.iloc[i] else 1
            else:
                direction.iloc[i] = 1 if close.iloc[i] < final_lower.iloc[i] else -1

            supertrend.iloc[i] = final_lower.iloc[i] if direction.iloc[i] == -1 else final_upper.iloc[i]

        df["supertrend"]           = supertrend
        df["supertrend_direction"] = direction
        return df

    # ── Volume analysis ───────────────────────────────────────────
    @staticmethod
    def add_volume(df: pd.DataFrame) -> pd.DataFrame:
        sma = settings.VOLUME_SMA
        df["vol_sma"]   = df["volume"].rolling(sma).mean()
        df["vol_ratio"] = df["volume"] / df["vol_sma"].replace(0, np.nan)
        df["vol_spike"] = df["vol_ratio"] >= settings.VOLUME_SPIKE

        # OBV
        obv = [0.0]
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i - 1]:
                obv.append(obv[-1] + df["volume"].iloc[i])
            elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
                obv.append(obv[-1] - df["volume"].iloc[i])
            else:
                obv.append(obv[-1])
        df["obv"] = obv

        # Cumulative Volume Delta (approximation)
        body    = df["close"] - df["open"]
        buy_vol = np.where(body >= 0, df["volume"], df["volume"] * (df["high"] - df["open"]) / (df["high"] - df["low"] + 1e-8))
        sell_vol = df["volume"] - buy_vol
        delta   = buy_vol - sell_vol
        df["cvd"] = pd.Series(delta, index=df.index).cumsum()
        df["candle_delta"] = delta
        return df

    # ── Hull MA (noise-filtered trend) ────────────────────────────
    @staticmethod
    def add_hull(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        half  = _ema(df["close"], period // 2)
        full  = _ema(df["close"], period)
        raw   = 2 * half - full
        df["hull"] = _ema(raw, int(math.sqrt(period)))
        return df

    # ══════════════════════════════════════════════════════════════
    #  Full analysis pipeline
    # ══════════════════════════════════════════════════════════════
    def analyze(self, raw: list, timeframe: str = "15m") -> Optional[IndicatorResult]:
        df = self.build_df(raw)
        if len(df) < 50:
            logger.debug("Not enough candles: %d", len(df))
            return None

        # Add all indicators
        self.add_ema(df)
        self.add_rsi(df)
        self.add_stoch_rsi(df)
        self.add_macd(df)
        self.add_atr(df)
        self.add_adx(df)
        self.add_bollinger(df)
        self.add_supertrend(df)
        self.add_volume(df)
        self.add_hull(df)

        result = IndicatorResult(df=df, last=df.iloc[-1])
        self._score(result, timeframe)
        return result

    # ── Scoring / confluence logic ────────────────────────────────
    def _score(self, res: IndicatorResult, timeframe: str):
        last = res.last
        df   = res.df

        score     = 0
        bull_pts  = 0
        bear_pts  = 0
        signals   = []
        warnings  = []

        # ── 1. EMA structure ──────────────────────────────────────
        if last["ema9"] > last["ema21"] > last["ema50"]:
            bull_pts += 10
            signals.append("EMA9>21>50 📈 bullish stack")
        elif last["ema9"] < last["ema21"] < last["ema50"]:
            bear_pts += 10
            signals.append("EMA9<21<50 📉 bearish stack")

        # EMA200 bias
        if last["close"] > last["ema200"]:
            bull_pts += 8
        else:
            bear_pts += 8

        # ── 2. RSI ────────────────────────────────────────────────
        rsi = last["rsi"]
        if 50 < rsi < 70:
            bull_pts += 8
            signals.append(f"RSI {rsi:.1f} — bullish territory")
        elif 30 < rsi < 50:
            bear_pts += 8
            signals.append(f"RSI {rsi:.1f} — bearish territory")
        elif rsi >= 70:
            warnings.append(f"RSI {rsi:.1f} — overbought ⚠️")
            bear_pts += 3
        elif rsi <= 30:
            warnings.append(f"RSI {rsi:.1f} — oversold ⚠️")
            bull_pts += 3

        # RSI divergence (last 5 candles)
        if len(df) >= 5:
            prev5 = df.iloc[-6:-1]
            if (df.iloc[-1]["close"] > prev5["close"].max() and
                    df.iloc[-1]["rsi"] < prev5["rsi"].max()):
                warnings.append("Bearish RSI divergence ⚠️")
                bear_pts += 5
            elif (df.iloc[-1]["close"] < prev5["close"].min() and
                    df.iloc[-1]["rsi"] > prev5["rsi"].min()):
                signals.append("Bullish RSI divergence 🔄")
                bull_pts += 5

        # ── 3. Stoch RSI ──────────────────────────────────────────
        k, d = last["stoch_k"], last["stoch_d"]
        prev_k = df.iloc[-2]["stoch_k"] if len(df) > 2 else k
        prev_d = df.iloc[-2]["stoch_d"] if len(df) > 2 else d

        if prev_k <= prev_d and k > d and k < 20:
            bull_pts += 12
            signals.append(f"Stoch RSI oversold crossover 🟢 K={k:.1f}")
        elif prev_k >= prev_d and k < d and k > 80:
            bear_pts += 12
            signals.append(f"Stoch RSI overbought crossover 🔴 K={k:.1f}")
        elif k > d and k < 50:
            bull_pts += 5
        elif k < d and k > 50:
            bear_pts += 5

        # ── 4. MACD ───────────────────────────────────────────────
        hist  = last["macd_hist"]
        prev_hist = df.iloc[-2]["macd_hist"] if len(df) > 2 else 0

        if hist > 0 and prev_hist <= 0:
            bull_pts += 12
            signals.append("MACD histogram bullish crossover 📊")
        elif hist < 0 and prev_hist >= 0:
            bear_pts += 12
            signals.append("MACD histogram bearish crossover 📊")
        elif hist > 0 and hist > prev_hist:
            bull_pts += 6
        elif hist < 0 and hist < prev_hist:
            bear_pts += 6

        # ── 5. Supertrend ─────────────────────────────────────────
        st_dir  = last["supertrend_direction"]
        prev_st = df.iloc[-2]["supertrend_direction"] if len(df) > 2 else 0

        if st_dir == -1:
            bull_pts += 10
            if prev_st != -1:
                signals.append("Supertrend flipped BULLISH 🚀")
        elif st_dir == 1:
            bear_pts += 10
            if prev_st != 1:
                signals.append("Supertrend flipped BEARISH 💥")

        # ── 6. ADX (trend strength) ───────────────────────────────
        adx = last["adx"]
        if adx > 25:
            # Strong trend — amplify the dominant side
            if bull_pts > bear_pts:
                bull_pts += 8
                signals.append(f"ADX {adx:.1f} — strong trend confirmed")
            elif bear_pts > bull_pts:
                bear_pts += 8
        elif adx < 20:
            warnings.append(f"ADX {adx:.1f} — weak trend, ranging market ⚠️")

        # ── 7. Volume ─────────────────────────────────────────────
        if last["vol_spike"]:
            vol_pct = (last["vol_ratio"] - 1) * 100
            if last["candle_delta"] > 0:
                bull_pts += 10
                signals.append(f"Volume spike +{vol_pct:.0f}% — bullish 🔊")
            else:
                bear_pts += 10
                signals.append(f"Volume spike +{vol_pct:.0f}% — bearish 🔊")

        # OBV trend (10 candles)
        if len(df) >= 10:
            obv_slope = df["obv"].iloc[-1] - df["obv"].iloc[-10]
            if obv_slope > 0:
                bull_pts += 5
            else:
                bear_pts += 5

        # CVD
        if last["candle_delta"] > 0:
            bull_pts += 3
        else:
            bear_pts += 3

        # ── 8. Bollinger ──────────────────────────────────────────
        pct_b = last["bb_pct_b"]
        width = last["bb_width"]
        if not pd.isna(pct_b):
            if pct_b > 1.0:
                warnings.append("Price outside upper BB — possible reversal ⚠️")
                bear_pts += 3
            elif pct_b < 0.0:
                warnings.append("Price outside lower BB — possible bounce ⚠️")
                bull_pts += 3
        if not pd.isna(width) and width < df["bb_width"].quantile(0.2):
            warnings.append("BB squeeze — breakout incoming ⚡")

        # ── 9. Hull MA ────────────────────────────────────────────
        if last["close"] > last["hull"]:
            bull_pts += 4
        else:
            bear_pts += 4

        # ── 10. Candle pattern (last 3 candles) ───────────────────
        pattern = self._detect_candle_pattern(df)
        if pattern:
            signals.append(pattern["label"])
            if pattern["bias"] == "bull":
                bull_pts += pattern["weight"]
            else:
                bear_pts += pattern["weight"]

        # ── Final score ───────────────────────────────────────────
        total = bull_pts + bear_pts
        if total > 0:
            if bull_pts > bear_pts:
                score = int((bull_pts / total) * 100)
                res.trend = "bullish"
            else:
                score = int((bear_pts / total) * 100)
                res.trend = "bearish"
        else:
            score = 50
            res.trend = "neutral"

        # Timeframe weight (higher TF = more reliable)
        tf_weight = {"5m": 0.7, "15m": 0.8, "1h": 0.9, "4h": 1.0, "1d": 1.05}
        score = min(100, int(score * tf_weight.get(timeframe, 0.8)))

        res.score    = score
        res.signals  = signals
        res.warnings = warnings

    # ── Candle pattern detector ───────────────────────────────────
    def _detect_candle_pattern(self, df: pd.DataFrame) -> Optional[dict]:
        if len(df) < 4:
            return None

        c0 = df.iloc[-1]   # current
        c1 = df.iloc[-2]   # previous
        c2 = df.iloc[-3]   # 2 back
        c3 = df.iloc[-4]   # 3 back

        def body(c): return abs(c["close"] - c["open"])
        def upper_wick(c): return c["high"] - max(c["open"], c["close"])
        def lower_wick(c): return min(c["open"], c["close"]) - c["low"]
        def bull_c(c): return c["close"] > c["open"]
        def bear_c(c): return c["close"] < c["open"]

        atr_val = c0["atr"] if "atr" in c0 else (c0["high"] - c0["low"])

        # Displacement (3 large consecutive candles)
        bodies = [body(df.iloc[-i]) for i in range(1, 4)]
        if all(b > atr_val * 0.5 for b in bodies):
            if all(bull_c(df.iloc[-i]) for i in range(1, 4)):
                return {"label": "📈 Displacement (3 bull candles) — strong momentum", "bias": "bull", "weight": 15}
            if all(bear_c(df.iloc[-i]) for i in range(1, 4)):
                return {"label": "📉 Displacement (3 bear candles) — strong momentum", "bias": "bear", "weight": 15}

        # Bullish engulfing
        if (bear_c(c1) and bull_c(c0)
                and c0["close"] > c1["open"] and c0["open"] < c1["close"]
                and body(c0) > body(c1) * 1.1):
            if c0["vol_spike"] if "vol_spike" in c0 else True:
                return {"label": "🕯 Bullish Engulfing + Volume ✅", "bias": "bull", "weight": 12}

        # Bearish engulfing
        if (bull_c(c1) and bear_c(c0)
                and c0["close"] < c1["open"] and c0["open"] > c1["close"]
                and body(c0) > body(c1) * 1.1):
            return {"label": "🕯 Bearish Engulfing ✅", "bias": "bear", "weight": 12}

        # Bullish Marubozu
        if (bull_c(c0)
                and body(c0) > atr_val * 0.6
                and upper_wick(c0) < body(c0) * 0.1
                and lower_wick(c0) < body(c0) * 0.1):
            return {"label": "🟢 Bullish Marubozu — continuation", "bias": "bull", "weight": 8}

        # Bearish Marubozu
        if (bear_c(c0)
                and body(c0) > atr_val * 0.6
                and upper_wick(c0) < body(c0) * 0.1
                and lower_wick(c0) < body(c0) * 0.1):
            return {"label": "🔴 Bearish Marubozu — continuation", "bias": "bear", "weight": 8}

        # Hammer (bullish reversal at low)
        if (lower_wick(c0) > body(c0) * 2
                and upper_wick(c0) < body(c0) * 0.3
                and bear_c(c1)):
            return {"label": "🔨 Hammer — bullish reversal signal", "bias": "bull", "weight": 7}

        # Shooting star (bearish reversal)
        if (upper_wick(c0) > body(c0) * 2
                and lower_wick(c0) < body(c0) * 0.3
                and bull_c(c1)):
            return {"label": "⭐ Shooting Star — bearish reversal signal", "bias": "bear", "weight": 7}

        return None


# Singleton
indicator_engine = IndicatorEngine()
