#!/usr/bin/env python3
"""
volume_monitor.py — 量能監控模組
每小時追蹤 top 100 幣種的「量比」(本根 vs 前 N 根均量) + 盤整天數 + 波動率。
量比 > 3x + 盤整 > 3天 → 產出警報
輸出 volume_alerts.json 供 scanner.py 或 paper_trader.py 使用。

獨立於 scanner 運作，可設每小時 cron job。
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
ALERTS_PATH = BASE_DIR / "volume_alerts.json"
VOLUME_HISTORY_PATH = BASE_DIR / "volume_history.json"
SIGNALS_PATH = BASE_DIR / "signals.json"

# 要監控的幣種數
TOP_N = 100

# 觸發條件
MIN_VOL_RATIO = 3.0    # 量比 > 3x
MIN_CONSOLIDATION_DAYS = 3  # 盤整 > 3天
MAX_CONSOLIDATION_RANGE = 8.0  # 盤整振幅 < 8%

# ------------------------------------------------
# 工具函數
# ------------------------------------------------

def http_get(path, params=None):
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


def get_top_tickers(n=TOP_N):
    """取得成交量最高的 N 個 USDT 交易對"""
    data = http_get("/api/v3/ticker/24hr")
    if not data:
        return []
    usdt = [t for t in data if t.get("symbol", "").endswith("USDT")]
    # 排除極大幣
    mega = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
    usdt = [t for t in usdt if t["symbol"] not in mega]
    # 排除穩定幣
    stables = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "DAIUSDT", "FDUSDUSDT", "USDPUSDT", "GUSDUSDT", "PAXUSDT", "SUSDUSDT", "LUSDUSDT", "FRAXUSDT"}
    usdt = [t for t in usdt if t["symbol"] not in stables]
    usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    return usdt[:n]


def get_klines_1h(symbol, limit=72):
    """抓過去 72 根 1h K 線 (3天)"""
    return http_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": "1h",
        "limit": str(limit)
    })


# ------------------------------------------------
# 核心計算
# ------------------------------------------------

def calc_volume_ratio(klines, lookback_short=3, lookback_long=10):
    """
    量比 = 最新 1 根量 / 前 N 根均量
    lookback_short: 短期 (用 1~3 根)
    lookback_long: 長期均量 (用 8~12 根)
    返回 (short_ratio, long_ratio, short_avg, long_avg)
    """
    if not klines or len(klines) < lookback_long + 1:
        return 0, 0, 0, 0
    
    volumes = [float(k[5]) for k in klines]
    latest_vol = volumes[-1]
    
    short_vols = volumes[-(lookback_short+1):-1]
    long_vols = volumes[-lookback_long:-1]
    
    # 排除最後一根 (最新)
    short_avg = sum(short_vols) / len(short_vols) if short_vols else 1
    long_avg = sum(long_vols) / len(long_vols) if long_vols else 1
    
    short_ratio = latest_vol / short_avg if short_avg > 0 else 0
    long_ratio = latest_vol / long_avg if long_avg > 0 else 0
    
    return short_ratio, long_ratio, short_avg, long_avg


def calc_consolidation_days(klines, range_pct=8.0):
    """
    計算價格在 range_pct% 內波動的天數 (最近持續天數)
    用 1h K 線，找最近多少小時價格在 range_pct% 內
    """
    if not klines or len(klines) < 12:
        return 0, 0, 0
    
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    
    current_price = float(klines[-1][4])
    
    # 從最新往舊找，看連續多少根在 ±range_pct/2 內
    range_threshold = current_price * (range_pct / 200)  # 半幅
    count = 0
    for k in reversed(klines):
        high, low = float(k[2]), float(k[3])
        half_range = float(k[4]) * (range_pct / 200)
        if abs(high - current_price) <= half_range * 2 and abs(low - current_price) <= half_range * 2:
            count += 1
        else:
            break
    
    days = count / 24  # 換算天數
    total_high = max(highs)
    total_low = min(lows)
    actual_range = (total_high - total_low) / total_low * 100 if total_low > 0 else 999
    
    return days, count, actual_range


def calc_consecutive_volume_growth(klines, lookback=5):
    """連續幾根量增？量增趨勢持續性"""
    if not klines or len(klines) < lookback + 1:
        return 0
    
    volumes = [float(k[5]) for k in klines[-lookback:]]
    count = 0
    for i in range(1, len(volumes)):
        if volumes[i] > volumes[i-1]:
            count += 1
    return count


# ------------------------------------------------
# 主邏輯
# ------------------------------------------------

def monitor():
    print(f"[{datetime.now().isoformat()}] 量能監控開始...")
    
    tickers = get_top_tickers()
    if not tickers:
        print("無法取得 tickers", file=sys.stderr)
        return None
    
    symbols = [t["symbol"] for t in tickers]
    print(f"監控 {len(symbols)} 個幣種...")
    
    alerts = []
    monitored = []
    
    for i, symbol in enumerate(symbols):
        klines = get_klines_1h(symbol, limit=72)
        if not klines or len(klines) < 24:
            continue
        
        ticker = tickers[i]
        last_price = float(ticker.get("lastPrice", 0))
        change_24h = float(ticker.get("priceChangePercent", 0))
        quote_vol = float(ticker.get("quoteVolume", 0))
        
        # 1. 量比計算 (短期 v3, 長期 v10)
        short_ratio, long_ratio, short_avg, long_avg = calc_volume_ratio(klines)
        
        # 2. 盤整天數
        cons_days, cons_hours, actual_range = calc_consolidation_days(klines)
        
        # 3. 連續量增
        vol_growth_count = calc_consecutive_volume_growth(klines)
        
        # 量比評分 (0-100): 3x = 60分, 5x = 90分, 8x+ = 100分
        vol_ratio_score = 0
        if short_ratio >= 3:
            vol_ratio_score = 60 + min((short_ratio - 3) / 5 * 40, 40)
        elif short_ratio >= 2:
            vol_ratio_score = 30 + (short_ratio - 2) * 30
        elif short_ratio >= 1.5:
            vol_ratio_score = 10 + (short_ratio - 1.5) * 40
        
        # 是否觸發警報
        is_alert = (
            short_ratio >= MIN_VOL_RATIO
            and cons_days >= MIN_CONSOLIDATION_DAYS
        )
        
        entry = {
            "symbol": symbol,
            "base": symbol.replace("USDT", ""),
            "price": last_price,
            "change_24h": change_24h,
            "volume_24h_usdt": round(quote_vol, 0),
            "volume_short_ratio": round(short_ratio, 2),
            "volume_long_ratio": round(long_ratio, 2),
            "volume_3h_avg": round(short_avg, 0),
            "volume_10h_avg": round(long_avg, 0),
            "consolidation_days": round(cons_days, 1),
            "consolidation_hours": cons_hours,
            "consolidation_range_pct": round(actual_range, 2),
            "consecutive_vol_growth": vol_growth_count,
            "vol_ratio_score": round(vol_ratio_score, 1),
            "is_alert": is_alert,
            "alert_reason": "",
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if is_alert:
            reason = f"量比 {short_ratio:.1f}x (短均 {short_avg:,.0f}), 盤整 {cons_days:.1f}天"
            entry["alert_reason"] = reason
            alerts.append(entry)
            print(f"   🚨 {symbol}: {reason}")
        elif short_ratio >= 2:
            print(f"   👀 {symbol}: 量比 {short_ratio:.2f}x, 盤整 {cons_days:.1f}天")
        
        monitored.append(entry)
    
    # 按量比排序
    monitored.sort(key=lambda x: x["volume_short_ratio"], reverse=True)
    
    output = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_monitored": len(monitored),
        "total_alerts": len(alerts),
        "alerts": alerts,
        "monitored": monitored[:30],  # 只保留前 30 筆 (節省空間)
    }
    
    with open(ALERTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"✓ 完成: 監控 {len(monitored)} 幣, {len(alerts)} 個警報")
    return output


if __name__ == "__main__":
    result = monitor()
    if not result:
        print("量能監控失敗", file=sys.stderr)
        sys.exit(1)
