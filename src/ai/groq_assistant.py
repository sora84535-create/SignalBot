"""
Groq AI Trading Assistant
==========================
Uses Groq's Llama 3.3 70B model for:
  • Trading Q&A
  • Market analysis
  • Deal recommendations based on current market state
  • Interpretation of signals

Commands: /ai <question>
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import List, Dict, Optional

import aiohttp

from config.settings import settings
from src.utils.logger import setup_logger

logger = setup_logger("groq_ai")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are an elite professional crypto trading assistant specialized in:
- Futures trading on MEXC (BTC, ETH, altcoins)
- Smart Money Concepts (SMC/ICT): BOS, CHoCH, FVG, Order Blocks, Liquidity sweeps
- Technical analysis: EMA, RSI, Stoch RSI, MACD, Supertrend, ADX, Volume
- Risk management: position sizing, SL/TP, RR ratios
- Geopolitical macro analysis impact on crypto markets

Your responses:
- Are concise, actionable, and professional
- Include specific price levels when relevant
- Consider risk management in every recommendation
- Use trader terminology naturally
- Respond in the same language as the user (Russian or English)
- Format with emojis for visual clarity in Telegram

When recommending trades:
- Always specify direction (LONG/SHORT)
- Give entry, SL, TP1, TP2
- State confidence level (Low/Medium/High)
- Warn about risks
- Never guarantee profits

You have access to real-time context that will be provided in messages."""


class GroqAssistant:

    def __init__(self):
        self._session:  Optional[aiohttp.ClientSession] = None
        self._history:  Dict[int, List[dict]] = {}   # user_id → conversation
        self._max_hist: int = 10

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Build context ─────────────────────────────────────────────
    def _build_context(self, market_data: dict = None) -> str:
        if not market_data:
            return ""
        parts = ["📊 Current Market Context:"]
        if "btc_price" in market_data:
            parts.append(f"BTC Price: ${market_data['btc_price']:,.2f}")
        if "btc_signal" in market_data:
            sig = market_data["btc_signal"]
            parts.append(f"BTC Signal: {sig.get('direction', 'N/A')} (confidence: {sig.get('confidence', 0)}%)")
        if "top_signals" in market_data:
            sigs = market_data["top_signals"][:3]
            if sigs:
                parts.append("Top Signals:")
                for s in sigs:
                    parts.append(f"  • {s.get('symbol', '')} {s.get('direction', '')} @ {s.get('entry', 0)}")
        if "news" in market_data and market_data["news"]:
            parts.append("Recent important news:")
            for n in market_data["news"][:2]:
                parts.append(f"  • {n.get('title', '')}")
        return "\n".join(parts)

    # ── Ask ───────────────────────────────────────────────────────
    async def ask(
        self,
        user_id: int,
        question: str,
        market_data: dict = None,
    ) -> str:
        if not settings.GROQ_API_KEY:
            return "❌ Groq API key not configured. Set GROQ_API_KEY in environment."

        # Build messages
        history = self._history.get(user_id, [])

        # Context injection
        ctx = self._build_context(market_data)
        if ctx:
            question = f"{ctx}\n\n---\n\nUser question: {question}"

        history.append({"role": "user", "content": question})

        # Trim history
        if len(history) > self._max_hist * 2:
            history = history[-self._max_hist * 2:]
        self._history[user_id] = history

        payload = {
            "model":       settings.GROQ_MODEL,
            "max_tokens":  1024,
            "temperature": 0.7,
            "messages":    [{"role": "system", "content": SYSTEM_PROMPT}] + history,
        }

        session = await self._sess()
        try:
            async with session.post(
                GROQ_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type":  "application/json",
                },
            ) as resp:
                if resp.status == 401:
                    return "❌ Invalid Groq API key."
                if resp.status == 429:
                    return "⏳ Groq rate limit. Please wait a moment."
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Groq error %d: %s", resp.status, text[:200])
                    return f"❌ Groq API error: {resp.status}"

                data = await resp.json()
                answer = data["choices"][0]["message"]["content"]

                # Save assistant response to history
                self._history[user_id].append({"role": "assistant", "content": answer})
                return answer

        except asyncio.TimeoutError:
            return "⏱ Groq request timed out. Please try again."
        except Exception as e:
            logger.error("Groq ask error: %s", e, exc_info=True)
            return f"❌ Error: {e}"

    def clear_history(self, user_id: int):
        self._history.pop(user_id, None)

    # ── Quick market summary ──────────────────────────────────────
    async def market_summary(self, market_data: dict) -> str:
        """Generate a brief AI market summary."""
        prompt = (
            "Based on the current market data provided, give a brief "
            "trading summary in 3-4 bullet points. Focus on: "
            "1) BTC direction, 2) Key levels to watch, "
            "3) Risk factors, 4) Best opportunities."
        )
        return await self.ask(0, prompt, market_data)

    # ── Trade recommendation ──────────────────────────────────────
    async def recommend_trade(
        self,
        symbol: str,
        ind_result,
        smc_result,
        user_id: int = 0,
    ) -> str:
        prompt = (
            f"Analyse {symbol} based on this data and give a trade recommendation:\n"
            f"Indicators: trend={getattr(ind_result, 'trend', 'N/A')}, "
            f"score={getattr(ind_result, 'score', 0)}, "
            f"signals={getattr(ind_result, 'signals', [])[:3]}\n"
            f"SMC: trend={getattr(smc_result, 'trend', 'N/A')}, "
            f"bias={getattr(smc_result, 'entry_bias', 'N/A')}, "
            f"signals={getattr(smc_result, 'signals', [])[:3]}\n"
            f"Should I enter? If yes — entry, SL, TP1, TP2, leverage suggestion."
        )
        return await self.ask(user_id, prompt)


# Singleton
groq_ai = GroqAssistant()
