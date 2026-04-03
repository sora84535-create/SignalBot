"""
Watchlist Manager
==================
Allows users to maintain a personal list of coins to monitor.
Stores per-user watchlists in a JSON file (persists across restarts).
Sends alerts when watched coins get signals.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Set

from src.utils.logger import setup_logger

logger = setup_logger("watchlist")

STORAGE_FILE = "data/watchlists.json"


class WatchlistManager:

    def __init__(self):
        self._data: Dict[int, List[str]] = {}   # user_id → [symbols]
        self._load()

    # ── Persistence ───────────────────────────────────────────────
    def _load(self):
        os.makedirs("data", exist_ok=True)
        if os.path.exists(STORAGE_FILE):
            try:
                with open(STORAGE_FILE, "r") as f:
                    raw = json.load(f)
                self._data = {int(k): v for k, v in raw.items()}
                logger.info("Watchlist loaded: %d users", len(self._data))
            except Exception as e:
                logger.error("Watchlist load error: %s", e)
                self._data = {}

    def _save(self):
        try:
            os.makedirs("data", exist_ok=True)
            with open(STORAGE_FILE, "w") as f:
                json.dump({str(k): v for k, v in self._data.items()}, f, indent=2)
        except Exception as e:
            logger.error("Watchlist save error: %s", e)

    # ── Operations ────────────────────────────────────────────────
    def get(self, uid: int) -> List[str]:
        return self._data.get(uid, [])

    def add(self, uid: int, symbol: str) -> bool:
        """Add symbol to watchlist. Returns False if already exists."""
        sym = self._normalise(symbol)
        lst = self._data.setdefault(uid, [])
        if sym in lst:
            return False
        if len(lst) >= 20:
            return False   # max 20 per user
        lst.append(sym)
        self._save()
        return True

    def remove(self, uid: int, symbol: str) -> bool:
        sym = self._normalise(symbol)
        lst = self._data.get(uid, [])
        if sym not in lst:
            return False
        lst.remove(sym)
        self._data[uid] = lst
        self._save()
        return True

    def clear(self, uid: int):
        self._data[uid] = []
        self._save()

    def all_symbols(self) -> Set[str]:
        """All unique symbols across all users."""
        result = set()
        for lst in self._data.values():
            result.update(lst)
        return result

    def users_watching(self, symbol: str) -> List[int]:
        """Which users are watching this symbol."""
        sym = self._normalise(symbol)
        return [uid for uid, lst in self._data.items() if sym in lst]

    @staticmethod
    def _normalise(symbol: str) -> str:
        s = symbol.upper().replace("/", "_").replace("-", "_")
        if not s.endswith("_USDT") and not s.endswith("USDT"):
            s += "_USDT"
        if "USDT" in s and "_" not in s:
            s = s.replace("USDT", "_USDT")
        return s

    def format_list(self, uid: int) -> str:
        lst = self.get(uid)
        if not lst:
            return "📋 Твой вотчлист пуст.\nДобавь монеты: `/watch add BTCUSDT`"
        lines = ["📋 *Твой вотчлист:*", ""]
        for i, sym in enumerate(lst, 1):
            base = sym.replace("_USDT", "")
            lines.append(f"{i}. `{base}/USDT`")
        lines.append(f"\n_{len(lst)}/20 монет_")
        return "\n".join(lines)


# Singleton
watchlist = WatchlistManager()
