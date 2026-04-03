"""
MEXC REST API client (futures + spot).
Handles authentication, rate-limits, retries.
"""

import asyncio
import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from config.settings import settings
from src.utils.logger import setup_logger

logger = setup_logger("mexc_api")

_RETRY_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES  = 3
_RETRY_DELAY  = 1.5   # seconds


class MexcAPIError(Exception):
    pass


class MexcClient:
    """Async MEXC API client — futures + spot."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Session ──────────────────────────────────────────────────
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"})
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Signing ──────────────────────────────────────────────────
    def _sign(self, params: Dict) -> str:
        ts = str(int(time.time() * 1000))
        params["timestamp"] = ts
        query = urlencode(sorted(params.items()))
        sig = hmac.new(
            settings.MEXC_API_SECRET.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return sig

    # ── Generic request ──────────────────────────────────────────
    async def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        params: Dict = None,
        signed: bool = False,
    ) -> Any:
        params = params or {}
        if signed:
            sig = self._sign(params)
            params["signature"] = sig

        url = base_url + path
        session = await self._get_session()
        headers = {"X-MEXC-APIKEY": settings.MEXC_API_KEY} if signed else {}

        for attempt in range(_MAX_RETRIES):
            try:
                async with session.request(
                    method, url, params=params, headers=headers
                ) as resp:
                    if resp.status in _RETRY_CODES:
                        await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
                        continue
                    data = await resp.json()
                    if resp.status != 200:
                        raise MexcAPIError(
                            f"HTTP {resp.status}: {data}"
                        )
                    return data
            except aiohttp.ClientError as e:
                if attempt == _MAX_RETRIES - 1:
                    raise MexcAPIError(f"Request failed: {e}") from e
                await asyncio.sleep(_RETRY_DELAY)

        raise MexcAPIError("Max retries exceeded")

    # ══════════════════════════════════════════════════════════════
    #  FUTURES endpoints
    # ══════════════════════════════════════════════════════════════

    async def get_futures_symbols(self) -> List[Dict]:
        """All active futures contracts."""
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/detail"
        )
        return data.get("data", [])

    async def get_futures_klines(
        self,
        symbol: str,
        interval: str = "Min15",
        limit: int = 200,
    ) -> List[Dict]:
        """
        Futures klines.
        interval: Min1 Min5 Min15 Min30 Min60 Hour4 Hour8 Day1 Week1 Month1
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/kline", params
        )
        return data.get("data", {})

    async def get_futures_ticker(self, symbol: str) -> Dict:
        params = {"symbol": symbol}
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/ticker", params
        )
        return data.get("data", {})

    async def get_futures_orderbook(self, symbol: str, depth: int = 10) -> Dict:
        params = {"symbol": symbol, "depth": depth}
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/depth", params
        )
        return data.get("data", {})

    async def get_futures_funding_rate(self, symbol: str) -> Dict:
        params = {"symbol": symbol}
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/funding_rate", params
        )
        return data.get("data", {})

    async def get_futures_open_interest(self, symbol: str) -> Dict:
        params = {"symbol": symbol}
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/open_interest", params
        )
        return data.get("data", {})

    async def get_all_futures_tickers(self) -> List[Dict]:
        data = await self._request(
            "GET", settings.MEXC_BASE_URL, "/api/v1/contract/ticker"
        )
        return data.get("data", [])

    # ══════════════════════════════════════════════════════════════
    #  SPOT endpoints
    # ══════════════════════════════════════════════════════════════

    async def get_spot_symbols(self) -> List[Dict]:
        data = await self._request(
            "GET", settings.MEXC_SPOT_URL, "/api/v3/exchangeInfo"
        )
        return data.get("symbols", [])

    async def get_spot_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 200,
    ) -> List[List]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return await self._request(
            "GET", settings.MEXC_SPOT_URL, "/api/v3/klines", params
        )

    async def get_spot_price(self, symbol: str) -> float:
        params = {"symbol": symbol}
        data = await self._request(
            "GET", settings.MEXC_SPOT_URL, "/api/v3/ticker/price", params
        )
        return float(data.get("price", 0))

    async def get_spot_24h(self, symbol: str) -> Dict:
        params = {"symbol": symbol}
        data = await self._request(
            "GET", settings.MEXC_SPOT_URL, "/api/v3/ticker/24hr", params
        )
        return data

    async def get_all_spot_prices(self) -> List[Dict]:
        return await self._request(
            "GET", settings.MEXC_SPOT_URL, "/api/v3/ticker/price"
        )

    async def get_spot_orderbook(self, symbol: str, limit: int = 10) -> Dict:
        params = {"symbol": symbol, "limit": limit}
        return await self._request(
            "GET", settings.MEXC_SPOT_URL, "/api/v3/depth", params
        )


# Singleton
mexc = MexcClient()
