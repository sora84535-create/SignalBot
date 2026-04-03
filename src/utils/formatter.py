"""
Telegram Message Formatter
===========================
All message templates for signals, spreads, news, BTC indicator, etc.
Mimics the professional channel format shown in the screenshots.
"""

from __future__ import annotations

import math
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.signals.btc_signal import BTCSignal
    from src.signals.scanner import CoinSignal
    from src.spread.scanner import SpreadAlert
    from src.news.fetcher import NewsItem


def _fmt_price(p: float) -> str:
    """Smart price formatting."""
    if p == 0:
        return "N/A"
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    if p >= 0.001:
        return f"${p:.5f}"
    return f"${p:.8f}"


def _fmt_vol(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:.0f}"


def _confidence_bar(score: int) -> str:
    filled = math.ceil(score / 10)
    return "█" * filled + "░" * (10 - filled)


def _direction_emoji(direction: str) -> str:
    return "🟢" if direction in ("LONG", "bullish") else "🔴"


def _tf_label(tf: str) -> str:
    labels = {
        "5m": "5 мин", "15m": "15 мин", "1h": "1 час",
        "4h": "4 часа", "1d": "Дневной",
    }
    return labels.get(tf, tf)


# ──────────────────────────────────────────────────────────────────
#  BTC Master Signal
# ──────────────────────────────────────────────────────────────────
def format_btc_signal(sig: "BTCSignal") -> str:
    emoji = "🚀" if sig.direction == "LONG" else "⚡"
    dir_text = "ЛОНГ" if sig.direction == "LONG" else "ШОРТ"
    color = "🟢" if sig.direction == "LONG" else "🔴"

    bar = _confidence_bar(sig.confidence)
    tf  = _tf_label(sig.timeframe)

    lines = [
        f"{'═' * 35}",
        f"₿ *BITCOIN СИГНАЛ* {emoji}",
        f"{'═' * 35}",
        f"",
        f"{color} Направление: *{dir_text}*",
        f"📊 Таймфрейм: `{tf}`",
        f"🎯 Уверенность: `{bar}` {sig.confidence}%",
        f"",
        f"💰 *Уровни входа/выхода:*",
        f"┌ Вход:  `{_fmt_price(sig.entry)}`",
        f"├ TP1:   `{_fmt_price(sig.tp1)}`",
        f"├ TP2:   `{_fmt_price(sig.tp2)}`",
        f"├ TP3:   `{_fmt_price(sig.tp3)}`",
        f"└ SL:    `{_fmt_price(sig.sl)}`",
        f"",
    ]

    # Risk/Reward
    if sig.sl != sig.entry:
        risk   = abs(sig.tp2 - sig.entry)
        reward = abs(sig.entry - sig.sl)
        rr     = risk / reward if reward > 0 else 0
        lines.append(f"⚖️ RR: `1:{rr:.1f}`")

    lines.append(f"")

    # Indicators
    lines.append(f"📈 *Индикаторы:*")
    rsi_emoji = "🔴" if sig.rsi > 70 else "🟢" if sig.rsi < 30 else "🟡"
    st_text   = "▲ Бычий" if sig.supertrend_dir == -1 else "▼ Медвежий"
    adx_str   = "Сильный" if sig.adx > 25 else "Слабый"
    macd_str  = "▲" if sig.macd_hist > 0 else "▼"

    lines += [
        f"• RSI: {rsi_emoji} `{sig.rsi:.1f}`",
        f"• ADX: `{sig.adx:.1f}` ({adx_str})",
        f"• Supertrend: `{st_text}`",
        f"• MACD hist: `{macd_str} {abs(sig.macd_hist):.4f}`",
        f"• Volume ratio: `{sig.vol_ratio:.1f}x`",
        f"• Funding rate: `{sig.funding_rate:+.4f}%`",
        f"",
    ]

    # Reasons
    if sig.reasons:
        lines.append(f"📋 *Причины:*")
        for r in sig.reasons[:4]:
            lines.append(f"• {r}")
        lines.append("")

    # SMC
    if sig.smc_reasons:
        lines.append(f"🏛 *SMC / ICT:*")
        for r in sig.smc_reasons[:3]:
            lines.append(f"• {r}")
        lines.append("")

    # Warnings
    if sig.warnings:
        lines.append(f"⚠️ *Предупреждения:*")
        for w in sig.warnings[:2]:
            lines.append(f"• {w}")
        lines.append("")

    lines.append(f"⏱ `Анализ обновляется каждые 5 мин`")
    lines.append(f"⚠️ _Не является финансовым советом. DYOR._")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
#  Coin Signal
# ──────────────────────────────────────────────────────────────────
def format_coin_signal(sig: "CoinSignal") -> str:
    emoji  = "🚀" if sig.direction == "LONG" else "💥"
    color  = "🟢" if sig.direction == "LONG" else "🔴"
    dir_ru = "ЛОНГ" if sig.direction == "LONG" else "ШОРТ"
    bar    = _confidence_bar(sig.confidence)
    base   = sig.symbol.replace("_USDT", "")

    lines = [
        f"{'─' * 32}",
        f"{emoji} *{base}/USDT* — {color} {dir_ru}",
        f"{'─' * 32}",
        f"",
        f"📊 Таймфрейм: `{_tf_label(sig.timeframe)}`",
        f"🎯 Уверенность: `{bar}` {sig.confidence}%",
        f"",
        f"💰 *Уровни:*",
        f"┌ Вход: `{_fmt_price(sig.entry)}`",
        f"├ TP1:  `{_fmt_price(sig.tp1)}`",
        f"├ TP2:  `{_fmt_price(sig.tp2)}`",
        f"└ SL:   `{_fmt_price(sig.sl)}`",
        f"",
    ]

    # Quick stats
    rsi_e = "🔴" if sig.rsi > 70 else "🟢" if sig.rsi < 30 else "🟡"
    lines += [
        f"📈 RSI: {rsi_e} `{sig.rsi:.1f}` | Vol: `{sig.vol_ratio:.1f}x`",
        f"📊 Funding: `{sig.funding:+.4f}%`",
        f"🏛 SMC trend: `{sig.trend_smc}`",
    ]

    flags = []
    if sig.fvg_present:
        flags.append("FVG ✅")
    if sig.bos_present:
        flags.append("BOS ✅")
    if flags:
        lines.append(f"🔑 {' | '.join(flags)}")

    lines.append("")

    # Reasons
    if sig.reasons:
        for r in sig.reasons[:3]:
            lines.append(f"• {r}")

    if sig.warnings:
        lines.append(f"")
        for w in sig.warnings[:2]:
            lines.append(f"⚠️ {w}")

    lines.append(f"")
    lines.append(f"_MEXC Futures — Не финансовый совет_")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
#  Spread Alert
# ──────────────────────────────────────────────────────────────────
def format_spread(alert: "SpreadAlert") -> str:
    color      = "🟢" if alert.direction == "LONG" else "🔴"
    dep_icon   = "🟢" if alert.deposit_ok  else "🔴"
    wd_icon    = "🟢" if alert.withdraw_ok else "🔴"
    chain_low  = alert.chain.lower()

    lines = [
        f"{color} {'LONG?' if alert.direction == 'LONG' else 'SHORT?'} "
        f"#{alert.symbol} Spread {alert.spread_pct:.2f}% detected",
        f"💥 Origin: {alert.origin} "
        f"[M: {((alert.mexc_price/alert.dex_price-1)*100):+.0f}% VS D: 0%]",
        f"💎 {alert.symbol} #{alert.symbol}_USDT (COPY: {alert.symbol})",
        f"",
        f"🌐 Price DEX     `{_fmt_price(alert.dex_price)}`",
        f"🎰 Price MEXC  `{_fmt_price(alert.mexc_price)}`",
        f"",
    ]

    # Max size (rough)
    max_size_tokens = int(alert.liquidity / alert.dex_price * 0.15) if alert.dex_price > 0 else 0
    max_size_usd    = alert.liquidity * 0.15

    lines += [
        f"⚖️ Max Size: {max_size_tokens:,} ${alert.symbol} ({_fmt_vol(max_size_usd)})",
        f"💹 Funding Rate: `{alert.funding_rate:+.4f}%`",
        f"",
        f"🏦 Market Cap: {_fmt_vol(alert.market_cap)}",
        f"💰 Liquidity: {_fmt_vol(alert.liquidity)}",
        f"💸 Vol DEX/MEXC: {_fmt_vol(alert.vol_dex)} / {_fmt_vol(alert.vol_mexc)}",
        f"",
        f"⛓️ #{alert.chain} "
        f"Dep: {dep_icon} ({alert.deposit_conf}) "
        f"W/d: {wd_icon}",
    ]

    if alert.contract:
        lines.append(f"`{alert.contract}`")

    lines += [
        f"",
        f"⏳ Avg Align Time: {alert.avg_align_sec}s",
        f"📊 Avg Spread / Max / Change: ±{alert.avg_spread:.0f}% / ±{alert.max_spread:.0f}% / ±2%",
    ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
#  News
# ──────────────────────────────────────────────────────────────────
def format_news(news: "NewsItem") -> str:
    cat_icons = {
        "geopolitical": "🌍",
        "crypto":       "₿",
        "macro":        "📊",
        "general":      "📰",
    }
    imp_icons = {
        "high":   "🔴",
        "medium": "🟡",
    }

    icon    = cat_icons.get(news.category, "📰")
    imp_ico = imp_icons.get(news.importance, "🟡")
    cat_ru  = {
        "geopolitical": "Геополитика",
        "crypto":       "Крипто",
        "macro":        "Макро",
        "general":      "Новости",
    }.get(news.category, "Новости")

    lines = [
        f"{imp_ico} {icon} *{cat_ru.upper()}* — Важная новость",
        f"",
        f"📌 *{news.title}*",
    ]

    if news.summary:
        # Truncate summary
        summary = news.summary[:250]
        if len(news.summary) > 250:
            summary += "..."
        lines.append(f"")
        lines.append(f"_{summary}_")

    lines += [
        f"",
        f"🔗 [{news.source}]({news.url})",
        f"🕐 {news.published[:16] if news.published else ''}",
    ]

    if news.keywords:
        kw = " ".join(f"#{k.replace(' ', '_')}" for k in news.keywords[:4])
        lines.append(f"🏷 {kw}")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
#  Multi-TF Analysis Summary
# ──────────────────────────────────────────────────────────────────
def format_mtf_analysis(results: dict) -> str:
    lines = [
        "🔭 *MULTI-TIMEFRAME BTC ANALYSIS*",
        f"{'─' * 32}",
    ]
    for tf, sig in results.items():
        tf_label = _tf_label(tf)
        if sig is None:
            lines.append(f"• {tf_label}: `Нет сигнала`")
        else:
            color = "🟢" if sig.direction == "LONG" else "🔴"
            lines.append(
                f"{color} {tf_label}: `{sig.direction}` "
                f"({sig.confidence}%) entry: `{_fmt_price(sig.entry)}`"
            )
    lines.append(f"{'─' * 32}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
#  Welcome / Help
# ──────────────────────────────────────────────────────────────────
WELCOME_MESSAGE = """
🤖 *MEXC Signal Bot v3.0*
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 *Что умеет бот:*

₿ *BTC Сигналы*
└ `/btc` — Сигнал по Bitcoin (15m/1h/4h)
└ `/btc_mtf` — Multi-timeframe анализ

📈 *Сигналы альткоинов*
└ `/scan` — Скан топ монет
└ `/signal <пара>` — Сигнал по монете
└ `/watchlist` — Мониторинг списка

💹 *Спред-арбитраж*
└ `/spread` — Спреды > 10% (MEXC vs DEX)
└ `/spread_scan` — Полный скан

📰 *Новости*
└ `/news` — Важные новости (геополитика, крипто)
└ `/geo` — Только геополитика

🤖 *ИИ Ассистент (Groq)*
└ `/ai <вопрос>` — Задать вопрос ИИ
└ `/ai_clear` — Очистить историю

📊 *Анализ*
└ `/smc <пара>` — SMC анализ (BOS/FVG/OB)
└ `/market` — Обзор рынка

⚙️ *Настройки*
└ `/set_tf <5m|15m|1h|4h>` — Таймфрейм
└ `/set_min <50-90>` — Мин. уверенность
└ `/status` — Статус бота

━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ _Не является финансовым советом.
Всегда управляйте рисками!_
"""

STATUS_TEMPLATE = """
⚙️ *Статус бота*
━━━━━━━━━━━━━━━━━━
• Версия: `v3.0`
• Uptime: `{uptime}`
• Сканирований: `{scans}`
• Сигналов отправлено: `{signals_sent}`
• Спредов найдено: `{spreads_found}`
• Новостей: `{news_sent}`
━━━━━━━━━━━━━━━━━━
• Min. confluence: `{min_score}%`
• Cooldown: `{cooldown} мин`
• Таймфрейм: `{timeframe}`
"""
