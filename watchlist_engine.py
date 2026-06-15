"""
Watchlist Engine v2.1

Теперь работает поверх Market Scanner:
Market Scanner (топ-50) → Watchlist Engine (топ-10)

Шаг 1: Получаем топ-50 от Market Scanner (Trend + RS 7d)
Шаг 2: Momentum Score (24h изменение, объём, позиция в диапазоне)
Шаг 3: OI + Funding Score
Шаг 4: Финальный рейтинг → топ-10 Active Universe
"""

import logging
import time
import numpy as np
import binance_client as bc
from config import (
    EXCLUDED_SYMBOLS, MIN_VOLUME_24H_USD,
    TOP_BY_MOMENTUM, ACTIVE_UNIVERSE_SIZE
)

logger = logging.getLogger(__name__)


def score_momentum(coins: list[dict], btc_change_24h: float) -> list[dict]:
    """Momentum Score с учётом 7d RS."""
    if not coins:
        return []

    volumes   = [c["volume_24h"] for c in coins]
    median_vol = float(np.median(volumes)) if volumes else 1

    scored = []
    for coin in coins:
        score = 0.0

        change = coin["change_24h"]

        # 1. Изменение цены за 24ч (0-30 баллов)
        if change > 15:   score += 30
        elif change > 10: score += 25
        elif change > 7:  score += 20
        elif change > 5:  score += 15
        elif change > 3:  score += 8
        elif change > 0:  score += 3

        # 2. RS 1d vs BTC (0-25 баллов)
        if btc_change_24h != 0:
            rs1d = change / abs(btc_change_24h)
        else:
            rs1d = 1.0

        if rs1d > 3:   score += 25
        elif rs1d > 2: score += 20
        elif rs1d > 1.5: score += 15
        elif rs1d > 1: score += 10
        elif rs1d > 0: score += 4

        # 3. RS 7d vs BTC (0-25 баллов) — НОВОЕ
        rs7d = coin.get("rs_7d", 0)
        if rs7d > 3:   score += 25
        elif rs7d > 2: score += 20
        elif rs7d > 1.5: score += 15
        elif rs7d > 1: score += 10
        elif rs7d > 0: score += 4

        # 4. Volume аномалия (0-15 баллов)
        vol_ratio = coin["volume_24h"] / median_vol if median_vol > 0 else 1
        if vol_ratio > 5:   score += 15
        elif vol_ratio > 3: score += 12
        elif vol_ratio > 2: score += 8
        elif vol_ratio > 1.5: score += 5
        elif vol_ratio > 1: score += 2

        # 5. Trend Score бонус (0-5 баллов) — НОВОЕ
        trend_score = coin.get("trend_score", 50)
        if trend_score > 75:  score += 5
        elif trend_score > 60: score += 2
        elif trend_score < 35: score -= 5

        coin["momentum_score"] = round(score, 2)
        coin["rs_vs_btc"]      = round(rs1d, 2)
        coin["vol_ratio"]      = round(vol_ratio, 2)
        scored.append(coin)

    scored.sort(key=lambda x: x["momentum_score"], reverse=True)
    top = scored[:TOP_BY_MOMENTUM]

    logger.info(f"[Watchlist] После Momentum Score: {len(top)} монет")
    if top:
        logger.info(f"  Топ-5: {[c['symbol'] for c in top[:5]]}")

    return top


def score_oi_funding(coins: list[dict]) -> list[dict]:
    """OI + Funding Score."""
    scored = []

    for coin in coins:
        symbol     = coin["symbol"]
        oi_score   = 50.0
        funding_score = 50.0

        try:
            oi_hist = bc.get_open_interest_history(symbol, period="1h", limit=8)
            if oi_hist is not None and len(oi_hist) >= 3:
                oi_vals    = oi_hist["sumOpenInterestValue"].values
                oi_change  = (oi_vals[-1] - oi_vals[0]) / oi_vals[0] * 100
                price_change = coin["change_24h"]

                if price_change > 0 and oi_change > 5:    oi_score = 85
                elif price_change > 0 and oi_change > 2:  oi_score = 75
                elif price_change > 0 and oi_change > 0:  oi_score = 65
                elif price_change > 0 and oi_change < 0:  oi_score = 45
                elif price_change < 0 and oi_change > 0:  oi_score = 30
                else:                                       oi_score = 50

                coin["oi_change_8h"] = round(oi_change, 2)
            else:
                coin["oi_change_8h"] = 0
        except Exception:
            coin["oi_change_8h"] = 0

        try:
            funding = bc.get_funding_rate(symbol)
            if funding is not None:
                fp = funding * 100
                coin["funding_rate"] = round(fp, 4)
                if fp < -0.01:            funding_score = 80
                elif fp <= 0.05:          funding_score = 70
                elif fp <= 0.1:           funding_score = 50
                else:                     funding_score = 25
            else:
                coin["funding_rate"] = 0
        except Exception:
            coin["funding_rate"] = 0

        coin["oi_score"]       = oi_score
        coin["funding_score"]  = funding_score
        coin["oi_funding_score"] = round(oi_score * 0.6 + funding_score * 0.4, 2)
        scored.append(coin)
        time.sleep(0.1)

    # Финальный watchlist score — теперь включает market_score
    for coin in scored:
        coin["watchlist_score"] = round(
            coin["momentum_score"]   * 0.35 +
            coin["oi_funding_score"] * 0.35 +
            coin.get("market_score", 50) * 0.30,
            2
        )

    scored.sort(key=lambda x: x["watchlist_score"], reverse=True)
    active = scored[:ACTIVE_UNIVERSE_SIZE]

    logger.info(f"[Watchlist] Active Universe ({len(active)} монет):")
    for i, c in enumerate(active, 1):
        logger.info(
            f"  {i}. {c['symbol']:16} "
            f"wl={c['watchlist_score']:5.1f} "
            f"mkt={c.get('market_score', 0):5.1f} "
            f"24h={c['change_24h']:+.1f}% "
            f"7d={c.get('return_7d', 0):+.1f}% "
            f"RS7d={c.get('rs_7d', 0):+.1f}x "
            f"OI={c['oi_change_8h']:+.1f}%"
        )

    return active


def build_watchlist(scanner_candidates: list[dict] = None) -> list[dict]:
    """
    Полный цикл отбора.

    scanner_candidates: топ-50 от Market Scanner
    Если не переданы — используем базовый режим (только тикеры).
    """
    logger.info("[Watchlist] Начинаем построение Active Universe...")

    tickers = bc.get_24h_tickers()
    if not tickers:
        logger.error("[Watchlist] Нет данных с Binance")
        return []

    btc_ticker    = next((t for t in tickers if t["symbol"] == "BTCUSDT"), None)
    btc_change_24h = float(btc_ticker["priceChangePercent"]) if btc_ticker else 0

    logger.info(f"[Watchlist] BTC 24h: {btc_change_24h:+.2f}%")

    if scanner_candidates:
        # Режим с Market Scanner — обогащаем данными тикеров
        ticker_map = {t["symbol"]: t for t in tickers}
        coins = []
        for c in scanner_candidates:
            sym = c["symbol"]
            t   = ticker_map.get(sym, {})
            if not t:
                continue
            vol = float(t.get("quoteVolume", 0))
            if vol < MIN_VOLUME_24H_USD:
                continue
            coins.append({
                **c,
                "volume_24h": vol,
                "change_24h": float(t.get("priceChangePercent", c.get("change_24h", 0))),
                "price":      float(t.get("lastPrice", c.get("price", 0))),
                "high_24h":   float(t.get("highPrice", 0)),
                "low_24h":    float(t.get("lowPrice", 0)),
            })
        logger.info(f"[Watchlist] Кандидатов от Scanner: {len(coins)}")
    else:
        # Базовый режим — фильтруем тикеры
        # Получаем 7d данные через klines (последние 8 дневных свечей)
        logger.info("[Watchlist] Базовый режим — загружаем 7d данные...")

        # Сначала собираем кандидатов
        candidates_raw = []
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
            candidates_raw.append({
                "symbol":     symbol,
                "price":      float(t.get("lastPrice", 0)),
                "change_24h": float(t.get("priceChangePercent", 0)),
                "volume_24h": vol,
                "high_24h":   float(t.get("highPrice", 0)),
                "low_24h":    float(t.get("lowPrice", 0)),
            })

        # Берём топ-50 по объёму для загрузки 7d данных
        candidates_raw.sort(key=lambda x: x["volume_24h"], reverse=True)

        # Загружаем 7d данные для топ-50
        btc_change_7d = 0
        coins = []
        for coin in candidates_raw[:80]:
            symbol = coin["symbol"]
            return_7d = 0
            rs_7d     = 0
            try:
                df_daily = bc.get_klines(symbol, "1d", limit=10)
                if df_daily is not None and len(df_daily) >= 8:
                    closes = df_daily["close"].values
                    return_7d = (closes[-1] - closes[-8]) / closes[-8] * 100
                    if symbol == "BTCUSDT":
                        btc_change_7d = return_7d
            except Exception:
                pass

            coins.append({
                **coin,
                "market_score": 50,
                "trend_score":  50,
                "rs_7d":        rs_7d,
                "return_7d":    round(return_7d, 2),
            })
            time.sleep(0.05)

        # Считаем RS vs BTC для всех монет
        if btc_change_7d != 0:
            for coin in coins:
                coin["rs_7d"] = round(coin["return_7d"] / abs(btc_change_7d), 2)

        logger.info(f"[Watchlist] Базовый режим: {len(coins)} монет (с 7d данными)")

    momentum_top     = score_momentum(coins, btc_change_24h)
    active_universe  = score_oi_funding(momentum_top)
    return active_universe
