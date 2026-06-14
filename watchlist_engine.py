"""
Watchlist Engine — 3-ступенчатый отбор монет.

Шаг 1: Ликвидность (объём, исключение мусора)
Шаг 2: Momentum Score (изменение цены, объём vs среднее, RS vs BTC)
Шаг 3: OI + Funding Score (структура участников)

Возвращает Active Universe — топ-10 монет для глубокого анализа.
"""

import logging
import time
import pandas as pd
import numpy as np
from config import (
    EXCLUDED_SYMBOLS, MIN_VOLUME_24H_USD,
    TOP_BY_MOMENTUM, ACTIVE_UNIVERSE_SIZE
)
import binance_client as bc

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# ШАГ 1: ФИЛЬТР ЛИКВИДНОСТИ
# ─────────────────────────────────────────

def filter_by_liquidity(tickers: list[dict]) -> list[dict]:
    """
    Из всех фьючерсов отбираем только ликвидные.
    Убираем стейблы, малый объём, мусорные монеты.
    """
    filtered = []
    for t in tickers:
        symbol = t.get("symbol", "")

        # Только USDT пары
        if not symbol.endswith("USDT"):
            continue

        # Убираем исключённые
        base = symbol.replace("USDT", "")
        if any(excl in base for excl in EXCLUDED_SYMBOLS):
            continue

        volume_24h = float(t.get("quoteVolume", 0))
        if volume_24h < MIN_VOLUME_24H_USD:
            continue

        filtered.append({
            "symbol": symbol,
            "base": base,
            "price": float(t.get("lastPrice", 0)),
            "change_24h": float(t.get("priceChangePercent", 0)),
            "volume_24h": volume_24h,
            "high_24h": float(t.get("highPrice", 0)),
            "low_24h": float(t.get("lowPrice", 0)),
        })

    logger.info(f"[Watchlist] После фильтра ликвидности: {len(filtered)} монет")
    return filtered


# ─────────────────────────────────────────
# ШАГ 2: MOMENTUM SCORE
# ─────────────────────────────────────────

def score_momentum(coins: list[dict], btc_change_24h: float) -> list[dict]:
    """
    Считаем Momentum Score для каждой монеты.

    Компоненты:
    - Изменение за 24ч (абсолютное)
    - Relative Strength vs BTC
    - Объём аномалия (volume vs median по выборке)
    - Позиция цены в диапазоне 24ч (сила тренда)
    """
    if not coins:
        return []

    # Считаем медианный объём по выборке для нормализации
    volumes = [c["volume_24h"] for c in coins]
    median_vol = np.median(volumes)

    scored = []
    for coin in coins:
        score = 0.0

        # 1. Изменение цены за 24ч (0-40 баллов)
        change = coin["change_24h"]
        if change > 15:
            score += 40
        elif change > 10:
            score += 35
        elif change > 7:
            score += 30
        elif change > 5:
            score += 25
        elif change > 3:
            score += 15
        elif change > 0:
            score += 5
        # отрицательное изменение = 0 баллов

        # 2. Relative Strength vs BTC (0-30 баллов)
        # RS > 1 = монета сильнее BTC
        if btc_change_24h != 0:
            rs = change / abs(btc_change_24h) if btc_change_24h != 0 else 0
        else:
            rs = 1.0

        if rs > 3:
            score += 30
        elif rs > 2:
            score += 25
        elif rs > 1.5:
            score += 20
        elif rs > 1:
            score += 15
        elif rs > 0:
            score += 5

        # 3. Volume аномалия (0-20 баллов)
        vol_ratio = coin["volume_24h"] / median_vol if median_vol > 0 else 1
        if vol_ratio > 5:
            score += 20
        elif vol_ratio > 3:
            score += 16
        elif vol_ratio > 2:
            score += 12
        elif vol_ratio > 1.5:
            score += 8
        elif vol_ratio > 1:
            score += 4

        # 4. Позиция в диапазоне 24ч (0-10 баллов)
        # Цена ближе к хаю = сила
        high = coin["high_24h"]
        low = coin["low_24h"]
        price = coin["price"]
        if high > low:
            position = (price - low) / (high - low)
            score += position * 10

        coin["momentum_score"] = round(score, 2)
        coin["rs_vs_btc"] = round(rs, 2)
        coin["vol_ratio"] = round(vol_ratio, 2)
        scored.append(coin)

    # Сортируем по score, берём топ
    scored.sort(key=lambda x: x["momentum_score"], reverse=True)
    top = scored[:TOP_BY_MOMENTUM]

    logger.info(f"[Watchlist] После Momentum Score: {len(top)} монет")
    if top:
        logger.info(f"  Топ-5: {[c['symbol'] for c in top[:5]]}")

    return top


# ─────────────────────────────────────────
# ШАГ 3: OI + FUNDING SCORE
# ─────────────────────────────────────────

def score_oi_funding(coins: list[dict]) -> list[dict]:
    """
    Для топ-30 монет получаем OI историю и Funding.
    Оцениваем структуру участников.

    Price ↑ + OI ↑ = реальный спрос (LONG friendly)
    Price ↑ + OI ↓ = закрытие шортов (слабее)
    Funding аномально высокий = рынок перегрет (осторожно)
    """
    scored = []

    for coin in coins:
        symbol = coin["symbol"]
        oi_score = 50.0   # нейтральный старт
        funding_score = 50.0

        try:
            # OI история за последние 8 часов
            oi_hist = bc.get_open_interest_history(symbol, period="1h", limit=8)
            if oi_hist is not None and len(oi_hist) >= 3:
                oi_values = oi_hist["sumOpenInterestValue"].values
                oi_change = (oi_values[-1] - oi_values[0]) / oi_values[0] * 100

                price_change = coin["change_24h"]

                # Price ↑ OI ↑ = сильный сигнал
                if price_change > 0 and oi_change > 5:
                    oi_score = 85
                elif price_change > 0 and oi_change > 2:
                    oi_score = 75
                elif price_change > 0 and oi_change > 0:
                    oi_score = 65
                elif price_change > 0 and oi_change < 0:
                    # закрытие шортов — менее убедительный рост
                    oi_score = 45
                elif price_change < 0 and oi_change > 0:
                    # рост OI при падении = наращивание шортов
                    oi_score = 30
                else:
                    oi_score = 50

                coin["oi_change_8h"] = round(oi_change, 2)
            else:
                coin["oi_change_8h"] = 0

        except Exception as e:
            logger.debug(f"OI error {symbol}: {e}")
            coin["oi_change_8h"] = 0

        try:
            # Funding rate
            funding = bc.get_funding_rate(symbol)
            if funding is not None:
                funding_pct = funding * 100

                if -0.01 <= funding_pct <= 0.05:
                    # Нормальный — нейтрально или чуть позитивно для лонгов
                    funding_score = 70
                elif 0.05 < funding_pct <= 0.1:
                    # Умеренно перегрет
                    funding_score = 50
                elif funding_pct > 0.1:
                    # Перегрет — осторожно с лонгами
                    funding_score = 25
                elif funding_pct < -0.01:
                    # Отрицательный — хорошо для лонгов
                    funding_score = 80

                coin["funding_rate"] = round(funding_pct, 4)
            else:
                coin["funding_rate"] = 0
                funding_score = 50

        except Exception as e:
            logger.debug(f"Funding error {symbol}: {e}")
            coin["funding_rate"] = 0

        coin["oi_score"] = oi_score
        coin["funding_score"] = funding_score
        coin["oi_funding_score"] = round((oi_score * 0.6 + funding_score * 0.4), 2)

        scored.append(coin)
        time.sleep(0.1)   # не спамим API

    # Финальный рейтинг
    for coin in scored:
        coin["watchlist_score"] = round(
            coin["momentum_score"] * 0.5 + coin["oi_funding_score"] * 0.5, 2
        )

    scored.sort(key=lambda x: x["watchlist_score"], reverse=True)
    active = scored[:ACTIVE_UNIVERSE_SIZE]

    logger.info(f"[Watchlist] Active Universe ({len(active)} монет):")
    for i, c in enumerate(active, 1):
        logger.info(
            f"  {i}. {c['symbol']:12} score={c['watchlist_score']:5.1f} "
            f"24h={c['change_24h']:+.1f}% RS={c['rs_vs_btc']:.1f}x "
            f"OI={c['oi_change_8h']:+.1f}% funding={c['funding_rate']:.4f}%"
        )

    return active


# ─────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────

def build_watchlist() -> list[dict]:
    """
    Полный цикл отбора:
    300+ монет → ликвидность → momentum → OI/funding → топ-10
    """
    logger.info("[Watchlist] Начинаем построение Active Universe...")

    # Получаем BTC изменение для RS расчёта
    tickers = bc.get_24h_tickers()
    if not tickers:
        logger.error("[Watchlist] Не удалось получить тикеры с Binance")
        return []

    btc_ticker = next((t for t in tickers if t["symbol"] == "BTCUSDT"), None)
    btc_change_24h = float(btc_ticker["priceChangePercent"]) if btc_ticker else 0

    logger.info(f"[Watchlist] BTC 24h: {btc_change_24h:+.2f}%")
    logger.info(f"[Watchlist] Всего тикеров: {len(tickers)}")

    # Шаг 1: Ликвидность
    liquid = filter_by_liquidity(tickers)

    # Шаг 2: Momentum
    momentum_top = score_momentum(liquid, btc_change_24h)

    # Шаг 3: OI + Funding
    active_universe = score_oi_funding(momentum_top)

    return active_universe
