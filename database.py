"""
Database — логирование всех сигналов.

Хранит:
- Сигнал и все его параметры
- Мнение каждого агента отдельно
- Результат сделки (обновляется командой /result)
"""

import sqlite3
import json
import logging
from datetime import datetime
from config import DB_PATH

logger = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Основная таблица сигналов
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            system TEXT DEFAULT 'v2',
            symbol TEXT NOT NULL,
            direction TEXT,
            final_score REAL,
            regime TEXT,
            position_multiplier REAL,
            entry REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            rr_ratio REAL,
            explanation TEXT,
            -- результат
            result TEXT,         -- TP1 / TP2 / SL / OPEN
            result_pnl REAL,
            closed_at TEXT
        )
    """)

    # Детали агентов
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            agent_name TEXT,
            score REAL,
            signal TEXT,
            reason TEXT,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        )
    """)

    # Watchlist история
    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            symbols TEXT,       -- JSON список
            btc_regime TEXT
        )
    """)

    conn.commit()
    conn.close()
    logger.info("[DB] База данных инициализирована")


def save_signal(decision: dict, explanation: str = "") -> int:
    """Сохраняет сигнал и возвращает его ID."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    now = datetime.utcnow().isoformat()

    c.execute("""
        INSERT INTO signals (
            created_at, system, symbol, direction, final_score,
            regime, position_multiplier, entry, sl, tp1, tp2,
            rr_ratio, explanation, result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """, (
        now,
        "v2",
        decision["symbol"],
        decision["direction"],
        decision["final_score"],
        decision["regime"],
        decision["position_multiplier"],
        decision["entry"],
        decision["sl"],
        decision["tp1"],
        decision["tp2"],
        decision["rr_ratio"],
        explanation
    ))

    signal_id = c.lastrowid

    # Сохраняем оценки агентов
    agents_data = [
        ("regime",    decision["scores"]["regime"],    decision["agents"]["regime"].get("regime"), ""),
        ("oi",        decision["scores"]["oi"],        decision["agents"]["oi"].get("signal"),     decision["agents"]["oi"].get("reason", "")),
        ("liquidity", decision["scores"]["liquidity"], decision["agents"]["liquidity"].get("signal"), decision["agents"]["liquidity"].get("reason", "")),
        ("setup",     decision["scores"]["setup"],     decision["agents"]["setup"].get("signal"),  decision["agents"]["setup"].get("reason", "")),
    ]

    for agent_name, score, signal, reason in agents_data:
        c.execute("""
            INSERT INTO agent_scores (signal_id, agent_name, score, signal, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (signal_id, agent_name, score, signal, reason[:500] if reason else ""))

    conn.commit()
    conn.close()

    logger.info(f"[DB] Сигнал #{signal_id} сохранён: {decision['symbol']} LONG")
    return signal_id


def update_result(signal_id: int, result: str, pnl: float = None):
    """Обновляет результат сделки."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()

    c.execute("""
        UPDATE signals
        SET result = ?, result_pnl = ?, closed_at = ?
        WHERE id = ?
    """, (result, pnl, now, signal_id))

    conn.commit()
    conn.close()
    logger.info(f"[DB] Сигнал #{signal_id} обновлён: {result} PnL={pnl}")


def get_recent_signals(limit: int = 10) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, created_at, symbol, direction, final_score,
               regime, entry, sl, tp1, tp2, result, result_pnl
        FROM signals
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM signals")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM signals WHERE result = 'TP1' OR result = 'TP2'")
    wins = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM signals WHERE result = 'SL'")
    losses = c.fetchone()[0]

    c.execute("SELECT AVG(result_pnl) FROM signals WHERE result_pnl IS NOT NULL")
    avg_pnl = c.fetchone()[0] or 0

    c.execute("SELECT AVG(final_score) FROM signals")
    avg_score = c.fetchone()[0] or 0

    conn.close()

    closed = wins + losses
    winrate = (wins / closed * 100) if closed > 0 else 0

    return {
        "total": total,
        "open": total - closed,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 1),
        "avg_pnl": round(avg_pnl, 2),
        "avg_score": round(avg_score, 1)
    }


def save_watchlist(symbols: list, regime: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO watchlist_history (created_at, symbols, btc_regime)
        VALUES (?, ?, ?)
    """, (datetime.utcnow().isoformat(), json.dumps(symbols), regime))
    conn.commit()
    conn.close()


def save_scanner_results(candidates: list):
    """Сохраняет результаты Market Scanner для расчёта ΔScore."""
    if not candidates:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Создаём таблицу если нет
    c.execute("""
        CREATE TABLE IF NOT EXISTS scanner_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            market_score REAL,
            trend_score REAL,
            rs_score REAL,
            rs_7d REAL,
            return_7d REAL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_scanner_symbol ON scanner_history(symbol)")

    now = datetime.utcnow().isoformat()
    for coin in candidates:
        c.execute("""
            INSERT INTO scanner_history
            (created_at, symbol, market_score, trend_score, rs_score, rs_7d, return_7d)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            coin["symbol"],
            coin.get("market_score", 0),
            coin.get("trend_score", 0),
            coin.get("rs_score", 0),
            coin.get("rs_7d", 0),
            coin.get("return_7d", 0)
        ))

    conn.commit()
    conn.close()


def get_delta_scores(hours_ago: int = 6) -> dict:
    """
    Считает ΔScore = market_score_now - market_score_N_часов_назад.
    Возвращает словарь {symbol: delta_score}.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        # Последние записи (текущий скан)
        c.execute("""
            SELECT symbol, market_score FROM scanner_history
            WHERE created_at = (SELECT MAX(created_at) FROM scanner_history)
        """)
        current = {row[0]: row[1] for row in c.fetchall()}

        # Записи N часов назад
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=hours_ago)).isoformat()
        c.execute("""
            SELECT symbol, market_score FROM scanner_history
            WHERE created_at <= ?
            ORDER BY created_at DESC
        """, (cutoff,))
        # Берём последнее значение для каждого символа до cutoff
        previous = {}
        for row in c.fetchall():
            if row[0] not in previous:
                previous[row[0]] = row[1]

        # Считаем дельту
        deltas = {}
        for symbol, score_now in current.items():
            if symbol in previous:
                deltas[symbol] = round(score_now - previous[symbol], 1)

        return deltas

    except Exception as e:
        return {}
    finally:
        conn.close()
