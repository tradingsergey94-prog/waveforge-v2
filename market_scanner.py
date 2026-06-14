"""
Market Scanner — ежедневный рейтинг монет.

Строит Score для каждой монеты на основе:
1. Trend Score    — структура тренда (EMA50/200, HH/HL)
2. RS Score       — сила относительно BTC (1d, 7d)
3. OI Structure   — качество OI (не просто рост, а структура)
4. Volume Profile — аномалия объёма vs 30-дневное среднее

Возвращает топ-50 кандидатов для Watchlist Engine.
"""

import logging
import time
import pandas as pd
import numpy as np
import ta
import binance_client as bc
from config import EXCLUDED_SYMBOLS, MIN_VOLUME_24H_USD

logger = logging.getLogger(__name__)

SCANNER_TOP_N = 50   # сколько монет передаём в Watchlist Engine


def get_btc_returns() -> dict:
    """Возвращает доходность BTC за 1d и 7d."""
    df = bc.get_btc_klines(interval="1d", limit=10)
    if df is None or len(df) < 8:
        return {"1d": 0, "7d": 0}

    close = df["close"].values
    r1d = (close[-1] - close[-2]) / close[-2] * 100
    r7d = (close[-1] - close[-8]) / close[-8] * 100
    return {"1d": round(r1d, 2), "7d": round(r7d, 2)}


def calculate_trend_score(df_daily: pd.DataFrame) -> dict:
    """
    Trend Score монеты на дневном таймфрейме.

    Компоненты:
    - Цена vs EMA50, EMA200
    - Структура: Higher Highs + Higher Lows
    - Наклон EMA50 (растёт или падает)
    """
    if df_daily is None or len(df_daily) < 55:
        return {"score": 50, "above_ema50": None, "above_ema200": None}

    close = df_daily["close"]
    high  = df_daily["high"]
    low   = df_daily["low"]
    price = close.iloc[-1]

    ema50  = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    above_ema50  = price > ema50.iloc[-1]

    # EMA200 только если данных достаточно
    above_ema200 = None
    if len(df_daily) >= 205:
        ema200 = ta.trend.EMAIndicator(close, window=200).ema_indicator()
        above_ema200 = price > ema200.iloc[-1]

    # Наклон EMA50 (сравниваем текущее с 5 свечами назад)
    ema50_slope = (ema50.iloc[-1] - ema50.iloc[-6]) / ema50.iloc[-6] * 100

    # Структура последних 20 дней
    highs_20 = high.tail(20).values
    lows_20  = low.tail(20).values

    # Higher Highs
    hh = highs_20[-1] > highs_20[-10]
    # Higher Lows
    hl = lows_20[-1] > lows_20[-10]

    score = 50.0

    # EMA позиция (0-30)
    if above_ema50 and (above_ema200 is True):
        score += 30
    elif above_ema50 and above_ema200 is None:
        score += 20
    elif above_ema50:
        score += 15
    elif not above_ema50 and (above_ema200 is False):
        score -= 20
    else:
        score -= 5

    # Структура (0-20)
    if hh and hl:
        score += 20
    elif hh or hl:
        score += 8
    elif not hh and not hl:
        score -= 10

    # Наклон EMA50 (0-10)
    if ema50_slope > 2:
        score += 10
    elif ema50_slope > 0.5:
        score += 5
    elif ema50_slope < -2:
        score -= 10
    elif ema50_slope < -0.5:
        score -= 5

    score = max(0, min(100, score))

    return {
        "score":        round(score, 1),
        "above_ema50":  above_ema50,
        "above_ema200": above_ema200,
        "ema50_slope":  round(ema50_slope, 2),
        "hh":           hh,
        "hl":           hl
    }


def calculate_rs_score(coin_returns: dict, btc_returns: dict) -> dict:
    """
    Relative Strength Score vs BTC.

    RS > 1 = монета сильнее BTC
    Считаем для 1d и 7d.
    """
    r1d_coin = coin_returns.get("1d", 0)
    r7d_coin = coin_returns.get("7d", 0)
    r1d_btc  = btc_returns.get("1d", 1)
    r7d_btc  = btc_returns.get("7d", 1)

    rs1d = r1d_coin / abs(r1d_btc) if r1d_btc != 0 else 0
    rs7d = r7d_coin / abs(r7d_btc) if r7d_btc != 0 else 0

    score = 50.0

    # RS 7d (вес 60%)
    if rs7d > 3:
        score += 30
    elif rs7d > 2:
        score += 22
    elif rs7d > 1.5:
        score += 15
    elif rs7d > 1:
        score += 8
    elif rs7d > 0:
        score += 2
    elif rs7d < -1:
        score -= 15
    else:
        score -= 5

    # RS 1d (вес 40%)
    if rs1d > 3:
        score += 20
    elif rs1d > 2:
        score += 15
    elif rs1d > 1:
        score += 8
    elif rs1d > 0:
        score += 3
    elif rs1d < -1:
        score -= 10

    score = max(0, min(100, score))

    return {
        "score": round(score, 1),
        "rs_1d": round(rs1d, 2),
        "rs_7d": round(rs7d, 2),
        "return_1d": round(r1d_coin, 2),
        "return_7d": round(r7d_coin, 2)
    }


def scan_all_coins() -> list[dict]:
    """
    Полное сканирование всех монет Binance Futures.
    Возвращает топ-50 по Market Score.
    """
    logger.info("[Scanner] Запуск Market Scanner...")

    # Получаем тикеры
    tickers = bc.get_24h_tickers()
    if not tickers:
        logger.error("[Scanner] Нет данных с Binance")
        return []

    # BTC доходность для RS расчёта
    btc_returns = get_btc_returns()
    logger.info(f"[Scanner] BTC: 1d={btc_returns['1d']:+.1f}% 7d={btc_returns['7d']:+.1f}%")

    # Фильтруем по ликвидности
    candidates = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        base = symbol.replace("USDT", "")
        if any(excl in base for excl in EXCLUDED_SYMBOLS):
            continue
        vol = float(t.get("quoteVolume", 0))
        if vol < MIN_VOLUME_24H_USD:
            continue
        candidates.append({
            "symbol":     symbol,
            "price":      float(t.get("lastPrice", 0)),
            "change_24h": float(t.get("priceChangePercent", 0)),
            "volume_24h": vol,
        })

    logger.info(f"[Scanner] Кандидатов после фильтра ликвидности: {len(candidates)}")

    # Для каждого кандидата считаем Score
    scored = []
    for i, coin in enumerate(candidates):
        symbol = coin["symbol"]
        try:
            # Дневные свечи для Trend Score и RS 7d
            df_daily = bc.get_klines(symbol, "1d", limit=210)

            # Trend Score
            trend = calculate_trend_score(df_daily)

            # RS Score (7d и 1d)
            coin_returns = {"1d": coin["change_24h"]}
            if df_daily is not None and len(df_daily) >= 8:
                closes = df_daily["close"].values
                r7d = (closes[-1] - closes[-8]) / closes[-8] * 100
                coin_returns["7d"] = round(r7d, 2)
            else:
                coin_returns["7d"] = 0

            rs = calculate_rs_score(coin_returns, btc_returns)

            # Итоговый Market Score
            market_score = round(
                trend["score"] * 0.45 +
                rs["score"]    * 0.55,
                1
            )

            scored.append({
                **coin,
                "market_score":  market_score,
                "trend_score":   trend["score"],
                "rs_score":      rs["score"],
                "rs_7d":         rs["rs_7d"],
                "rs_1d":         rs["rs_1d"],
                "return_7d":     coin_returns.get("7d", 0),
                "above_ema50":   trend["above_ema50"],
                "above_ema200":  trend["above_ema200"],
                "ema50_slope":   trend.get("ema50_slope", 0),
                "hh":            trend.get("hh", False),
                "hl":            trend.get("hl", False),
            })

            time.sleep(0.15)   # не спамим API

        except Exception as e:
            logger.debug(f"[Scanner] {symbol} ошибка: {e}")
            continue

        # Прогресс каждые 20 монет
        if (i + 1) % 20 == 0:
            logger.info(f"[Scanner] Обработано {i+1}/{len(candidates)}...")

    # Сортируем и берём топ
    scored.sort(key=lambda x: x["market_score"], reverse=True)
    top = scored[:SCANNER_TOP_N]

    logger.info(f"[Scanner] Топ-10 по Market Score:")
    for i, c in enumerate(top[:10], 1):
        logger.info(
            f"  {i:2}. {c['symbol']:16} "
            f"score={c['market_score']:5.1f} "
            f"trend={c['trend_score']:5.1f} "
            f"RS7d={c['rs_7d']:+.1f}x "
            f"7d={c['return_7d']:+.1f}%"
        )

    return top
