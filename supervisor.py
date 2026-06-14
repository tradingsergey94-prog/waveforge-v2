"""
Supervisor — детерминированный Score Engine
Поддерживает LONG и SHORT сигналы.
"""

import logging
from config import (
    WEIGHT_REGIME, WEIGHT_OI, WEIGHT_LIQUIDITY,
    WEIGHT_SETUP, WEIGHT_MOMENTUM,
    MIN_SCORE_TO_SIGNAL, MIN_SCORE_NEUTRAL,
    REGIME_MULTIPLIERS
)

logger = logging.getLogger(__name__)


def calculate_final_score(regime_score, oi_score, liquidity_score, setup_score, momentum_score):
    raw = (
        regime_score    * WEIGHT_REGIME +
        oi_score        * WEIGHT_OI +
        liquidity_score * WEIGHT_LIQUIDITY +
        setup_score     * WEIGHT_SETUP +
        momentum_score  * WEIGHT_MOMENTUM
    )
    return round(min(100, max(0, raw)), 1)


def should_trade(final_score, regime, setup_signal, allowed_directions, rr_ratio=0):
    if not allowed_directions:
        return False, "RISK_OFF — запрет входов"

    if setup_signal not in allowed_directions:
        return False, f"Setup дал {setup_signal}, но Regime разрешает только {allowed_directions}"

    if rr_ratio < 1.5:
        return False, f"RR ratio {rr_ratio:.1f} < 1.5"

    # Порог score зависит от режима
    if regime == "RISK_ON":
        min_score = MIN_SCORE_TO_SIGNAL
    elif regime == "BEAR":
        min_score = MIN_SCORE_TO_SIGNAL
    else:  # NEUTRAL
        min_score = MIN_SCORE_NEUTRAL

    if final_score >= min_score:
        return True, f"Score {final_score} >= {min_score} | Режим: {regime}"
    else:
        return False, f"Score {final_score} < {min_score} (порог для {regime})"


def build_decision(symbol, regime_result, oi_result, liquidity_result, setup_result, watchlist_coin):
    regime             = regime_result.get("regime", "NEUTRAL")
    allowed_directions = regime_result.get("allowed_directions", ["LONG", "SHORT"])
    regime_score       = regime_result.get("score", 50)
    oi_score           = oi_result.get("score", 50)
    liquidity_score    = liquidity_result.get("score", 50)
    setup_score        = setup_result.get("score", 0)
    momentum_score     = min(100, watchlist_coin.get("watchlist_score", 50))

    final_score  = calculate_final_score(regime_score, oi_score, liquidity_score, setup_score, momentum_score)
    setup_signal = setup_result.get("signal")
    rr_ratio     = setup_result.get("rr_ratio", 0)

    trade, reason = should_trade(final_score, regime, setup_signal, allowed_directions, rr_ratio)

    # Множитель размера позиции
    mult_map = {"RISK_ON": 1.0, "NEUTRAL": 0.7, "BEAR": 0.7, "RISK_OFF": 0.0}
    position_mult = mult_map.get(regime, 0.5)

    decision = {
        "symbol":             symbol,
        "trade":              trade,
        "direction":          setup_signal if trade else None,
        "final_score":        final_score,
        "regime":             regime,
        "allowed_directions": allowed_directions,
        "position_multiplier": position_mult,
        "reason":             reason,
        "scores": {
            "regime":    regime_score,
            "oi":        oi_score,
            "liquidity": liquidity_score,
            "setup":     setup_score,
            "momentum":  momentum_score,
            "final":     final_score
        },
        "entry":    setup_result.get("entry"),
        "sl":       setup_result.get("sl"),
        "tp1":      setup_result.get("tp1"),
        "tp2":      setup_result.get("tp2"),
        "rr_ratio": rr_ratio,
        "agents": {
            "regime":    regime_result,
            "oi":        oi_result,
            "liquidity": liquidity_result,
            "setup":     setup_result
        }
    }

    logger.info(
        f"[Supervisor] {symbol}: trade={trade} dir={setup_signal} score={final_score} | "
        f"R={regime_score:.0f} OI={oi_score:.0f} L={liquidity_score:.0f} S={setup_score:.0f}"
    )

    return decision
