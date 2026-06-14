"""
WaveForge v2 — главный цикл
Поддержка LONG + SHORT + NEUTRAL режимов
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import binance_client as bc
import database as db
import notifier
import watchlist_engine as we
from agents import regime_agent, oi_agent, liquidity_agent, setup_agent
import supervisor
import explainer
from config import (
    TELEGRAM_BOT_TOKEN, SCAN_INTERVAL_MINUTES,
    WATCHLIST_UPDATE_HOURS, SYSTEM_VERSION
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("waveforge_v2")

state = {
    "active_universe": [],
    "regime": {},
    "last_watchlist_update": None,
    "last_scan": None,
    "signals_sent": {},
    "running": True
}

REGIME_EMOJI = {
    "RISK_ON":  "🟢",
    "NEUTRAL":  "🟡",
    "BEAR":     "🔴",
    "RISK_OFF": "⛔"
}


def update_watchlist():
    logger.info("=" * 50)
    logger.info("🔄 Обновление Watchlist...")
    active = we.build_watchlist()
    if active:
        state["active_universe"] = active
        state["last_watchlist_update"] = datetime.utcnow()
        regime_name = state["regime"].get("regime", "UNKNOWN")
        btc_price = bc.get_btc_price() or 0
        db.save_watchlist([c["symbol"] for c in active], regime_name)
        notifier.send_watchlist_update(active, regime_name, btc_price)
        logger.info(f"✅ Active Universe: {[c['symbol'] for c in active]}")
    else:
        logger.warning("❌ Watchlist пустой")


def update_regime():
    regime = regime_agent.get_regime()
    state["regime"] = regime
    allowed = regime.get("allowed_directions", [])
    logger.info(f"📊 BTC Regime: {regime['regime']} | Разрешено: {allowed} | score={regime['score']}")
    return regime


def scan_symbol(coin: dict, regime_result: dict) -> bool:
    symbol = coin["symbol"]
    allowed = regime_result.get("allowed_directions", [])

    if not allowed:
        return False

    last_signal = state["signals_sent"].get(symbol)
    if last_signal and (datetime.utcnow() - last_signal) < timedelta(hours=4):
        return False

    df_1h = bc.get_klines(symbol, "1h", limit=150)
    if df_1h is None or len(df_1h) < 50:
        return False

    price_change_24h = coin.get("change_24h", 0)

    oi_result  = oi_agent.analyze_oi(symbol, price_change_24h)
    liq_result = liquidity_agent.analyze_liquidity(symbol, df_1h)

    # Передаём allowed_directions в setup_agent
    setup_result = setup_agent.analyze_setup(symbol, df_1h, allowed_directions=allowed)

    decision = supervisor.build_decision(
        symbol=symbol,
        regime_result=regime_result,
        oi_result=oi_result,
        liquidity_result=liq_result,
        setup_result=setup_result,
        watchlist_coin=coin
    )
    decision["watchlist_data"] = coin

    if not decision["trade"]:
        logger.info(f"[{symbol}] ❌ {decision['reason']}")
        return False

    explanation = explainer.explain_signal(decision)
    signal_id   = db.save_signal(decision, explanation)
    notifier.send_signal(decision, explanation, signal_id)

    state["signals_sent"][symbol] = datetime.utcnow()
    logger.info(f"✅ [{symbol}] {decision['direction']} #{signal_id} Score={decision['final_score']}")
    return True


def run_scan():
    if not state["active_universe"]:
        logger.warning("[Scan] Active Universe пустой")
        return

    regime_result = update_regime()
    allowed = regime_result.get("allowed_directions", [])

    if not allowed:
        logger.warning(f"[Scan] {regime_result['regime']} — входы запрещены")
        return

    logger.info(f"[Scan] Режим: {regime_result['regime']} | Ищем: {allowed}")
    logger.info(f"[Scan] Анализируем {len(state['active_universe'])} монет...")

    signals_count = 0
    for coin in state["active_universe"]:
        try:
            sent = scan_symbol(coin, regime_result)
            if sent:
                signals_count += 1
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"[{coin['symbol']}] Ошибка: {e}", exc_info=True)

    state["last_scan"] = datetime.utcnow()
    logger.info(f"[Scan] Завершён. Сигналов: {signals_count}")


# ── Telegram команды ──────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 <b>WaveForge v2</b>\n\n"
        "Режимы:\n"
        "🟢 RISK_ON  → только LONG\n"
        "🟡 NEUTRAL  → LONG + SHORT\n"
        "🔴 BEAR     → только SHORT\n"
        "⛔ RISK_OFF → запрет входов\n\n"
        "Команды:\n"
        "/status — режим и watchlist\n"
        "/stats — статистика\n"
        "/scan — сканирование вручную\n"
        "/watchlist — обновить список\n"
        "/result ID RESULT — итог сделки\n"
        "   Пример: /result 5 TP1",
        parse_mode="HTML"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    regime  = state.get("regime", {})
    active  = state.get("active_universe", [])
    details = regime.get("details", {})

    regime_name = regime.get("regime", "UNKNOWN")
    allowed     = regime.get("allowed_directions", [])
    emoji       = REGIME_EMOJI.get(regime_name, "⚪")

    coins_str = ""
    for i, c in enumerate(active[:10], 1):
        coins_str += f"{i}. {c['symbol']} {c['change_24h']:+.1f}% RS:{c['rs_vs_btc']:.1f}x\n"

    last_scan = state.get("last_scan")
    scan_str  = last_scan.strftime("%H:%M UTC") if last_scan else "Ещё не было"

    await update.message.reply_text(
        f"📊 <b>WaveForge v2 Status</b>\n\n"
        f"BTC: ${details.get('price', 0):,.0f}\n"
        f"Режим: {emoji} <b>{regime_name}</b>\n"
        f"Разрешено: {' + '.join(allowed) if allowed else '⛔ СТОП'}\n"
        f"EMA200: ${details.get('ema200', 0):,.0f} "
        f"({'выше ✅' if details.get('above_ema200') else 'ниже ❌'})\n"
        f"Dist EMA200: {details.get('dist_ema200_pct', 0):+.1f}%\n"
        f"ADX: {details.get('adx', 0):.0f} | RSI: {details.get('rsi_4h', 0):.0f}\n\n"
        f"<b>Active Universe:</b>\n{coins_str}\n"
        f"Последнее сканирование: {scan_str}",
        parse_mode="HTML"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_stats()
    notifier.send_stats(stats)
    await update.message.reply_text("📊 Статистика отправлена")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Запускаю сканирование...")
    run_scan()
    await update.message.reply_text("✅ Готово")


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Обновляю Watchlist...")
    update_watchlist()


async def cmd_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /result <ID> <TP1|TP2|SL>")
        return
    try:
        signal_id = int(args[0])
        result    = args[1].upper()
        if result not in ["TP1", "TP2", "SL"]:
            await update.message.reply_text("Результат: TP1 / TP2 / SL")
            return

        signals = db.get_recent_signals(50)
        signal  = next((s for s in signals if s[0] == signal_id), None)
        pnl     = None

        if signal:
            entry = signal[6]
            sl    = signal[7]
            tp1   = signal[8]
            tp2   = signal[9]
            direction = signal[3]  # LONG или SHORT

            if entry:
                if result == "TP1" and tp1:
                    raw = (tp1 - entry) / entry * 100
                    pnl = round(raw if direction == "LONG" else -raw, 2)
                elif result == "TP2" and tp2:
                    raw = (tp2 - entry) / entry * 100
                    pnl = round(raw if direction == "LONG" else -raw, 2)
                elif result == "SL" and sl:
                    raw = (sl - entry) / entry * 100
                    pnl = round(raw if direction == "LONG" else -raw, 2)

        db.update_result(signal_id, result, pnl)
        emoji   = "✅" if result in ["TP1", "TP2"] else "❌"
        pnl_str = f" ({pnl:+.2f}%)" if pnl else ""
        await update.message.reply_text(f"{emoji} Сигнал #{signal_id}: {result}{pnl_str}")

    except ValueError:
        await update.message.reply_text("ID должен быть числом")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# ── Фоновый цикл ─────────────────────────

async def background_loop():
    logger.info("🔄 Фоновый цикл запущен")
    update_watchlist()
    update_regime()

    last_watchlist = datetime.utcnow()
    last_scan      = datetime.utcnow() - timedelta(minutes=SCAN_INTERVAL_MINUTES)

    while state["running"]:
        now = datetime.utcnow()

        if (now - last_watchlist).total_seconds() >= WATCHLIST_UPDATE_HOURS * 3600:
            update_watchlist()
            last_watchlist = now

        if (now - last_scan).total_seconds() >= SCAN_INTERVAL_MINUTES * 60:
            run_scan()
            last_scan = now

        await asyncio.sleep(60)


def main():
    db.init_db()
    logger.info(f"🚀 WaveForge {SYSTEM_VERSION} стартует...")

    btc_price = bc.get_btc_price()
    if not btc_price:
        logger.error("❌ Нет подключения к Binance API")
        return

    logger.info(f"✅ Binance OK | BTC: ${btc_price:,.0f}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("scan",      cmd_scan))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("result",    cmd_result))

    regime = regime_agent.get_regime()
    state["regime"] = regime
    notifier.send_startup_message(regime["regime"], btc_price)

    async def run():
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await background_loop()

    asyncio.run(run())


if __name__ == "__main__":
    main()
