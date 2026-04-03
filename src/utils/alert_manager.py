"""
Alert Manager
==============
Users can set custom price/RSI/level alerts that fire once triggered.

Types:
  • price_above  — price crosses above target
  • price_below  — price crosses below target
  • rsi_above    — RSI crosses above threshold
  • rsi_below    — RSI crosses below threshold
  • pct_move     — price moves X% in either direction

Storage: JSON file, persists across restarts.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from src.utils.logger import setup_logger

logger = setup_logger("alerts")

STORAGE_FILE = "data/alerts.json"
MAX_ALERTS_PER_USER = 10


@dataclass
class PriceAlert:
    id:        str
    uid:       int
    symbol:    str
    kind:      str     # price_above | price_below | rsi_above | rsi_below | pct_move
    target:    float
    ref_price: float   # price at time of creation (for pct_move)
    created:   float
    triggered: bool = False
    note:      str  = ""


class AlertManager:

    def __init__(self):
        self._alerts: List[PriceAlert] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────
    def _load(self):
        os.makedirs("data", exist_ok=True)
        if os.path.exists(STORAGE_FILE):
            try:
                with open(STORAGE_FILE) as f:
                    raw = json.load(f)
                self._alerts = [PriceAlert(**a) for a in raw]
                # Remove old triggered ones
                self._alerts = [a for a in self._alerts if not a.triggered]
                logger.info("Alerts loaded: %d active", len(self._alerts))
            except Exception as e:
                logger.error("Alerts load error: %s", e)

    def _save(self):
        try:
            os.makedirs("data", exist_ok=True)
            active = [a for a in self._alerts if not a.triggered]
            with open(STORAGE_FILE, "w") as f:
                json.dump([asdict(a) for a in active], f, indent=2)
        except Exception as e:
            logger.error("Alerts save error: %s", e)

    # ── CRUD ──────────────────────────────────────────────────────
    def add(
        self,
        uid: int,
        symbol: str,
        kind: str,
        target: float,
        ref_price: float = 0.0,
        note: str = "",
    ) -> Optional[PriceAlert]:
        user_alerts = [a for a in self._alerts if a.uid == uid and not a.triggered]
        if len(user_alerts) >= MAX_ALERTS_PER_USER:
            return None

        sym = symbol.upper().replace("/", "_")
        if not sym.endswith("_USDT") and "USDT" not in sym:
            sym += "_USDT"

        alert = PriceAlert(
            id        = f"{uid}_{int(time.time()*1000)}",
            uid       = uid,
            symbol    = sym,
            kind      = kind,
            target    = target,
            ref_price = ref_price,
            created   = time.time(),
            note      = note,
        )
        self._alerts.append(alert)
        self._save()
        return alert

    def remove(self, uid: int, alert_id: str) -> bool:
        for a in self._alerts:
            if a.uid == uid and a.id == alert_id:
                a.triggered = True
                self._save()
                return True
        return False

    def remove_by_index(self, uid: int, idx: int) -> bool:
        user_alerts = [a for a in self._alerts if a.uid == uid and not a.triggered]
        if 0 <= idx < len(user_alerts):
            user_alerts[idx].triggered = True
            self._save()
            return True
        return False

    def get_user_alerts(self, uid: int) -> List[PriceAlert]:
        return [a for a in self._alerts if a.uid == uid and not a.triggered]

    def get_all_active(self) -> List[PriceAlert]:
        return [a for a in self._alerts if not a.triggered]

    # ── Check trigger ─────────────────────────────────────────────
    def check(
        self,
        alert: PriceAlert,
        current_price: float,
        current_rsi: float = 50.0,
    ) -> bool:
        if alert.triggered:
            return False

        triggered = False
        if alert.kind == "price_above" and current_price >= alert.target:
            triggered = True
        elif alert.kind == "price_below" and current_price <= alert.target:
            triggered = True
        elif alert.kind == "rsi_above" and current_rsi >= alert.target:
            triggered = True
        elif alert.kind == "rsi_below" and current_rsi <= alert.target:
            triggered = True
        elif alert.kind == "pct_move" and alert.ref_price > 0:
            move = abs(current_price - alert.ref_price) / alert.ref_price * 100
            if move >= alert.target:
                triggered = True

        if triggered:
            alert.triggered = True
            self._save()
        return triggered

    # ── Formatting ────────────────────────────────────────────────
    def format_user_alerts(self, uid: int) -> str:
        alerts = self.get_user_alerts(uid)
        if not alerts:
            return (
                "🔔 *Твои алерты:* пусто\n\n"
                "Добавить: `/alert BTCUSDT above 70000`\n"
                "Типы: `above` `below` `rsi_above` `rsi_below` `move 5`"
            )

        lines = [f"🔔 *Твои алерты* ({len(alerts)}/{MAX_ALERTS_PER_USER}):"]
        kind_labels = {
            "price_above": "цена >",
            "price_below": "цена <",
            "rsi_above":   "RSI >",
            "rsi_below":   "RSI <",
            "pct_move":    "движение ≥",
        }
        for i, a in enumerate(alerts, 1):
            sym    = a.symbol.replace("_USDT", "")
            label  = kind_labels.get(a.kind, a.kind)
            suffix = "%" if a.kind in ("rsi_above", "rsi_below", "pct_move") else ""
            note   = f" — {a.note}" if a.note else ""
            lines.append(f"{i}. `{sym}` {label} `{a.target}{suffix}`{note}")

        lines.append("\nУдалить: `/alert del 1`")
        return "\n".join(lines)

    def format_trigger(self, alert: PriceAlert, current_price: float) -> str:
        sym  = alert.symbol.replace("_USDT", "")
        kind_text = {
            "price_above": f"цена пробила ↑ `${alert.target:,.4f}`",
            "price_below": f"цена пробила ↓ `${alert.target:,.4f}`",
            "rsi_above":   f"RSI превысил `{alert.target}`",
            "rsi_below":   f"RSI упал ниже `{alert.target}`",
            "pct_move":    f"движение `{alert.target}%` от `${alert.ref_price:,.4f}`",
        }.get(alert.kind, alert.kind)

        note = f"\n💬 _{alert.note}_" if alert.note else ""
        return (
            f"🔔 *АЛЕРТ СРАБОТАЛ!*\n"
            f"{'─' * 28}\n"
            f"💎 `{sym}/USDT` — {kind_text}\n"
            f"📍 Текущая цена: `${current_price:,.4f}`"
            f"{note}"
        )


# Singleton
alert_manager = AlertManager()
