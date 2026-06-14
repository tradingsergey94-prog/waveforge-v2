"""
BTC Regime Agent — главный гейткипер системы.

Определяет текущий режим рынка:
- RISK_ON  → торгуем полным размером
- NEUTRAL  → торгуем половиной, только сильные сигналы
- RISK_OFF → запрет новых входов

Логика:
- EMA 50 / EMA 200 на 4H (Golden/Death Cross)
- ADX для силы тренда
- Волатильность (ATR)
- Расстояние цены от EMA
"""

import logging
import pandas as pd
import numpy as np
import ta
import binance_client as bc

logger = logging.getLogger(__name__)


def calculate_regime(df: pd.DataFrame) -> dict:
    """
    Принимает 4H свечи BTC, возвращает режим рынка.
    """
    if df is None or len(df) < 210:
        return {
            "regime": "NEUTRAL",
            "score": 50,
            "details": {},
            "error": "Недостаточно данных"
        }

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── EMA ──────────────────────────────
    ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    ema200 = ta.trend.EMAIndicator(close, window=200).ema_indicator()

    price = close.iloc[-1]
    ema50_val = ema50.iloc[-1]
    ema200_val = ema200.iloc[-1]

    above_ema50 = price > ema50_val
    above_ema200 = price > ema200_val
    golden_cross = ema50_val > ema200_val

    # Расстояние от EMA200 в процентах
    dist_from_ema200 = (price - ema200_val) / ema200_val * 100

    # ── ADX (сила тренда) ─────────────────
    adx_ind = ta.trend.ADXIndicator(high, low, close, window=14)
    adx = adx_ind.adx().iloc[-1]
    di_plus = adx_ind.adx_pos().iloc[-1]
    di_minus = adx_ind.adx_neg().iloc[-1]

    # ── ATR (волатильность) ───────────────
    atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr_val = atr.iloc[-1]
    atr_pct = atr_val / price * 100

    # ── RSI ───────────────────────────────
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    # ── Свечи последние 3 (структура) ─────
    last_closes = close.iloc[-4:].values
    higher_lows = all(last_closes[i] > last_closes[i-1] for i in range(1, len(last_closes)))

    # ─────────────────────────────────────
    # SCORING
    # ─────────────────────────────────────
    score = 50.0

    # EMA структура (0-30 баллов)
    if golden_cross and above_ema50 and above_ema200:
        score += 30
    elif golden_cross and above_ema200:
        score += 20
    elif above_ema200:
        score += 10
    elif not golden_cross and not above_ema200:
        score -= 20
    elif not above_ema200:
        score -= 10

    # ADX (0-20 баллов)
    if adx > 30 and di_plus > di_minus:
        score += 20
    elif adx > 25 and di_plus > di_minus:
        score += 15
    elif adx > 20:
        score += 5
    elif adx < 15:
        score -= 5

    # RSI (позиция, не экстремум)
    if 50 < rsi < 70:
        score += 10
    elif rsi >= 70:
        score -= 5     # перекупленность
    elif 40 < rsi <= 50:
        score += 0
    elif rsi <= 35:
        score -= 10

    # Волатильность аномалия (очень высокая ATR = стресс)
    if atr_pct > 3.0:
        score -= 10   # высокая волатильность = риск
    elif atr_pct < 1.0:
        score += 5    # низкая волатильность = стабильность

    score = max(0, min(100, score))

    # ─────────────────────────────────────
    # ОПРЕДЕЛЯЕМ РЕЖИМ
    # ─────────────────────────────────────
    if score >= 70:
        regime = "RISK_ON"
    elif score >= 45:
        regime = "NEUTRAL"
    else:
        regime = "RISK_OFF"

    details = {
        "price": round(price, 2),
        "ema50": round(ema50_val, 2),
        "ema200": round(ema200_val, 2),
        "above_ema50": above_ema50,
        "above_ema200": above_ema200,
        "golden_cross": golden_cross,
        "dist_ema200_pct": round(dist_from_ema200, 2),
        "adx": round(adx, 1),
        "di_plus": round(di_plus, 1),
        "di_minus": round(di_minus, 1),
        "rsi_4h": round(rsi, 1),
        "atr_pct": round(atr_pct, 2),
    }

    logger.info(
        f"[Regime] BTC: {regime} | score={score:.0f} | "
        f"EMA50={'✅' if above_ema50 else '❌'} "
        f"EMA200={'✅' if above_ema200 else '❌'} "
        f"ADX={adx:.0f} RSI={rsi:.0f}"
    )

    return {
        "regime": regime,
        "score": round(score, 1),
        "details": details
    }


def get_regime() -> dict:
    """Главная функция — загружает данные и считает режим."""
    df = bc.get_btc_klines(interval="4h", limit=250)
    return calculate_regime(df)
