"""
News Fetcher
============
Fetches important geopolitical news (Iran, Trump, wars, sanctions)
and crypto-market-moving news.

Sources:
  • NewsAPI.org
  • CryptoPanic
  • RSS feeds (Reuters, Bloomberg crypto, etc.)
  • Fallback: free newsdata.io

Filters: only high-importance news, no noise.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import aiohttp

from config.settings import settings
from src.utils.logger import setup_logger

logger = setup_logger("news")

# ── RSS sources (no API key needed) ───────────────────────────────
RSS_FEEDS = [
    ("Reuters World",    "https://feeds.reuters.com/reuters/worldnews"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("BBC World",        "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",    "https://cointelegraph.com/rss"),
    ("CryptoSlate",      "https://cryptoslate.com/feed/"),
]

# Keywords that make news HIGH importance for traders
CRITICAL_KEYWORDS = [
    # Geopolitical
    "iran", "trump", "sanctions", "war", "nuclear", "oil", "opec",
    "strait of hormuz", "ormuz", "middle east", "attack", "missile",
    "russia", "ukraine", "nato", "china", "taiwan",
    # Macro
    "fed", "federal reserve", "interest rate", "inflation", "cpi",
    "recession", "gdp", "unemployment",
    # Crypto
    "bitcoin", "btc", "ethereum", "crypto", "sec", "etf",
    "binance", "coinbase", "mexc", "hack", "exploit", "stablecoin",
    "usdt", "tether", "defi", "halving", "whale",
]

# Keywords that indicate NOISE — skip
NOISE_KEYWORDS = [
    "celebrity", "sports", "entertainment", "fashion", "cooking",
    "weather", "local", "travel",
]

IMPORTANCE_HIGH = [
    "iran", "trump", "nuclear", "war", "federal reserve", "rate hike",
    "bitcoin crash", "bitcoin surge", "sec", "hack", "exploit",
    "sanctions", "oil", "opec", "china", "taiwan",
]


@dataclass
class NewsItem:
    title:       str
    summary:     str
    source:      str
    url:         str
    published:   str
    importance:  str      # "high" | "medium"
    category:    str      # "geopolitical" | "crypto" | "macro"
    keywords:    List[str] = field(default_factory=list)
    ts:          float    = 0.0


class NewsFetcher:

    def __init__(self):
        self._session:     Optional[aiohttp.ClientSession] = None
        self._sent_urls:   set = set()     # dedup
        self._cache:       List[NewsItem] = []
        self._cache_ts:    float = 0.0

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; TradeBot/1.0)"}
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers=headers,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Importance filter ─────────────────────────────────────────
    def _classify(self, title: str, summary: str = "") -> Optional[dict]:
        text_lower = (title + " " + summary).lower()

        # Skip noise
        if any(k in text_lower for k in NOISE_KEYWORDS):
            return None

        # Check relevance
        found_keywords = [k for k in CRITICAL_KEYWORDS if k in text_lower]
        if not found_keywords:
            return None

        # Importance level
        is_high = any(k in text_lower for k in IMPORTANCE_HIGH)
        importance = "high" if is_high else "medium"

        # Category
        geo_kw    = ["iran", "trump", "war", "russia", "china", "taiwan", "sanctions", "nuclear", "oil", "opec", "attack"]
        crypto_kw = ["bitcoin", "btc", "ethereum", "crypto", "sec", "defi", "hack", "exploit", "stablecoin", "halving"]
        macro_kw  = ["fed", "federal reserve", "interest rate", "inflation", "cpi", "recession", "gdp"]

        if any(k in text_lower for k in geo_kw):
            category = "geopolitical"
        elif any(k in text_lower for k in crypto_kw):
            category = "crypto"
        elif any(k in text_lower for k in macro_kw):
            category = "macro"
        else:
            category = "general"

        return {
            "importance": importance,
            "category":   category,
            "keywords":   found_keywords[:5],
        }

    # ── RSS parser ────────────────────────────────────────────────
    async def _fetch_rss(self, name: str, url: str) -> List[NewsItem]:
        session = await self._sess()
        items   = []
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text(errors="replace")

            root = ET.fromstring(text)
            ns   = {"media": "http://search.yahoo.com/mrss/"}

            for item in root.iter("item"):
                title   = (item.findtext("title") or "").strip()
                link    = (item.findtext("link") or "").strip()
                desc    = (item.findtext("description") or "").strip()
                pubdate = (item.findtext("pubDate") or "").strip()

                if not title or link in self._sent_urls:
                    continue

                cls = self._classify(title, desc)
                if not cls:
                    continue

                # Only HIGH importance from geopolitical
                if cls["category"] == "geopolitical" and cls["importance"] != "high":
                    continue

                items.append(NewsItem(
                    title      = title[:200],
                    summary    = desc[:400],
                    source     = name,
                    url        = link,
                    published  = pubdate,
                    importance = cls["importance"],
                    category   = cls["category"],
                    keywords   = cls["keywords"],
                    ts         = time.time(),
                ))

        except Exception as e:
            logger.debug("RSS %s error: %s", name, e)
        return items

    # ── NewsAPI ───────────────────────────────────────────────────
    async def _fetch_newsapi(self) -> List[NewsItem]:
        if not settings.NEWS_API_KEY:
            return []
        session = await self._sess()
        items   = []
        queries = [
            "Iran Trump war oil sanctions",
            "Bitcoin crypto market",
            "Federal Reserve interest rate",
        ]
        for q in queries:
            try:
                params = {
                    "q":        q,
                    "sortBy":   "publishedAt",
                    "pageSize": 5,
                    "apiKey":   settings.NEWS_API_KEY,
                    "language": "en",
                }
                url = "https://newsapi.org/v2/everything?" + urlencode(params)
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    for art in data.get("articles", []):
                        title   = (art.get("title") or "").strip()
                        desc    = (art.get("description") or "").strip()
                        link    = art.get("url", "")
                        pubdate = art.get("publishedAt", "")

                        if not title or link in self._sent_urls:
                            continue
                        cls = self._classify(title, desc)
                        if not cls:
                            continue

                        items.append(NewsItem(
                            title      = title[:200],
                            summary    = desc[:400],
                            source     = art.get("source", {}).get("name", "NewsAPI"),
                            url        = link,
                            published  = pubdate,
                            importance = cls["importance"],
                            category   = cls["category"],
                            keywords   = cls["keywords"],
                            ts         = time.time(),
                        ))
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug("NewsAPI error: %s", e)
        return items

    # ── CryptoPanic ───────────────────────────────────────────────
    async def _fetch_cryptopanic(self) -> List[NewsItem]:
        if not settings.CRYPTOPANIC_KEY:
            return []
        session = await self._sess()
        items   = []
        try:
            url = (
                f"https://cryptopanic.com/api/v1/posts/"
                f"?auth_token={settings.CRYPTOPANIC_KEY}"
                f"&filter=important&public=true&kind=news"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                for post in data.get("results", [])[:10]:
                    title   = (post.get("title") or "").strip()
                    link    = post.get("url", "")
                    pubdate = post.get("published_at", "")
                    if not title or link in self._sent_urls:
                        continue
                    cls = self._classify(title)
                    if not cls:
                        continue
                    items.append(NewsItem(
                        title      = title[:200],
                        summary    = "",
                        source     = "CryptoPanic",
                        url        = link,
                        published  = pubdate,
                        importance = cls["importance"],
                        category   = cls["category"],
                        keywords   = cls["keywords"],
                        ts         = time.time(),
                    ))
        except Exception as e:
            logger.debug("CryptoPanic error: %s", e)
        return items

    # ── Main fetch ────────────────────────────────────────────────
    async def fetch(self) -> List[NewsItem]:
        """Fetch all news, filter, deduplicate, sort by importance."""
        if time.time() - self._cache_ts < 120:
            return self._cache

        tasks = [self._fetch_rss(name, url) for name, url in RSS_FEEDS]
        tasks += [self._fetch_newsapi(), self._fetch_cryptopanic()]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items: List[NewsItem] = []
        for r in results:
            if isinstance(r, list):
                all_items.extend(r)

        # Dedup by URL
        seen = set()
        unique = []
        for item in all_items:
            if item.url not in seen and item.url not in self._sent_urls:
                seen.add(item.url)
                unique.append(item)

        # Sort: high first, then by ts
        unique.sort(key=lambda x: (0 if x.importance == "high" else 1, -x.ts))

        # Mark as sent
        for item in unique:
            self._sent_urls.add(item.url)

        self._cache    = unique[:20]   # keep top 20
        self._cache_ts = time.time()
        return self._cache

    async def fetch_high_only(self) -> List[NewsItem]:
        all_news = await self.fetch()
        return [n for n in all_news if n.importance == "high"]


# Singleton
news_fetcher = NewsFetcher()
