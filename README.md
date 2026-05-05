# 🌙 Moon Sniper

暴漲潛力幣種偵測 + 紙交易追蹤系統。

## 功能

- **自動掃描：** 每 4 小時掃描 Binance 所有 USDT 交易對
- **評分機制：** 成交量變化、價格動能、突破確認、流動性
- **紙交易：** 評分超過門檻自動進場，追蹤停利停損
- **績效統計：** 勝率、總損益、最大回撤

## 運作方式

```
GitHub Actions (每 4h)
    → scanner.py 抓資料 + 評分
    → paper_trader.py 管理紙交易
    → commit signals.json + paper_trades.json
    → GitHub Pages 顯示
```

## 部署

1. Fork 這個 repo
2. 開啟 GitHub Pages（Settings → Pages → 選 main 分支 / root）
3. 在 repo Settings → Secrets and variables → Actions 加入：
   - `BINANCE_API_KEY` — 你的 Binance API Key
   - `BINANCE_API_SECRET` — 你的 Binance API Secret
4. GitHub Actions 會自動每 4 小時執行一次
5. 也可以手動觸發：Actions → Moon Sniper Scan → Run workflow

## 本地執行

```bash
# 安裝依賴
npm install -g @binance/binance-cli

# 設定 API
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret

# 執行掃描
python scanner.py

# 執行紙交易
python paper_trader.py

# 打開網頁
open index.html
```

## 設定

編輯 `config.json`：

- `scan.interval_hours` — 掃描間隔（預設 4h）
- `scoring.*` — 各項評分權重
- `paper_trade.min_score_to_trade` — 進場門檻（預設 70）
- `paper_trade.max_risk_usdt` — 單筆風險（預設 10U）
