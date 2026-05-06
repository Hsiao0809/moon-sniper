#!/usr/bin/env python3
"""
market-structure-snapshot.py
快速掃描 BTC 市場微結構，輸出四層分析摘要。
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta

def http_get(base_url, path, params=None):
    url = base_url + path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + qs
    resp = urllib.request.urlopen(url, timeout=15)
    return json.loads(resp.read())

def get_btc_data():
    """拉 BTC 的訂單簿、ticker、日線 klines"""
    # 訂單簿
    depth = http_get("https://api.binance.com", "/api/v3/depth", {"symbol": "BTCUSDT", "limit": 50})
    bid_vol = sum(float(b[1]) for b in depth["bids"][:10])
    ask_vol = sum(float(a[1]) for a in depth["asks"][:10])
    bid_ask_ratio = bid_vol / (ask_vol if ask_vol > 0 else 1)

    # 24hr ticker
    ticker = http_get("https://api.binance.com", "/api/v3/ticker/24hr", {"symbol": "BTCUSDT"})
    price = float(ticker["lastPrice"])
    chg24 = float(ticker["priceChangePercent"])
    vol24 = float(ticker["quoteVolume"])

    # 日線 klines（90 天）
    klines = http_get("https://api.binance.com", "/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1d", "limit": 90})
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None

    # 小時線 klines（48 小時）
    klines_1h = http_get("https://api.binance.com", "/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": 48})
    closes_1h = [float(k[4]) for k in klines_1h]
    vol_1h = [float(k[5]) for k in klines_1h]
    avg_vol_1h = sum(vol_1h) / len(vol_1h) if vol_1h else 0
    last_vol_1h = vol_1h[-1] if vol_1h else 0
    vol_ratio_1h = last_vol_1h / (avg_vol_1h if avg_vol_1h > 0 else 1)

    # CVD 模擬（用 ticker 的 bid/ask pressure + 1h 量比）
    # 真實 CVD 需要 tick 數據，這裡用 bid/ask + 成交量變化逼近
    cvd_score = "neutral"
    if bid_ask_ratio > 1.3 and vol_ratio_1h > 1.5:
        cvd_score = "bullish"
    elif bid_ask_ratio < 0.7 and vol_ratio_1h > 1.5:
        cvd_score = "bearish"
    elif bid_ask_ratio > 1.1:
        cvd_score = "slightly_bullish"
    elif bid_ask_ratio < 0.9:
        cvd_score = "slightly_bearish"

    # OI 資料（從 Binance Futures）
    try:
        oi_now = http_get("https://fapi.binance.com", "/fapi/v1/openInterest", {"symbol": "BTCUSDT"})
        oi_value = float(oi_now["openInterest"])
        oi_hist = http_get("https://fapi.binance.com", "/futures/data/openInterestHist", {"symbol": "BTCUSDT", "period": "1h", "limit": 24})
        oi_values = [float(o.get("sumOpenInterest", o.get("openInterest", 0))) for o in oi_hist]
        oi_24h_ago = oi_values[0] if oi_values else oi_value
        oi_change_pct = ((oi_value - oi_24h_ago) / oi_24h_ago * 100) if oi_24h_ago > 0 else 0
    except Exception:
        oi_value = 0
        oi_change_pct = 0

    return {
        "price": price,
        "chg24_pct": round(chg24, 2),
        "vol24_usdt": round(vol24, 0),
        "sma20": round(sma20, 0) if sma20 else None,
        "sma50": round(sma50, 0) if sma50 else None,
        "bid_ask_ratio": round(bid_ask_ratio, 2),
        "vol_ratio_1h": round(vol_ratio_1h, 2),
        "cvd_estimate": cvd_score,
        "oi_value": round(oi_value, 0),
        "oi_change_pct": round(oi_change_pct, 2),
    }

def analyze_layer1(data):
    """第 1 層：訂單簿分析"""
    ratio = data["bid_ask_ratio"]
    if ratio > 1.5:
        return {"signal": "bullish", "detail": f"買盤強勁（ratio={ratio}），有人在接"}
    elif ratio > 1.1:
        return {"signal": "slightly_bullish", "detail": f"買盤略優（ratio={ratio}）"}
    elif ratio < 0.7:
        return {"signal": "bearish", "detail": f"賣壓沉重（ratio={ratio}），有人在砸"}
    elif ratio < 0.9:
        return {"signal": "slightly_bearish", "detail": f"賣盤略多（ratio={ratio}）"}
    else:
        return {"signal": "neutral", "detail": f"買賣均衡（ratio={ratio}）"}

def analyze_layer2(data):
    """第 2 層：成交量分析"""
    vr = data["vol_ratio_1h"]
    chg = data["chg24_pct"]

    if chg > 3 and vr > 1.5:
        return {"signal": "bullish", "detail": f"價漲量增（chg={chg}%, vol_ratio={vr}），健康趨勢"}
    elif chg > 3 and vr < 0.7:
        return {"signal": "bearish_div", "detail": f"價漲量縮（chg={chg}%, vol_ratio={vr}），趨勢衰竭"}
    elif chg < -3 and vr > 1.5:
        return {"signal": "bearish", "detail": f"價跌量增（chg={chg}%, vol_ratio={vr}），恐慌或換手"}
    elif chg < -3 and vr < 0.7:
        return {"signal": "neutral", "detail": f"價跌量縮（chg={chg}%, vol_ratio={vr}），正常回檔"}
    else:
        return {"signal": "neutral", "detail": f"量能正常（vol_ratio={vr}）"}

def analyze_layer3(data):
    """第 3 層：CVD 分析"""
    cvd = data["cvd_estimate"]
    chg = data["chg24_pct"]
    mapping = {
        "bullish": {"signal": "bullish", "detail": "主動買盤主導，有人在吸籌"},
        "slightly_bullish": {"signal": "slightly_bullish", "detail": "買盤略佔優勢"},
        "neutral": {"signal": "neutral", "detail": "買賣平衡，不明確"},
        "slightly_bearish": {"signal": "slightly_bearish", "detail": "賣盤略佔優勢"},
        "bearish": {"signal": "bearish", "detail": "主動賣盤主導，有人在出貨"},
    }
    return mapping.get(cvd, {"signal": "unknown", "detail": "無法判斷"})

def analyze_layer4(data):
    """第 4 層：Gamma 分析（透過價格 vs SMA 推估）"""
    price = data["price"]
    sma20 = data["sma20"]
    sma50 = data["sma50"]

    if sma20 and sma50:
        if price > sma20 > sma50:
            return {"signal": "bullish", "detail": f"價格 ${price:.0f} > SMA20 ${sma20:.0f} > SMA50 ${sma50:.0f}，多頭排列，可能負 gamma"}
        elif price < sma20 < sma50:
            return {"signal": "bearish", "detail": f"價格 ${price:.0f} < SMA20 ${sma20:.0f} < SMA50 ${sma50:.0f}，空頭排列"}
        elif price > sma20 and price < sma50:
            return {"signal": "neutral", "detail": f"價格在 SMA20(${sma20:.0f}) 和 SMA50(${sma50:.0f}) 之間，盤整"}
        else:
            return {"signal": "mixed", "detail": "方向不明確"}
    return {"signal": "unknown", "detail": "數據不足"}

def analyze_layer5(data):
    """第 5 層：OI（未平倉量）分析"""
    chg = data["chg24_pct"]
    oi_change = data["oi_change_pct"]

    if chg > 2 and oi_change > 5:
        return {"signal": "bullish", "detail": f"OI +{oi_change}%，新資金進場做多，趨勢健康"}
    elif chg > 2 and oi_change < -5:
        return {"signal": "bearish_div", "detail": f"OI {oi_change}%，多頭在平倉，趨勢可能結束"}
    elif chg < -2 and oi_change > 5:
        return {"signal": "bearish", "detail": f"OI +{oi_change}%，新資金進場做空"}
    elif chg < -2 and oi_change < -5:
        return {"signal": "bullish_div", "detail": f"OI {oi_change}%，空頭在平倉，底部可能接近"}
    else:
        return {"signal": "neutral", "detail": f"OI 變化 {oi_change}%，無異常"}

def main():
    print("=" * 60)
    print("  BTC 市場微結構快照")
    print(f"  {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')}")
    print("=" * 60)

    data = get_btc_data()
    print(f"\n價格：${data['price']:,.0f} | 24h：{data['chg24_pct']:+.2f}% | 24h量：${data['vol24_usdt']:,.0f}")
    print(f"SMA20：${data['sma20']:,.0f} | SMA50：${data['sma50']:,.0f}")

    layers = [
        ("① 訂單簿", analyze_layer1(data)),
        ("② 成交量", analyze_layer2(data)),
        ("③ CVD", analyze_layer3(data)),
        ("④ Gamma", analyze_layer4(data)),
        ("⑤ OI 未平倉", analyze_layer5(data)),
    ]

    print(f"\n{'─' * 75}")
    print(f"{'層級':<12} {'訊號':<20} {'說明'}")
    print(f"{'─' * 75}")
    bullish_count = 0
    bearish_count = 0
    for name, result in layers:
        sig = result["signal"]
        if "bullish" in sig:
            sig_display = "🟢 " + sig
            bullish_count += 1
        elif "bearish" in sig:
            sig_display = "🔴 " + sig
            bearish_count += 1
        else:
            sig_display = "⚪ " + sig
        print(f"{name:<12} {sig_display:<20} {result['detail']}")

    print(f"{'─' * 75}")
    if bullish_count >= 4:
        print(f"\n✅ 結論：五層中 {bullish_count} 層偏多 → 結構偏多")
    elif bearish_count >= 4:
        print(f"\n❌ 結論：四層中 {bearish_count} 層偏空 → 結構偏空")
    elif bullish_count >= 2 and bearish_count < 2:
        print(f"\n🟡 結論：微偏多（bullish={bullish_count}, bearish={bearish_count}）→ 可找多單機會")
    elif bearish_count >= 2:
        print(f"\n🟠 結論：微偏空（bullish={bullish_count}, bearish={bearish_count}）→ 可找空單機會")
    else:
        print(f"\n⚪ 結論：方向不明確 → 不交易或等更多確認")
    print()

if __name__ == "__main__":
    main()
