#!/usr/bin/env python3
"""發送 Telegram 掃描報告"""
import json, os, urllib.request, urllib.parse

with open("signals.json", encoding="utf-8") as f:
    signals = json.load(f)
with open("paper_trades.json", encoding="utf-8") as f:
    trades = json.load(f)

lines = ["🌙 Moon Sniper 掃描報告"]
lines.append("")
lines.append(f"📡 潛力幣種：{signals['total_scanned']} 個")
lines.append("")
lines.append("🏆 前 5 名：")

for s in signals["signals"][:5]:
    chg = s["price_change_24h"]
    price = float(s["price"])
    lines.append(
        f"  {s['base']:8s} ${price:<10.4f} {chg:>7s}%  分數:{s['scores']['total']}"
    )

stats = trades.get("stats", {})
if stats.get("total_trades", 0) > 0:
    realized = stats.get("total_realized_pnl_usdt", stats.get("total_pnl_usdt", 0))
    unrealized = stats.get("total_unrealized_pnl_usdt", 0)
    total_equity_pnl = realized + unrealized
    lines.append("")
    lines.append(
        f"📊 紙交易：{stats.get('open_count', 0)} 筆進行中 | "
        f"已實現 {realized:+.2f}U | 未實現 {unrealized:+.2f}U | 總浮盈 {total_equity_pnl:+.2f}U"
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
