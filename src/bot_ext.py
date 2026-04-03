"""
Extended command handlers — watchlist, risk, alerts, settings, market overview.
Imported and registered in bot.py.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from src.signals.scanner import coin_scanner
from src.analyzers.market_context import market_ctx
from src.utils.watchlist import watchlist
from src.utils.risk_calc import calculate_risk, format_risk_result
from src.utils.alert_manager import alert_manager
from src.utils.user_settings import user_settings
from src.utils.mexc_client import mexc
from src.utils.logger import setup_logger

logger = setup_logger("bot_ext")


# ── Watchlist ─────────────────────────────────────────────────────
async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /watch            — show list
    /watch add SYM    — add coin
    /watch del SYM    — remove coin
    /watch scan       — scan watchlist for signals
    /watch clear      — clear all
    """
    uid  = update.effective_user.id
    args = ctx.args or []

    if not args:
        await update.message.reply_text(
            watchlist.format_list(uid), parse_mode=ParseMode.MARKDOWN
        )
        return

    sub = args[0].lower()

    if sub == "add" and len(args) > 1:
        ok = watchlist.add(uid, args[1])
        if ok:
            base = args[1].upper().replace("USDT", "").replace("_", "")
            await update.message.reply_text(
                f"✅ `{base}/USDT` добавлен в вотчлист.", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Уже есть или достигнут лимит (20 монет).")

    elif sub in ("del", "remove") and len(args) > 1:
        ok = watchlist.remove(uid, args[1])
        await update.message.reply_text(
            "✅ Удалено." if ok else "❌ Не найдено в вотчлисте."
        )

    elif sub == "clear":
        watchlist.clear(uid)
        await update.message.reply_text("✅ Вотчлист очищен.")

    elif sub == "scan":
        syms = watchlist.get(uid)
        if not syms:
            await update.message.reply_text("📋 Вотчлист пуст. Добавь: `/watch add SOLUSDT`",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        tf  = user_settings.get(uid, "timeframe")
        msg = await update.message.reply_text(
            f"⏳ Сканирую {len(syms)} монет из вотчлиста на `{tf}`...",
            parse_mode=ParseMode.MARKDOWN,
        )
        from src.utils.formatter import format_coin_signal
        signals = await coin_scanner.scan_all(tf, syms)
        if not signals:
            await msg.edit_text("😴 Нет сигналов по вотчлисту.")
            return
        await msg.edit_text(f"✅ Найдено *{len(signals)}* сигналов:",
                            parse_mode=ParseMode.MARKDOWN)
        for sig in signals[:5]:
            await update.message.reply_text(
                format_coin_signal(sig), parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
    else:
        await update.message.reply_text(
            "📋 *Вотчлист команды:*\n"
            "`/watch` — показать список\n"
            "`/watch add SOLUSDT` — добавить\n"
            "`/watch del SOLUSDT` — удалить\n"
            "`/watch scan` — скан сигналов\n"
            "`/watch clear` — очистить",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Risk Calculator ───────────────────────────────────────────────
async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /risk <entry> <sl> [long|short] [account] [risk%]
    Example: /risk 67000 66500 long 1000 1
    """
    uid  = update.effective_user.id
    args = ctx.args or []

    if len(args) < 2:
        acct = user_settings.get(uid, "account_size")
        rsk  = user_settings.get(uid, "risk_pct")
        await update.message.reply_text(
            f"📐 *Калькулятор риска*\n\n"
            f"Использование: `/risk <вход> <sl> [long|short] [депозит] [риск%]`\n\n"
            f"Пример: `/risk 67000 66500 long {acct:.0f} {rsk}`\n\n"
            f"Текущие настройки:\n"
            f"• Депозит: `${acct:,.0f}` → /set\\_account\n"
            f"• Риск: `{rsk}%` → /set\\_risk",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        entry     = float(args[0])
        sl        = float(args[1])
        direction = "long"
        if len(args) > 2 and args[2].lower() in ("long", "short"):
            direction = args[2].lower()
        elif sl > entry:
            direction = "short"
        account  = float(args[3]) if len(args) > 3 else user_settings.get(uid, "account_size")
        risk_pct = float(args[4]) if len(args) > 4 else user_settings.get(uid, "risk_pct")

        result = calculate_risk(account, risk_pct, entry, sl, direction)
        if result is None:
            await update.message.reply_text(
                "❌ Ошибка: для лонга SL < вход, для шорта SL > вход."
            )
            return
        await update.message.reply_text(
            format_risk_result(result), parse_mode=ParseMode.MARKDOWN
        )
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Неверный формат. Пример: `/risk 67000 66500`",
                                        parse_mode=ParseMode.MARKDOWN)


# ── Price Alerts ──────────────────────────────────────────────────
async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /alert               — show my alerts
    /alert BTCUSDT above 70000 [note]
    /alert BTCUSDT below 65000
    /alert BTCUSDT rsi_above 70
    /alert BTCUSDT rsi_below 30
    /alert BTCUSDT move 5
    /alert del 1
    """
    uid  = update.effective_user.id
    args = ctx.args or []

    if not args:
        await update.message.reply_text(
            alert_manager.format_user_alerts(uid), parse_mode=ParseMode.MARKDOWN
        )
        return

    if args[0].lower() == "del":
        if len(args) < 2:
            await update.message.reply_text("Использование: `/alert del 1`",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        try:
            ok = alert_manager.remove_by_index(uid, int(args[1]) - 1)
            await update.message.reply_text("✅ Алерт удалён." if ok else "❌ Не найден.")
        except ValueError:
            await update.message.reply_text("❌ Укажи номер.")
        return

    if len(args) < 3:
        await update.message.reply_text(
            "🔔 *Как установить алерт:*\n"
            "`/alert BTCUSDT above 70000` — цена выше\n"
            "`/alert BTCUSDT below 65000` — цена ниже\n"
            "`/alert BTCUSDT rsi_above 70` — RSI выше\n"
            "`/alert BTCUSDT rsi_below 30` — RSI ниже\n"
            "`/alert BTCUSDT move 5` — движение ≥5%\n"
            "`/alert del 1` — удалить #1",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    sym      = args[0].upper()
    kind_raw = args[1].lower()
    kind_map = {
        "above": "price_above", "below": "price_below",
        "rsi_above": "rsi_above", "rsi_below": "rsi_below",
        "move": "pct_move",
    }
    kind = kind_map.get(kind_raw)
    if not kind:
        await update.message.reply_text(
            "❌ Тип: `above` `below` `rsi_above` `rsi_below` `move`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        target = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ Неверное числовое значение.")
        return

    note = " ".join(args[3:]) if len(args) > 3 else ""

    # Fetch current price for ref
    ref_price = 0.0
    try:
        clean = sym.replace("/", "").replace("_", "")
        if not clean.endswith("USDT"):
            clean += "USDT"
        ref_price = await mexc.get_spot_price(clean)
    except Exception:
        pass

    a = alert_manager.add(uid, sym, kind, target, ref_price, note)
    if a is None:
        await update.message.reply_text(
            "❌ Лимит 10 алертов. Удали старые: `/alert del N`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    kind_text = {
        "price_above": f"цена ≥ `${target:,.4f}`",
        "price_below": f"цена ≤ `${target:,.4f}`",
        "rsi_above":   f"RSI ≥ `{target}`",
        "rsi_below":   f"RSI ≤ `{target}`",
        "pct_move":    f"движение ≥ `{target}%`",
    }.get(kind, kind)

    await update.message.reply_text(
        f"🔔 Алерт установлен!\n`{sym}` — {kind_text}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Settings ──────────────────────────────────────────────────────
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        user_settings.format_settings(uid), parse_mode=ParseMode.MARKDOWN
    )


async def cmd_set_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Использование: `/set_account 5000`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    try:
        val = float(ctx.args[0])
        assert val > 0
        user_settings.set(uid, "account_size", val)
        await update.message.reply_text(f"✅ Депозит: `${val:,.0f}`",
                                        parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("❌ Неверное значение.")


async def cmd_set_risk_pct(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Использование: `/set_risk 1.5`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    try:
        val = float(ctx.args[0])
        assert 0.1 <= val <= 10
        user_settings.set(uid, "risk_pct", val)
        await update.message.reply_text(f"✅ Риск на сделку: `{val}%`",
                                        parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("❌ Значение от 0.1 до 10")


async def cmd_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = ctx.args or []
    if not args or args[0].lower() not in ("signals", "news"):
        await update.message.reply_text(
            "Использование: `/toggle signals` или `/toggle news`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    key     = f"auto_{args[0].lower()}"
    cur     = user_settings.get(uid, key)
    user_settings.set(uid, key, not cur)
    label   = "Авто-сигналы" if args[0].lower() == "signals" else "Авто-новости"
    status  = "включены ✅" if not cur else "выключены ❌"
    await update.message.reply_text(f"{label} {status}")


# ── Market Overview (extended) ────────────────────────────────────
async def cmd_market_overview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Загружаю обзор рынка...")
    try:
        data = await market_ctx.get()
        text = market_ctx.format(data)
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error("cmd_market_overview: %s", e)
        await msg.edit_text(f"❌ Ошибка: {e}")


# ── Alert check job ───────────────────────────────────────────────
async def job_check_alerts(context) -> None:
    """Check all active price alerts against current prices."""
    alerts = alert_manager.get_all_active()
    if not alerts:
        return

    # Group by symbol
    sym_map: dict = {}
    for a in alerts:
        sym_map.setdefault(a.symbol, []).append(a)

    for sym, sym_alerts in sym_map.items():
        try:
            clean = sym.replace("_", "")
            price = await mexc.get_spot_price(clean)
            if not price:
                continue

            for a in sym_alerts:
                if alert_manager.check(a, price):
                    text = alert_manager.format_trigger(a, price)
                    try:
                        await context.bot.send_message(
                            chat_id   = a.uid,
                            text      = text,
                            parse_mode = ParseMode.MARKDOWN,
                        )
                    except Exception as e:
                        logger.debug("Alert send to %d: %s", a.uid, e)
        except Exception as e:
            logger.debug("Alert check %s: %s", sym, e)
