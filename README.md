# WaveForge v2

Параллельная торговая система рядом со swing_detector (v1).

## Архитектура

```
300+ монет Binance Futures
    ↓ Ликвидность (Volume > $20M)
~100 монет
    ↓ Momentum + RS vs BTC + Volume Score
~30 монет
    ↓ OI + Funding Score
~10 монет (Active Universe)
    ↓
BTC Regime (гейткипер)
    ↓
OI Agent + Liquidity Agent + Setup Agent
    ↓
Supervisor (детерминированный score)
    ↓
Claude (только объясняет)
    ↓
Telegram Signal
```

## Ключевые отличия от v1 (swing_detector)

| | v1 (swing_detector) | v2 (WaveForge) |
|---|---|---|
| Символы | Фиксированные 7 | Динамический топ-10 |
| Источник сигнала | SuperTrend + Fibo | OI + Liquidity + Structure |
| LLM роль | Подтверждение | Только объяснение |
| Данные | OKX | Binance Public API |
| BTC фильтр | Планируется | Встроен (Regime) |

## Установка

```bash
git clone <repo>
cd waveforge_v2
pip install -r requirements.txt
cp .env.example .env
# Заполни .env
python main.py
```

## Переменные окружения (.env)

```
TELEGRAM_BOT_TOKEN=   # новый бот от @BotFather
TELEGRAM_CHAT_ID=     # твой chat_id
ANTHROPIC_API_KEY=    # ключ Claude API
```

## Telegram команды

| Команда | Описание |
|---|---|
| /start | Список команд |
| /status | BTC режим + Active Universe |
| /scan | Запустить сканирование вручную |
| /watchlist | Обновить список монет |
| /stats | Статистика сигналов |
| /result 5 TP1 | Отметить результат сделки #5 |

## Railway.app деплой

1. Push в GitHub
2. New Project → Deploy from GitHub
3. Add Variables (из .env)
4. Deploy

## Данные (бесплатно, без API ключей)

- `fapi.binance.com` — фьючерсы OHLCV, тикеры, OI, funding
- `futures/data/openInterestHist` — история OI
- `futures/data/globalLongShortAccountRatio` — L/S ratio

## Логика Score

```python
final_score = (
    regime_score    * 0.25 +
    oi_score        * 0.25 +
    liquidity_score * 0.20 +
    setup_score     * 0.20 +
    momentum_score  * 0.10
)

# Порог для сигнала
RISK_ON  → score >= 72
NEUTRAL  → score >= 80
RISK_OFF → запрет входов
```

## Сравнение с v1

После 20+ сигналов от каждой системы сравниваем:
- Win Rate
- Средний PnL
- Средний Score
- Profit Factor
