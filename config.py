import os
from dotenv import load_dotenv
load_dotenv()

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# === ANTHROPIC ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# === WATCHLIST FILTERS ===
MIN_VOLUME_24H_USD = 20_000_000       # минимум $20M объём за 24ч
MIN_QUOTE_VOLUME = 50_000_000         # минимум $50M на споте
TOP_BY_MOMENTUM = 30                  # после первого фильтра
ACTIVE_UNIVERSE_SIZE = 10             # финальный список для анализа

# Исключаем стейблы и неподходящие монеты
EXCLUDED_SYMBOLS = [
    "USDT", "USDC", "BUSD", "TUSD", "DAI", "FDUSD",
    "USDP", "USDD", "GUSD", "FRAX", "LUSD", "CRVUSD",
    "BTCDOM", "DEFI", "NFT", "CHESS", "BTTC"
]

# === SCORING WEIGHTS ===
WEIGHT_REGIME = 0.25
WEIGHT_OI = 0.25
WEIGHT_LIQUIDITY = 0.20
WEIGHT_SETUP = 0.20
WEIGHT_MOMENTUM = 0.10

# === SIGNAL THRESHOLDS ===
MIN_SCORE_TO_SIGNAL = 72.0    # минимальный score для сигнала (из 100)
MIN_SCORE_RISK_ON = 72.0
MIN_SCORE_NEUTRAL = 80.0      # в нейтральном режиме — выше планка

# === RISK ENGINE ===
RISK_PER_TRADE = 0.01         # 1% от депозита
MAX_OPEN_POSITIONS = 3        # максимум позиций одновременно

# BTC Regime → позиционный множитель
REGIME_MULTIPLIERS = {
    "RISK_ON": 1.0,
    "NEUTRAL": 0.5,
    "RISK_OFF": 0.0            # запрет входов
}

# TP/SL множители от ATR
SL_ATR_MULT = 1.5
TP1_ATR_MULT = 2.0
TP2_ATR_MULT = 3.5

# === TIMING ===
SCAN_INTERVAL_MINUTES = 30    # частота сканирования
WATCHLIST_UPDATE_HOURS = 4    # обновление watchlist

# === SYSTEM ===
SYSTEM_VERSION = "v2"
DB_PATH = "waveforge_v2.db"
LOG_LEVEL = "INFO"
