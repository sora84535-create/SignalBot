"""
Main Telegram Bot
==================
Handles all commands, inline keyboards, scheduled tasks.
Uses python-telegram-bot v20+ (async).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from config.settings import settings
from src.signals.btc_signal import btc_signal_engine, BTCSignal
from src.signals.scanner import coin_scanner, CoinSignal
from src.spread.scanner import spread_scanner
from src.news.fetcher import news_fetcher
from src.ai.groq_assistant import groq_ai
from src.analyzers.market_context import market_ctx
from src.utils.formatter import (
    format_btc_signal, format_coin_signal, format_spread,
    format_news, format_mtf_analysis,
    WELCOME_MESSAGE, STATUS_TEMPLATE,
)
from src.utils.user_settings import user_settings
from src.utils.rate_limiter import rate_limiter
from src.utils.logger import setup_logger
from src.bot_ext import (
    cmd_watch, cmd_risk, cmd_alert, cmd_settings,
    cmd_set_account, cmd_set_risk_pct, cmd_toggle,
    cmd_market_overview, job_check_alerts,
)

logger = setup_logger("bot")


# ──────────────────────────────────────────────────────────────────
#  Bot state
# ──────────────────────────────────────────────────────────────────
class BotState:
    start_time:      float = time.time()
    scans:           int   = 0
    signals_sent:    int   = 0
    spreads_found:   int   = 0
    news_sent:       int   = 0
    user_settings:   Dict[int, dict] = {}

    def get_user_tf(self, uid: int) -> str:
        return self.user_settings.get(uid, {}).get("timeframe", "1h")

    def get_user_score(self, uid: int) -> int:
        return self.user_settings.get(uid, {}).get("min_score", settings.MIN_CONFLUENCE_SCORE)

    def set_user(self, uid: int, key: str, val):
        if uid not in self.user_settings:
            self.user_settings[uid] = {}
        self.user_settings[uid][key] = val


state = BotState()


# ──────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────
async def send_safe(context: ContextTypes.DEFAULT_TYPE, chat_id, text: str, **kwargs):
    try:
        await rate_limiter.acquire(chat_id)
        kwargs.setdefault("parse_mode", ParseMode.MARKDOWN)
        kwargs.setdefault("disable_web_page_preview", True)
        await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except Exception as e:
        logger.error("send_safe error: %s", e)


def uptime_str() -> str:
    secs = int(time.time() - state.start_time)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}ч {m}м {s}с"


# ──────────────────────────────────────────────────────────────────
#  Command handlers
# ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("₿ BTC Сигнал",   callback_data="btc_1h"),
             InlineKeyboardButton("📊 Скан монет",   callback_data="scan_15m")],
            [InlineKeyboardButton("💹 Спреды",       callback_data="spread"),
             InlineKeyboardButton("📰 Новости",      callback_data="news")],
            [InlineKeyboardButton("🤖 ИИ Ассистент", callback_data="ai_help"),
             InlineKeyboardButton("⚙️ Статус",       callback_data="status")],
        ]),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode=ParseMode.MARKDOWN)


async def cmd_btc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tf  = state.get_user_tf(uid)

    msg = await update.message.reply_text(f"⏳ Анализирую BTC/{tf}...")

    try:
        sig = await btc_signal_engine.get_signal(tf)
        if sig is None:
            await msg.edit_text(
                f"⚠️ BTC: нет сигнала на `{tf}` (уверенность ниже порога или рынок в диапазоне)",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        text = format_btc_signal(sig)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить",     callback_data=f"btc_{tf}"),
             InlineKeyboardButton("📊 Multi-TF",     callback_data="btc_mtf")],
            [InlineKeyboardButton("🤖 Спросить ИИ", callback_data=f"ai_btc_{tf}")],
        ])
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
                            disable_web_page_preview=True)
        state.signals_sent += 1
    except Exception as e:
        logger.error("cmd_btc: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_btc_mtf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Анализирую BTC на 15m / 1h / 4h...")
    try:
        results = await btc_signal_engine.multi_tf_analysis()
        text    = format_mtf_analysis(results)
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tf  = state.get_user_tf(uid) if state.get_user_tf(uid) in ("5m", "15m") else "15m"
    msg = await update.message.reply_text(f"🔍 Сканирую топ монет на `{tf}`...", parse_mode=ParseMode.MARKDOWN)

    try:
        signals = await coin_scanner.scan_all(tf)
        state.scans += 1

        if not signals:
            await msg.edit_text("😴 Нет сигналов. Рынок в диапазоне или низкие объёмы.")
            return

        await msg.edit_text(
            f"✅ Найдено *{len(signals)}* сигналов! Отправляю...",
            parse_mode=ParseMode.MARKDOWN,
        )

        for sig in signals[:5]:    # top 5
            text = format_coin_signal(sig)
            await send_safe(ctx, update.effective_chat.id, text)
            await asyncio.sleep(0.3)

        state.signals_sent += len(signals[:5])
    except Exception as e:
        logger.error("cmd_scan: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Ошибка скана: {e}")


async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Usage: /signal BTCUSDT [15m]"""
    args = ctx.args or []
    if not args:
        await update.message.reply_text("Использование: `/signal BTCUSDT [15m]`",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    symbol = args[0].upper().replace("/", "_").replace("USDT", "_USDT")
    if not symbol.endswith("_USDT"):
        symbol += "_USDT"
    tf = args[1] if len(args) > 1 else "15m"

    msg = await update.message.reply_text(f"⏳ Анализирую `{symbol}` [{tf}]...",
                                          parse_mode=ParseMode.MARKDOWN)
    try:
        sig = await coin_scanner._analyse_coin(symbol, tf)
        if sig is None:
            await msg.edit_text(
                f"⚠️ `{symbol}`: нет сигнала. Уверенность ниже {settings.MIN_CONFLUENCE_SCORE}%",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        text = format_coin_signal(sig)
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        state.signals_sent += 1
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_spread(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        f"⏳ Ищу спреды > {settings.MIN_SPREAD_PCT}% на MEXC vs DEX..."
    )
    try:
        result = await spread_scanner.scan()
        if not result.alerts:
            await msg.edit_text(
                f"😴 Нет спредов > {settings.MIN_SPREAD_PCT}% в данный момент.\n"
                f"Проверено {result.scanned} пар."
            )
            return

        await msg.edit_text(
            f"💥 Найдено *{len(result.alerts)}* спредов! Отправляю...",
            parse_mode=ParseMode.MARKDOWN,
        )
        for alert in result.alerts[:3]:
            text = format_spread(alert)
            await send_safe(ctx, update.effective_chat.id, text)
            await asyncio.sleep(0.3)
        state.spreads_found += len(result.alerts)
    except Exception as e:
        logger.error("cmd_spread: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Загружаю важные новости...")
    try:
        items = await news_fetcher.fetch()
        if not items:
            await msg.edit_text("😴 Нет новых важных новостей.")
            return
        await msg.delete()
        for item in items[:5]:
            text = format_news(item)
            await send_safe(ctx, update.effective_chat.id, text)
            await asyncio.sleep(0.3)
        state.news_sent += len(items[:5])
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_geo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Загружаю геополитические новости...")
    try:
        items = await news_fetcher.fetch_high_only()
        geo   = [i for i in items if i.category == "geopolitical"]
        if not geo:
            await msg.edit_text("😴 Нет актуальных геополитических новостей.")
            return
        await msg.delete()
        for item in geo[:4]:
            text = format_news(item)
            await send_safe(ctx, update.effective_chat.id, text)
            await asyncio.sleep(0.3)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_smc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Usage: /smc BTCUSDT [1h]"""
    from src.smc.engine import smc_engine
    from src.indicators.engine import indicator_engine

    args = ctx.args or []
    symbol = (args[0].upper().replace("/", "_").replace("USDT", "_USDT")
              if args else "BTCUSDT")
    if not symbol.endswith("_USDT"):
        symbol += "_USDT"
    tf = args[1] if len(args) > 1 else "1h"

    TF_MAP = {"5m": "Min5", "15m": "Min15", "1h": "Min60", "4h": "Hour4", "1d": "Day1"}
    interval = TF_MAP.get(tf, "Min60")

    msg = await update.message.reply_text(f"⏳ SMC анализ `{symbol}` [{tf}]...",
                                          parse_mode=ParseMode.MARKDOWN)
    try:
        from src.utils.mexc_client import mexc
        raw = await mexc.get_futures_klines(symbol, interval, 200)
        klines = coin_scanner._norm(raw)
        ind = indicator_engine.analyze(klines, tf)
        if ind is None:
            await msg.edit_text("❌ Недостаточно данных.")
            return

        smc = smc_engine.analyze(ind.df)
        base = symbol.replace("_USDT", "")
        close = float(ind.last["close"])

        lines = [
            f"🏛 *SMC АНАЛИЗ — {base}/USDT* [{tf}]",
            f"{'─' * 32}",
            f"",
            f"📍 Цена: `${close:,.4f}`",
            f"🧭 Структура: `{smc.trend.upper()}`",
            f"🎯 Bias: `{smc.entry_bias.upper()}`",
            f"",
        ]

        if smc.last_bos:
            bos = smc.last_bos
            ch_label = "CHoCH 🔄 (РАЗВОРОТ)" if bos.is_choch else "BOS (продолжение)"
            lines += [
                f"{'🔼' if bos.direction == 'bullish' else '🔽'} *{ch_label}*",
                f"Уровень: `${bos.level:,.4f}` | Сила: `{bos.strength:.2f} ATR`",
                f"",
            ]

        if smc.last_fvg:
            fvg = smc.last_fvg
            filled_str = "✅ заполнен" if fvg.filled else "⚡ открыт"
            lines += [
                f"📊 *FVG ({fvg.direction})*: `${fvg.bottom:,.4f}–${fvg.top:,.4f}` {filled_str}",
            ]

        if smc.last_ob:
            ob = smc.last_ob
            lines += [
                f"🏦 *Order Block ({ob.direction})*: `${ob.bottom:,.4f}–${ob.top:,.4f}`",
            ]

        if smc.poi_zone:
            lines += [
                f"",
                f"🎯 *POI зона*: `${smc.poi_zone[0]:,.4f}–${smc.poi_zone[1]:,.4f}`",
            ]

        if smc.last_sweep:
            sw = smc.last_sweep
            rev = "🔄 разворот подтверждён" if sw.reversal else "⏳ разворот ожидается"
            lines += [
                f"",
                f"💧 *Sweep {sw.direction}* @ `${sw.level:,.4f}` — {rev}",
            ]

        if smc.signals:
            lines.append("")
            lines.append("📋 *Сигналы:*")
            for s in smc.signals[:4]:
                lines.append(f"• {s}")

        lines.append(f"\n_Скор SMC: {smc.score}/100_")
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True)
    except Exception as e:
        logger.error("cmd_smc: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cmd_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Использование: `/ai <вопрос>`\nПример: `/ai Стоит ли шортить BTC сейчас?`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    question = " ".join(ctx.args)
    uid      = update.effective_user.id
    msg      = await update.message.reply_text("🤖 ИИ думает...")

    try:
        # Gather minimal market context
        market_data = {}
        try:
            from src.utils.mexc_client import mexc
            ticker = await mexc.get_futures_ticker("BTCUSDT")
            market_data["btc_price"] = float(ticker.get("lastPrice", 0))
        except Exception:
            pass

        answer = await groq_ai.ask(uid, question, market_data)
        await msg.edit_text(f"🤖 *ИИ Ассистент:*\n\n{answer}",
                            parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка ИИ: {e}")


async def cmd_ai_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    groq_ai.clear_history(uid)
    await update.message.reply_text("✅ История разговора с ИИ очищена.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = STATUS_TEMPLATE.format(
        uptime        = uptime_str(),
        scans         = state.scans,
        signals_sent  = state.signals_sent,
        spreads_found = state.spreads_found,
        news_sent     = state.news_sent,
        min_score     = state.get_user_score(uid),
        cooldown      = settings.SIGNAL_COOLDOWN_MIN,
        timeframe     = state.get_user_tf(uid),
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_set_tf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    valid = ("5m", "15m", "1h", "4h", "1d")
    if not ctx.args or ctx.args[0] not in valid:
        await update.message.reply_text(
            f"Использование: `/set_tf {'|'.join(valid)}`", parse_mode=ParseMode.MARKDOWN
        )
        return
    uid = update.effective_user.id
    state.set_user(uid, "timeframe", ctx.args[0])
    await update.message.reply_text(f"✅ Таймфрейм установлен: `{ctx.args[0]}`",
                                    parse_mode=ParseMode.MARKDOWN)


async def cmd_set_min(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: `/set_min 65`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        val = int(ctx.args[0])
        assert 30 <= val <= 95
    except Exception:
        await update.message.reply_text("❌ Значение от 30 до 95")
        return
    uid = update.effective_user.id
    state.set_user(uid, "min_score", val)
    await update.message.reply_text(f"✅ Мин. уверенность: `{val}%`",
                                    parse_mode=ParseMode.MARKDOWN)


async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Анализ рынка...")
    try:
        from src.utils.mexc_client import mexc
        tickers = await mexc.get_all_futures_tickers()

        gainers = sorted(
            [t for t in tickers if isinstance(t.get("priceChangePercent"), (int, float))],
            key=lambda x: float(x.get("priceChangePercent", 0)),
            reverse=True,
        )

        top5_g = gainers[:5]
        top5_l = gainers[-5:][::-1]

        lines = [
            "📊 *ОБЗОР РЫНКА — MEXC FUTURES*",
            f"{'─' * 32}",
            "",
            "🚀 *Топ роста:*",
        ]
        for t in top5_g:
            sym = t.get("symbol", "").replace("_USDT", "")
            pct = float(t.get("priceChangePercent", 0))
            lines.append(f"  • `{sym}` +{pct:.2f}%")

        lines += ["", "💥 *Топ падения:*"]
        for t in top5_l:
            sym = t.get("symbol", "").replace("_USDT", "")
            pct = float(t.get("priceChangePercent", 0))
            lines.append(f"  • `{sym}` {pct:.2f}%")

        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


# ──────────────────────────────────────────────────────────────────
#  Callback query handler
# ──────────────────────────────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("btc_"):
        tf = data.replace("btc_", "")
        if tf == "mtf":
            results = await btc_signal_engine.multi_tf_analysis()
            text    = format_mtf_analysis(results)
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        else:
            sig = await btc_signal_engine.get_signal(tf)
            if sig:
                text = format_btc_signal(sig)
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Обновить", callback_data=f"btc_{tf}"),
                    InlineKeyboardButton("📊 Multi-TF", callback_data="btc_mtf"),
                ]])
                await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=kb, disable_web_page_preview=True)
            else:
                await query.edit_message_text(f"⚠️ BTC: нет сигнала на `{tf}`",
                                              parse_mode=ParseMode.MARKDOWN)

    elif data == "scan_15m":
        await query.edit_message_text("⏳ Сканирую монеты...", parse_mode=ParseMode.MARKDOWN)
        signals = await coin_scanner.scan_all("15m")
        if signals:
            for sig in signals[:3]:
                await send_safe(ctx, query.message.chat_id, format_coin_signal(sig))
        else:
            await send_safe(ctx, query.message.chat_id, "😴 Нет сигналов в данный момент.")

    elif data == "spread":
        await query.edit_message_text("⏳ Сканирую спреды...", parse_mode=ParseMode.MARKDOWN)
        result = await spread_scanner.scan()
        if result.alerts:
            for a in result.alerts[:2]:
                await send_safe(ctx, query.message.chat_id, format_spread(a))
        else:
            await send_safe(ctx, query.message.chat_id,
                            f"😴 Нет спредов > {settings.MIN_SPREAD_PCT}%")

    elif data == "news":
        items = await news_fetcher.fetch()
        if items:
            for item in items[:3]:
                await send_safe(ctx, query.message.chat_id, format_news(item))
        else:
            await send_safe(ctx, query.message.chat_id, "😴 Нет новостей.")

    elif data == "status":
        uid = update.effective_user.id
        text = STATUS_TEMPLATE.format(
            uptime=uptime_str(), scans=state.scans, signals_sent=state.signals_sent,
            spreads_found=state.spreads_found, news_sent=state.news_sent,
            min_score=state.get_user_score(uid), cooldown=settings.SIGNAL_COOLDOWN_MIN,
            timeframe=state.get_user_tf(uid),
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

    elif data == "ai_help":
        await send_safe(ctx, query.message.chat_id,
                        "🤖 *ИИ Ассистент*\n\nИспользование: `/ai <вопрос>`\n"
                        "Например: `/ai Стоит ли шортить BTC сейчас?`",
                        parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("ai_btc_"):
        tf = data.replace("ai_btc_", "")
        uid = update.effective_user.id
        sig = await btc_signal_engine.get_signal(tf)
        market_data = {}
        if sig:
            market_data["btc_signal"] = {
                "direction": sig.direction, "confidence": sig.confidence,
                "entry": sig.entry, "rsi": sig.rsi,
            }
        answer = await groq_ai.ask(uid,
            f"Текущий сигнал BTC {tf}: {sig.direction if sig else 'N/A'}. "
            f"Что скажешь? Стоит ли входить?",
            market_data,
        )
        await send_safe(ctx, query.message.chat_id,
                        f"🤖 *ИИ по BTC:*\n\n{answer}",
                        parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────────
#  Scheduled jobs
# ──────────────────────────────────────────────────────────────────
async def job_auto_signals(context: ContextTypes.DEFAULT_TYPE):
    """Auto-scan and send signals every N minutes."""
    if not settings.TELEGRAM_CHAT_ID:
        return
    try:
        signals = await coin_scanner.scan_all("15m")
        for sig in signals[:3]:
            if sig.confidence >= settings.MIN_CONFLUENCE_SCORE + 5:  # higher bar for auto
                text = format_coin_signal(sig)
                await send_safe(context, settings.TELEGRAM_CHAT_ID, text)
                await asyncio.sleep(1)
        state.scans += 1
    except Exception as e:
        logger.error("job_auto_signals: %s", e)


async def job_btc_monitor(context: ContextTypes.DEFAULT_TYPE):
    """Send BTC signal if strong."""
    if not settings.TELEGRAM_CHAT_ID:
        return
    try:
        sig = await btc_signal_engine.get_signal("1h")
        if sig and sig.confidence >= 75:
            text = format_btc_signal(sig)
            await send_safe(context, settings.TELEGRAM_CHAT_ID, text)
            state.signals_sent += 1
    except Exception as e:
        logger.error("job_btc_monitor: %s", e)


async def job_news(context: ContextTypes.DEFAULT_TYPE):
    """Auto-send high importance news."""
    if not settings.TELEGRAM_CHAT_ID:
        return
    try:
        items = await news_fetcher.fetch_high_only()
        for item in items[:2]:
            text = format_news(item)
            await send_safe(context, settings.TELEGRAM_CHAT_ID, text)
            await asyncio.sleep(0.5)
        if items:
            state.news_sent += len(items[:2])
    except Exception as e:
        logger.error("job_news: %s", e)


async def job_spread(context: ContextTypes.DEFAULT_TYPE):
    """Auto spread scanner."""
    if not settings.TELEGRAM_CHAT_ID:
        return
    try:
        result = await spread_scanner.scan()
        for alert in result.alerts[:2]:
            if alert.spread_pct >= settings.MIN_SPREAD_PCT:
                text = format_spread(alert)
                await send_safe(context, settings.TELEGRAM_CHAT_ID, text)
                await asyncio.sleep(0.5)
        if result.alerts:
            state.spreads_found += len(result.alerts)
    except Exception as e:
        logger.error("job_spread: %s", e)


# ──────────────────────────────────────────────────────────────────
#  Bot class
# ──────────────────────────────────────────────────────────────────
class TelegramBot:

    def __init__(self):
        self._app: Optional[Application] = None

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN not set!")

        self._app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        app = self._app

        # Commands
        app.add_handler(CommandHandler("start",    cmd_start))
        app.add_handler(CommandHandler("help",     cmd_help))
        app.add_handler(CommandHandler("btc",      cmd_btc))
        app.add_handler(CommandHandler("btc_mtf",  cmd_btc_mtf))
        app.add_handler(CommandHandler("scan",     cmd_scan))
        app.add_handler(CommandHandler("signal",   cmd_signal))
        app.add_handler(CommandHandler("spread",   cmd_spread))
        app.add_handler(CommandHandler("spread_scan", cmd_spread))
        app.add_handler(CommandHandler("news",     cmd_news))
        app.add_handler(CommandHandler("geo",      cmd_geo))
        app.add_handler(CommandHandler("smc",      cmd_smc))
        app.add_handler(CommandHandler("ai",       cmd_ai))
        app.add_handler(CommandHandler("ai_clear", cmd_ai_clear))
        app.add_handler(CommandHandler("status",   cmd_status))
        app.add_handler(CommandHandler("market",   cmd_market))
        app.add_handler(CommandHandler("set_tf",   cmd_set_tf))
        app.add_handler(CommandHandler("set_min",  cmd_set_min))
        # ── Extended ───────────────────────────────────────────────
        app.add_handler(CommandHandler("watch",        cmd_watch))
        app.add_handler(CommandHandler("risk",         cmd_risk))
        app.add_handler(CommandHandler("alert",        cmd_alert))
        app.add_handler(CommandHandler("settings",     cmd_settings))
        app.add_handler(CommandHandler("set_account",  cmd_set_account))
        app.add_handler(CommandHandler("set_risk",     cmd_set_risk_pct))
        app.add_handler(CommandHandler("toggle",       cmd_toggle))
        app.add_handler(CommandHandler("overview",     cmd_market_overview))

        # Callbacks
        app.add_handler(CallbackQueryHandler(callback_handler))

        # Schedules
        jq = app.job_queue
        if jq:
            jq.run_repeating(job_auto_signals, interval=settings.SIGNAL_SCAN_INTERVAL,  first=60)
            jq.run_repeating(job_btc_monitor,  interval=settings.SIGNAL_SCAN_INTERVAL,  first=90)
            jq.run_repeating(job_news,         interval=settings.NEWS_SCAN_INTERVAL,    first=30)
            jq.run_repeating(job_spread,       interval=settings.SPREAD_SCAN_SEC,       first=120)
            jq.run_repeating(job_check_alerts, interval=60,                             first=15)

        # Set bot commands
        commands = [
            BotCommand("start",      "Главное меню"),
            BotCommand("btc",        "BTC сигнал"),
            BotCommand("btc_mtf",    "Multi-TF BTC анализ"),
            BotCommand("scan",       "Скан монет"),
            BotCommand("signal",     "Сигнал по монете"),
            BotCommand("spread",     "Спред-арбитраж"),
            BotCommand("news",       "Важные новости"),
            BotCommand("geo",        "Геополитика"),
            BotCommand("smc",        "SMC анализ"),
            BotCommand("ai",         "ИИ ассистент"),
            BotCommand("market",     "Обзор рынка"),
            BotCommand("status",     "Статус бота"),
            BotCommand("set_tf",      "Установить таймфрейм"),
            BotCommand("set_min",     "Мин. уверенность"),
            BotCommand("watch",       "Вотчлист монет"),
            BotCommand("risk",        "Калькулятор риска"),
            BotCommand("alert",       "Ценовые алерты"),
            BotCommand("settings",    "Мои настройки"),
            BotCommand("set_account", "Размер депозита"),
            BotCommand("set_risk",    "Риск на сделку %"),
            BotCommand("toggle",      "Вкл/выкл авто-сигналы/новости"),
            BotCommand("overview",    "Обзор рынка + Fear&Greed"),
        ]
        await app.bot.set_my_commands(commands)

        logger.info("Bot started. Polling...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

    async def stop(self):
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.error("Stop error: %s", e)
        from src.utils.mexc_client import mexc
        await mexc.close()
        await groq_ai.close()
        await news_fetcher.close()
        await spread_scanner.close()
        await market_ctx.close()
        logger.info("Bot stopped.")
