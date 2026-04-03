"""
Rate Limiter
=============
Prevents Telegram flood (429 errors) and per-user spam.

Limits:
  - Global: max 30 messages/second to Telegram
  - Per chat: max 1 message/second
  - Per user per command: configurable cooldown
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:

    def __init__(
        self,
        global_rps: float = 25.0,   # messages per second (Telegram limit is 30)
        chat_rps:   float = 1.0,    # per chat per second
    ):
        self._global_rps  = global_rps
        self._chat_rps    = chat_rps
        self._global_ts:  Deque[float] = deque()
        self._chat_ts:    Dict[int, Deque[float]] = defaultdict(deque)
        self._cmd_cd:     Dict[str, float] = {}   # "uid:cmd" → last call ts
        self._lock = asyncio.Lock()

    async def acquire(self, chat_id: int) -> bool:
        """
        Wait until it's safe to send a message to chat_id.
        Returns True when acquired.
        """
        async with self._lock:
            now = time.monotonic()
            window = 1.0   # 1 second window

            # Global rate
            while (self._global_ts and
                   now - self._global_ts[0] > window):
                self._global_ts.popleft()
            if len(self._global_ts) >= self._global_rps:
                sleep = window - (now - self._global_ts[0])
                if sleep > 0:
                    await asyncio.sleep(sleep)

            # Per-chat rate
            q = self._chat_ts[chat_id]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= self._chat_rps:
                sleep = window - (now - q[0])
                if sleep > 0:
                    await asyncio.sleep(sleep)

            self._global_ts.append(time.monotonic())
            self._chat_ts[chat_id].append(time.monotonic())
            return True

    def check_cmd_cooldown(self, uid: int, cmd: str, seconds: float = 5.0) -> float:
        """
        Returns 0 if command is allowed, or remaining cooldown in seconds.
        """
        key  = f"{uid}:{cmd}"
        last = self._cmd_cd.get(key, 0)
        rem  = seconds - (time.time() - last)
        if rem <= 0:
            self._cmd_cd[key] = time.time()
            return 0
        return rem


# Singleton
rate_limiter = RateLimiter()
