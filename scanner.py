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
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def run_binance_cli(args):
    """執行 binance-cli 或直接 HTTP 呼叫 Binance API"""
    # 方法 1: 本地 binance-cli
    local_path = os.path.expanduser("~/.hermes/node/bin/binance-cli")
    if os.path.exists(local_path):
        cmd = [local_path] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
    # 方法 2: PATH 上的 binance-cli
    try:
        cmd = ["binance-cli"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    # 方法 3: 直接 HTTP API（GitHub Actions 用這個）
    return call_binance_api(args)

def call_binance_api(args):
    """直接用 HTTP 呼叫 Binance 公開 API（不需要 API key）"""
    import urllib.request
    
    # 把 binance-cli 的 args 轉成 HTTP 路徑
    # 支援: spot ticker24hr, spot klines --symbol X --interval 1d --limit N, spot depth --symbol X
    api_path = ""
    params = {}
    
    if len(args) >= 2 and args[0] == "spot":
        if args[1] == "ticker24hr":
            api_path = "/api/v3/ticker/24hr"
            # 如果有 --symbol 參數
            for j, a in enumerate(args):
                if a == "--symbol" and j + 1 < len(args):
                    params["symbol"] = args[j + 1]
        elif args[1] == "klines":
            api_path = "/api/v3/klines"
            for j, a in enumerate(args):
                if a == "--symbol" and j + 1 < len(args):
                    params["symbol"] = args[j + 1]
                elif a == "--interval" and j + 1 < len(args):
                    params["interval"] = args[j + 1]
                elif a == "--limit" and j + 1 < len(args):
                    params["limit"] = args[j + 1]
        elif args[1] == "depth":
            api_path = "/api/v3/depth"
            for j, a in enumerate(args):
                if a == "--symbol" and j + 1 < len(args):
                    params["symbol"] = args[j + 1]
                elif a == "--limit" and j + 1 < len(args):
                    params["limit"] = args[j + 1]
        elif args[1] == "exchange-info":
            api_path = "/api/v3/exchangeInfo"
        elif args[1] == "ticker-price" or args[1] == "ticker":
            api_path = "/api/v3/ticker/price"
            for j, a in enumerate(args):
                if a == "--symbol" and j + 1 < len(args):
                    params["symbol"] = args[j + 1]
    
    if not api_path:
        return None
    
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.binance.com{api_path}"
    if query:
        url += f"?{query}"
    
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        print(f"HTTP API error: {e}", file=sys.stderr)
        return None

def get_all_tickers():
    """取得所有 USDT 交易對的 24hr 行情 — 用 urllib（相容性最高）"""
    import urllib.request
    try:
        resp = urllib.request.urlopen("https://api.binance.com/api/v3/ticker/24hr", timeout=30)
        data = json.loads(resp.read())
        if isinstance(data, dict):
            data = [data]
        usdt_pairs = [t for t in data if t.get("symbol", "").endswith("USDT")]
        return usdt_pairs
    except Exception as e:
        print(f"get_all_tickers error: {e}", file=sys.stderr)
        return []

def http_get(path, params=None):
    """直接 HTTP GET Binance API"""
    import urllib.request
    url = f"https://api.binance.com{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{query}"
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        print(f"HTTP error {path}: {e}", file=sys.stderr)
        return None

def get_exchange_info():
    """取得交易對資訊"""
    data = http_get("/api/v3/exchangeInfo")
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
        data = http_get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": str(limit)})
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
        data = http_get("/api/v3/depth", {"symbol": symbol, "limit": str(limit)})
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

def get_smart_money_signals():
    """從 Binance Web3 API 取得聰明錢買入訊號"""
    import urllib.request, json
    
    try:
        # 同時查 Solana 和 BSC 的聰明錢訊號
        chains = {"CT_501": "solana", "56": "bsc"}
        all_signals = {}
        
        for chain_id, chain_name in chains.items():
            data = json.dumps({
                "smartSignalType": "",
                "page": 1,
                "pageSize": 50,
                "chainId": chain_id
            }).encode()
            
            req = urllib.request.Request(
                "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "binance-web3/1.1 (Skill)",
                }
            )
            
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read())
            
            if result.get("code") == "000000" and result.get("data"):
                for signal in result["data"]:
                    ticker = signal.get("ticker", "").upper()
                    direction = signal.get("direction", "")
                    smart_money_count = signal.get("smartMoneyCount", 0)
                    max_gain = signal.get("maxGain", "0")
                    status = signal.get("status", "")
                    
                    if direction == "buy" and status == "active" and smart_money_count >= 1:
                        # 用 ticker 做 key，如果多個訊號取最高的
                        if ticker not in all_signals or int(smart_money_count) > all_signals[ticker]["count"]:
                            all_signals[ticker] = {
                                "count": smart_money_count,
                                "max_gain": max_gain,
                                "chain": chain_name,
                                "direction": direction,
                            }
        
        print(f"Smart Money 訊號：{len(all_signals)} 個幣種有買入訊號")
        return all_signals
    except Exception as e:
        print(f"Smart Money API 錯誤：{e}", file=sys.stderr)
        return {}

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

def detect_patterns(klines, ticker):
    """技術型態分析：雙底/雙頂/Bollinger Squeeze/量價背離"""
    if not klines or len(klines) < 20:
        return {}

    patterns = {}
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    last_price = float(ticker.get("lastPrice", 0))

    # 1. 雙底偵測（反轉看多）
    # 找最近 20 根 K 線中的兩個相近低點，間隔 5-15 根
    recent_lows = lows[-20:]
    min1_idx = recent_lows.index(min(recent_lows))
    # 排除 min1 附近，找第二個低點
    mask = [True] * len(recent_lows)
    for offset in range(-3, 4):
        if 0 <= min1_idx + offset < len(recent_lows):
            mask[min1_idx + offset] = False
    filtered_lows = [recent_lows[i] for i in range(len(recent_lows)) if mask[i]]
    if filtered_lows:
        min2 = min(filtered_lows)
        min1 = recent_lows[min1_idx]
        low_diff = abs(min1 - min2) / max(min1, min2) * 100
        # 兩個低點差距 < 3%，且中間有反彈
        if low_diff < 3.0 and min1_idx < len(recent_lows) * 0.7:
            neckline = max(closes[-20:])  # 頸線 = 期間最高收盤
            patterns["double_bottom"] = {
                "left_low": round(min1, 2),
                "right_low": round(min2, 2),
                "neckline": round(neckline, 2),
                "distance_pct": round(low_diff, 2),
                "broken": last_price > neckline,
                "signal": "bullish_reversal" if last_price > neckline else "potential_bullish"
            }

    # 2. 雙頂偵測（反轉看空）
    recent_highs = highs[-20:]
    max1_idx = recent_highs.index(max(recent_highs))
    mask = [True] * len(recent_highs)
    for offset in range(-3, 4):
        if 0 <= max1_idx + offset < len(recent_highs):
            mask[max1_idx + offset] = False
    filtered_highs = [recent_highs[i] for i in range(len(recent_highs)) if mask[i]]
    if filtered_highs:
        max2 = max(filtered_highs)
        max1 = recent_highs[max1_idx]
        high_diff = abs(max1 - max2) / max(max1, max2) * 100
        if high_diff < 3.0 and max1_idx < len(recent_highs) * 0.7:
            neckline = min(closes[-20:])
            patterns["double_top"] = {
                "left_high": round(max1, 2),
                "right_high": round(max2, 2),
                "neckline": round(neckline, 2),
                "distance_pct": round(high_diff, 2),
                "broken": last_price < neckline,
                "signal": "bearish_reversal" if last_price < neckline else "potential_bearish"
            }

    # 3. Bollinger Squeeze（突破前兆）
    if len(closes) >= 20:
        sma20 = sum(closes[-20:]) / 20
        variance = sum((c - sma20) ** 2 for c in closes[-20:]) / 20
        std = variance ** 0.5
        upper = sma20 + 2 * std
        lower = sma20 - 2 * std
        bandwidth = (upper - lower) / sma20 * 100
        # 帶寬 < 5% 視為壓縮（BTC 通常 5-15%，小幣更寬）
        if bandwidth < 5.0:
            patterns["bollinger_squeeze"] = {
                "bandwidth_pct": round(bandwidth, 2),
                "sma20": round(sma20, 4),
                "upper": round(upper, 4),
                "lower": round(lower, 4),
                "signal": "breakout_imminent"
            }

    # 4. 量價背離
    if len(closes) >= 10:
        price_trend = closes[-1] - closes[-10]
        vol_5 = sum(volumes[-5:]) / 5
        vol_20 = sum(volumes[-20:]) / 20
        vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1

        if price_trend > 0 and vol_ratio < 0.8:
            patterns["volume_divergence"] = {
                "type": "bearish_divergence",
                "detail": f"價格上漲但量比僅 {vol_ratio:.2f}x",
                "vol_ratio": round(vol_ratio, 2)
            }
        elif price_trend < 0 and vol_ratio > 1.2:
            patterns["volume_divergence"] = {
                "type": "healthy_down",
                "detail": "下跌量增，趨勢健康",
                "vol_ratio": round(vol_ratio, 2)
            }

    return patterns

def scan(config):
    """主掃描邏輯"""
    print(f"[{datetime.now(timezone.utc).isoformat()}] 開始掃描...")
    
    tickers = get_all_tickers()
    if not tickers:
        print("錯誤：無法取得 ticker 資料", file=sys.stderr)
        return None
    
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
    smart_money_signals = get_smart_money_signals()
    
    for ticker in candidate_tickers:
        symbol = ticker["symbol"]
        
        # 檢查交易所狀態
        if symbol in exchange_info:
            if exchange_info[symbol].get("status") != "TRADING":
                continue
        
        # 加入流動性過濾（直接排除流動性太差的幣）
        ask_price = float(ticker.get("askPrice", 0))
        bid_price = float(ticker.get("bidPrice", 0))
        last_price = float(ticker.get("lastPrice", 1))
        spread_pct = (ask_price - bid_price) / last_price * 100 if ask_price > 0 and bid_price > 0 else 0
        if spread_pct > 0.5:  # 價差大於 0.5% 直接排除
            continue
        
        # 計算各項分數
        vol_score, quote_vol = calculate_volume_score(ticker, config)
        momentum_score = calculate_momentum_score(ticker)
        
        klines = klines_data.get(symbol, [])
        breakout_score = calculate_breakout_score(ticker, klines)
        
        # 訂單簿評分
        ob = orderbook_data.get(symbol, {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        last_price = float(ticker.get("lastPrice", 0))
        ob_score, ob_summary, ob_detail = calculate_orderbook_score(bids, asks, last_price)

        # 技術型態分析
        patterns = detect_patterns(klines, ticker)
        
        # Smart Money 評分
        base = symbol.replace("USDT", "")
        sm = smart_money_signals.get(base, smart_money_signals.get(symbol, {}))
        if sm and sm.get("direction") == "buy":
            count = sm.get("count", 0)
            max_gain = float(sm.get("max_gain", 0))
            if count >= 5:
                smart_money_score = 90 + min(int(count) * 2, 10)
            elif count >= 3:
                smart_money_score = 70 + int(count) * 5
            elif count >= 1:
                smart_money_score = 50 + int(count) * 10
            else:
                smart_money_score = 0
            if max_gain > 20:
                smart_money_score = min(smart_money_score + 10, 100)
        else:
            smart_money_score = 0
        
        # 加權總分
        total_score = (
            vol_score * config_score["volume_weight"] +
            momentum_score * config_score["momentum_weight"] +
            breakout_score * config_score["breakout_weight"] +
            ob_score * config_score["orderbook_weight"] +
            smart_money_score * config_score["smart_money_weight"]
        )

        # 做空評分：動能過高反轉 + 雙頂 + 賣壓
        short_score = 0
        change_pct = float(ticker.get("priceChangePercent", 0))
        # 漲太多（>15%）且動能可能衰竭
        if change_pct > 15:
            short_score += 30
        elif change_pct > 10:
            short_score += 20
        elif change_pct > 5:
            short_score += 10
        # 雙頂型態
        if "double_top" in patterns:
            short_score += 30
        # 賣壓沉重（訂單簿）
        if ob_summary.get("bid_ask_ratio", 1) < 0.6:
            short_score += 20
        # 量價背離
        if "volume_divergence" in patterns and "bearish" in patterns["volume_divergence"].get("type", ""):
            short_score += 20
        short_score = min(short_score, 100)

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
                "smart_money": round(smart_money_score, 1),
                "orderbook": round(ob_score, 1),
                "total": round(total_score, 1),
                "short": round(short_score, 1),
            },
            "orderbook": ob_summary,
            "smart_money": sm if sm else {},
            "patterns": patterns,
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
        # Smart Money 標籤
        sm = s.get("smart_money", {})
        if sm and sm.get("direction") == "buy":
            count = sm.get("count", 0)
            chain = sm.get("chain", "")
            tags.append(f"🐋 聰明買入({chain},{count}地址)")
        
        # 型態標籤
        pat = s.get("patterns", {})
        if "double_bottom" in pat:
            db = pat["double_bottom"]
            if db.get("broken"):
                tags.append("📈 雙底突破")
            else:
                tags.append("🔄 潛在雙底")
        if "double_top" in pat:
            dt = pat["double_top"]
            if dt.get("broken"):
                tags.append("📉 雙頂跌破")
            else:
                tags.append("⚠️ 潛在雙頂")
        if "bollinger_squeeze" in pat:
            tags.append("📦 壓縮待突破")
        if "volume_divergence" in pat:
            vd = pat["volume_divergence"]
            if "bearish" in vd.get("type", ""):
                tags.append("🔻 量價背離")
            elif "healthy" in vd.get("type", ""):
                tags.append("✅ 量價健康")
        
        # 做空標籤
        if s["scores"].get("short", 0) >= 60:
            tags.append("📉 做空訊號")
        elif s["scores"].get("short", 0) >= 40:
            tags.append("⚠️ 可能做空")
        
        s["tags"] = tags
    
    print(f"掃描完成：{len(signals)} 個潛力幣種")
    return signals

def save_signals(signals):
    """儲存 signals.json"""
    if signals is None:
        print("未更新 signals.json：本次掃描沒有取得 ticker 資料", file=sys.stderr)
        return
    output = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": len(signals),
        "signals": signals,
    }
    with open(BASE_DIR / "signals.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"已寫入 signals.json（{len(signals)} 筆）")

if __name__ == "__main__":
    config = load_config()
    signals = scan(config)
    save_signals(signals)
