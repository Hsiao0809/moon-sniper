#!/usr/bin/env python3
"""
moon-sniper scanner.py
掃描 Binance USDT 交易對，評分找出有暴漲潛力的幣種。
輸出 signals.json 供 index.html 和 paper_trader.py 使用。
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SIGNALS_PATH = BASE_DIR / "signals.json"

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def run_binance_cli(args):
    """執行 binance-cli 並回傳 parsed JSON"""
    cmd = [os.path.expanduser("~/.hermes/node/bin/binance-cli")] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"binance-cli error: {result.stderr}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"JSON parse error: {result.stdout[:200]}", file=sys.stderr)
        return None

def get_all_tickers():
    """取得所有 USDT 交易對的 24hr 行情"""
    data = run_binance_cli(["spot", "ticker24hr"])
    if not data:
        return []
    # binance-cli 可能回傳 list 或 dict
    if isinstance(data, dict):
        data = [data]
    # 只保留 USDT 交易對
    usdt_pairs = [t for t in data if t.get("symbol", "").endswith("USDT")]
    return usdt_pairs

def get_exchange_info():
    """取得交易對資訊（狀態、最小交易量等）"""
    data = run_binance_cli(["spot", "exchange-info"])
    if not data:
        return {}
    symbols = {}
    for s in data.get("symbols", []):
        symbols[s["symbol"]] = {
            "status": s["status"],
            "baseAsset": s["baseAsset"],
            "quoteAsset": s["quoteAsset"],
        }
    return symbols

def get_klines_batch(symbols, interval="1h", limit=12):
    """平行取得多個幣種的 K 線資料"""
    import concurrent.futures
    result = {}
    
    def fetch(symbol):
        data = run_binance_cli(["spot", "klines", "--symbol", symbol, "--interval", interval, "--limit", str(limit)])
        return symbol, data
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch, s) for s in symbols]
        for future in concurrent.futures.as_completed(futures):
            symbol, data = future.result()
            if data:
                result[symbol] = data
    return result

def get_orderbook_batch(symbols, limit=20):
    """平行取得多個幣種的訂單簿深度資料"""
    import concurrent.futures
    result = {}
    
    def fetch(symbol):
        data = run_binance_cli(["spot", "depth", "--symbol", symbol, "--limit", str(limit)])
        return symbol, data
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch, s) for s in symbols]
        for future in concurrent.futures.as_completed(futures):
            symbol, data = future.result()
            if data:
                result[symbol] = data
    return result

def calculate_orderbook_score(bids, asks, last_price):
    """訂單簿評分：買賣力道不平衡程度"""
    if not bids or not asks or last_price <= 0:
        return 50, {}, {}
    
    total_bid_vol = sum(float(b[1]) * float(b[0]) for b in bids)  # 買單總額 USDT
    total_ask_vol = sum(float(a[1]) * float(a[0]) for a in asks)  # 賣單總額 USDT
    total_vol = total_bid_vol + total_ask_vol
    
    if total_vol == 0:
        return 50, {}, {}
    
    bid_ask_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 2.0
    
    # 買單遠大於賣單 => 暴漲潛力高
    if bid_ask_ratio >= 1.5:
        score = 80 + min((bid_ask_ratio - 1.5) * 20, 20)  # 1.5x = 80, 4x = 100
    elif bid_ask_ratio >= 1.2:
        score = 60 + (bid_ask_ratio - 1.2) * 50  # 1.2x = 60, 1.5x = 75
    elif bid_ask_ratio >= 0.8:
        score = 50  # 均衡
    elif bid_ask_ratio >= 0.5:
        score = 30  # 賣壓稍大
    else:
        score = 20  # 賣壓很大
    
    # 爬梯分析：累積買單集中在附近價格
    # 如果有大單在 current price 附近支撐，加分
    support_score = 0
    for b in bids[:5]:  # 前 5 檔買單
        bid_price = float(b[0])
        bid_qty = float(b[1])
        bid_value = bid_price * bid_qty
        distance = (last_price - bid_price) / last_price * 100  # 離當前價格 % 距離
        if distance < 0.5 and bid_value > total_vol * 0.1:  # 0.5% 內有大單
            support_score += 20
        elif distance < 1.0 and bid_value > total_vol * 0.15:
            support_score += 10
    
    resistance_score = 0
    for a in asks[:5]:  # 前 5 檔賣單
        ask_price = float(a[0])
        ask_qty = float(a[1])
        ask_value = ask_price * ask_qty
        distance = (ask_price - last_price) / last_price * 100
        if distance < 0.5 and ask_value > total_vol * 0.1:  # 0.5% 內有大賣單
            resistance_score -= 10
    
    final_score = min(max(score + support_score + resistance_score, 0), 100)
    
    summary = {
        "bid_vol_usdt": round(total_bid_vol, 0),
        "ask_vol_usdt": round(total_ask_vol, 0),
        "bid_ask_ratio": round(bid_ask_ratio, 2),
        "support_score": support_score,
        "resistance_score": resistance_score,
    }
    
    return final_score, summary, {"bids": bids[:5], "asks": asks[:5]}

def calculate_volume_score(ticker, config):
    """成交量評分：24h 量 vs 7日均量"""
    quote_vol = float(ticker.get("quoteVolume", 0))
    if quote_vol < config["scan"]["min_24h_volume_usdt"]:
        return 0, 0
    
    # 用 count 近似估算交易活躍度
    count = int(ticker.get("count", 0))
    vol_score = min(quote_vol / 5000000, 1.0) * 100  # 500萬U以上滿分
    
    return vol_score, quote_vol

def calculate_momentum_score(ticker):
    """價格動能評分：24h 漲跌幅"""
    change_pct = float(ticker.get("priceChangePercent", 0))
    high = float(ticker.get("highPrice", 0))
    low = float(ticker.get("lowPrice", 0))
    last = float(ticker.get("lastPrice", 0))
    
    # 漲幅 3-20% 最佳：太低代表沒動，太高代表可能已經漲完
    if 3 <= change_pct <= 20:
        score = 80 + (change_pct - 3) / 17 * 20  # 3% = 80, 20% = 100
    elif 0 < change_pct < 3:
        score = change_pct / 3 * 70  # 0-3% = 0-70
    elif -5 <= change_pct <= 0:
        score = 20  # 小幅下跌，可能即將反轉
    else:
        score = max(0, 30 - abs(change_pct) * 0.5)  # 跌太多或漲太多
    
    return min(score, 100)

def calculate_breakout_score(ticker, klines):
    """突破確認評分：價格是否突破近期高點"""
    high_24h = float(ticker.get("highPrice", 0))
    last = float(ticker.get("lastPrice", 0))
    
    if not klines or len(klines) < 6:
        return 50
    
    # 計算前 6 根 K 線的最高價
    prev_highs = [float(k[2]) for k in klines[:-1] if k]
    if not prev_highs:
        return 50
    
    prev_high_max = max(prev_highs)
    
    # 當前價格接近或突破前 6h 高點
    if last >= prev_high_max and high_24h > prev_high_max:
        return 100  # 突破
    elif last >= prev_high_max * 0.98:
        return 70   # 接近突破
    elif last >= prev_high_max * 0.95:
        return 40   # 有機會
    else:
        return 10   # 沒有突破跡象

def calculate_liquidity_score(ticker):
    """流動性評分"""
    bid = float(ticker.get("bidPrice", 0))
    ask = float(ticker.get("askPrice", 0))
    last = float(ticker.get("lastPrice", 1))
    volume = float(ticker.get("quoteVolume", 0))
    
    # 價差分數（越小越好）
    spread = abs(ask - bid) / last if last > 0 and ask > 0 and bid > 0 else 0.01
    spread_score = max(0, 100 - spread * 10000)  # 0.1% spread = 90分
    
    # 成交量分數
    vol_score = min(volume / 10000000, 1.0) * 100  # 1000萬U以上滿分
    
    return spread_score * 0.4 + vol_score * 0.6

def scan(config):
    """主掃描邏輯"""
    print(f"[{datetime.now(timezone.utc).isoformat()}] 開始掃描...")
    
    tickers = get_all_tickers()
    if not tickers:
        print("錯誤：無法取得 ticker 資料", file=sys.stderr)
        return []
    
    exchange_info = get_exchange_info()
    config_scan = config["scan"]
    config_score = config["scoring"]
    
    signals = []
    
    # 限制掃描數量：先按成交量排序，只掃成交量最高的 50 個（排除 BTC/ETH 等大幣）
    tickers.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    
    # 排除 BTC、ETH、BNB、SOL、XRP 等超大市值（暴漲空間有限）
    mega_caps = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT"}
    tickers = [t for t in tickers if t["symbol"] not in mega_caps]
    tickers = tickers[:50]
    
    # 批次取得 klines（只抓前 20 個最有潛力的）
    # 先用 24hr 資料做初步篩選
    candidate_tickers = []
    for ticker in tickers:
        symbol = ticker["symbol"]
        quote_vol = float(ticker.get("quoteVolume", 0))
        change = float(ticker.get("priceChangePercent", 0))
        
        if quote_vol < config_scan.get("min_24h_volume_usdt", 100000):
            continue
            
        # 過濾穩定幣
        if config_scan["exclude_stablecoins"]:
            base = symbol.replace("USDT", "")
            stables = {"USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDP", "GUSD", "PAX", "SUSD", "LUSD", "FRAX"}
            if base in stables:
                continue
        
        candidate_tickers.append(ticker)
    
    # 對每個候選幣種進行完整評分
    # 先批次取得所有 klines 和訂單簿
    symbols_to_scan = [t["symbol"] for t in candidate_tickers]
    klines_data = get_klines_batch(symbols_to_scan)
    orderbook_data = get_orderbook_batch(symbols_to_scan)
    
    for ticker in candidate_tickers:
        symbol = ticker["symbol"]
        
        # 檢查交易所狀態
        if symbol in exchange_info:
            if exchange_info[symbol].get("status") != "TRADING":
                continue
        
        # 計算各項分數
        vol_score, _ = calculate_volume_score(ticker, config)
        momentum_score = calculate_momentum_score(ticker)
        
        klines = klines_data.get(symbol, [])
        breakout_score = calculate_breakout_score(ticker, klines)
        liquidity_score = calculate_liquidity_score(ticker)
        
        # 訂單簿評分
        ob = orderbook_data.get(symbol, {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        last_price = float(ticker.get("lastPrice", 0))
        ob_score, ob_summary, ob_detail = calculate_orderbook_score(bids, asks, last_price)
        
        # 加權總分（含訂單簿）
        total_score = (
            vol_score * config_score["volume_weight"] +
            momentum_score * config_score["momentum_weight"] +
            breakout_score * config_score["breakout_weight"] +
            liquidity_score * config_score["liquidity_weight"] +
            ob_score * config_score["orderbook_weight"]
        )
        
        # Smart Money 分數（暫時為 0）
        smart_money_score = 0
        total_score += smart_money_score * config_score["smart_money_weight"]
        
        signals.append({
            "symbol": symbol,
            "base": symbol.replace("USDT", ""),
            "price": ticker["lastPrice"],
            "price_change_24h": ticker["priceChangePercent"],
            "high_24h": ticker["highPrice"],
            "low_24h": ticker["lowPrice"],
            "volume_24h_usdt": round(quote_vol, 0),
            "scores": {
                "volume": round(vol_score, 1),
                "momentum": round(momentum_score, 1),
                "breakout": round(breakout_score, 1),
                "liquidity": round(liquidity_score, 1),
                "smart_money": round(smart_money_score, 1),
                "orderbook": round(ob_score, 1),
                "total": round(total_score, 1),
            },
            "orderbook": ob_summary,
            "tags": [],
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        })
    
    # 按總分排序
    signals.sort(key=lambda x: x["scores"]["total"], reverse=True)
    
    # 只保留前 N 個
    signals = signals[:config_scan.get("max_signals", 20)]
    
    # 加上標籤
    for s in signals:
        tags = []
        if s["scores"]["breakout"] >= 80:
            tags.append("📈 突破壓力")
        if float(s["price_change_24h"]) >= 10:
            tags.append("🔥 強勢")
        elif float(s["price_change_24h"]) >= 5:
            tags.append("⚡ 上漲中")
        if s["scores"]["volume"] >= 70:
            tags.append("📊 量爆增")
        if float(s["price_change_24h"]) < 0 and abs(float(s["price_change_24h"])) < 5:
            tags.append("🔄 可能反轉")
        # 訂單簿標籤
        ob = s.get("orderbook", {})
        if ob.get("bid_ask_ratio", 1) >= 1.5:
            tags.append("📗 買盤強勁")
        if ob.get("support_score", 0) >= 20:
            tags.append("🛡️ 有支撐")
        if ob.get("bid_ask_ratio", 1) <= 0.6:
            tags.append("📕 賣壓沉重")
        s["tags"] = tags
    
    print(f"掃描完成：{len(signals)} 個潛力幣種")
    return signals

def save_signals(signals):
    """儲存 signals.json"""
    output = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": len(signals),
        "signals": signals,
    }
    with open(BASE_DIR / "signals.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"已寫入 signals.json（{len(signals)} 筆）")

if __name__ == "__main__":
    config = load_config()
    signals = scan(config)
    save_signals(signals)
