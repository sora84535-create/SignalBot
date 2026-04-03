"""
Market Context Engine
======================
Fetches macro market data:
  • Fear & Greed Index (alternative.me)
  • BTC Dominance (CoinGecko)
  • Total market cap & 24h change
  • Top gainers/losers on MEXC
  • Funding rate heatmap (top 10 pairs)
  • Open Interest changes
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import aiohttp

from src.utils.mexc_client import mexc
from src.utils.logger import setup_logger

logger = setup_logger("market_ctx")

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"


@dataclass
class MarketContext:
    # Fear & Greed
    fg_value:    int    = 50
    fg_label:    str    = "Neutral"
    fg_emoji:    str    = "😐"

    # BTC
    btc_price:        float = 0.0
    btc_dominance:    float = 0.0
    btc_change_24h:   float = 0.0

    # Total market
    total_mcap:       float = 0.0
    total_mcap_change: float = 0.0
    total_volume_24h:  float = 0.0

    # MEXC top movers
    top_gainers: List[Tuple[str, float]] = field(default_factory=list)
    top_losers:  List[Tuple[str, float]] = field(default_factory=list)

    # Funding rates (symbol → rate%)
    funding_rates: Dict[str, float] = field(default_factory=dict)

    # Timestamp
    ts: float = 0.0


class MarketContextEngine:

    def __init__(self):
        self._session:  Optional[aiohttp.ClientSession] = None
        self._cache:    Optional[MarketContext] = None
        self._cache_ts: float = 0.0
        self._ttl:      int   = 300   # 5 min cache

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Fear & Greed ──────────────────────────────────────────────
    async def _fetch_fg(self) -> Tuple[int, str]:
        session = await self._sess()
        try:
            async with session.get(FEAR_GREED_URL) as resp:
                if resp.status != 200:
                    return 50, "Neutral"
                data = await resp.json(content_type=None)
                val   = int(data["data"][0]["value"])
                label = data["data"][0]["value_classification"]
                return val, label
        except Exception as e:
            logger.debug("Fear&Greed error: %s", e)
            return 50, "Neutral"

    # ── CoinGecko global ──────────────────────────────────────────
    async def _fetch_global(self) -> dict:
        session = await self._sess()
        try:
            async with session.get(COINGECKO_GLOBAL) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("data", {})
        except Exception as e:
            logger.debug("CoinGecko global error: %s", e)
            return {}

    # ── MEXC top movers ───────────────────────────────────────────
    async def _fetch_movers(self) -> Tuple[list, list]:
        try:
            tickers = await mexc.get_all_futures_tickers()
            valid = []
            for t in tickers:
                try:
                    pct = float(t.get("priceChangePercent", 0) or 0)
                    sym = t.get("symbol", "")
                    if sym and abs(pct) > 0.1:
                        valid.append((sym.replace("_USDT", ""), pct))
                except Exception:
                    continue
            valid.sort(key=lambda x: x[1], reverse=True)
            return valid[:5], valid[-5:][::-1]
        except Exception as e:
            logger.debug("Movers error: %s", e)
            return [], []

    # ── Funding rates ─────────────────────────────────────────────
    async def _fetch_funding(self) -> Dict[str, float]:
        symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT",
                   "XRP_USDT", "DOGE_USDT", "ADA_USDT", "AVAX_USDT"]
        result = {}
        for sym in symbols:
            try:
                data = await mexc.get_futures_funding_rate(sym)
                rate = float(data.get("fundingRate", 0)) * 100
                result[sym.replace("_USDT", "")] = round(rate, 4)
                await asyncio.sleep(0.1)
            except Exception:
                continue
        return result

    # ── Full fetch ────────────────────────────────────────────────
    async def get(self, force: bool = False) -> MarketContext:
        if not force and self._cache and (time.time() - self._cache_ts) < self._ttl:
            return self._cache

        ctx = MarketContext(ts=time.time())

        # Run in parallel
        fg_task      = self._fetch_fg()
        global_task  = self._fetch_global()
        movers_task  = self._fetch_movers()
        funding_task = self._fetch_funding()

        results = await asyncio.gather(
            fg_task, global_task, movers_task, funding_task,
            return_exceptions=True,
        )

        # Fear & Greed
        if isinstance(results[0], tuple):
            ctx.fg_value, ctx.fg_label = results[0]
            ctx.fg_emoji = self._fg_emoji(ctx.fg_value)

        # Global market
        if isinstance(results[1], dict) and results[1]:
            g = results[1]
            ctx.btc_dominance      = round(g.get("market_cap_percentage", {}).get("btc", 0), 1)
            ctx.total_mcap         = g.get("total_market_cap", {}).get("usd", 0)
            ctx.total_mcap_change  = round(g.get("market_cap_change_percentage_24h_usd", 0), 2)
            ctx.total_volume_24h   = g.get("total_volume", {}).get("usd", 0)

        # Movers
        if isinstance(results[2], tuple):
            ctx.top_gainers, ctx.top_losers = results[2]

        # Funding
        if isinstance(results[3], dict):
            ctx.funding_rates = results[3]

        # BTC price from MEXC
        try:
            ticker = await mexc.get_futures_ticker("BTC_USDT")
            ctx.btc_price      = float(ticker.get("lastPrice", 0))
            ctx.btc_change_24h = float(ticker.get("priceChangePercent", 0) or 0)
        except Exception:
            pass

        self._cache    = ctx
        self._cache_ts = time.time()
        return ctx

    @staticmethod
    def _fg_emoji(val: int) -> str:
        if val >= 75: return "🤑"
        if val >= 55: return "😊"
        if val >= 45: return "😐"
        if val >= 25: return "😨"
        return "🫨"

    def format(self, ctx: MarketContext) -> str:
        def fmt_mcap(v):
            if v >= 1e12: return f"${v/1e12:.2f}T"
            if v >= 1e9:  return f"${v/1e9:.1f}B"
            return f"${v/1e6:.0f}M"

        ch_emoji = "📈" if ctx.total_mcap_change >= 0 else "📉"
        btc_emoji = "📈" if ctx.btc_change_24h >= 0 else "📉"

        lines = [
            "🌐 *ОБЗОР РЫНКА*",
            f"{'─' * 32}",
            f"",
            f"{ctx.fg_emoji} *Fear & Greed:* `{ctx.fg_value}` — {ctx.fg_label}",
            f"",
            f"₿ *Bitcoin:*",
            f"  Цена: `${ctx.btc_price:,.2f}` {btc_emoji} {ctx.btc_change_24h:+.2f}%",
            f"  Доминация: `{ctx.btc_dominance:.1f}%`",
            f"",
            f"📊 *Крипторынок:*",
            f"  Капитализация: `{fmt_mcap(ctx.total_mcap)}` {ch_emoji} {ctx.total_mcap_change:+.2f}%",
            f"  Объём 24h: `{fmt_mcap(ctx.total_volume_24h)}`",
            f"",
        ]

        if ctx.top_gainers:
            lines.append("🚀 *Топ роста (MEXC):*")
            for sym, pct in ctx.top_gainers[:5]:
                lines.append(f"  `{sym}` +{pct:.2f}%")
            lines.append("")

        if ctx.top_losers:
            lines.append("💥 *Топ падения (MEXC):*")
            for sym, pct in ctx.top_losers[:5]:
                lines.append(f"  `{sym}` {pct:.2f}%")
            lines.append("")

        if ctx.funding_rates:
            lines.append("💹 *Funding rates:*")
            for sym, rate in sorted(ctx.funding_rates.items(),
                                    key=lambda x: abs(x[1]), reverse=True)[:6]:
                emoji = "🔴" if rate > 0.05 else "🟢" if rate < -0.05 else "⚪"
                lines.append(f"  {emoji} `{sym}`: {rate:+.4f}%")

        return "\n".join(lines)


# Singleton
market_ctx = MarketContextEngine()
