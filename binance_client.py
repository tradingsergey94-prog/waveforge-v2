"""
Binance Public API Client
Все запросы — публичные, ключи не нужны.
"""

import requests
import pandas as pd
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"        # Futures
SPOT_URL = "https://api.binance.com"         # Spot (для доп. данных)


def _get(url: str, params: dict = None, retries: int = 3) -> Optional[dict | list]:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Request failed ({attempt+1}/{retries}): {url} — {e}")
            time.sleep(1)
    return None


# ─────────────────────────────────────────
# СИМВОЛЫ
# ─────────────────────────────────────────

def get_all_futures_symbols() -> list[str]:
    """Все USDT-M фьючерсные пары."""
    data = _get(f"{BASE_URL}/fapi/v1/exchangeInfo")
    if not data:
        return []
    return [
        s["symbol"] for s in data["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["contractType"] == "PERPETUAL"
    ]


# ─────────────────────────────────────────
# ТИКЕРЫ (объём, изменение цены)
# ─────────────────────────────────────────

def get_24h_tickers() -> list[dict]:
    """24h статистика по всем фьючерсам."""
    data = _get(f"{BASE_URL}/fapi/v1/ticker/24hr")
    return data or []


def get_ticker(symbol: str) -> Optional[dict]:
    data = _get(f"{BASE_URL}/fapi/v1/ticker/24hr", {"symbol": symbol})
    return data


# ─────────────────────────────────────────
# СВЕЧИ (OHLCV)
# ─────────────────────────────────────────

def get_klines(symbol: str, interval: str, limit: int = 500) -> Optional[pd.DataFrame]:
    """
    Загружаем OHLCV свечи.
    interval: '15m', '1h', '4h', '1d'
    """
    data = _get(
        f"{BASE_URL}/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit}
    )
    if not data:
        return None

    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume',
                'taker_buy_base', 'taker_buy_quote']:
        df[col] = df[col].astype(float)

    df.set_index('timestamp', inplace=True)
    return df


# ─────────────────────────────────────────
# OPEN INTEREST
# ─────────────────────────────────────────

def get_open_interest(symbol: str) -> Optional[float]:
    """Текущий OI в USDT."""
    data = _get(f"{BASE_URL}/fapi/v1/openInterest", {"symbol": symbol})
    if not data:
        return None
    return float(data.get("openInterest", 0))


def get_open_interest_history(symbol: str, period: str = "1h", limit: int = 24) -> Optional[pd.DataFrame]:
    """
    История OI для анализа динамики.
    period: '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'
    """
    data = _get(
        f"{BASE_URL}/futures/data/openInterestHist",
        {"symbol": symbol, "period": period, "limit": limit}
    )
    if not data:
        return None

    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['sumOpenInterest'] = df['sumOpenInterest'].astype(float)
    df['sumOpenInterestValue'] = df['sumOpenInterestValue'].astype(float)
    df.set_index('timestamp', inplace=True)
    return df


# ─────────────────────────────────────────
# FUNDING RATE
# ─────────────────────────────────────────

def get_funding_rate(symbol: str) -> Optional[float]:
    """Текущий funding rate."""
    data = _get(f"{BASE_URL}/fapi/v1/premiumIndex", {"symbol": symbol})
    if not data:
        return None
    return float(data.get("lastFundingRate", 0))


def get_funding_history(symbol: str, limit: int = 8) -> Optional[list]:
    """История funding rate."""
    data = _get(
        f"{BASE_URL}/fapi/v1/fundingRate",
        {"symbol": symbol, "limit": limit}
    )
    return data


# ─────────────────────────────────────────
# BTC ДАННЫЕ (для Regime)
# ─────────────────────────────────────────

def get_btc_price() -> Optional[float]:
    data = _get(f"{BASE_URL}/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
    if not data:
        return None
    return float(data["price"])


def get_btc_klines(interval: str = "4h", limit: int = 200) -> Optional[pd.DataFrame]:
    return get_klines("BTCUSDT", interval, limit)


# ─────────────────────────────────────────
# LONG/SHORT RATIO (настроения)
# ─────────────────────────────────────────

def get_long_short_ratio(symbol: str, period: str = "1h", limit: int = 1) -> Optional[float]:
    """Long/Short Ratio трейдеров."""
    data = _get(
        f"{BASE_URL}/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol, "period": period, "limit": limit}
    )
    if not data or len(data) == 0:
        return None
    return float(data[0].get("longShortRatio", 1.0))
