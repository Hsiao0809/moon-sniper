# Moon Sniper Changelog

所有重要版本變更都記錄在此檔案。

時間一律使用台灣時間（CST, UTC+8）。

---

## [v2.0.0] - 2026-05-08

### 主題：雙軌制架構 — Swing 長線 + Scalp 短線

本次改版的核心目標：解決原系統「長線埋伏」和「短線日內獲利」混用同一套掃描/資金管理邏輯，導致資金被長線佔住、短線沒有已實現收益的問題。

---

### Added

#### 雙軌掃描模式
- `scanner.py` 新增 CLI mode：
  - `python scanner.py --mode swing`
  - `python scanner.py --mode scalp`
- 新增雙 signals 輸出：
  - `swing_signals.json`
  - `scalp_signals.json`

#### Swing 長線軌
- 目標：盤整低位入場，等待 3-10 天波段上漲。
- Pool：180U（帳戶 60%）。
- 最大持倉：4 筆。
- TP/SL：
  - TP1: +15%，出 33%
  - TP2: +30%，全出
  - SL: -5%
- 最長持有：10 天。
- 核心條件：
  - 盤整 ≥ 3 天
  - 量比 ≥ 2x
  - OBI > 0
  - ADX ≤ 25

#### Scalp 短線軌
- 目標：日內動能交易，產生已實現收益。
- Pool：90U（帳戶 30%）。
- 最大持倉：4 筆。
- TP/SL：
  - TP1: +5%，出 50%
  - TP2: +8%，全出
  - SL: -3%
- 最長持有：4 小時。
- 核心條件：
  - 24h 漲幅 ≥ 3%
  - 量比 ≥ 2x
  - OBI ≥ 0.3
  - ADX ≥ 20

#### 新增微結構指標
- `calculate_obi(bids, asks, depth=10)`：Orderbook Imbalance。
- `calculate_adx(klines, period=14)`：Regime Detection 用。
- `get_funding_rate(symbol)`：Funding Rate 讀取。

#### 雙資金池紙交易
- `paper_trader.py` 改為雙 pool：
  - `swing`
  - `scalp`
- 每筆交易新增欄位：
  - `pool`
  - `obi`
  - `adx`
- `paper_trades.json.stats.pools` 新增分池統計：
  - pool_initial
  - pool_equity
  - open_count
  - closed_count
  - total_realized_pnl_usdt
  - total_unrealized_pnl_usdt
  - used_margin

#### 前端雙軌顯示
- `index.html` 新增：
  - Swing 長線 tab
  - Scalp 短線 tab
  - Swing Pool equity card
  - Scalp Pool equity card
  - 持倉依 pool 分區顯示
- 前端改為同時 fetch：
  - `swing_signals.json`
  - `scalp_signals.json`
  - `paper_trades.json`

#### GitHub Actions
- `scan.yml`：主 workflow 改為同時跑 swing + scalp。
- 新增 `scalp-scan.yml`：每 15 分鐘跑短線掃描。

#### Telegram 通知
- `notify.py` 改為雙軌報告：
  - Swing 前 3 名
  - Scalp 前 3 名
  - 分 pool 統計

---

### Changed

#### Config 架構
`config.json` 從原本：
- `scan`
- `scoring`
- `paper_trade`

改為：
- `scan`
- `swing_trader`
- `scalp_trader`

#### 評分邏輯
原本所有訊號使用單一權重。

現在改為：

Swing：
- 盤整 30%
- 量比 25%
- OBI 15%
- 訂單簿 15%
- 動能 10%
- Funding Rate 5%

Scalp：
- 動能 30%
- OBI 30%
- 量比 20%
- 流動性 10%
- 訂單簿 10%

#### 資金管理
原本：
- 單一資金池
- max 8 筆
- TP1 +10%、TP2 +20%、SL -5%
- max hold 3 天

現在：
- Swing pool 180U，max 4 筆，TP 15/30，SL -5，max hold 10 天
- Scalp pool 90U，max 4 筆，TP 5/8，SL -3，max hold 4 小時
- Reserve 30U

---

### Fixed

- 解決長線持倉佔用全部資金，短線無法開倉的問題。
- 解決短線交易使用過寬 TP/SL，導致日內沒有已實現收益的問題。
- 解決單一評分權重無法同時服務盤整初爆與短線動能的問題。
- 解決前端只能顯示單一 signals 來源的問題。

---

### Knowledge Integration

本次改版將已學習內容實際落地：

- OBI：兩軌都納入；Swing 用作突破確認，Scalp 作為核心短線權重。
- ADX / Regime Detection：Swing 排除強趨勢，Scalp 排除無動能盤整。
- Funding Rate：作為 pool reduction / 擁擠風險調整依據。
- 量比：兩軌皆保留，Swing 用於初爆確認，Scalp 用於即時動能確認。

---

### Git Commits

- `b21c748` — `feat: 雙軌制架構 — Swing長線 + Scalp短線`
- `1348d64` — `chore: add scalp-scan workflow (每 15 分鐘)`

---

### Files Changed

- `.github/workflows/scan.yml`
- `.github/workflows/scalp-scan.yml`
- `config.json`
- `index.html`
- `notify.py`
- `paper_trader.py`
- `scanner.py`
- `CHANGELOG.md`

---

## [v1.x] - 2026-05-06 ~ 2026-05-07

### Main Features Before v2

- 單一 scanner：`signals.json`
- 單一 paper trader：`paper_trades.json`
- 單一資金池：300U
- TP1 +10%、TP2 +20%、SL -5%
- max open trades: 8
- max hold: 3 天
- 掃描因子：
  - 24h 成交量
  - 量比
  - 動能
  - 訂單簿
  - Smart Money
  - Breakout
- 新增 TON 案例後的量比與盤整偵測。
- 新增做空評分與做空 PnL 修正。
