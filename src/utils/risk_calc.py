"""
Risk & Position Size Calculator
=================================
Given account size, risk %, entry, SL → calculates:
  - Position size (contracts / USDT)
  - Leverage recommendation
  - TP1/TP2/TP3 at RR 1:1.5 / 1:2.5 / 1:4
  - Liquidation price estimate
  - Max loss in USDT

Also provides a quick /rr command for Risk:Reward calc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskCalcResult:
    # Inputs
    account:     float
    risk_pct:    float
    entry:       float
    sl:          float
    direction:   str       # "long" | "short"

    # Calculated
    risk_usdt:   float     # $ amount at risk
    sl_pct:      float     # % distance to SL
    position_usdt: float   # total position size in USDT
    leverage:    int       # recommended leverage
    liq_price:   float     # estimated liquidation price

    tp1:         float     # RR 1:1.5
    tp2:         float     # RR 1:2.5
    tp3:         float     # RR 1:4.0
    tp1_pct:     float
    tp2_pct:     float
    tp3_pct:     float

    rr1:         float = 1.5
    rr2:         float = 2.5
    rr3:         float = 4.0


def calculate_risk(
    account: float,
    risk_pct: float,
    entry: float,
    sl: float,
    direction: str = "long",
    rr1: float = 1.5,
    rr2: float = 2.5,
    rr3: float = 4.0,
) -> Optional[RiskCalcResult]:
    """
    Calculate position parameters.

    Args:
        account:   Account size in USDT
        risk_pct:  Risk per trade as % of account (e.g. 1.0 = 1%)
        entry:     Entry price
        sl:        Stop loss price
        direction: "long" or "short"
        rr1/2/3:   Risk:Reward ratios for TP1/2/3
    """
    if entry <= 0 or sl <= 0 or account <= 0 or risk_pct <= 0:
        return None

    if direction == "long" and sl >= entry:
        return None
    if direction == "short" and sl <= entry:
        return None

    # Risk in USDT
    risk_usdt = account * (risk_pct / 100)

    # SL distance
    sl_dist_abs = abs(entry - sl)
    sl_pct      = sl_dist_abs / entry * 100

    if sl_dist_abs == 0:
        return None

    # Position size (USDT) = risk_usdt / sl_pct_as_decimal
    position_usdt = risk_usdt / (sl_dist_abs / entry)

    # Recommended leverage (round down to common values)
    raw_lev = position_usdt / account
    lev_options = [1, 2, 3, 5, 7, 10, 15, 20, 25, 50, 75, 100]
    leverage = max(1, min([l for l in lev_options if l >= raw_lev], default=100,
                          key=lambda l: abs(l - raw_lev)))

    # Liquidation price (simplified, isolated margin)
    # Liq = entry - (entry / leverage) * maintenance_margin_factor
    maintenance = 0.005   # 0.5% typical
    if direction == "long":
        liq_price = entry * (1 - 1/leverage + maintenance)
    else:
        liq_price = entry * (1 + 1/leverage - maintenance)

    # TP levels
    if direction == "long":
        tp1 = entry + sl_dist_abs * rr1
        tp2 = entry + sl_dist_abs * rr2
        tp3 = entry + sl_dist_abs * rr3
    else:
        tp1 = entry - sl_dist_abs * rr1
        tp2 = entry - sl_dist_abs * rr2
        tp3 = entry - sl_dist_abs * rr3

    tp1_pct = abs(tp1 - entry) / entry * 100
    tp2_pct = abs(tp2 - entry) / entry * 100
    tp3_pct = abs(tp3 - entry) / entry * 100

    return RiskCalcResult(
        account       = account,
        risk_pct      = risk_pct,
        entry         = entry,
        sl            = sl,
        direction     = direction,
        risk_usdt     = round(risk_usdt, 2),
        sl_pct        = round(sl_pct, 3),
        position_usdt = round(position_usdt, 2),
        leverage      = leverage,
        liq_price     = round(liq_price, 4),
        tp1           = round(tp1, 6),
        tp2           = round(tp2, 6),
        tp3           = round(tp3, 6),
        tp1_pct       = round(tp1_pct, 3),
        tp2_pct       = round(tp2_pct, 3),
        tp3_pct       = round(tp3_pct, 3),
        rr1           = rr1,
        rr2           = rr2,
        rr3           = rr3,
    )


def format_risk_result(r: RiskCalcResult) -> str:
    dir_emoji = "🟢 LONG" if r.direction == "long" else "🔴 SHORT"
    dir_arrow = "▲" if r.direction == "long" else "▼"

    def fp(p):
        if p >= 1000: return f"${p:,.2f}"
        if p >= 1: return f"${p:.4f}"
        return f"${p:.8f}"

    lines = [
        "💰 *КАЛЬКУЛЯТОР РИСКА*",
        f"{'─' * 32}",
        f"",
        f"{dir_emoji}",
        f"",
        f"📊 *Параметры:*",
        f"┌ Депозит:   `${r.account:,.0f}`",
        f"├ Риск:      `{r.risk_pct}%` → `${r.risk_usdt:,.2f}`",
        f"├ Вход:      `{fp(r.entry)}`",
        f"└ SL:        `{fp(r.sl)}` ({r.sl_pct:.2f}% от входа)",
        f"",
        f"📐 *Позиция:*",
        f"┌ Размер:    `${r.position_usdt:,.2f}` USDT",
        f"├ Плечо:     `{r.leverage}×`",
        f"└ Ликвидация: `{fp(r.liq_price)}`",
        f"",
        f"🎯 *Тейк-профиты:*",
        f"┌ TP1 (RR {r.rr1}): `{fp(r.tp1)}` (+{r.tp1_pct:.2f}%) → `+${r.risk_usdt * r.rr1:,.2f}`",
        f"├ TP2 (RR {r.rr2}): `{fp(r.tp2)}` (+{r.tp2_pct:.2f}%) → `+${r.risk_usdt * r.rr2:,.2f}`",
        f"└ TP3 (RR {r.rr3}): `{fp(r.tp3)}` (+{r.tp3_pct:.2f}%) → `+${r.risk_usdt * r.rr3:,.2f}`",
        f"",
        f"⚠️ Макс. убыток: `-${r.risk_usdt:,.2f}` ({r.risk_pct}% депо)",
    ]
    return "\n".join(lines)
