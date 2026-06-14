"""
OI + Funding Agent

Анализирует структуру участников рынка:
- Динамика Open Interest (рост/падение)
- Funding Rate (перегрев/охлаждение)
- Long/Short Ratio (настроение толпы)

Price ↑ + OI ↑ = реальный спрос         → BULLISH
Price ↑ + OI ↓ = закрытие шортов (слабо) → NEUTRAL
Price ↑ + OI ↑ + Funding высокий         → ОСТОРОЖНО (перегрев)
"""

import logging
import binance_client as bc

logger = logging.getLogger(__name__)

# Пороги для funding rate
FUNDING_NEUTRAL_MAX = 0.05    # %
FUNDING_OVERHEATED = 0.10     # %
FUNDING_NEGATIVE = -0.01      # % (хорошо для лонгов)


def analyze_oi(symbol: str, price_change_24h: float) -> dict:
    """
    Полный OI + Funding анализ для одного символа.
    Возвращает score (0-100) и детали.
    """
    result = {
        "symbol": symbol,
        "score": 50,
        "signal": "NEUTRAL",
        "oi_trend": "unknown",
        "funding_status": "unknown",
        "details": {},
        "reason": ""
    }

    score = 50.0
    reasons = []

    # ── OI динамика ──────────────────────
    oi_hist = bc.get_open_interest_history(symbol, period="1h", limit=12)

    if oi_hist is not None and len(oi_hist) >= 4:
        oi_vals = oi_hist["sumOpenInterestValue"].values

        # Изменение за последние 4 часа
        oi_change_4h = (oi_vals[-1] - oi_vals[-4]) / oi_vals[-4] * 100
        # Изменение за последние 12 часов
        oi_change_12h = (oi_vals[-1] - oi_vals[0]) / oi_vals[0] * 100

        result["details"]["oi_change_4h"] = round(oi_change_4h, 2)
        result["details"]["oi_change_12h"] = round(oi_change_12h, 2)
        result["details"]["oi_value"] = round(float(oi_vals[-1]), 0)

        # Price ↑ + OI ↑ — сильная комбинация
        if price_change_24h > 0:
            if oi_change_4h > 8:
                score += 30
                reasons.append(f"OI +{oi_change_4h:.1f}% за 4h при росте цены (сильный спрос)")
                result["oi_trend"] = "strong_bullish"
            elif oi_change_4h > 4:
                score += 20
                reasons.append(f"OI +{oi_change_4h:.1f}% за 4h (накопление позиций)")
                result["oi_trend"] = "bullish"
            elif oi_change_4h > 1:
                score += 10
                reasons.append(f"OI слабо растёт +{oi_change_4h:.1f}%")
                result["oi_trend"] = "weak_bullish"
            elif oi_change_4h < -3:
                score -= 15
                reasons.append(f"OI падает {oi_change_4h:.1f}% — закрытие шортов, не реальный спрос")
                result["oi_trend"] = "short_squeeze"
            else:
                reasons.append("OI стабильный")
                result["oi_trend"] = "neutral"

        elif price_change_24h < 0:
            if oi_change_4h > 5:
                score -= 20
                reasons.append(f"OI растёт +{oi_change_4h:.1f}% при падении — наращивание шортов")
                result["oi_trend"] = "bearish"
            else:
                result["oi_trend"] = "neutral"
    else:
        reasons.append("OI данные недоступны")

    # ── Funding Rate ─────────────────────
    funding = bc.get_funding_rate(symbol)

    if funding is not None:
        funding_pct = funding * 100
        result["details"]["funding_rate"] = round(funding_pct, 4)

        if funding_pct < FUNDING_NEGATIVE:
            # Отрицательный funding — шорты платят лонгам
            score += 20
            reasons.append(f"Funding {funding_pct:.4f}% (отрицательный — хорошо для лонгов)")
            result["funding_status"] = "negative_bullish"
        elif funding_pct <= FUNDING_NEUTRAL_MAX:
            # Нормальный диапазон
            score += 10
            reasons.append(f"Funding {funding_pct:.4f}% (норма)")
            result["funding_status"] = "normal"
        elif funding_pct <= FUNDING_OVERHEATED:
            # Умеренно высокий
            score -= 5
            reasons.append(f"Funding {funding_pct:.4f}% (умеренно высокий)")
            result["funding_status"] = "elevated"
        else:
            # Перегрет
            score -= 20
            reasons.append(f"Funding {funding_pct:.4f}% (перегрет — риск ликвидации лонгов)")
            result["funding_status"] = "overheated"
    else:
        reasons.append("Funding данные недоступны")

    # ── Long/Short Ratio ─────────────────
    ls_ratio = bc.get_long_short_ratio(symbol, period="1h", limit=1)

    if ls_ratio is not None:
        result["details"]["ls_ratio"] = round(ls_ratio, 2)

        if ls_ratio < 0.9:
            # Больше шортов — потенциальный short squeeze
            score += 10
            reasons.append(f"L/S ratio {ls_ratio:.2f} (шорты доминируют — потенциальный squeeze)")
        elif ls_ratio > 1.8:
            # Слишком много лонгов — толпа на одной стороне
            score -= 10
            reasons.append(f"L/S ratio {ls_ratio:.2f} (лонги доминируют — осторожно)")
        else:
            reasons.append(f"L/S ratio {ls_ratio:.2f} (сбалансированный)")

    # Итог
    score = max(0, min(100, score))

    if score >= 70:
        result["signal"] = "BULLISH"
    elif score >= 45:
        result["signal"] = "NEUTRAL"
    else:
        result["signal"] = "BEARISH"

    result["score"] = round(score, 1)
    result["reason"] = " | ".join(reasons)

    logger.info(
        f"[OI] {symbol}: score={score:.0f} ({result['signal']}) | "
        f"OI trend={result['oi_trend']} funding={result['funding_status']}"
    )

    return result
