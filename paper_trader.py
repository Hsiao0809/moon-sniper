#!/usr/bin/env python3
"""
moon-sniper paper_trader.py
雙資金池紙交易管理（swing + scalp）
- swing_pool（180U）：長線，4 筆 max，TP15%/30%，SL5%，10 天
- scalp_pool（90U）：短線，4 筆 max，TP5%/8%，SL3%，4 小時
- 共用統計算核心，輸出 paper_trades.json
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SWING_SIGNALS_PATH = BASE_DIR / "swing_signals.json"
SCALP_SIGNALS_PATH = BASE_DIR / "scalp_signals.json"
TRADES_PATH = BASE_DIR / "paper_trades.json"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_signals(mode):
    """載入指定 mode 的 signals.json"""
    path = SWING_SIGNALS_PATH if mode == "swing" else SCALP_SIGNALS_PATH
    if not path.exists():
        return {"signals": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_trades():
    if not TRADES_PATH.exists():
        return {"trades": [], "stats": {}}
    with open(TRADES_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_trades(data):
    with open(TRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_pool_config(config, pool):
    """根據 pool 回傳對應的 config 區塊"""
    if pool == "swing":
        return config["swing_trader"]
    else:
        return config["scalp_trader"]


def get_position_value(config, trades, pool):
    """
    計算指定 pool 的 margin / position_value
    各 pool 資金獨立管理
    """
    pool_cfg = get_pool_config(config, pool)
    total_equity = pool_cfg["account_balance"]
    leverage = pool_cfg.get("default_leverage", 2)
    max_open = pool_cfg["max_open_trades"]
    pool_allocation = pool_cfg["pool_allocation"]

    # pool 初始資金
    pool_initial = total_equity * pool_allocation

    # 計算該 pool 已佔用保證金
    used_margin = 0
    if trades and "trades" in trades:
        for t in trades["trades"]:
            if t.get("status") == "open" and t.get("pool") == pool:
                used_margin += t.get("margin", 0)

    # 該 pool 已實現損益
    realized_pnl = 0
    if trades and "trades" in trades:
        for t in trades["trades"]:
            if t.get("status") == "closed" and t.get("pool") == pool:
                realized_pnl += t.get("realized_pnl_usdt", 0)

    pool_equity = pool_initial + realized_pnl
    available = pool_equity - used_margin

    open_count = sum(1 for t in (trades["trades"] if trades else [])
                     if t.get("status") == "open" and t.get("pool") == pool)
    slots_left = max_open - open_count

    if slots_left <= 0 or available <= 0:
        return 0, 0, 0, 0, pool_equity, leverage

    # 根據 FR 調整 pool（如果 config 有 fr adjust）
    fr_adjust = pool_cfg.get("funding_rate_adjust", {})
    fr_high = fr_adjust.get("fr_high", 0.001)
    pool_reduction = fr_adjust.get("pool_reduction_pct", 0)
    # 實際 FR 載入會由外部決定，這裡先不縮減，讓外部調用時調整

    margin_per_trade = available / slots_left
    sl_pct = abs(pool_cfg.get("stop_loss", 0.05))
    max_risk = margin_per_trade * sl_pct
    position_value = margin_per_trade * leverage

    return position_value, margin_per_trade, leverage, max_risk, pool_equity, leverage


def calc_pnl(current_price, entry_price, position_value, direction="long"):
    """計算損益 USDT 和百分比（支援多空方向）"""
    if entry_price == 0:
        return 0, 0
    if direction == "short":
        pnl_pct = (entry_price - current_price) / entry_price
    else:
        pnl_pct = (current_price - entry_price) / entry_price
    pnl_usdt = pnl_pct * position_value
    return round(pnl_usdt, 2), round(pnl_pct * 100, 2)


def check_new_trades(signals_data, trades, config, pool):
    """檢查指定 pool 的新訊號"""
    pool_cfg = get_pool_config(config, pool)
    min_score = pool_cfg["min_score_to_trade"]
    short_min = pool_cfg.get("short_min_score", 50)
    max_open = pool_cfg["max_open_trades"]

    signals = signals_data.get("signals", [])
    position_value, margin, leverage, max_risk, pool_equity, _ = \
        get_position_value(config, trades, pool)

    existing_symbols = {t["symbol"] for t in trades["trades"]
                        if t["status"] == "open" and t.get("pool") == pool}

    new_trades = []
    for s in signals:
        symbol = s["symbol"]
        total_score = s["scores"]["total"]
        short_score = s["scores"].get("short", 0)

        if not s.get("trade_eligible", False):
            continue

        if symbol in existing_symbols:
            continue
        if len(existing_symbols) + len(new_trades) >= max_open:
            break

        # 決定方向
        is_short = short_score >= short_min and short_score > total_score
        is_long = total_score >= min_score and not is_short

        if not is_long and not is_short:
            continue

        # 空方過濾
        if is_short:
            change_pct = float(s.get("price_change_24h", 0))
            if change_pct < -15:
                continue
            if float(s.get("volume_24h_usdt", 0)) < 50000:
                continue
            consolidation_days = s.get("consolidation_days", 0)
            consolidation_range = s.get("consolidation_range_pct", 0)
            if consolidation_days >= 2 and consolidation_range <= 8:
                continue

        # 根據 pool 設定 TP/SL
        if pool == "swing":
            tp1_pct = pool_cfg["take_profit_1"]      # 0.15
            tp1_exit = pool_cfg["take_profit_1_exit_ratio"]  # 0.33
            tp2_pct = pool_cfg["take_profit_2"]       # 0.30
            sl_pct = pool_cfg["stop_loss"]            # -0.05
            max_hold = timedelta(days=pool_cfg["max_hold_days"])
        else:
            tp1_pct = pool_cfg["take_profit_1"]       # 0.05
            tp1_exit = pool_cfg["take_profit_1_exit_ratio"]  # 0.5
            tp2_pct = pool_cfg["take_profit_2"]        # 0.08
            sl_pct = pool_cfg["stop_loss"]             # -0.03
            max_hold = timedelta(hours=pool_cfg["max_hold_hours"])

        entry_price = float(s["price"])
        now = datetime.now(timezone.utc)

        if is_short:
            multiplier = -1
        else:
            multiplier = 1

        trade = {
            "id": f"{pool.upper()}-{now.strftime('%Y%m%d-%H%M%S')}-{symbol}",
            "symbol": symbol,
            "base": s["base"],
            "pool": pool,
            "direction": "short" if is_short else "long",
            "entry_price": entry_price,
            "entry_time": now.isoformat(),
            "status": "open",
            "score": short_score if is_short else total_score,
            "tags": s.get("tags", []),
            "obi": s.get("obi", 0),
            "adx": s.get("adx", 0),
            # 保證金與槓桿
            "leverage": leverage,
            "margin": round(margin, 2),
            "position_value": round(position_value, 2),
            # TP/SL 價格
            "stop_loss_price": round(entry_price * (1 + sl_pct * multiplier), 8),
            "tp1_price": round(entry_price * (1 + tp1_pct * multiplier), 8),
            "tp2_price": round(entry_price * (1 + tp2_pct * multiplier), 8),
            "take_profit_1_exit_ratio": tp1_exit,
            "max_hold_until": (now + max_hold).isoformat(),
            # TP 狀態
            "take_profit_1_hit": False,
            "take_profit_1_exit_price": None,
            "take_profit_2_hit": False,
            # 出場
            "exit_price": None,
            "exit_time": None,
            "exit_reason": None,
            # 損益
            "realized_pnl_usdt": 0.0,
            "realized_pnl_pct": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "unrealized_pnl_pct": 0.0,
            # 極值追蹤
            "max_unrealized_pnl_usdt": 0.0,
            "max_unrealized_pnl_pct": 0.0,
            "min_unrealized_pnl_usdt": 0.0,
            "min_unrealized_pnl_pct": 0.0,
        }
        new_trades.append(trade)

    return new_trades


def update_open_trades(trades, config):
    """更新所有進行中的紙交易（不分 pool，共用價格訊號）"""
    # 從兩個 signals 來源建立價格 map
    swing_signals = load_signals("swing").get("signals", [])
    scalp_signals = load_signals("scalp").get("signals", [])
    all_signals = swing_signals + scalp_signals
    # 去重：後者覆蓋前者
    signal_map = {}
    for s in all_signals:
        signal_map[s["symbol"]] = s

    now = datetime.now(timezone.utc)
    updated = 0

    for trade in trades["trades"]:
        if trade["status"] != "open":
            continue

        pool = trade.get("pool", "swing")
        pool_cfg = get_pool_config(config, pool)
        symbol = trade["symbol"]
        entry = trade["entry_price"]
        direction = trade.get("direction", "long")
        pos_value = trade.get("position_value", 0)

        # 從 signals 取最新價格
        current_price = None
        high_24h = None
        low_24h = None
        if symbol in signal_map:
            current_price = float(signal_map[symbol]["price"])
            high_24h = float(signal_map[symbol].get("high_24h", current_price))
            low_24h = float(signal_map[symbol].get("low_24h", current_price))

        if current_price is None:
            continue

        # 更新 OBI / ADX
        trade["obi"] = signal_map[symbol].get("obi", trade.get("obi", 0))
        trade["adx"] = signal_map[symbol].get("adx", trade.get("adx", 0))

        # 浮動損益
        unrealized_u, unrealized_pct = calc_pnl(current_price, entry, pos_value, direction)
        trade["unrealized_pnl_usdt"] = unrealized_u
        trade["unrealized_pnl_pct"] = unrealized_pct

        # 追蹤極值
        if unrealized_u > trade["max_unrealized_pnl_usdt"]:
            trade["max_unrealized_pnl_usdt"] = unrealized_u
            trade["max_unrealized_pnl_pct"] = unrealized_pct
        if unrealized_u < trade["min_unrealized_pnl_usdt"]:
            trade["min_unrealized_pnl_usdt"] = unrealized_u
            trade["min_unrealized_pnl_pct"] = unrealized_pct

        # 根據方向檢查 TP/SL
        if direction == "short":
            price_for_tp = min(current_price, low_24h) if low_24h else current_price
            tp2_hit = not trade["take_profit_2_hit"] and price_for_tp <= trade["tp2_price"]
            tp1_hit = not trade["take_profit_1_hit"] and current_price <= trade["tp1_price"]
            sl_hit = current_price >= trade["stop_loss_price"]
        else:
            price_for_tp = max(current_price, high_24h) if high_24h else current_price
            tp2_hit = not trade["take_profit_2_hit"] and price_for_tp >= trade["tp2_price"]
            tp1_hit = not trade["take_profit_1_hit"] and current_price >= trade["tp1_price"]
            sl_hit = current_price <= trade["stop_loss_price"]

        # TP2（全出）
        if tp2_hit:
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

        # TP1（出一半，只標記）
        if tp1_hit:
            trade["take_profit_1_hit"] = True
            trade["take_profit_1_exit_price"] = current_price
            updated += 1

        # 停損
        if sl_hit:
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

        # 時間停損
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


def calculate_stats(trades, config):
    """計算績效統計（分 pool + 合計）"""
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

    # 分 pool 統計
    pivot = {"swing": {}, "scalp": {}}
    for pool in ["swing", "scalp"]:
        pool_closed = [t for t in closed if t.get("pool") == pool]
        pool_open = [t for t in open_trades if t.get("pool") == pool]
        pool_wins = [t for t in pool_closed if t["realized_pnl_usdt"] > 0]
        pool_losses = [t for t in pool_closed if t["realized_pnl_usdt"] <= 0]
        pool_realized = sum(t["realized_pnl_usdt"] for t in pool_closed)
        pool_unrealized = sum(t["unrealized_pnl_usdt"] for t in pool_open)

        pool_cfg = get_pool_config(config, pool)
        pool_initial = pool_cfg["account_balance"] * pool_cfg["pool_allocation"]

        pivot[pool] = {
            "pool_initial": round(pool_initial, 2),
            "pool_equity": round(pool_initial + pool_realized, 2),
            "open_count": len(pool_open),
            "closed_count": len(pool_closed),
            "wins": len(pool_wins),
            "losses": len(pool_losses),
            "win_rate": round(len(pool_wins) / len(pool_closed) * 100, 1) if pool_closed else 0,
            "total_realized_pnl_usdt": round(pool_realized, 2),
            "total_unrealized_pnl_usdt": round(pool_unrealized, 2),
            "used_margin": sum(t.get("margin", 0) for t in pool_open),
        }

    # 最大回撤（全部 pool 合計）
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

    # 帳戶總權益
    total_equity = 300 + total_realized_pnl  # 起始 300U

    stats = {
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
        "total_equity": round(total_equity, 2),
        "account_balance": 300,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "pools": pivot,
    }
    trades["stats"] = stats


def run():
    config = load_config()

    # 載入兩個 pool 的 signals
    swing_signals = load_signals("swing").get("signals", [])
    scalp_signals = load_signals("scalp").get("signals", [])
    trades = load_trades()

    trading_cfg = config.get("paper_trading", {})
    trading_enabled = trading_cfg.get("enabled", True)
    if not trading_enabled:
        print(f"紙交易暫停：{trading_cfg.get('reason', 'paper_trading.enabled=false')}")
        calculate_stats(trades, config)
        trades["stats"]["paper_trading_enabled"] = False
        trades["stats"]["paper_trading_pause_reason"] = trading_cfg.get("reason", "paper_trading.enabled=false")
        save_trades(trades)
        print(f"紙交易狀態：{trades['stats']['total_trades']} 筆總計，{trades['stats']['open_count']} 筆進行中")
        return

    # 更新既有持倉（不分 pool，用訊號價格更新）
    updated = update_open_trades(trades, config)
    if updated:
        print(f"更新了 {updated} 筆紙交易")

    # Swing 新訊號
    new_swing = check_new_trades({"signals": swing_signals}, trades, config, "swing")
    if new_swing:
        trades["trades"].extend(new_swing)
        print(f"Swing 新增 {len(new_swing)} 筆紙交易")

    # Scalp 新訊號
    new_scalp = check_new_trades({"signals": scalp_signals}, trades, config, "scalp")
    if new_scalp:
        trades["trades"].extend(new_scalp)
        print(f"Scalp 新增 {len(new_scalp)} 筆紙交易")

    # 計算統計
    calculate_stats(trades, config)
    save_trades(trades)

    print(f"紙交易狀態：{trades['stats']['total_trades']} 筆總計，{trades['stats']['open_count']} 筆進行中")
    print(f"帳戶權益：{trades['stats']['total_equity']} USDT")
    print(f"已實現損益：{trades['stats']['total_realized_pnl_usdt']} USDT")
    print(f"未實現損益：{trades['stats']['total_unrealized_pnl_usdt']} USDT")
    for pool in ["swing", "scalp"]:
        p = trades['stats'].get('pools', {}).get(pool, {})
        if p:
            print(f"  {pool.upper()}: equity={p['pool_equity']}U  open={p['open_count']} realized={p['total_realized_pnl_usdt']}U")


if __name__ == "__main__":
    run()
