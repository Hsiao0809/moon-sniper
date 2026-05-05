#!/usr/bin/env python3
"""發送 Telegram 掃描報告"""
import json, os, urllib.request, urllib.parse

with open("signals.json") as f:
    signals = json.load(f)
with open("paper_trades.json") as f:
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
    lines.append("")
    lines.append(
        f"📊 紙交易：{stats['open_count']} 筆進行中 | "
        f"總損益 {stats['total_pnl_usdt']} USDT"
    )
    lines.append(f"勝率 {stats['win_rate']}% | {stats['total_trades']} 筆總計")

lines.append("")
lines.append("🔗 https://hsiao0809.github.io/moon-sniper/")

msg = "\n".join(lines)

bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
data = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": msg,
}).encode()

resp = urllib.request.urlopen(url, data=data)
print(f"Telegram 通知已發送: {resp.status}")
