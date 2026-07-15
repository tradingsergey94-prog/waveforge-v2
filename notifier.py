"""
Notifier — Telegram уведомления WaveForge v2.2
Человекочитаемый формат для всех сообщений.
"""

import requests
import logging
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

REGIME_EMOJI = {
    "RISK_ON":  "🟢",
    "NEUTRAL":  "🟡",
    "BEAR":     "🔴",
    "RISK_OFF": "⛔"
}

REGIME_RU = {
    "RISK_ON":  "Бычий рынок",
    "NEUTRAL":  "Боковик",
    "BEAR":     "Медвежий рынок",
    "RISK_OFF": "Паника — входы закрыты"
}

DIRECTION_EMOJI = {
    "LONG":  "🟢",
    "SHORT": "🔴"
}

DIRECTION_RU = {
    "LONG":  "ПОКУПКА (LONG)",
    "SHORT": "ПРОДАЖА (SHORT)"
}


def _stars(score: float) -> str:
    """Переводит score 0-100 в звёзды ⭐."""
    if score >= 90: return "⭐⭐⭐⭐⭐"
    if score >= 75: return "⭐⭐⭐⭐"
    if score >= 60: return "⭐⭐⭐"
    if score >= 45: return "⭐⭐"
    return "⭐"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    ok = True
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            ok = ok and r.status_code == 200
        except Exception as e:
            logger.error(f"Telegram error ({chat_id}): {e}")
            ok = False
    return ok


def format_signal_message(decision: dict, explanation: str, signal_id: int) -> str:
    sym       = decision["symbol"].replace("USDT", "")
    direction = decision["direction"]
    regime    = decision["regime"]
    scores    = decision["scores"]
    oi        = decision["agents"]["oi"]
    liq       = decision["agents"]["liquidity"]
    setup     = decision["agents"]["setup"]
    watchlist = decision.get("watchlist_data", {})

    entry = decision["entry"]
    sl    = decision["sl"]
    tp1   = decision["tp1"]
    tp2   = decision["tp2"]
    rr    = decision["rr_ratio"]
    mult  = decision["position_multiplier"]

    sl_pct  = abs(entry - sl)  / entry * 100
    tp1_pct = abs(tp1 - entry) / entry * 100
    tp2_pct = abs(tp2 - entry) / entry * 100

    # Данные
    funding   = oi.get("details", {}).get("funding_rate", 0)
    oi_change = oi.get("details", {}).get("oi_change_4h", 0)
    rsi_val   = setup.get("details", {}).get("rsi", 0)
    liq_det   = liq.get("details", {})
    eqh_target = liq_det.get("eqh_target")

    regime_icon = REGIME_EMOJI.get(regime, "⚪")
    regime_ru   = REGIME_RU.get(regime, regime)
    dir_emoji   = DIRECTION_EMOJI.get(direction, "⚪")
    dir_ru      = DIRECTION_RU.get(direction, direction)
    stars       = _stars(scores["final"])
    size_str    = "Полный размер" if mult >= 1.0 else f"Половина размера ({mult:.0%})"

    # OI читаемо
    oi_str = f"растёт +{oi_change:.1f}%" if oi_change > 0 else f"падает {oi_change:.1f}%"

    # Funding читаемо
    if funding < -0.01:
        fund_str = f"{funding:.4f}% — шорты платят лонгам 👍"
    elif funding <= 0.05:
        fund_str = f"{funding:.4f}% — нормальный"
    elif funding <= 0.1:
        fund_str = f"{funding:.4f}% — умеренно высокий ⚠️"
    else:
        fund_str = f"{funding:.4f}% — перегрет ❗"

    # Цель
    target_str = f"${eqh_target:.4f}" if eqh_target else "следующий уровень сопротивления"

    # BOS читаемо
    bos_str = "Подтверждена ✅" if liq_det.get("bos") else "Не подтверждена"

    now = datetime.utcnow().strftime("%d %b %Y | %H:%M UTC")

    msg = f"""{dir_emoji} <b>{sym} — {dir_ru}</b>  #{signal_id}
Уверенность: {stars} ({scores['final']:.0f}/100)
━━━━━━━━━━━━━━━━━━━━

🌍 <b>Состояние рынка</b>
Биткоин сейчас: {regime_icon} {regime_ru}
Открытый интерес: {oi_str}
Ставка финансирования: {fund_str}

📐 <b>Техническая картина</b>
Структура рынка: {bos_str}
RSI (импульс): {rsi_val:.0f}/100
Цель движения: {target_str}

💰 <b>Параметры сделки</b>
Монета: <b>{sym}/USDT</b>
Вход: <b>${entry:.4f}</b>
Стоп-лосс: ${sl:.4f} <i>({'-' if direction=='LONG' else '+'}{sl_pct:.1f}%)</i>
Цель 1: ${tp1:.4f} <i>(+{tp1_pct:.1f}%)</i>
Цель 2: ${tp2:.4f} <i>(+{tp2_pct:.1f}%)</i>
Соотношение риск/прибыль: 1:{rr:.1f}
Размер позиции: {size_str}

🤖 <b>Почему этот сигнал:</b>
<i>{explanation}</i>

━━━━━━━━━━━━━━━━━━━━
⏱ {now} | WaveForge v2.2"""

    return msg


def send_signal(decision: dict, explanation: str, signal_id: int) -> bool:
    msg = format_signal_message(decision, explanation, signal_id)
    ok  = send_message(msg)
    if ok:
        logger.info(f"[Telegram] Сигнал #{signal_id} отправлен: {decision['symbol']}")
    return ok


def send_scanner_update(candidates: list) -> bool:
    """Читаемое сообщение о результатах Market Scanner."""
    if not candidates:
        return False

    coins_str = ""
    for i, c in enumerate(candidates[:5], 1):
        sym   = c["symbol"].replace("USDT", "")
        score = c.get("combined_score", c.get("market_score", 0))
        stars = _stars(score)
        r7d   = c.get("return_7d", 0)
        rs7d  = c.get("rs_7d", 0)
        delta = c.get("delta_score", 0)
        delta_str = f" | Рост рейтинга: +{delta:.0f}" if delta > 2 else ""

        coins_str += (
            f"\n{i}. <b>{sym}</b>  {stars}\n"
            f"   За неделю: {r7d:+.1f}% | "
            f"В {rs7d:.1f}x сильнее BTC"
            f"{delta_str}\n"
        )

    now = datetime.utcnow().strftime("%H:%M UTC")
    msg = (
        f"🔭 <b>Лучшие монеты сейчас</b>\n\n"
        f"Система проанализировала 600+ монет и выбрала "
        f"самые сильные по тренду и динамике за 7 дней:\n"
        f"{coins_str}\n"
        f"<i>🕐 {now} | WaveForge v2.2</i>"
    )
    return send_message(msg)


def send_watchlist_update(active_universe: list, regime: str, btc_price: float) -> bool:
    """Читаемое обновление Active Universe."""
    regime_icon = REGIME_EMOJI.get(regime, "⚪")
    regime_ru   = REGIME_RU.get(regime, regime)

    # Что ищем сейчас
    if regime == "RISK_ON":
        looking = "ищем точки для покупки"
    elif regime == "BEAR":
        looking = "ищем точки для продажи"
    elif regime == "NEUTRAL":
        looking = "ищем покупки и продажи"
    else:
        looking = "входы приостановлены"

    coins_str = ""
    for i, coin in enumerate(active_universe[:10], 1):
        sym   = coin["symbol"].replace("USDT", "")
        r24h  = coin["change_24h"]
        r7d   = coin.get("return_7d", 0)
        rs7d  = coin.get("rs_7d", 0)
        coins_str += (
            f"{i}. <b>{sym}</b> "
            f"сегодня {r24h:+.1f}% | "
            f"неделя {r7d:+.1f}% | "
            f"сила {rs7d:.1f}x BTC\n"
        )

    now = datetime.utcnow().strftime("%H:%M UTC")
    msg = (
        f"👀 <b>Список наблюдения обновлён</b>\n\n"
        f"BTC: ${btc_price:,.0f}\n"
        f"Рынок: {regime_icon} {regime_ru}\n"
        f"Сейчас {looking}\n\n"
        f"<b>Топ-10 монет под наблюдением:</b>\n"
        f"{coins_str}\n"
        f"<i>🕐 {now} | WaveForge v2.2</i>"
    )
    return send_message(msg)


def send_stats(stats: dict) -> bool:
    winrate_str = f"{stats['winrate']:.1f}%" if stats['winrate'] > 0 else "нет данных"
    pnl_str     = f"{stats['avg_pnl']:+.2f}%" if stats['avg_pnl'] != 0 else "нет данных"

    msg = (
        f"📊 <b>Статистика WaveForge v2.2</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Всего сигналов: {stats['total']}\n"
        f"Открытых сделок: {stats['open']}\n"
        f"Прибыльных: {stats['wins']} ✅\n"
        f"Убыточных: {stats['losses']} ❌\n"
        f"Процент побед: {winrate_str}\n"
        f"Средний результат: {pnl_str}\n"
        f"Средний Score сигнала: {stats['avg_score']:.1f}/100\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    return send_message(msg)


def send_startup_message(regime: str, btc_price: float) -> bool:
    regime_icon = REGIME_EMOJI.get(regime, "⚪")
    regime_ru   = REGIME_RU.get(regime, regime)

    msg = (
        f"🚀 <b>WaveForge v2.2 запущен</b>\n\n"
        f"BTC сейчас: ${btc_price:,.0f}\n"
        f"Состояние рынка: {regime_icon} {regime_ru}\n\n"
        f"Как работает система:\n"
        f"1️⃣ Анализирует 600+ монет каждые 6 часов\n"
        f"2️⃣ Выбирает 10 самых сильных\n"
        f"3️⃣ Ищет точки входа каждые 30 минут\n"
        f"4️⃣ Отправляет сигнал с объяснением\n\n"
        f"Данные: Binance (бесплатно, без ключей)\n\n"
        f"Напиши /start чтобы увидеть все команды"
    )
    return send_message(msg)


def send_error(text: str) -> bool:
    return send_message(f"⚠️ <b>Ошибка WaveForge</b>\n{text}")
