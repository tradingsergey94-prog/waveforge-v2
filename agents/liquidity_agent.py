"""
Liquidity Agent

Ищет зоны ликвидности и структурные точки:
- EQH (Equal Highs) — ликвидность над рынком (стопы покупателей)
- EQL (Equal Lows)  — ликвидность под рынком (стопы продавцов)
- FVG (Fair Value Gap) — имбалансы, которые рынок стремится закрыть
- BOS (Break of Structure) — подтверждение смены структуры
- CHoCH (Change of Character) — ранний сигнал разворота

Логика:
- Если цена в зоне FVG или у EQL → высокий шанс отскока
- Если был BOS → структура подтверждена
- Цель = ликвидность над рынком (EQH)
"""

import logging
import numpy as np
import pandas as pd
import ta
import binance_client as bc

logger = logging.getLogger(__name__)

LOOKBACK = 100          # свечей для анализа структуры
EQH_EQL_TOLERANCE = 0.003   # 0.3% отклонение для equal highs/lows
FVG_MIN_SIZE = 0.002         # минимальный размер FVG (0.2% от цены)


def find_swing_points(df: pd.DataFrame, left: int = 5, right: int = 5):
    """
    Поиск значимых свинг-хаёв и свинг-лоёв.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)

    swing_highs = []
    swing_lows = []

    for i in range(left, n - right):
        # Свинг-хай: выше всех соседей слева и справа
        if highs[i] == max(highs[i-left:i+right+1]):
            swing_highs.append({"index": i, "price": highs[i], "ts": df.index[i]})
        # Свинг-лоу: ниже всех соседей
        if lows[i] == min(lows[i-left:i+right+1]):
            swing_lows.append({"index": i, "price": lows[i], "ts": df.index[i]})

    return swing_highs, swing_lows


def find_equal_highs(swing_highs: list, tolerance: float = EQH_EQL_TOLERANCE) -> list:
    """
    EQH — две или более вершины на одном уровне.
    Это зона ликвидности выше рынка.
    """
    eqh_zones = []
    for i in range(len(swing_highs)):
        for j in range(i+1, len(swing_highs)):
            h1 = swing_highs[i]["price"]
            h2 = swing_highs[j]["price"]
            if abs(h1 - h2) / h1 < tolerance:
                level = (h1 + h2) / 2
                eqh_zones.append({
                    "level": level,
                    "count": 2,
                    "touches": [h1, h2]
                })
    return eqh_zones


def find_equal_lows(swing_lows: list, tolerance: float = EQH_EQL_TOLERANCE) -> list:
    """
    EQL — два или более основания на одном уровне.
    Это зона ликвидности ниже рынка.
    """
    eql_zones = []
    for i in range(len(swing_lows)):
        for j in range(i+1, len(swing_lows)):
            l1 = swing_lows[i]["price"]
            l2 = swing_lows[j]["price"]
            if abs(l1 - l2) / l1 < tolerance:
                level = (l1 + l2) / 2
                eql_zones.append({
                    "level": level,
                    "count": 2,
                    "touches": [l1, l2]
                })
    return eql_zones


def find_fvg(df: pd.DataFrame) -> list:
    """
    FVG (Fair Value Gap / Imbalance)

    Бычий FVG: high[i-2] < low[i]
    Между свечами i-2 и i образовался разрыв — незаполненный имбаланс.
    Цена часто возвращается в эту зону.
    """
    fvgs = []
    for i in range(2, len(df)):
        high_before = df["high"].iloc[i-2]
        low_after = df["low"].iloc[i]
        low_before = df["low"].iloc[i-2]
        high_after = df["high"].iloc[i]

        price = df["close"].iloc[-1]

        # Бычий FVG (цена прыгнула вверх, оставив разрыв)
        if low_after > high_before:
            gap_size = (low_after - high_before) / high_before
            if gap_size > FVG_MIN_SIZE:
                fvgs.append({
                    "type": "bullish",
                    "top": low_after,
                    "bottom": high_before,
                    "mid": (low_after + high_before) / 2,
                    "size_pct": round(gap_size * 100, 3),
                    "ts": df.index[i]
                })

        # Медвежий FVG
        if high_after < low_before:
            gap_size = (low_before - high_after) / low_before
            if gap_size > FVG_MIN_SIZE:
                fvgs.append({
                    "type": "bearish",
                    "top": low_before,
                    "bottom": high_after,
                    "mid": (low_before + high_after) / 2,
                    "size_pct": round(gap_size * 100, 3),
                    "ts": df.index[i]
                })

    return fvgs


def detect_bos_choch(swing_highs: list, swing_lows: list, current_price: float) -> dict:
    """
    BOS (Break of Structure):
    - Цена пробила предыдущий значимый хай → структура бычья

    CHoCH (Change of Character):
    - После нисходящего тренда цена пробила последний значимый хай
    """
    result = {
        "bos": False,
        "choch": False,
        "structure": "undefined",
        "last_swing_high": None,
        "last_swing_low": None
    }

    if not swing_highs or not swing_lows:
        return result

    # Последние значимые точки (берём последние 3)
    recent_highs = sorted(swing_highs[-3:], key=lambda x: x["index"])
    recent_lows = sorted(swing_lows[-3:], key=lambda x: x["index"])

    last_high = recent_highs[-1]["price"] if recent_highs else None
    last_low = recent_lows[-1]["price"] if recent_lows else None

    result["last_swing_high"] = last_high
    result["last_swing_low"] = last_low

    if last_high and last_low:
        # Бычья структура: Higher Highs + Higher Lows
        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            hh = recent_highs[-1]["price"] > recent_highs[-2]["price"]
            hl = recent_lows[-1]["price"] > recent_lows[-2]["price"]

            if hh and hl:
                result["structure"] = "bullish"
                result["bos"] = True
            elif not hh and not hl:
                result["structure"] = "bearish"
            else:
                result["structure"] = "mixed"

        # CHoCH: медвежья структура но цена пробила последний хай
        if result["structure"] in ["bearish", "mixed"]:
            if current_price > last_high:
                result["choch"] = True
                result["structure"] = "choch_bullish"

    return result


def analyze_liquidity(symbol: str, df_1h: pd.DataFrame) -> dict:
    """
    Полный liquidity анализ для символа.
    """
    if df_1h is None or len(df_1h) < 50:
        return {
            "score": 50,
            "signal": "NEUTRAL",
            "reason": "Недостаточно данных",
            "details": {}
        }

    # Работаем с последними LOOKBACK свечами
    df = df_1h.tail(LOOKBACK).copy()
    price = df["close"].iloc[-1]

    # ATR для определения "близко"
    atr = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range().iloc[-1]

    # Ищем структурные точки
    swing_highs, swing_lows = find_swing_points(df, left=5, right=5)

    # Зоны ликвидности
    eqh_zones = find_equal_highs(swing_highs[-10:] if len(swing_highs) >= 10 else swing_highs)
    eql_zones = find_equal_lows(swing_lows[-10:] if len(swing_lows) >= 10 else swing_lows)

    # FVG (последние 50 свечей)
    fvg_list = find_fvg(df.tail(50))
    bullish_fvgs = [f for f in fvg_list if f["type"] == "bullish"]

    # BOS / CHoCH
    structure = detect_bos_choch(swing_highs, swing_lows, price)

    score = 50.0
    reasons = []
    details = {
        "price": price,
        "atr": round(atr, 4),
        "structure": structure["structure"],
        "bos": structure["bos"],
        "choch": structure["choch"],
        "eqh_count": len(eqh_zones),
        "eql_count": len(eql_zones),
        "bullish_fvg_count": len(bullish_fvgs),
        "last_swing_high": structure["last_swing_high"],
        "last_swing_low": structure["last_swing_low"]
    }

    # ── Структура рынка ───────────────────
    if structure["bos"]:
        score += 25
        reasons.append("BOS ✅ — бычья структура (Higher Highs + Higher Lows)")
    elif structure["choch"]:
        score += 15
        reasons.append("CHoCH — смена характера, потенциальный разворот")
    elif structure["structure"] == "bearish":
        score -= 20
        reasons.append("Медвежья структура (Lower Highs + Lower Lows)")

    # ── Цена в зоне FVG ──────────────────
    price_in_fvg = False
    for fvg in bullish_fvgs[-5:]:    # последние 5 FVG
        if fvg["bottom"] <= price <= fvg["top"]:
            score += 20
            reasons.append(f"Цена в бычьем FVG [{fvg['bottom']:.4f}–{fvg['top']:.4f}]")
            details["fvg_active"] = fvg
            price_in_fvg = True
            break

    if not price_in_fvg and bullish_fvgs:
        # Ближайший FVG снизу
        below_fvgs = [f for f in bullish_fvgs if f["top"] < price]
        if below_fvgs:
            nearest = max(below_fvgs, key=lambda x: x["top"])
            dist = (price - nearest["top"]) / atr
            if dist < 2:
                score += 10
                reasons.append(f"Бычий FVG рядом снизу (в {dist:.1f}x ATR)")

    # ── EQL под ценой (зона поддержки) ───
    eql_below = [z for z in eql_zones if z["level"] < price]
    if eql_below:
        nearest_eql = max(eql_below, key=lambda x: x["level"])
        dist_eql = (price - nearest_eql["level"]) / atr
        details["nearest_eql"] = round(nearest_eql["level"], 4)
        details["eql_distance_atr"] = round(dist_eql, 2)

        if dist_eql < 1.5:
            score += 15
            reasons.append(f"EQL поддержка в {dist_eql:.1f}x ATR (стопы собраны)")
        elif dist_eql < 3:
            score += 8
            reasons.append(f"EQL поддержка в {dist_eql:.1f}x ATR")

    # ── EQH над ценой (цель) ─────────────
    eqh_above = [z for z in eqh_zones if z["level"] > price]
    if eqh_above:
        nearest_eqh = min(eqh_above, key=lambda x: x["level"])
        dist_eqh = (nearest_eqh["level"] - price) / atr
        details["nearest_eqh"] = round(nearest_eqh["level"], 4)
        details["eqh_distance_atr"] = round(dist_eqh, 2)
        details["eqh_target"] = round(nearest_eqh["level"], 4)

        if dist_eqh < 10:
            score += 10
            reasons.append(f"EQH цель в {dist_eqh:.1f}x ATR (ликвидность выше)")

    score = max(0, min(100, score))

    if score >= 70:
        signal = "BULLISH"
    elif score >= 45:
        signal = "NEUTRAL"
    else:
        signal = "BEARISH"

    logger.info(
        f"[Liquidity] {symbol}: score={score:.0f} ({signal}) | "
        f"structure={structure['structure']} "
        f"BOS={'✅' if structure['bos'] else '❌'} "
        f"FVG={'✅' if price_in_fvg else '❌'} "
        f"EQH={len(eqh_zones)} EQL={len(eql_zones)}"
    )

    return {
        "score": round(score, 1),
        "signal": signal,
        "reason": " | ".join(reasons) if reasons else "Нет значимых уровней",
        "details": details
    }
