"""
BTC Regime Agent — главный гейткипер системы.

Определяет текущий режим рынка:
- RISK_ON   → выше EMA200, тренд вверх → только LONG
- NEUTRAL   → боковик около EMA200    → LONG + SHORT
- BEAR      → ниже EMA200, тренд вниз → только SHORT
- RISK_OFF  → паника/каскад           → запрет входов

Логика:
- EMA 50 / EMA 200 на 4H
- ADX для силы тренда
- DI+ vs DI- для направления
- RSI и ATR
"""

import logging
import pandas as pd
import numpy as np
import ta
import binance_client as bc

logger = logging.getLogger(__name__)


def calculate_regime(df: pd.DataFrame) -> dict:
    if df is None or len(df) < 210:
        return {
            "regime": "NEUTRAL",
            "allowed_directions": ["LONG", "SHORT"],
            "score": 50,
            "details": {},
            "error": "Недостаточно данных"
        }

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── EMA ──────────────────────────────
    ema50  = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    ema200 = ta.trend.EMAIndicator(close, window=200).ema_indicator()

    price      = close.iloc[-1]
    ema50_val  = ema50.iloc[-1]
    ema200_val = ema200.iloc[-1]

    above_ema50  = price > ema50_val
    above_ema200 = price > ema200_val
    golden_cross = ema50_val > ema200_val

    dist_from_ema200 = (price - ema200_val) / ema200_val * 100

    # ── ADX ──────────────────────────────
    adx_ind  = ta.trend.ADXIndicator(high, low, close, window=14)
    adx      = adx_ind.adx().iloc[-1]
    di_plus  = adx_ind.adx_pos().iloc[-1]
    di_minus = adx_ind.adx_neg().iloc[-1]
    bearish_adx = adx > 20 and di_minus > di_plus

    # ── ATR ──────────────────────────────
    atr     = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr_val = atr.iloc[-1]
    atr_pct = atr_val / price * 100

    # ── RSI ──────────────────────────────
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    # ── Последние 10 свечей: структура ───
    last_closes = close.iloc[-10:].values
    lower_highs = last_closes[-1] < last_closes[0]   # цена падает

    # ─────────────────────────────────────
    # ОПРЕДЕЛЯЕМ РЕЖИМ
    # ─────────────────────────────────────

    # RISK_OFF: паника — ATR очень высокий + резкое падение
    panic = atr_pct > 4.0 and not above_ema200 and rsi < 30

    # RISK_ON: чёткий бычий тренд
    bull = above_ema200 and golden_cross and adx > 20 and di_plus > di_minus

    # BEAR: чёткий медвежий тренд (под EMA200, DI- > DI+)
    bear = not above_ema200 and bearish_adx and dist_from_ema200 < -3

    # NEUTRAL: всё остальное (боковик, около EMA200)
    if panic:
        regime = "RISK_OFF"
        allowed = []
    elif bull:
        regime = "RISK_ON"
        allowed = ["LONG"]
    elif bear:
        regime = "BEAR"
        allowed = ["SHORT"]
    else:
        regime = "NEUTRAL"
        allowed = ["LONG", "SHORT"]

    # Score для весов в supervisor
    score = 50.0
    if above_ema200:
        score += 20
    else:
        score -= 10

    if golden_cross:
        score += 10
    else:
        score -= 10

    if adx > 25 and di_plus > di_minus:
        score += 20
    elif adx > 25 and di_minus > di_plus:
        score -= 10
    elif adx > 20:
        score += 5

    if 45 < rsi < 65:
        score += 10
    elif rsi >= 70:
        score -= 5
    elif rsi <= 30:
        score -= 10

    if atr_pct > 4.0:
        score -= 15
    elif atr_pct < 1.0:
        score += 5

    score = max(0, min(100, score))

    details = {
        "price":          round(price, 2),
        "ema50":          round(ema50_val, 2),
        "ema200":         round(ema200_val, 2),
        "above_ema50":    above_ema50,
        "above_ema200":   above_ema200,
        "golden_cross":   golden_cross,
        "dist_ema200_pct": round(dist_from_ema200, 2),
        "adx":            round(adx, 1),
        "di_plus":        round(di_plus, 1),
        "di_minus":       round(di_minus, 1),
        "rsi_4h":         round(rsi, 1),
        "atr_pct":        round(atr_pct, 2),
    }

    logger.info(
        f"[Regime] BTC: {regime} ({'/'.join(allowed) if allowed else 'STOP'}) | "
        f"score={score:.0f} | dist_EMA200={dist_from_ema200:.1f}% "
        f"ADX={adx:.0f} DI+={di_plus:.0f} DI-={di_minus:.0f} RSI={rsi:.0f}"
    )

    return {
        "regime":             regime,
        "allowed_directions": allowed,
        "score":              round(score, 1),
        "details":            details
    }


def get_regime() -> dict:
    df = bc.get_btc_klines(interval="4h", limit=250)
    return calculate_regime(df)
