"""
WaveForge v2 — Backtester
Без внешних зависимостей кроме pandas и numpy.
Все индикаторы считаются вручную.
"""

import pandas as pd
import numpy as np
import json
import time
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import binance_client as bc

# ─────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────

SYMBOLS_TOP10 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"
]

SYMBOLS_ACTIVE = [
    "ZECUSDT", "OPGUSDT", "JELLYJELLYUSDT", "TAOUSDT",
    "HYPEUSDT", "EIGENUSDT", "MUUSDT", "INTCUSDT",
    "EVAAUSDT", "BABYUSDT"
]

ST_PERIOD     = 10
ST_MULTIPLIER = 3.0
RSI_PERIOD    = 14
EMA21_PERIOD  = 21
EMA50_PERIOD  = 50
RSI_MAX       = 72
RSI_MIN       = 28
SL_ATR_MULT   = 1.5
TP1_ATR_MULT  = 2.5
TP2_ATR_MULT  = 4.0
MIN_RR        = 1.5
VOL_MULT      = 1.3
MAX_BARS_HOLD = 48

RISK_PCT     = 0.01
INITIAL_CAP  = 10000
CANDLE_LIMIT = 26280
START_DATE   = "2022-01-01"
END_DATE     = "2024-12-31"


# ─────────────────────────────────────────
# ИНДИКАТОРЫ (без ta библиотеки)
# ─────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, adjust=False).mean()
    avg_loss = loss.ewm(com=period-1, adjust=False).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=period-1, adjust=False).mean()


def calc_supertrend(high, low, close, period=ST_PERIOD, mult=ST_MULTIPLIER):
    atr  = calc_atr(high, low, close, period)
    hl2  = (high + low) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    n         = len(close)
    direction = np.zeros(n, dtype=bool)
    st_line   = np.zeros(n)

    for i in range(period, n):
        if i == period:
            direction[i] = False
            st_line[i]   = upper.iloc[i]
            continue

        prev_upper = st_line[i-1] if not direction[i-1] else upper.iloc[i]
        prev_lower = st_line[i-1] if direction[i-1]     else lower.iloc[i]

        curr_upper = upper.iloc[i] if upper.iloc[i] < prev_upper or close.iloc[i-1] > prev_upper else prev_upper
        curr_lower = lower.iloc[i] if lower.iloc[i] > prev_lower or close.iloc[i-1] < prev_lower else prev_lower

        if direction[i-1]:
            direction[i] = close.iloc[i] >= curr_lower
        else:
            direction[i] = close.iloc[i] > curr_upper

        st_line[i] = curr_lower if direction[i] else curr_upper

    return pd.Series(direction, index=close.index), atr


def add_indicators(df):
    df = df.copy()
    df["rsi"]     = calc_rsi(df["close"], RSI_PERIOD)
    df["ema21"]   = calc_ema(df["close"], EMA21_PERIOD)
    df["ema50"]   = calc_ema(df["close"], EMA50_PERIOD)
    df["vol_avg"] = df["volume"].rolling(20).mean()
    df["st_bull"], df["atr"] = calc_supertrend(df["high"], df["low"], df["close"])
    return df


# ─────────────────────────────────────────
# СИГНАЛ
# ─────────────────────────────────────────

def get_signal(df, i):
    if i < 55:
        return None, 0

    row      = df.iloc[i]
    prev_row = df.iloc[i-1]

    price   = row["close"]
    rsi     = row["rsi"]
    st_bull = row["st_bull"]
    st_prev = prev_row["st_bull"]
    ema21   = row["ema21"]
    ema50   = row["ema50"]
    atr     = row["atr"]
    vol     = row["volume"]
    vol_avg = row["vol_avg"]

    if pd.isna(rsi) or pd.isna(ema21) or pd.isna(atr) or atr == 0:
        return None, 0

    st_turned_bull = bool(st_bull) and not bool(st_prev)
    st_turned_bear = not bool(st_bull) and bool(st_prev)

    vol_ok = bool(vol > vol_avg * VOL_MULT) if not pd.isna(vol_avg) else False

    lows_20  = df["low"].iloc[max(0,i-20):i].values
    highs_20 = df["high"].iloc[max(0,i-20):i].values

    hl_check = False
    lh_check = False
    if len(lows_20) >= 20:
        hl_check = float(min(lows_20[10:])) > float(min(lows_20[:10])) * 0.998
    if len(highs_20) >= 20:
        lh_check = float(max(highs_20[10:])) < float(max(highs_20[:10])) * 1.002

    # LONG score
    long_score = 0
    if st_turned_bull:         long_score += 35
    elif bool(st_bull):        long_score += 20

    if RSI_MIN < rsi < 60 and rsi > prev_row["rsi"]: long_score += 20
    elif RSI_MIN < rsi < RSI_MAX:                     long_score += 12

    if price > ema21 and price > ema50: long_score += 20
    elif price > ema21:                 long_score += 10

    if hl_check: long_score += 15
    if vol_ok:   long_score += 10

    # SHORT score
    short_score = 0
    if st_turned_bear:         short_score += 35
    elif not bool(st_bull):    short_score += 20

    if 40 < rsi < RSI_MAX and rsi < prev_row["rsi"]: short_score += 20
    elif RSI_MIN < rsi < RSI_MAX:                      short_score += 12

    if price < ema21 and price < ema50: short_score += 20
    elif price < ema21:                 short_score += 10

    if lh_check: short_score += 15
    if vol_ok:   short_score += 10

    if long_score >= 55 and bool(st_bull) and rsi < RSI_MAX and long_score >= short_score:
        return "LONG", long_score
    if short_score >= 55 and not bool(st_bull) and rsi > RSI_MIN and short_score > long_score:
        return "SHORT", short_score

    return None, 0


# ─────────────────────────────────────────
# БЭКТЕСТ ОДНОГО СИМВОЛА
# ─────────────────────────────────────────

def backtest_symbol(symbol, df):
    df       = add_indicators(df)
    trades   = []
    equity   = [INITIAL_CAP]
    capital  = INITIAL_CAP
    in_trade = False
    entry_data = {}

    for i in range(55, len(df)):
        price  = float(df["close"].iloc[i])
        high_i = float(df["high"].iloc[i])
        low_i  = float(df["low"].iloc[i])
        ts     = df.index[i]

        # Проверяем выход
        if in_trade:
            direction = entry_data["direction"]
            sl        = entry_data["sl"]
            tp1       = entry_data["tp1"]
            tp2       = entry_data["tp2"]
            entry     = entry_data["entry"]

            result     = None
            exit_price = None

            if direction == "LONG":
                if low_i <= sl:     result = "SL";  exit_price = sl
                elif high_i >= tp2: result = "TP2"; exit_price = tp2
                elif high_i >= tp1: result = "TP1"; exit_price = tp1
            else:
                if high_i >= sl:    result = "SL";  exit_price = sl
                elif low_i <= tp2:  result = "TP2"; exit_price = tp2
                elif low_i <= tp1:  result = "TP1"; exit_price = tp1

            if not result and (i - entry_data["entry_i"]) >= MAX_BARS_HOLD:
                result     = "TIMEOUT"
                exit_price = price

            if result:
                if direction == "LONG":
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100

                sl_dist_pct = abs(entry - sl) / entry * 100
                pnl_usd     = capital * RISK_PCT * (pnl_pct / sl_dist_pct) if sl_dist_pct > 0 else 0
                capital    += pnl_usd
                capital     = max(capital, 0)

                trades.append({
                    "symbol":    symbol,
                    "direction": direction,
                    "entry_ts":  str(entry_data["entry_ts"])[:16],
                    "exit_ts":   str(ts)[:16],
                    "entry":     round(entry, 6),
                    "exit":      round(exit_price, 6),
                    "sl":        round(sl, 6),
                    "tp1":       round(tp1, 6),
                    "result":    result,
                    "pnl_pct":   round(pnl_pct, 2),
                    "pnl_usd":   round(pnl_usd, 2),
                    "capital":   round(capital, 2),
                    "score":     entry_data["score"]
                })
                equity.append(capital)
                in_trade = False

        # Ищем вход
        if not in_trade:
            signal, score = get_signal(df, i)
            if signal:
                atr   = float(df["atr"].iloc[i])
                entry = price

                if signal == "LONG":
                    sl  = entry - SL_ATR_MULT * atr
                    tp1 = entry + TP1_ATR_MULT * atr
                    tp2 = entry + TP2_ATR_MULT * atr
                else:
                    sl  = entry + SL_ATR_MULT * atr
                    tp1 = entry - TP1_ATR_MULT * atr
                    tp2 = entry - TP2_ATR_MULT * atr

                in_trade   = True
                entry_data = {
                    "direction": signal,
                    "entry":     entry,
                    "sl":        sl,
                    "tp1":       tp1,
                    "tp2":       tp2,
                    "entry_ts":  ts,
                    "entry_i":   i,
                    "score":     score
                }

    return trades, equity


# ─────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────

def calc_stats(trades, equity, label):
    if not trades:
        return {"label": label, "trades": 0, "win_rate": 0, "pf": 0,
                "max_dd": 0, "sharpe": 0, "avg_win": 0, "avg_loss": 0,
                "final_cap": INITIAL_CAP, "total_pnl": 0}

    df     = pd.DataFrame(trades)
    wins   = df[df["result"].isin(["TP1", "TP2"])]
    losses = df[df["result"] == "SL"]

    total    = len(df)
    win_rate = len(wins) / total * 100 if total > 0 else 0
    gw = wins["pnl_usd"].sum()   if len(wins)   > 0 else 0
    gl = abs(losses["pnl_usd"].sum()) if len(losses) > 0 else 1
    pf = gw / gl if gl > 0 else 0

    eq     = pd.Series(equity)
    rm     = eq.cummax()
    dd     = (eq - rm) / rm * 100
    max_dd = float(dd.min())

    rets   = df["pnl_pct"] / 100
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0

    return {
        "label":     label,
        "trades":    total,
        "wins":      len(wins),
        "losses":    len(losses),
        "timeouts":  len(df[df["result"] == "TIMEOUT"]),
        "win_rate":  round(win_rate, 1),
        "pf":        round(pf, 2),
        "max_dd":    round(max_dd, 1),
        "sharpe":    round(sharpe, 2),
        "avg_win":   round(float(wins["pnl_pct"].mean()), 2) if len(wins) > 0 else 0,
        "avg_loss":  round(float(losses["pnl_pct"].mean()), 2) if len(losses) > 0 else 0,
        "total_pnl": round(float(df["pnl_usd"].sum()), 2),
        "final_cap": round(float(equity[-1]), 2) if equity else INITIAL_CAP
    }


# ─────────────────────────────────────────
# HTML ОТЧЁТ
# ─────────────────────────────────────────

def generate_report(stats_list, all_trades, eq_top10, eq_active):
    def color_pf(v):
        return "#22c55e" if v >= 1.4 else "#f59e0b" if v >= 1.0 else "#ef4444"
    def color_dd(v):
        return "#22c55e" if v > -10 else "#f59e0b" if v > -20 else "#ef4444"
    def color_wr(v):
        return "#22c55e" if v >= 50 else "#f59e0b" if v >= 40 else "#ef4444"

    cards = ""
    for s in stats_list:
        if s["trades"] == 0:
            cards += f'<div class="card"><h3>{s["label"]}</h3><p style="color:#64748b">Нет сделок</p></div>'
            continue
        cards += f"""<div class="card">
<h3>{s['label']}</h3>
<div class="grid4">
  <div class="m"><span class="lbl">Сделок</span><span class="val">{s['trades']}</span></div>
  <div class="m"><span class="lbl">Побед / Потерь</span><span class="val">{s['wins']} / {s['losses']}</span></div>
  <div class="m"><span class="lbl">Таймаутов</span><span class="val">{s['timeouts']}</span></div>
  <div class="m"><span class="lbl">Win Rate</span><span class="val" style="color:{color_wr(s['win_rate'])}">{s['win_rate']}%</span></div>
  <div class="m"><span class="lbl">Profit Factor</span><span class="val" style="color:{color_pf(s['pf'])}">{s['pf']}</span></div>
  <div class="m"><span class="lbl">Max Drawdown</span><span class="val" style="color:{color_dd(s['max_dd'])}">{s['max_dd']}%</span></div>
  <div class="m"><span class="lbl">Sharpe</span><span class="val">{s['sharpe']}</span></div>
  <div class="m"><span class="lbl">Avg Win / Loss</span><span class="val">+{s['avg_win']}% / {s['avg_loss']}%</span></div>
  <div class="m"><span class="lbl">Итог ($10k)</span><span class="val">${s['final_cap']:,.0f}</span></div>
  <div class="m"><span class="lbl">Total PnL</span><span class="val" style="color:{'#22c55e' if s['total_pnl']>0 else '#ef4444'}">${s['total_pnl']:,.0f}</span></div>
</div></div>"""

    rows = ""
    for t in sorted(all_trades, key=lambda x: x["entry_ts"])[-200:]:
        c = "#22c55e" if t["result"] in ["TP1","TP2"] else "#ef4444" if t["result"]=="SL" else "#94a3b8"
        p = f"+{t['pnl_pct']:.1f}%" if t["pnl_pct"] > 0 else f"{t['pnl_pct']:.1f}%"
        rows += f"""<tr>
<td>{t['entry_ts']}</td>
<td>{t['symbol'].replace('USDT','')}</td>
<td>{'🟢 LONG' if t['direction']=='LONG' else '🔴 SHORT'}</td>
<td>${t['entry']:.4f}</td>
<td>${t['exit']:.4f}</td>
<td style="color:{c}">{t['result']}</td>
<td style="color:{c}">{p}</td>
<td>${t['pnl_usd']:.2f}</td>
</tr>"""

    n1 = len(eq_top10)
    n2 = len(eq_active)
    nmax = max(n1, n2, 1)
    step = max(1, nmax // 500)

    eq1_sampled = eq_top10[::step]
    eq2_sampled = eq_active[::step]
    eq1_norm = [round(v/eq_top10[0]*100, 2) for v in eq1_sampled]
    eq2_norm = [round(v/eq_active[0]*100, 2) for v in eq2_sampled]
    labels   = list(range(len(eq1_norm)))

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>WaveForge v2 — Backtest</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f172a;color:#e2e8f0;font-family:'Segoe UI',sans-serif;padding:24px}}
h1{{font-size:26px;color:#7c3aed;margin-bottom:6px}}
.sub{{color:#64748b;margin-bottom:28px;font-size:14px}}
h2{{font-size:18px;color:#94a3b8;margin:28px 0 14px}}
h3{{font-size:15px;color:#c4b5fd;margin-bottom:14px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;margin-bottom:14px}}
.grid4{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}}
.m{{display:flex;flex-direction:column;gap:3px}}
.lbl{{font-size:11px;color:#64748b}}
.val{{font-size:18px;font-weight:700}}
.chart-wrap{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden;font-size:13px}}
th{{background:#334155;padding:10px 12px;text-align:left;color:#94a3b8;font-size:12px}}
td{{padding:9px 12px;border-bottom:1px solid #0f172a}}
tr:hover{{background:#263548}}
</style>
</head>
<body>
<h1>🔬 WaveForge v2 — Backtest Report</h1>
<p class="sub">Период: {START_DATE} — {END_DATE} &nbsp;|&nbsp; Риск: {RISK_PCT*100:.0f}%/сделку &nbsp;|&nbsp; Капитал: ${INITIAL_CAP:,}</p>

<h2>📊 Результаты</h2>
{cards}

<h2>📈 Equity Curve (нормализовано к 100%)</h2>
<div class="chart-wrap">
  <canvas id="eq" height="100"></canvas>
</div>

<h2>📋 Последние 200 сделок</h2>
<table>
<thead><tr>
<th>Дата</th><th>Монета</th><th>Направление</th>
<th>Вход</th><th>Выход</th><th>Результат</th><th>PnL %</th><th>PnL $</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
new Chart(document.getElementById('eq').getContext('2d'),{{
  type:'line',
  data:{{
    labels:{json.dumps(labels)},
    datasets:[
      {{label:'Топ-10 по объёму',data:{json.dumps(eq1_norm)},
       borderColor:'#7c3aed',backgroundColor:'rgba(124,58,237,0.08)',
       borderWidth:2,pointRadius:0,fill:true,tension:0.3}},
      {{label:'Active Universe',data:{json.dumps(eq2_norm)},
       borderColor:'#06b6d4',backgroundColor:'rgba(6,182,212,0.08)',
       borderWidth:2,pointRadius:0,fill:true,tension:0.3}}
    ]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#94a3b8'}}}},
      tooltip:{{mode:'index',intersect:false}}}},
    scales:{{
      x:{{display:false}},
      y:{{ticks:{{color:'#94a3b8',callback:v=>v+'%'}},
         grid:{{color:'rgba(51,65,85,0.5)'}}}}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


# ─────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────

def run():
    print("="*60)
    print("WaveForge v2 — Backtester")
    print(f"Период: {START_DATE} — {END_DATE}")
    print("="*60)

    all_trades_top10  = []
    all_trades_active = []
    eq_top10  = [INITIAL_CAP]
    eq_active = [INITIAL_CAP]

    for group, symbols, trades_list, equity_list in [
        ("Топ-10 по объёму", SYMBOLS_TOP10,  all_trades_top10,  eq_top10),
        ("Active Universe",  SYMBOLS_ACTIVE, all_trades_active, eq_active)
    ]:
        print(f"\n▶ {group}:")
        for symbol in symbols:
            print(f"  {symbol}...", end=" ", flush=True)
            df = bc.get_klines(symbol, "1h", limit=CANDLE_LIMIT)
            if df is None or len(df) < 200:
                print("❌ нет данных")
                continue

            df = df[df.index >= pd.Timestamp(START_DATE)]
            df = df[df.index <= pd.Timestamp(END_DATE)]

            if len(df) < 200:
                print("❌ мало данных")
                continue

            trades, equity = backtest_symbol(symbol, df)
            trades_list.extend(trades)
            equity_list.extend(equity[1:])
            print(f"✅ {len(trades)} сделок")
            time.sleep(0.2)

    stats_top10  = calc_stats(all_trades_top10,  eq_top10,  "Топ-10 по объёму")
    stats_active = calc_stats(all_trades_active, eq_active, "Active Universe")

    print("\n" + "="*60)
    print("РЕЗУЛЬТАТЫ")
    print("="*60)
    for s in [stats_top10, stats_active]:
        print(f"\n{s['label']}:")
        print(f"  Сделок:        {s['trades']}")
        print(f"  Win Rate:      {s['win_rate']}%")
        print(f"  Profit Factor: {s['pf']}")
        print(f"  Max Drawdown:  {s['max_dd']}%")
        print(f"  Sharpe:        {s['sharpe']}")
        print(f"  Avg Win/Loss:  +{s['avg_win']}% / {s['avg_loss']}%")
        print(f"  Итог ($10k):   ${s['final_cap']:,.0f}")

    all_trades = all_trades_top10 + all_trades_active
    html = generate_report([stats_top10, stats_active], all_trades, eq_top10, eq_active)

    path = "/home/claude/waveforge_backtest_report.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Отчёт: {path}")
    return path


if __name__ == "__main__":
    run()
