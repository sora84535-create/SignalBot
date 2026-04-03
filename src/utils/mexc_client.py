import asyncio
from typing import Any, Dict, List, Optional
import aiohttp
from config.settings import settings
from src.utils.logger import setup_logger

logger = setup_logger("api")

BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"
MEXC_SPOT = "https://api.mexc.com"
MEXC_FUTURES = "https://contract.mexc.com"

TF_MAP = {"Min1":"1m","Min5":"5m","Min15":"15m","Min30":"30m","Min60":"1h","Hour4":"4h","Hour8":"8h","Day1":"1d","1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d"}

class MexcAPIError(Exception):
    pass

class MexcClient:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, url: str, params: dict = None) -> Any:
        session = await self._sess()
        for i in range(3):
            try:
                async with session.get(url, params=params or {}) as r:
                    if r.status in {429,500,502,503,504}:
                        await asyncio.sleep(1.5*(i+1)); continue
                    return await r.json(content_type=None)
            except Exception as e:
                if i == 2: raise MexcAPIError(f"Request failed: {e}")
                await asyncio.sleep(1.5)

    def _sym(self, s: str) -> str:
        return s.replace("_","").replace("/","")

    async def get_futures_klines(self, symbol: str, interval: str = "Min15", limit: int = 200) -> dict:
        tf = TF_MAP.get(interval, "15m")
        data = await self._get(f"{BINANCE_FUTURES}/fapi/v1/klines", {"symbol":self._sym(symbol),"interval":tf,"limit":limit})
        if not isinstance(data, list): return {}
        t,o,h,l,c,v = [],[],[],[],[],[]
        for k in data:
            t.append(k[0]);o.append(k[1]);h.append(k[2]);l.append(k[3]);c.append(k[4]);v.append(k[5])
        return {"time":t,"open":o,"high":h,"low":l,"close":c,"vol":v}

    async def get_spot_klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list:
        tf = TF_MAP.get(interval, interval)
        data = await self._get(f"{BINANCE_SPOT}/api/v3/klines", {"symbol":self._sym(symbol),"interval":tf,"limit":limit})
        return data if isinstance(data, list) else []

    async def get_futures_ticker(self, symbol: str) -> dict:
        try:
            data = await self._get(f"{BINANCE_FUTURES}/fapi/v1/ticker/24hr", {"symbol":self._sym(symbol)})
            return {"lastPrice":data.get("lastPrice",0),"priceChangePercent":data.get("priceChangePercent",0)}
        except: return {}

    async def get_futures_funding_rate(self, symbol: str) -> dict:
        try:
            data = await self._get(f"{BINANCE_FUTURES}/fapi/v1/fundingRate", {"symbol":self._sym(symbol),"limit":1})
            if isinstance(data, list) and data: return {"fundingRate":float(data[0].get("fundingRate",0))}
        except: pass
        return {"fundingRate": 0}

    async def get_futures_symbols(self) -> list:
        try:
            data = await self._get(f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo")
            return [{"symbol":s["symbol"].replace("USDT","_USDT"),"state":"open"} for s in data.get("symbols",[]) if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"]
        except: return []

    async def get_all_futures_tickers(self) -> list:
        try:
            data = await self._get(f"{BINANCE_FUTURES}/fapi/v1/ticker/24hr")
            return [{"symbol":d["symbol"].replace("USDT","_USDT"),"lastPrice":d.get("lastPrice",0),"priceChangePercent":d.get("priceChangePercent",0)} for d in data if d.get("symbol","").endswith("USDT")]
        except: return []

    async def get_spot_price(self, symbol: str) -> float:
        try:
            data = await self._get(f"{BINANCE_SPOT}/api/v3/ticker/price", {"symbol":self._sym(symbol)})
            return float(data.get("price", 0))
        except: return 0.0

    async def get_spot_24h(self, symbol: str) -> dict:
        try:
            return await self._get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", {"symbol":self._sym(symbol)})
        except: return {}

    async def get_all_spot_prices(self) -> list:
        try:
            return await self._get(f"{BINANCE_SPOT}/api/v3/ticker/price")
        except: return []

    async def get_futures_orderbook(self, symbol: str, depth: int = 10) -> dict:
        try:
            return await self._get(f"{BINANCE_FUTURES}/fapi/v1/depth", {"symbol":self._sym(symbol),"limit":depth})
        except: return {}

    async def get_futures_open_interest(self, symbol: str) -> dict:
        try:
            return await self._get(f"{BINANCE_FUTURES}/fapi/v1/openInterest", {"symbol":self._sym(symbol)})
        except: return {}

    async def get_spot_orderbook(self, symbol: str, limit: int = 10) -> dict:
        try:
            return await self._get(f"{BINANCE_SPOT}/api/v3/depth", {"symbol":self._sym(symbol),"limit":limit})
        except: return {}

mexc = MexcClient()
