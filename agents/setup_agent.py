"""
Setup Agent — Entry Trigger для LONG и SHORT

LONG триггеры:
- SuperTrend бычий
- RSI не перекуплен
- Higher Low структура
- Volume подтверждение

SHORT триггеры:
- SuperTrend медвежий
- RSI не перепродан
- Lower High структура
- Volume подтверждение
"""

import logging
import numpy as np
import pandas as pd
import ta

logger = logging.getLogger(__name__)

ST_PERIOD     = 10
ST_MULTIPLIER = 3.0
RSI_MAX       = 72
RSI_MIN       = 28
VOLUME_MULT   = 1.3


def calculate_supertrend(df, period=ST_PERIOD, multiplier=ST_MULTIPLIER):
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    atr    = ta.volatility.AverageTrueRange(high, low, close, window=period).average_true_range()
    hl2    = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=bool)

    for i in range(period, len(df)):
        if i == period:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i]  = False
            continue

        prev_upper = supertrend.iloc[i-1] if not direction.iloc[i-1] else upper_band.iloc[i]
        prev_lower = supertrend.iloc[i-1] if direction.iloc[i-1]     else lower_band.iloc[i]

        curr_upper = upper_band.iloc[i] if upper_band.iloc[i] < prev_upper or close.iloc[i-1] > prev_upper else prev_upper
        curr_lower = lower_band.iloc[i] if lower_band.iloc[i] > prev_lower or close.iloc[i-1] < prev_lower else prev_lower

        if direction.iloc[i-1]:
            direction.iloc[i] = close.iloc[i] >= curr_lower
        else:
            direction.iloc[i] = close.iloc[i] > curr_upper

        supertrend.iloc[i] = curr_lower if direction.iloc[i] else curr_upper

    return direction, supertrend, atr


def analyze_setup(symbol: str, df_1h: pd.DataFrame, allowed_directions: list = None) -> dict:
    if allowed_directions is None:
        allowed_directions = ["LONG", "SHORT"]

    if df_1h is None or len(df_1h) < 50:
        return {
            "score": 0, "signal": None,
            "entry": None, "sl": None, "tp1": None, "tp2": None,
            "reason": "Недостаточно данных", "details": {}
        }

    df    = df_1h.tail(100).copy()
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    volume = df["volume"]
    price  = close.iloc[-1]

    # ── Индикаторы ────────────────────────
    st_direction, st_line, atr_series = calculate_supertrend(df)

    st_bullish      = bool(st_direction.iloc[-1])
    st_prev_bullish = bool(st_direction.iloc[-2])
    st_just_turned_bull  = st_bullish and not st_prev_bullish
    st_just_turned_bear  = not st_bullish and st_prev_bullish
    st_val  = st_line.iloc[-1]
    atr_val = atr_series.iloc[-1]

    rsi      = ta.momentum.RSIIndicator(close, window=14).rsi()
    rsi_val  = rsi.iloc[-1]
    rsi_prev = rsi.iloc[-2]
    rsi_rising  = rsi_val > rsi_prev
    rsi_falling = rsi_val < rsi_prev

    ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    above_ema21 = price > ema21.iloc[-1]
    above_ema50 = price > ema50.iloc[-1]
    below_ema21 = price < ema21.iloc[-1]
    below_ema50 = price < ema50.iloc[-1]

    lows_recent  = low.tail(20).values
    highs_recent = high.tail(20).values

    # Higher Low для LONG
    hl_check = False
    if len(lows_recent) >= 10:
        mid_low    = min(lows_recent[:10])
        recent_low = min(lows_recent[10:])
        hl_check   = recent_low > mid_low * 0.998

    # Lower High для SHORT
    lh_check = False
    if len(highs_recent) >= 10:
        mid_high    = max(highs_recent[:10])
        recent_high = max(highs_recent[10:])
        lh_check    = recent_high < mid_high * 1.002

    vol_avg     = volume.tail(20).mean()
    vol_current = volume.iloc[-1]
    vol_spike   = vol_current > vol_avg * VOLUME_MULT

    # ─────────────────────────────────────
    # LONG SETUP
    # ─────────────────────────────────────
    long_score = 0.0
    long_reasons = []

    if "LONG" in allowed_directions:
        if st_bullish and st_just_turned_bull:
            long_score += 35
            long_reasons.append("SuperTrend только что развернулся вверх ✅✅")
        elif st_bullish:
            long_score += 20
            long_reasons.append("SuperTrend бычий ✅")

        if RSI_MIN < rsi_val < 60 and rsi_rising:
            long_score += 20
            long_reasons.append(f"RSI {rsi_val:.0f} растёт ✅")
        elif RSI_MIN < rsi_val < RSI_MAX:
            long_score += 12
            long_reasons.append(f"RSI {rsi_val:.0f} норма")
        elif rsi_val >= RSI_MAX:
            long_reasons.append(f"RSI {rsi_val:.0f} перекупленность ❌")

        if above_ema21 and above_ema50:
            long_score += 20
            long_reasons.append("Выше EMA21 и EMA50 ✅")
        elif above_ema21:
            long_score += 10
            long_reasons.append("Выше EMA21")

        if hl_check:
            long_score += 15
            long_reasons.append("Higher Low ✅")

        if vol_spike:
            long_score += 10
            long_reasons.append(f"Volume x{vol_current/vol_avg:.1f} ✅")

    # ─────────────────────────────────────
    # SHORT SETUP
    # ─────────────────────────────────────
    short_score = 0.0
    short_reasons = []

    if "SHORT" in allowed_directions:
        if not st_bullish and st_just_turned_bear:
            short_score += 35
            short_reasons.append("SuperTrend только что развернулся вниз ✅✅")
        elif not st_bullish:
            short_score += 20
            short_reasons.append("SuperTrend медвежий ✅")

        if 40 < rsi_val < RSI_MAX and rsi_falling:
            short_score += 20
            short_reasons.append(f"RSI {rsi_val:.0f} падает ✅")
        elif RSI_MIN < rsi_val < RSI_MAX:
            short_score += 12
            short_reasons.append(f"RSI {rsi_val:.0f} норма")
        elif rsi_val <= RSI_MIN:
            short_reasons.append(f"RSI {rsi_val:.0f} перепроданность ❌")

        if below_ema21 and below_ema50:
            short_score += 20
            short_reasons.append("Ниже EMA21 и EMA50 ✅")
        elif below_ema21:
            short_score += 10
            short_reasons.append("Ниже EMA21")

        if lh_check:
            short_score += 15
            short_reasons.append("Lower High ✅")

        if vol_spike:
            short_score += 10
            short_reasons.append(f"Volume x{vol_current/vol_avg:.1f} ✅")

    # ─────────────────────────────────────
    # ВЫБИРАЕМ ЛУЧШИЙ СЕТАП
    # ─────────────────────────────────────
    if long_score >= short_score and long_score >= 55 and st_bullish and rsi_val < RSI_MAX:
        signal    = "LONG"
        score     = long_score
        reasons   = long_reasons
        sl  = round(price - 1.5 * atr_val, 6)
        tp1 = round(price + 2.0 * atr_val, 6)
        tp2 = round(price + 3.5 * atr_val, 6)
    elif short_score > long_score and short_score >= 55 and not st_bullish and rsi_val > RSI_MIN:
        signal    = "SHORT"
        score     = short_score
        reasons   = short_reasons
        sl  = round(price + 1.5 * atr_val, 6)
        tp1 = round(price - 2.0 * atr_val, 6)
        tp2 = round(price - 3.5 * atr_val, 6)
    else:
        signal  = None
        score   = max(long_score, short_score)
        reasons = long_reasons if long_score >= short_score else short_reasons
        sl = tp1 = tp2 = None

    risk     = abs(price - sl) if sl else atr_val
    reward   = abs(tp1 - price) if tp1 else 0
    rr_ratio = reward / risk if risk > 0 else 0

    score = max(0, min(100, score))

    details = {
        "supertrend_bullish":    st_bullish,
        "supertrend_just_turned": st_just_turned_bull or st_just_turned_bear,
        "rsi":         round(rsi_val, 1),
        "ema21":       round(ema21.iloc[-1], 6),
        "ema50":       round(ema50.iloc[-1], 6),
        "above_ema21": above_ema21,
        "above_ema50": above_ema50,
        "higher_low":  hl_check,
        "lower_high":  lh_check,
        "volume_spike": vol_spike,
        "volume_ratio": round(vol_current / vol_avg, 2),
        "atr":         round(atr_val, 6),
        "rr_ratio":    round(rr_ratio, 2),
        "long_score":  round(long_score, 1),
        "short_score": round(short_score, 1),
    }

    logger.info(
        f"[Setup] {symbol}: signal={signal} score={score:.0f} | "
        f"ST={'🟢' if st_bullish else '🔴'} RSI={rsi_val:.0f} "
        f"LONG={long_score:.0f} SHORT={short_score:.0f} RR={rr_ratio:.1f}"
    )

    return {
        "score":    round(score, 1),
        "signal":   signal,
        "entry":    round(price, 6),
        "sl":       sl,
        "tp1":      tp1,
        "tp2":      tp2,
        "rr_ratio": round(rr_ratio, 2),
        "reason":   " | ".join(reasons),
        "details":  details
    }
