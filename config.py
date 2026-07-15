import os
from dotenv import load_dotenv
load_dotenv()

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = [x.strip() for x in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if x.strip()]

# === ANTHROPIC ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# === WATCHLIST FILTERS ===
MIN_VOLUME_24H_USD    = 20_000_000
TOP_BY_MOMENTUM       = 30
ACTIVE_UNIVERSE_SIZE  = 10

EXCLUDED_SYMBOLS = [
    "USDT","USDC","BUSD","TUSD","DAI","FDUSD",
    "USDP","USDD","GUSD","FRAX","LUSD","CRVUSD",
    "BTCDOM","DEFI","NFT","CHESS","BTTC"
]

# === SCORING WEIGHTS (сумма = 1.0) ===
WEIGHT_REGIME    = 0.25
WEIGHT_OI        = 0.15   # снижено с 0.25
WEIGHT_LIQUIDITY = 0.20
WEIGHT_SETUP     = 0.20
WEIGHT_MOMENTUM  = 0.20   # повышено с 0.10

# === SIGNAL THRESHOLDS ===
MIN_SCORE_TO_SIGNAL = 72.0
MIN_SCORE_NEUTRAL   = 80.0

# === RISK ENGINE ===
RISK_PER_TRADE      = 0.01
MAX_OPEN_POSITIONS  = 3

REGIME_MULTIPLIERS = {
    "RISK_ON":  1.0,
    "NEUTRAL":  0.7,
    "BEAR":     0.7,
    "RISK_OFF": 0.0
}

SL_ATR_MULT  = 1.5
TP1_ATR_MULT = 2.0
TP2_ATR_MULT = 3.5

# === TIMING ===
SCAN_INTERVAL_MINUTES  = 30
WATCHLIST_UPDATE_HOURS = 4
SCANNER_INTERVAL_HOURS = 6    # обновление Market Scanner каждые 6 часов

# === SYSTEM ===
SYSTEM_VERSION = "v2.1"
DB_PATH        = "waveforge_v2.db"
LOG_LEVEL      = "INFO"
