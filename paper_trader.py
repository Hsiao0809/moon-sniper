#!/usr/bin/env python3
"""
moon-sniper paper_trader.py
根據 signals.json 的評分結果，管理紙交易。
- 新訊號評分 >= min_score_to_trade → 進場
- 定期檢查持倉：停利、停損、時間停損
- 每筆交易記錄最大漲幅、最大回撤、已實現/未實現損益
- 輸出 paper_trades.json
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from copy import deepcopy

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SIGNALS_PATH = BASE_DIR / "signals.json"
TRADES_PATH = BASE_DIR / "paper_trades.json"

# 部位值 = max_risk / stop_loss_pct，每筆固定
POSITION_VALUE_MULTIPLIER = 1.0  # 稍後從 config 計算

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def load_signals():
    if not SIGNALS_PATH.exists():
        return {"signals": []}
    with open(SIGNALS_PATH, encoding="utf-8") as f:
        return json.load(f)

def load_trades():
    if not TRADES_PATH.exists():
        return {"trades": [], "stats": {}}
    with open(TRADES_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_trades(data):
    with open(TRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_position_value(config):
    """計算每筆交易的部位值（USDT）"""
    tc = config["paper_trade"]
    # 支援兩種設定方式
    if "max_risk_usdt" in tc:
        max_risk = tc["max_risk_usdt"]
    else:
        max_risk = tc["account_balance"] * tc["max_risk_per_trade_pct"]
    stop_loss_pct = abs(tc["stop_loss"])
    if stop_loss_pct == 0:
        return 0
    return max_risk / stop_loss_pct  # 30 / 0.05 = 600 USDT

def calc_pnl(current_price, entry_price, position_value):
    """計算損益 USDT 和百分比"""
    if entry_price == 0:
        return 0, 0
    pnl_pct = (current_price - entry_price) / entry_price
    pnl_usdt = pnl_pct * position_value
    return round(pnl_usdt, 2), round(pnl_pct * 100, 2)

def check_new_trades(signals, trades, config):
    """檢查新訊號是否有符合進場條件的（多空雙向）"""
    trade_config = config["paper_trade"]
    min_score = trade_config["min_score_to_trade"]
    short_min = trade_config.get("short_min_score", 50)
    max_open = trade_config["max_open_trades"]
    position_value = get_position_value(config)

    existing_symbols = {t["symbol"] for t in trades["trades"] if t["status"] == "open"}

    new_trades = []
    for s in signals:
        symbol = s["symbol"]
        total_score = s["scores"]["total"]
        short_score = s["scores"].get("short", 0)

        if symbol in existing_symbols:
            continue
        if len(existing_symbols) + len(new_trades) >= max_open:
            break

        # 決定方向：做多或做空
        is_short = short_score >= short_min and short_score > total_score
        is_long = total_score >= min_score and not is_short

        if not is_long and not is_short:
            continue

        entry_price = float(s["price"])
        now = datetime.now(timezone.utc)

        if is_short:
            # 做空：反向 TP/SL
            multiplier = -1
        else:
            multiplier = 1

        trade = {
            "id": f"PT-{now.strftime('%Y%m%d-%H%M%S')}-{symbol}",
            "symbol": symbol,
            "base": s["base"],
            "direction": "short" if is_short else "long",
            "entry_price": entry_price,
            "entry_time": now.isoformat(),
            "status": "open",
            "score": short_score if is_short else total_score,
            "tags": s["tags"],
            # TP/SL 價格
            "stop_loss_price": round(entry_price * (1 + trade_config["stop_loss"] * multiplier), 8),
            "tp1_price": round(entry_price * (1 + trade_config["take_profit_1"] * multiplier), 8),
            "tp2_price": round(entry_price * (1 + trade_config["take_profit_2"] * multiplier), 8),
            "max_hold_until": (now + timedelta(days=trade_config["max_hold_days"])).isoformat(),
            # TP 狀態
            "take_profit_1_hit": False,
            "take_profit_1_exit_price": None,
            "take_profit_2_hit": False,
            # 出場
            "exit_price": None,
            "exit_time": None,
            "exit_reason": None,
            # 損益（已實現 + 未實現）
            "realized_pnl_usdt": 0.0,
            "realized_pnl_pct": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "unrealized_pnl_pct": 0.0,
            # 最大漲幅 / 最大回撤（追蹤 unrelized 極值）
            "max_unrealized_pnl_usdt": 0.0,
            "max_unrealized_pnl_pct": 0.0,
            "min_unrealized_pnl_usdt": 0.0,
            "min_unrealized_pnl_pct": 0.0,
        }
        new_trades.append(trade)

    return new_trades

def update_open_trades(trades, signals, config):
    """更新進行中的紙交易：計算浮動損益、追蹤極值、檢查 TP/SL/時間"""
    trade_config = config["paper_trade"]
    signal_map = {s["symbol"]: s for s in signals}
    now = datetime.now(timezone.utc)
    position_value = get_position_value(config)
    updated = 0

    for trade in trades["trades"]:
        if trade["status"] != "open":
            continue

        symbol = trade["symbol"]
        entry = trade["entry_price"]

        # 從 signals 取得最新價格
        current_price = None
        high_24h = None
        if symbol in signal_map:
            current_price = float(signal_map[symbol]["price"])
            high_24h = float(signal_map[symbol].get("high_24h", current_price))

        if current_price is None:
            continue

        # 計算浮動損益
        unrealized_u, unrealized_pct = calc_pnl(current_price, entry, position_value)
        trade["unrealized_pnl_usdt"] = unrealized_u
        trade["unrealized_pnl_pct"] = unrealized_pct

        # 追蹤最大漲幅
        if unrealized_u > trade["max_unrealized_pnl_usdt"]:
            trade["max_unrealized_pnl_usdt"] = unrealized_u
            trade["max_unrealized_pnl_pct"] = unrealized_pct

        # 追蹤最大回撤（最低點）
        if unrealized_u < trade["min_unrealized_pnl_usdt"]:
            trade["min_unrealized_pnl_usdt"] = unrealized_u
            trade["min_unrealized_pnl_pct"] = unrealized_pct

        # 檢查 TP2（+20% 全出）— 用當前價或 24h 高點判斷
        price_for_tp = max(current_price, high_24h) if high_24h else current_price
        if not trade["take_profit_2_hit"] and price_for_tp >= trade["tp2_price"]:
            trade["status"] = "closed"
            trade["exit_price"] = current_price
            trade["exit_time"] = now.isoformat()
            trade["take_profit_2_hit"] = True
            trade["realized_pnl_usdt"] = unrealized_u
            trade["realized_pnl_pct"] = unrealized_pct
            trade["unrealized_pnl_usdt"] = 0.0
            trade["unrealized_pnl_pct"] = 0.0
            trade["exit_reason"] = "tp2"
            updated += 1
            continue

        # 檢查 TP1（+10% 出一半）— 只標記，不全出
        if not trade["take_profit_1_hit"] and current_price >= trade["tp1_price"]:
            trade["take_profit_1_hit"] = True
            trade["take_profit_1_exit_price"] = current_price
            updated += 1

        # 檢查停損
        if current_price <= trade["stop_loss_price"]:
            trade["status"] = "closed"
            trade["exit_price"] = current_price
            trade["exit_time"] = now.isoformat()
            trade["realized_pnl_usdt"] = unrealized_u
            trade["realized_pnl_pct"] = unrealized_pct
            trade["unrealized_pnl_usdt"] = 0.0
            trade["unrealized_pnl_pct"] = 0.0
            trade["exit_reason"] = "stop_loss"
            updated += 1
            continue

        # 檢查時間停損
        max_hold = datetime.fromisoformat(trade["max_hold_until"])
        if now >= max_hold:
            trade["status"] = "closed"
            trade["exit_price"] = current_price
            trade["exit_time"] = now.isoformat()
            trade["realized_pnl_usdt"] = unrealized_u
            trade["realized_pnl_pct"] = unrealized_pct
            trade["unrealized_pnl_usdt"] = 0.0
            trade["unrealized_pnl_pct"] = 0.0
            trade["exit_reason"] = "timeout"
            updated += 1

    return updated

def calculate_stats(trades):
    """計算績效統計"""
    config = load_config()
    trade_config = config["paper_trade"]
    max_risk = trade_config["max_risk_usdt"]

    closed = [t for t in trades["trades"] if t["status"] == "closed"]
    open_trades = [t for t in trades["trades"] if t["status"] == "open"]

    total_trades = len(trades["trades"])
    wins = [t for t in closed if t["realized_pnl_usdt"] > 0]
    losses = [t for t in closed if t["realized_pnl_usdt"] <= 0]

    total_realized_pnl = sum(t["realized_pnl_usdt"] for t in closed)
    total_unrealized_pnl = sum(t["unrealized_pnl_usdt"] for t in open_trades)
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win = sum(t["realized_pnl_usdt"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["realized_pnl_usdt"] for t in losses) / len(losses) if losses else 0

    # 最大回撤（基於已實現損益的累積）
    max_drawdown = 0
    cumulative = 0
    peak = 0
    for t in sorted(closed, key=lambda x: x.get("entry_time", "")):
        cumulative += t["realized_pnl_usdt"]
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    trades["stats"] = {
        "total_trades": total_trades,
        "open_count": len(open_trades),
        "closed_count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_realized_pnl_usdt": round(total_realized_pnl, 2),
        "total_unrealized_pnl_usdt": round(total_unrealized_pnl, 2),
        "avg_win_usdt": round(avg_win, 2),
        "avg_loss_usdt": round(avg_loss, 2),
        "max_drawdown_usdt": round(max_drawdown, 2),
        "max_risk_per_trade": max_risk,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

def run():
    config = load_config()
    signals_data = load_signals()
    trades = load_trades()

    signals = signals_data.get("signals", [])

    # 更新既有持倉
    updated = update_open_trades(trades, signals, config)
    if updated:
        print(f"更新了 {updated} 筆紙交易")

    # 檢查新訊號
    new_trades = check_new_trades(signals, trades, config)
    if new_trades:
        trades["trades"].extend(new_trades)
        print(f"新增 {len(new_trades)} 筆紙交易")

    # 計算統計
    calculate_stats(trades)
    save_trades(trades)

    print(f"紙交易狀態：{trades['stats']['total_trades']} 筆總計，{trades['stats']['open_count']} 筆進行中")
    print(f"已實現損益：{trades['stats']['total_realized_pnl_usdt']} USDT")
    print(f"未實現損益：{trades['stats']['total_unrealized_pnl_usdt']} USDT")

if __name__ == "__main__":
    run()
