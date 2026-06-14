"""
Setup Agent — Entry Trigger

Ищет конкретную точку входа ПОСЛЕ того как:
- BTC Regime разрешил торговлю
- OI подтверждает структуру
- Liquidity показал зону входа

Триггеры:
- SuperTrend разворот (переход в бычий)
- Swing структура (Higher Low подтверждён)
- RSI не перекуплен
- Volume подтверждение
- ATR для расчёта SL/TP
"""

import logging
import numpy as np
import pandas as pd
import ta

logger = logging.getLogger(__name__)

# SuperTrend параметры
ST_PERIOD = 10
ST_MULTIPLIER = 3.0

# Entry условия
RSI_MAX = 72          # не входим в перекупленность
RSI_MIN = 30          # не входим в панику
VOLUME_MULT = 1.3     # объём должен быть выше среднего


def calculate_supertrend(df: pd.DataFrame, period: int = ST_PERIOD, multiplier: float = ST_MULTIPLIER):
    """
    SuperTrend индикатор.
    Возвращает серию: True = бычий, False = медвежий.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    atr = ta.volatility.AverageTrueRange(high, low, close, window=period).average_true_range()

    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=bool)   # True = bullish

    for i in range(period, len(df)):
        if i == period:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = False
            continue

        prev_upper = supertrend.iloc[i-1] if not direction.iloc[i-1] else upper_band.iloc[i]
        prev_lower = supertrend.iloc[i-1] if direction.iloc[i-1] else lower_band.iloc[i]

        # Обновляем бэнды
        curr_upper = upper_band.iloc[i] if upper_band.iloc[i] < prev_upper or close.iloc[i-1] > prev_upper else prev_upper
        curr_lower = lower_band.iloc[i] if lower_band.iloc[i] > prev_lower or close.iloc[i-1] < prev_lower else prev_lower

        if direction.iloc[i-1]:
            direction.iloc[i] = close.iloc[i] >= curr_lower
        else:
            direction.iloc[i] = close.iloc[i] > curr_upper

        supertrend.iloc[i] = curr_lower if direction.iloc[i] else curr_upper

    return direction, supertrend, atr


def analyze_setup(symbol: str, df_1h: pd.DataFrame) -> dict:
    """
    Анализирует технический setup для входа.
    """
    if df_1h is None or len(df_1h) < 50:
        return {
            "score": 0,
            "signal": None,
            "entry": None,
            "sl": None,
            "tp1": None,
            "tp2": None,
            "reason": "Недостаточно данных",
            "details": {}
        }

    df = df_1h.tail(100).copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    price = close.iloc[-1]

    # ── SuperTrend ───────────────────────
    st_direction, st_line, atr_series = calculate_supertrend(df)

    st_bullish = bool(st_direction.iloc[-1])
    st_prev_bullish = bool(st_direction.iloc[-2])
    st_just_turned = st_bullish and not st_prev_bullish   # только что развернулся
    st_val = st_line.iloc[-1]
    atr_val = atr_series.iloc[-1]

    # ── RSI ──────────────────────────────
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    rsi_val = rsi.iloc[-1]
    rsi_prev = rsi.iloc[-2]
    rsi_rising = rsi_val > rsi_prev

    # ── EMA для тренда ───────────────────
    ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    above_ema21 = price > ema21.iloc[-1]
    above_ema50 = price > ema50.iloc[-1]
    ema_bullish = above_ema21 and above_ema50

    # ── Свинг-структура ──────────────────
    lows_recent = low.tail(20).values
    highs_recent = high.tail(20).values

    # Простая проверка Higher Low
    hl_check = False
    if len(lows_recent) >= 10:
        mid_low = min(lows_recent[:10])
        recent_low = min(lows_recent[10:])
        hl_check = recent_low > mid_low * 0.998

    # ── Volume ───────────────────────────
    vol_avg = volume.tail(20).mean()
    vol_current = volume.iloc[-1]
    vol_spike = vol_current > vol_avg * VOLUME_MULT

    # ─────────────────────────────────────
    # SCORING SETUP
    # ─────────────────────────────────────
    score = 0.0
    reasons = []

    # SuperTrend (0-35 баллов)
    if st_bullish and st_just_turned:
        score += 35
        reasons.append("SuperTrend только что развернулся вверх ✅✅")
    elif st_bullish:
        score += 20
        reasons.append("SuperTrend бычий ✅")
    else:
        score += 0
        reasons.append("SuperTrend медвежий ❌")

    # RSI (0-20 баллов)
    if RSI_MIN < rsi_val < 60 and rsi_rising:
        score += 20
        reasons.append(f"RSI {rsi_val:.0f} растёт (идеальная зона) ✅")
    elif RSI_MIN < rsi_val < RSI_MAX:
        score += 12
        reasons.append(f"RSI {rsi_val:.0f} (норма)")
    elif rsi_val >= RSI_MAX:
        score += 0
        reasons.append(f"RSI {rsi_val:.0f} — перекупленность ❌")
    else:
        score += 5
        reasons.append(f"RSI {rsi_val:.0f}")

    # EMA структура (0-20 баллов)
    if ema_bullish:
        score += 20
        reasons.append("Цена выше EMA21 и EMA50 ✅")
    elif above_ema21:
        score += 10
        reasons.append("Цена выше EMA21")
    else:
        reasons.append("Цена под EMA ❌")

    # Swing структура (0-15 баллов)
    if hl_check:
        score += 15
        reasons.append("Higher Low подтверждён ✅")
    else:
        reasons.append("Структура недостаточно чёткая")

    # Volume (0-10 баллов)
    if vol_spike:
        score += 10
        reasons.append(f"Volume x{vol_current/vol_avg:.1f} выше среднего ✅")
    else:
        reasons.append(f"Volume норма (x{vol_current/vol_avg:.1f})")

    score = max(0, min(100, score))

    # ─────────────────────────────────────
    # РАСЧЁТ SL / TP
    # ─────────────────────────────────────
    sl = round(price - 1.5 * atr_val, 6)
    tp1 = round(price + 2.0 * atr_val, 6)
    tp2 = round(price + 3.5 * atr_val, 6)

    # RR ratio
    risk = price - sl
    reward_tp1 = tp1 - price
    rr_ratio = reward_tp1 / risk if risk > 0 else 0

    signal = None
    if score >= 55 and st_bullish and rsi_val < RSI_MAX:
        signal = "LONG"

    details = {
        "supertrend_bullish": st_bullish,
        "supertrend_just_turned": st_just_turned,
        "supertrend_level": round(st_val, 6),
        "rsi": round(rsi_val, 1),
        "ema21": round(ema21.iloc[-1], 6),
        "ema50": round(ema50.iloc[-1], 6),
        "above_ema21": above_ema21,
        "above_ema50": above_ema50,
        "higher_low": hl_check,
        "volume_spike": vol_spike,
        "volume_ratio": round(vol_current / vol_avg, 2),
        "atr": round(atr_val, 6),
        "rr_ratio": round(rr_ratio, 2)
    }

    logger.info(
        f"[Setup] {symbol}: score={score:.0f} signal={signal} | "
        f"ST={'✅' if st_bullish else '❌'} "
        f"RSI={rsi_val:.0f} EMA={'✅' if ema_bullish else '❌'} "
        f"HL={'✅' if hl_check else '❌'} RR={rr_ratio:.1f}"
    )

    return {
        "score": round(score, 1),
        "signal": signal,
        "entry": round(price, 6),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr_ratio": round(rr_ratio, 2),
        "reason": " | ".join(reasons),
        "details": details
    }
