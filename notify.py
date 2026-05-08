#!/usr/bin/env python3
"""發送 Telegram 掃描報告（雙軌 Swing + Scalp）"""
import json, os, urllib.request, urllib.parse

swing = json.load(open("swing_signals.json", encoding="utf-8"))
scalp = json.load(open("scalp_signals.json", encoding="utf-8"))
trades = json.load(open("paper_trades.json", encoding="utf-8"))

lines = ["🌙 Moon Sniper 雙軌掃描報告"]
lines.append("")

# Swing 長線（前 3）
lines.append("📡 Swing 長線（前 3）：")
for s in swing.get("signals", [])[:3]:
    chg = s["price_change_24h"]
    price = float(s["price"])
    tags = " ".join(t for t in s.get("tags", [])[:2])
    lines.append(
        f"  {s['base']:8s} ${price:<10.4f} {chg:>7s}%  {s['scores']['total']}分  {tags}"
    )

# Scalp 短線（前 3）
lines.append("")
lines.append("⚡ Scalp 短線（前 3）：")
for s in scalp.get("signals", [])[:3]:
    chg = s["price_change_24h"]
    price = float(s["price"])
    obi = s.get("obi", 0)
    lines.append(
        f"  {s['base']:8s} ${price:<10.4f} {chg:>7s}%  OBI:{obi:.2f}  {s['scores']['total']}分"
    )

# 紙交易統計
stats = trades.get("stats", {})
pools = stats.get("pools", {})
if stats.get("total_trades", 0) > 0:
    realized = stats.get("total_realized_pnl_usdt", 0)
    unrealized = stats.get("total_unrealized_pnl_usdt", 0)
    lines.append("")
    lines.append(
        f"📊 總計：{stats.get('open_count', 0)} 筆進行中 | "
        f"已實現 {realized:+.2f}U | 未實現 {unrealized:+.2f}U"
    )
    for pool in ["swing", "scalp"]:
        p = pools.get(pool, {})
        if p:
            label = "Swing" if pool == "swing" else "Scalp"
            lines.append(
                f"  {label}: equity={p.get('pool_equity',0):.1f}U "
                f"open={p.get('open_count',0)} "
                f"realized={p.get('total_realized_pnl_usdt',0):+.2f}U"
            )
    lines.append(f"勝率 {stats.get('win_rate', 0)}% | {stats.get('total_trades', 0)} 筆總計")

lines.append("")
lines.append("🔗 https://hsiao0809.github.io/moon-sniper/")

msg = "\n".join(lines)

bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

if not bot_token or not chat_id:
    print("Telegram secrets not configured; skip notification")
else:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": msg,
    }).encode()
    resp = urllib.request.urlopen(url, data=data)
    print(f"Telegram 通知已發送: {resp.status}")
