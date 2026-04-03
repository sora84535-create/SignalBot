"""
Persistent User Settings
=========================
Stores user preferences in JSON so they survive bot restarts.

Settings per user:
  - timeframe (default: 1h)
  - min_score (default: 65)
  - auto_signals (bool)
  - auto_news (bool)
  - account_size (for risk calc)
  - risk_pct (default: 1.0)
  - language (ru/en)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from src.utils.logger import setup_logger

logger = setup_logger("user_settings")

STORAGE_FILE = "data/user_settings.json"

DEFAULTS: Dict[str, Any] = {
    "timeframe":    "1h",
    "min_score":    65,
    "auto_signals": True,
    "auto_news":    True,
    "account_size": 1000.0,
    "risk_pct":     1.0,
    "language":     "ru",
}


class UserSettings:

    def __init__(self):
        self._data: Dict[int, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        os.makedirs("data", exist_ok=True)
        if os.path.exists(STORAGE_FILE):
            try:
                with open(STORAGE_FILE) as f:
                    raw = json.load(f)
                self._data = {int(k): v for k, v in raw.items()}
            except Exception as e:
                logger.error("UserSettings load: %s", e)

    def _save(self):
        try:
            os.makedirs("data", exist_ok=True)
            with open(STORAGE_FILE, "w") as f:
                json.dump({str(k): v for k, v in self._data.items()}, f, indent=2)
        except Exception as e:
            logger.error("UserSettings save: %s", e)

    def get(self, uid: int, key: str) -> Any:
        return self._data.get(uid, {}).get(key, DEFAULTS.get(key))

    def set(self, uid: int, key: str, value: Any):
        if uid not in self._data:
            self._data[uid] = {}
        self._data[uid][key] = value
        self._save()

    def get_all(self, uid: int) -> Dict[str, Any]:
        base = dict(DEFAULTS)
        base.update(self._data.get(uid, {}))
        return base

    def format_settings(self, uid: int) -> str:
        s = self.get_all(uid)
        auto_sig  = "✅" if s["auto_signals"] else "❌"
        auto_news = "✅" if s["auto_news"]    else "❌"
        return (
            f"⚙️ *Твои настройки:*\n"
            f"{'─' * 28}\n"
            f"📊 Таймфрейм:        `{s['timeframe']}`\n"
            f"🎯 Мин. уверенность: `{s['min_score']}%`\n"
            f"💰 Депозит:          `${s['account_size']:,.0f}`\n"
            f"⚖️ Риск на сделку:   `{s['risk_pct']}%`\n"
            f"🤖 Авто-сигналы:     {auto_sig}\n"
            f"📰 Авто-новости:     {auto_news}\n\n"
            f"Изменить:\n"
            f"`/set_tf 15m` — таймфрейм\n"
            f"`/set_min 70` — мин. уверенность\n"
            f"`/set_account 5000` — депозит\n"
            f"`/set_risk 1.5` — риск %\n"
            f"`/toggle signals` — авто-сигналы вкл/выкл\n"
            f"`/toggle news` — авто-новости вкл/выкл"
        )


# Singleton
user_settings = UserSettings()
