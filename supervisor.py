"""
Supervisor — детерминированный Score Engine

Принимает результаты всех агентов, считает финальный score.
LLM НЕ принимает решение — только объясняет.

Веса:
- Regime:    25%
- OI:        25%
- Liquidity: 20%
- Setup:     20%
- Momentum:  10%
"""

import logging
from config import (
    WEIGHT_REGIME, WEIGHT_OI, WEIGHT_LIQUIDITY,
    WEIGHT_SETUP, WEIGHT_MOMENTUM,
    MIN_SCORE_TO_SIGNAL, MIN_SCORE_NEUTRAL,
    REGIME_MULTIPLIERS
)

logger = logging.getLogger(__name__)


def calculate_final_score(
    regime_score: float,
    oi_score: float,
    liquidity_score: float,
    setup_score: float,
    momentum_score: float,
    regime: str
) -> float:
    """
    Взвешенный финальный score (0-100).
    """
    raw = (
        regime_score    * WEIGHT_REGIME +
        oi_score        * WEIGHT_OI +
        liquidity_score * WEIGHT_LIQUIDITY +
        setup_score     * WEIGHT_SETUP +
        momentum_score  * WEIGHT_MOMENTUM
    )

    # Нормализуем momentum_score из watchlist (0-100) если нужно
    return round(min(100, max(0, raw)), 1)


def should_trade(
    final_score: float,
    regime: str,
    setup_signal: str,
    rr_ratio: float = 0
) -> tuple[bool, str]:
    """
    Финальное решение: торговать или нет.

    Правила:
    - RISK_OFF → никогда
    - RISK_ON → score >= MIN_SCORE_TO_SIGNAL
    - NEUTRAL → score >= MIN_SCORE_NEUTRAL (планка выше)
    - Setup должен дать LONG
    - RR должен быть >= 1.5
    """
    if regime == "RISK_OFF":
        return False, "BTC Regime: RISK_OFF — запрет входов"

    if setup_signal != "LONG":
        return False, f"Setup не дал сигнал LONG (результат: {setup_signal})"

    if rr_ratio < 1.5:
        return False, f"RR ratio {rr_ratio:.1f} < 1.5 — риск не оправдан"

    min_score = MIN_SCORE_TO_SIGNAL if regime == "RISK_ON" else MIN_SCORE_NEUTRAL

    if final_score >= min_score:
        return True, f"Score {final_score} >= {min_score} | Режим: {regime}"
    else:
        return False, f"Score {final_score} < {min_score} (порог для {regime})"


def get_position_multiplier(regime: str) -> float:
    return REGIME_MULTIPLIERS.get(regime, 0.5)


def build_decision(
    symbol: str,
    regime_result: dict,
    oi_result: dict,
    liquidity_result: dict,
    setup_result: dict,
    watchlist_coin: dict
) -> dict:
    """
    Собирает финальное решение из результатов всех агентов.
    """
    regime = regime_result.get("regime", "NEUTRAL")
    regime_score = regime_result.get("score", 50)
    oi_score = oi_result.get("score", 50)
    liquidity_score = liquidity_result.get("score", 50)
    setup_score = setup_result.get("score", 0)
    momentum_score = min(100, watchlist_coin.get("watchlist_score", 50))

    final_score = calculate_final_score(
        regime_score, oi_score, liquidity_score,
        setup_score, momentum_score, regime
    )

    setup_signal = setup_result.get("signal")
    rr_ratio = setup_result.get("rr_ratio", 0)

    trade, reason = should_trade(final_score, regime, setup_signal, rr_ratio)

    position_mult = get_position_multiplier(regime)

    decision = {
        "symbol": symbol,
        "trade": trade,
        "direction": "LONG" if trade else None,
        "final_score": final_score,
        "regime": regime,
        "position_multiplier": position_mult,
        "reason": reason,
        "scores": {
            "regime": regime_score,
            "oi": oi_score,
            "liquidity": liquidity_score,
            "setup": setup_score,
            "momentum": momentum_score,
            "final": final_score
        },
        "entry": setup_result.get("entry"),
        "sl": setup_result.get("sl"),
        "tp1": setup_result.get("tp1"),
        "tp2": setup_result.get("tp2"),
        "rr_ratio": rr_ratio,
        "agents": {
            "regime": regime_result,
            "oi": oi_result,
            "liquidity": liquidity_result,
            "setup": setup_result
        }
    }

    logger.info(
        f"[Supervisor] {symbol}: trade={trade} score={final_score} | "
        f"R={regime_score:.0f} OI={oi_score:.0f} "
        f"L={liquidity_score:.0f} S={setup_score:.0f} M={momentum_score:.0f}"
    )

    return decision
