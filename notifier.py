"""
Notifier — Telegram уведомления.

Форматирует и отправляет:
- Сигналы (с полным контекстом)
- Watchlist обновления
- Статистику
- Системные сообщения
"""

import requests
import logging
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

REGIME_EMOJI = {
    "RISK_ON": "🟢",
    "NEUTRAL": "🟡",
    "RISK_OFF": "🔴"
}

SIGNAL_EMOJI = {
    "BULLISH": "✅",
    "NEUTRAL": "⚪",
    "BEARISH": "❌"
}


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            },
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def format_signal_message(decision: dict, explanation: str, signal_id: int) -> str:
    """
    Форматирует полное сообщение о сигнале.
    """
    sym = decision["symbol"]
    regime = decision["regime"]
    scores = decision["scores"]
    oi = decision["agents"]["oi"]
    liq = decision["agents"]["liquidity"]
    setup = decision["agents"]["setup"]
    watchlist = decision.get("watchlist_data", {})

    entry = decision["entry"]
    sl = decision["sl"]
    tp1 = decision["tp1"]
    tp2 = decision["tp2"]
    rr = decision["rr_ratio"]
    mult = decision["position_multiplier"]

    sl_pct = abs(entry - sl) / entry * 100
    tp1_pct = abs(tp1 - entry) / entry * 100
    tp2_pct = abs(tp2 - entry) / entry * 100

    # Funding rate
    funding = oi.get("details", {}).get("funding_rate", 0)
    oi_change = oi.get("details", {}).get("oi_change_4h", 0)
    oi_signal = SIGNAL_EMOJI.get(oi.get("signal", "NEUTRAL"), "⚪")

    # Liquidity details
    liq_details = liq.get("details", {})
    bos = "✅" if liq_details.get("bos") else "❌"
    fvg = "✅" if liq_details.get("bullish_fvg_count", 0) > 0 else "❌"
    eqh_target = liq_details.get("eqh_target")
    eqh_str = f"${eqh_target:.4f}" if eqh_target else "—"

    # Setup details
    setup_details = setup.get("details", {})
    st_bullish = "✅" if setup_details.get("supertrend_bullish") else "❌"
    rsi_val = setup_details.get("rsi", 0)
    hl = "✅" if setup_details.get("higher_low") else "❌"

    regime_icon = REGIME_EMOJI.get(regime, "⚪")
    size_str = f"{mult:.1f}x" if mult < 1 else "полный"

    now = datetime.utcnow().strftime("%d %b %Y | %H:%M UTC")

    msg = f"""🟢 <b>{sym} — LONG</b>  #{signal_id}
━━━━━━━━━━━━━━━━━━━━

📊 <b>Контекст рынка</b>
BTC Regime: {regime_icon} <b>{regime}</b>
OI 4h: {oi_signal} {oi_change:+.1f}%
Funding: {funding:.4f}%

💧 <b>Ликвидность</b>
BOS структура: {bos}
FVG имбаланс: {fvg}
Цель EQH: {eqh_str}

📍 <b>Точка входа</b>
SuperTrend: {st_bullish}
RSI: {rsi_val:.0f}
Higher Low: {hl}

⚖️ <b>Параметры сделки</b>
Вход: <b>${entry:.4f}</b>
SL: ${sl:.4f} <i>(-{sl_pct:.1f}%)</i>
TP1: ${tp1:.4f} <i>(+{tp1_pct:.1f}%)</i>
TP2: ${tp2:.4f} <i>(+{tp2_pct:.1f}%)</i>
RR: 1:{rr:.1f} | Размер: {size_str}

🤖 <b>Claude говорит:</b>
<i>{explanation}</i>

📈 <b>Score: {scores['final']:.0f}/100</b>
R:{scores['regime']:.0f} OI:{scores['oi']:.0f} L:{scores['liquidity']:.0f} S:{scores['setup']:.0f}
━━━━━━━━━━━━━━━━━━━━
⏱ {now} | WaveForge v2"""

    return msg


def send_signal(decision: dict, explanation: str, signal_id: int) -> bool:
    msg = format_signal_message(decision, explanation, signal_id)
    ok = send_message(msg)
    if ok:
        logger.info(f"[Telegram] Сигнал #{signal_id} отправлен: {decision['symbol']}")
    return ok


def send_watchlist_update(active_universe: list, regime: str, btc_price: float) -> bool:
    regime_icon = REGIME_EMOJI.get(regime, "⚪")

    coins_str = ""
    for i, coin in enumerate(active_universe[:10], 1):
        coins_str += (
            f"{i}. <b>{coin['symbol']}</b> "
            f"{coin['change_24h']:+.1f}% "
            f"RS:{coin['rs_vs_btc']:.1f}x "
            f"OI:{coin.get('oi_change_8h', 0):+.1f}%\n"
        )

    now = datetime.utcnow().strftime("%H:%M UTC")
    msg = f"""🔍 <b>Active Universe обновлён</b>
BTC: ${btc_price:,.0f} | Режим: {regime_icon} {regime}

{coins_str}
<i>{now} | WaveForge v2</i>"""

    return send_message(msg)


def send_stats(stats: dict) -> bool:
    msg = f"""📊 <b>WaveForge v2 — Статистика</b>
━━━━━━━━━━━━━━━━━━━━
Всего сигналов: {stats['total']}
Открытых: {stats['open']}
Побед: {stats['wins']} | Потерь: {stats['losses']}
Win Rate: {stats['winrate']:.1f}%
Средний PnL: {stats['avg_pnl']:+.2f}%
Средний Score: {stats['avg_score']:.1f}/100
━━━━━━━━━━━━━━━━━━━━"""
    return send_message(msg)


def send_startup_message(regime: str, btc_price: float) -> bool:
    regime_icon = REGIME_EMOJI.get(regime, "⚪")
    msg = f"""🚀 <b>WaveForge v2 запущен</b>

BTC: ${btc_price:,.0f}
Режим: {regime_icon} {regime}

Архитектура:
BTC Regime → OI → Liquidity → Setup → Risk

Источник данных: Binance Public API
Сканирование: каждые 30 мин
Watchlist: обновление каждые 4ч"""
    return send_message(msg)


def send_error(text: str) -> bool:
    return send_message(f"⚠️ <b>WaveForge v2 Error</b>\n{text}")
