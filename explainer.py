"""
Explainer — Claude объясняет сигнал.

LLM НЕ принимает решение.
LLM только пишет понятное объяснение
почему система открыла сигнал.
"""

import anthropic
import logging
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def explain_signal(decision: dict) -> str:
    """
    Генерирует краткое объяснение сигнала на русском.
    2-3 предложения максимум.
    """
    if not decision.get("trade"):
        return ""

    symbol = decision["symbol"]
    regime = decision["regime"]
    scores = decision["scores"]
    oi_result = decision["agents"]["oi"]
    liquidity_result = decision["agents"]["liquidity"]
    setup_result = decision["agents"]["setup"]
    watchlist = decision.get("watchlist_data", {})

    prompt = f"""Ты трейдинг-аналитик. Напиши КРАТКОЕ объяснение торгового сигнала в 2-3 предложениях.
Пиши на русском, без воды, только факты.

Символ: {symbol}
Направление: LONG
Финальный score: {scores['final']}/100
BTC Режим: {regime}

Данные агентов:
- Momentum: изменение 24ч = {watchlist.get('change_24h', 0):+.1f}%, RS vs BTC = {watchlist.get('rs_vs_btc', 0):.1f}x
- OI: {oi_result.get('reason', '')}
- Ликвидность: {liquidity_result.get('reason', '')}
- Setup: {setup_result.get('reason', '')}

Напиши 2-3 предложения объяснения. Без заголовков, без markdown."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return f"Технический сигнал на основе анализа структуры рынка. Score: {scores['final']}/100."
