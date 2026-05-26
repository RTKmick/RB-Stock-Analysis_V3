For RUMBOR Data Mining

---

核心概念：**用 FinMind/TWSE 原始資料 → 籌碼/技術/Geo 指標 → 策略分數 + 儀表板**

---

### 快速開始：在 Dashboard 顯示數據（不需 ngrok / 本機 Flask）

若**只要在網頁上看籌碼數據**、不需要即時對外或 TradingView webhook，建議用 **GitHub Pages 靜態版**：

> 資料來自 GitHub 倉庫 `data/`，不需 ngrok 或本機 Flask。Push 更新後重新整理即可。

1. **本機產生/更新資料**  
   ```bash
   python scraper_chip.py --stock_id 6239
   ```  
   會輸出 `data/6239_whale_track.json`，並自動更新 `data/manifest.json`。
2. **若已有 `data/*_whale_track.json` 但沒有 manifest**：  
   ```bash
   python SubPY/build_manifest.py
   ```
3. **Push 到 GitHub**（含 `data/`、`index.html`）。  
   官方倉庫：**[RTKmick/RB-Stock-Analysis_V3](https://github.com/RTKmick/RB-Stock-Analysis_V3)**；本機可執行根目錄 **`upl_rb.bat`** 或 **`6_publish_to_pages.bat`**（皆為推送到遠端 **`rtkmick`** 的 **`main`**）。舊倉 **`runbordev111/RB-stock-analysis`** 已停用，請勿再依賴該路徑。
4. **開啟 GitHub Pages（建議用 GitHub Actions）**  
   倉庫 → **Settings** → **Pages** → **Build and deployment** → **Source** 選 **「GitHub Actions」**（勿選「Deploy from a branch」：本倉內建 **pages build and deployment** 常因體量失敗，會導致 **`https://rtkmick.github.io/.../Version.txt` 卡在舊版**）。  
   若介面要求選 workflow，請選 **`.github/workflows/deploy-static-pages.yml`**（會組精簡 **`_site`** 再 `deploy-pages`）。  
   首次可到 **Actions** → **Deploy static site to Pages** → **Run workflow** 手動跑一次；之後每次 **push `main`** 會自動佈署。
5. **開啟 Dashboard**  
   網址：**`https://rtkmick.github.io/RB-Stock-Analysis_V3/`**  
   之後只要 push 更新 `data/`，等 Actions **build + deploy 綠燈**後重新整理頁面即可看到最新數據。

**不需要**執行 `ngrok http ...` 或 `python rb_tv_app.py`。  
若需要即時對外網址或 TradingView webhook，再使用 `bat/1_ngrok_http.bat` 與 `bat/2_start_flask_rb.bat`。

**Git 遠端**：若本機仍設定已刪除的 `origin`（`runbordev111/RB-stock-analysis`），可只保留 **`rtkmick`**：`git remote remove origin`（若不需要該別名）。

### GitHub Pages：網頁版號仍舊、但 `main` 已是新版？

- **先比對兩個網址**：`https://raw.githubusercontent.com/RTKmick/RB-Stock-Analysis_V3/main/Version.txt`（應為新版）與 `https://rtkmick.github.io/RB-Stock-Analysis_V3/Version.txt`（若仍舊＝**線上站沒成功佈署**）。
- **本倉請用「GitHub Actions」當 Pages 來源**：**Settings → Pages → Source → GitHub Actions**，並選 **`.github/workflows/deploy-static-pages.yml`**。自訂 workflow 會 **build（組 `_site`）→ deploy**，且 **不整包複製 `data/`**（見該 YAML）。**push `main` 會觸發佈署**；亦可 **Actions → Run workflow** 手動跑一次。
- 若 Pages 仍設為 **Deploy from a branch**：GitHub 會跑內建 **「pages build and deployment」**，在本倉庫常 **failure**，失敗時 **`github.io` 不會更新**（例如卡在 **V2.0.11**）。此情況無法只靠改本倉 YAML 修好，請改為上一步的 **Actions 來源**。
- Actions 裡 **`report-build-status` 打勾** 只代表「回報狀態」那一步成功；若 **`build` 失敗**，**`deploy` 會被跳過**，`https://<user>.github.io/<repo>/` 就不會更新。
- **`data/cache/`**、**`data/models/`**、**`data/signal_vs_returns_figures/`** 等勿提交到 Git（見 **`.gitignore`**），以免 Pages／clone 負擔過大。

---

### 資料分層：GitHub 放什麼、CSV 放哪、前端怎麼讀、長期歸檔

對齊「**程式與展示在 GitHub；大量原始資料不要塞進同一個 repo**」的做法，建議心照四層：

| 層級 | 建議放什麼 | 本專案對應 |
|------|------------|------------|
| **1. GitHub Repo** | Python、`index.html`／`dashboard.html`、儀表板用**小型 JSON**、設定與說明 | `core/`、`*.html`、`Version.txt`、`data/manifest.json`、`data/*_whale_track.json`、`signal_stats.json`、`market_context.json` 等 |
| **2. 大檔／歷史 CSV** | 分點快取、長期匯出、回測 raw | **`data/cache/`**、歷史 CSV → **Google Drive**（或本機），以 **`scripts/sync_data_from_gdrive.py`** 拉回再跑 pipeline |
| **3. 前端讀取** | GitHub Pages **只穩定讀小 JSON**（不要讓瀏覽器直接 fetch Drive CSV） | 儀表板 `fetch('data/...json')`；部署見 **`.github/workflows/deploy-static-pages.yml`**（精簡 `data/`） |
| **4. 長期歸檔** | 備份、換機、稽核 | Drive 資料夾分區（raw／processed／reports）；進階再考慮 **GCS / BigQuery** 等 |

**`.gitignore` 原則**：已忽略 `data/cache/`、`data/models/`、`data/raw/` 等目錄，以及 **`data/*.csv` 預設不提交**，但**保留** `*_boss_list.csv` 與 `broker_master_enriched.csv` 可進版控（小表）。**`rawdata/`** 內公司／券商主檔**不**套用全 repo 的 `*.csv` 規則，避免誤擋。

若大檔曾經進過 Git **歷史**，僅改 `.gitignore` 無法縮小遠端體積，需另做 **`git filter-repo` / BFG**（請自行備份後操作）。

### Google Drive 大檔（CSV 等）外置備份（可選）

若不想把大量 CSV／快取放進 GitHub，可上傳到 **Google Drive 共用資料夾**（須設為「**知道連結的使用者可檢視**」），本機再用腳本拉回專案目錄後，**`scraper_chip.py` 仍讀本機 `data/cache/tdr/...`**（與原本一致）。

- **範例資料夾**（請自行確認共用權限）：[RB-Stock-Analysis_V3_Data](https://drive.google.com/drive/u/0/folders/1L9H-Suhii63Zur1Md0FbUtA65a5n9UM4)
- **依賴**：`pip install -r requirements.txt`（內含 **`gdown`**）
- **`.env`（擇一）**  
  - `RB_GDRIVE_DATA_FOLDER_ID=1L9H-Suhii63Zur1Md0FbUtA65a5n9UM4`  
  - 或 `RB_GDRIVE_DATA_FOLDER_URL=https://drive.google.com/drive/folders/1L9H-Suhii63Zur1Md0FbUtA65a5n9UM4`
- **下載到本機**（專案根目錄執行）：

```bash
python scripts/sync_data_from_gdrive.py --output data/cache/tdr
```

若 Drive 內層級與本專 **`data/cache/tdr/<股號>/<日期>.csv`** 一致，可直接用 `--output data/cache/tdr`；否則先下載到預設 **`data/_gdrive_sync`** 再手動整理。

**說明**：FinMind 分點快取仍以**本機路徑**讀寫較穩；Drive 適合備份／換機還原，不建議在每次 `scraper_chip` 內自動連線 Drive（延遲與配額）。

---

### 一、分層架構總覽

- **資料抓取與分析層**
  - `scraper_chip.py`：從 FinMind 抓分點 & 價格，呼叫 `core.pipeline.analyze_whale_trajectory`，輸出：
    - `./data/{stock_id}_whale_track.json`（dashboard 使用）
    - `./data/{stock_id}_boss_list.csv`（Top20 大戶彙總表）
  - `core/services/`：流程與服務
    - `core/pipeline.py`：主流程 orchestrator，串接各種 signals 模組與 I/O。
    - `core/services/adapter_tw.py`：台股專用 adapter，封裝 FinMindClient 的操作（交易日、日 K、分點日報等）。
  - `core/signals/`：所有純「訊號/指標」計算
    - `whale.py`：主力集中度/廣度/Top15/外本淨額/主力趨勢分數等。
    - `whale_extras.py`：Turning Points + Whale Radar。
    - `enhanced.py`：coherence / cost zone / streak_strength 等進階統計。
    - `tv.py`：TradingView 風格技術指標與 `tv_score/tv_grade`。
    - `regime.py`：長期 regime 分類（多頭/空頭/盤整/轉折）。
    - `validation.py` / `risk.py`：價格突破驗證、ATR% / 成交值 / 失效條件。
    - `geo.py`：Geo TopN + baseline + zscore + grade/tag。
    - `distribution.py`：HHI / Entropy + 派發風險（Distribution risk）。
    - `monitor.py`：Whale Trend Monitor 五態（ACCUMULATION / MARKUP / FADING / DISTRIBUTION / NEUTRAL）。
  - `core/io/`：外部資料來源與檔案 I/O
    - `finmind_client.py`：FinMind v4 API client（含 retry/log）。
    - `price_data.py`：抓 OHLCV（近 20 日/長期日 K）。
    - `broker_master.py`：讀券商主檔（xlsx/csv），輸出 `broker_id -> meta`。
  - 其它核心：
    - `core/aggregate.py`：主力分數 + regime 分數 + geo_adjust → `final_score/final_grade`。
    - `core/geo_utils.py`：HQ–券商距離與 TopN geo 計算。
    - `core/types.py` / `core/config.py`：TypedDict + 各種 config（PipelineConfig 等）。

- **Web 與視覺化層**
  - **靜態 Dashboard（推薦，不需本機伺服器）**  
    - `index.html`：單頁靜態儀表板，直接讀取 `data/*_whale_track.json` 與 `data/manifest.json`。  
    - 部署方式：將專案 push 到 **[RTKmick/RB-Stock-Analysis_V3](https://github.com/RTKmick/RB-Stock-Analysis_V3)** 的 **`main`**，**GitHub Pages** 請設為 **Source: GitHub Actions** 並使用 **`deploy-static-pages.yml`**（見上方「快速開始」步驟 4），即可在 **`https://rtkmick.github.io/RB-Stock-Analysis_V3/`** 查看。**不需 ngrok、不需執行 Flask**；本地跑 scraper、push 後等 Actions **deploy** 完成再重新整理即可看到最新數據。
  - `rb_tv_app.py`（Flask，可選）：
    - `/dashboard/`：讀取 `*_whale_track.json` + 券商 master，完整版儀表板。
    - `/webhook`：串 TradingView 訊號 + TWSE T86，Telegram 推播。
  - `templates/dashboard.html`：Flask 版 Bootstrap + Chart.js 儀表板。

- **資料與輔助腳本層**
  - `rawdata/`：公司清單、券商 master、geocode cache 等來源資料。
  - `data/`：pipeline 輸出（JSON/CSV）；`data/manifest.json` 由 scraper 自動更新，供靜態 dashboard 股票清單使用。
  - `sub-py/`：更新券商主檔、geocode、`build_manifest.py`、**`analyze_signal_vs_returns.py`（Phase 1）**、**`ml_signal_winrate.py`（Phase 3 ML 勝率）** 等。
  - `bat/`：scraper、下載專案、Phase 1 / Phase 3 分析；可選：ngrok、Flask。
  - **`send_daily_report.py`（Phase 6）**：讀 `data/*_whale_track.json` + `market_context.json`，組成純文字日報；若已設定 **`TELEGRAM_BOT_TOKEN`**、**`TELEGRAM_CHAT_ID`**（與 `rb_tv_app.py` 相同，建議寫在 `.env`）則推送到 Telegram。未設定時僅列印摘要。`5_run_all_for_stock.bat` 在產生 `market_context.json` 後會自動呼叫一次。
  - **`5_run_all_for_stock.bat`**：預設追蹤 8 檔（2454、2486、3035、2330、2603、3661、2345、6547）；直接按 Enter 即跑清單內全部股票；個股 FinMind 跑完後會執行 **`[1b] generate_cross_stock.py`** 更新 `data/cross_stock_flow.json`。


### 建議流程（摘要）

- **只顯示數據**：見上方「快速開始」→ 本機跑 scraper → push → 開 GitHub Pages → 用 `index.html` 靜態 dashboard 看數據。
- **需要即時對外或 webhook**：再使用 `bat/1_ngrok_http.bat`、`bat/2_start_flask_rb.bat`。

### Phase 1：把 Signal vs 未來報酬看清楚

1. 先產生 backtest 樣本（需 FinMind token）：  
   `python sub-py/backtest_signals_60d.py --stock_ids 2338 --days 60 --horizons 5,10,20`
2. 再執行 Phase 1 分析：  
   `python sub-py/analyze_signal_vs_returns.py`  
   可選流動性與交叉表參數（建議正式報告時開啟）：  
   `python sub-py/analyze_signal_vs_returns.py --min-avg-volume-20d-lot 500 --liquidity-drop-bottom-pct 0.05 --min-score-state-n 8`  
   （`avg_volume_20d_lot` 需由新版 `backtest_signals_60d.py` 寫入 CSV；舊檔僅會顯示提示並略過張數濾網。）  
   或雙擊 `bat/4_analyze_signal_vs_returns.bat`
3. 開啟 `data/signal_vs_returns_report.html` 檢視：Score 區間 / Monitor state 的未來 5/10/20 日報酬統計與分佈圖，據此調整策略門檻。

### Phase 2：一眼看盤（大戶儀表板）

- 開啟 **`dashboard.html`**（與 `index.html` 同層，GitHub Pages 根路徑即可）。  
- 網址參數切股：`dashboard.html?stock=6239`（載入 `data/{id}_whale_track.json`）；頂部下拉選單會讀 `manifest.json` 並同步更新網址。  
- 內容：頂部 **chip_score／燈號／headline.summary**、融資／借券 **高壓警報徽章**（`margin_risk_flag` / `sbl_short_pressure_flag`）、**whale_layers** 三張分層卡、**Chart.js** Top6 累積軌跡、`headline.key_events` 清單。  
- 戰情室分頁列亦有 **「Phase 2 一眼看盤」** 連結。

### Phase 3：ML 勝率估計（整合）

從 `data/backtest_signals_60d.csv` 用 RandomForest 估計「訊號 → 未來報酬 > 0」的勝率，並產出模型與特徵重要度供後續 pipeline 或報表使用。

1. **一鍵流程（含 Phase 3）**：雙擊 `bat/5_run_all_for_stock.bat`，輸入股票代號與 lookback 天數，跑完會自動執行 Phase 1 + Phase 3。
2. **僅跑 Phase 3**（需先有 backtest CSV）：  
   `python sub-py/ml_signal_winrate.py --horizons 5,10,20`  
   或雙擊 `bat/7_phase3_ml_winrate.bat`
3. **產出**：
   - `data/models/ml_winrate_ret5d.pkl`、`ret10d`、`ret20d`：訓練好的模型
   - `data/ml_feature_importance_ret{N}d.csv`：特徵重要度排序
   - `data/ml_winrate_report_ret{N}d.html`：簡易 HTML 報表（accuracy / AUC / Top 30 特徵）

依賴：`pip install scikit-learn joblib`（已列入 `requirements.txt`）。

### Phase 9：大戶深層追蹤（V2.0.5 併入同一小版號）

版本策略：**以小版號逐步累積**（例如 V2.0.4 → V2.0.5），同一小版內可合併多項改動與文件更新，避免跳號（如直接跳到 V2.2.0）。

- **FinMind 資料流**：仍以 `scraper_chip.py` 為主（分點、價格、法人／融資等經 FinMind v4 API），寫入 `data/{stock_id}_whale_track.json` 與 `data/cache/tdr/{stock_id}/`。
- **R1 跨股資金流**：`generate_cross_stock.py` 掃描 `data/*_whale_track.json`，產出 **`data/cross_stock_flow.json`**（儀表板讀取「輪動」券商）。`5_run_all_for_stock.bat` 在個股 scraper 跑完後會自動執行 **`[1b]`** 此步驟。
- **R2 累積部位**：`core/phase9_deep.py` 依快取 CSV 彙總 Top6 分點之 **`accumulated_net` / `active_days`**（**股數加總÷1000**，與「10日/5日」欄位同口徑）。快取欄位為 **`securities_trader_id`** 時會對應為內部使用的 `broker_id`。
- **R3 籌碼沉澱率**：`signals["chip_settlement_rate"]`（Top6 淨額絕對值合計 ÷ 全市場買賣量合計，上限 1）。
- **靜態儀表板**：`index.html` 新增跨股區塊（讀 `cross_stock_flow.json`）；Top6 表可顯示累積淨額與沉澱率提示。

**本機只跑 FinMind 與跨股彙整（不跑 Phase 1/3 時）**：

```bash
python scraper_chip.py --stock_id 2330 --days 60
python generate_cross_stock.py
python sub-py/build_manifest.py
```

追蹤清單內 8 檔可於 PowerShell 迴圈執行，或雙擊 `5_run_all_for_stock.bat` 並對提示直接按 Enter（預設 8 檔、`days=60`）。

### Phase 10：大船轉向偵測（V2.0.6）

規格：`phase10_turning_signal_spec.md`（目標版號可與專案 `Version.txt` 分開標示）。

- **Bugfix（R2 單位）**：FinMind 分點 CSV 的 `buy`/`sell` 為**股數**；`accumulated_net` 與 Top6「10日/5日」一致改為 **股數加總後 ÷1000**（與 `core/signals_whale.py` 註解一致），避免累積欄位出現百萬級誤讀。
- **T1 動量時間線**：`core/phase10_turning.py` 自 `data/cache/tdr/{stock_id}/` 計算 Top6 各分點之 **5 日滾動淨額**（`momentum_rolling_5d`）、**轉向點**（`momentum_turn_point` / `momentum_turn_type`），並寫入 `signals.momentum_dates`；`core/pipeline.py` 於 Phase 9 之後呼叫。
- **T2 跨股歷史**：`generate_cross_stock.py` 產出 `cross_stock_flow.json` 後會 **`append_cross_flow_history()`**，累積至 **`data/cross_flow_history.json`**（同日不重複寫入，最多 60 筆）；前端可待資料累積後再擴充。
- **儀表板**：`index.html` Top6 表「**動量**」欄（SVG 迷你折線 + 轉向標示）；`phase10_review_v2_0_6.md` 建議之 **轉向掃描視窗延伸（近 30 根滾動索引）** 與 **📉／📈** 轉向文字。

### Phase 11：大戶異常走向偵測（V2.0.7）

規格：`phase11_anomaly_spec.md`。

- **T1 分點爆量／加速**：`core/phase11_anomaly.py` 之 `detect_volume_anomaly`，重用 `compute_whale_momentum_timeline` 的 **daily_net**（不重複讀檔）；寫入 `top6_details[].anomaly`（`z_score`、`is_spike`、`is_accelerating`、`severity` 等）。
- **T2 共振**：`signals["whale_resonance"]`（Top6 當日方向門檻 STRONG／MODERATE；fallback 用 **`net_1d`**）。
- **T3 量價背離**：`signals["pv_divergence"]`；`signals["price_change_pct"]` 由 **OHLCV 20 日** 最後兩根收盤計算；Top6 合計淨額用 **`net_1d`**（千張口徑）。
- **Pipeline**：`enrich_phase10_momentum` 之後呼叫 **`enrich_phase11_anomaly(..., ohlcv_20d=...)`**。
- **儀表板**：Top6「**異常**」欄（`buildAnomalyBadge`）；LED 區 **`getResonanceLED` / `getDivergenceLED`**。

### Phase 12：投信／外資鎖碼分數（V2.0.8）

規格：`phase12_lockup_spec.md`。

- **T1**：`core/phase12_lockup.py` 自 FinMind **`TaiwanStockInstitutionalInvestorsBuySell`**（`Investment_Trust` / `Foreign_Investor`）與 **`TaiwanStockShareholding.NumberOfSharesIssued`**、**OHLCV 20 日** 計算連買、買超／股本比、連買期漲幅，寫入 **`signals.lockup`**（`investment_trust`、`foreign`、`is_dual_lockup`）。
- **Pipeline**：`compute_institutional_and_margin_signals` 回傳 **`(signals_pack, inst_df)`**；於 **`enrich_phase11_anomaly`** 之後呼叫 **`enrich_phase12_lockup`**。
- **儀表板**：`index.html` 之 **`getLockupLED(sig.lockup)`**（雙鎖碼深紅 🔒🔒／🔒投信鎖／🔒外資鎖 LED）。

### Phase 13：隔日沖分點識別（V2.0.9）

規格：`phase13_dayhop_spec.md`。

- **T1**：`core/phase13_dayhop.py` 復用 **`compute_whale_momentum_timeline`** 之 60 日 **`daily_net`**（無額外 IO），計算 **`day_hop_score`**、`broker_type`（`DAY_HOPPER` / `SWING_TRADER` / `POSITION_HOLDER` / `UNKNOWN`），寫入 **`top6_details[].dayhop`**。
- **Pipeline**：於 **`enrich_phase12_lockup`** 之後呼叫 **`enrich_phase13_dayhop`**。
- **儀表板**：Top6 欄 **`buildBrokerTypeBadge(b.dayhop)`**（與異常徽章同欄）；Phase 12 LED 視覺依 R1 微調。

### Phase 14：過濾型共振／真主力共識（V2.0.10）

規格：`phase14_filtered_resonance_spec.md`。

- **T1**：`core/phase14_filtered_resonance.py` 排除 **`DAY_HOPPER`** 後，沿用 Phase 11 之方向判定（`anomaly.consecutive_direction` → **`net_1d` / `net_lot`**），寫入 **`signals.filtered_resonance`**（與 **`whale_resonance`** 並存）。
- **Pipeline**：於 **`enrich_phase13_dayhop`** 之後呼叫 **`enrich_phase14_filtered_resonance`**。
- **儀表板**：**`getFilteredResonanceLED(sig.filtered_resonance)`** 與 **`getResonanceLED`** 並排（深綠／深紅＋🛡）。

### Phase 15：訊號歷史追蹤（V2.0.11）

規格：`phase15_history_spec.md`。

- **T1**：`core/phase15_history.py` 之 **`append_signals_history`** 將每日最小 **`signals` 快照** append 至 **`data/{stock_id}_signals_history.json`**（同日覆寫、最多 **60** 筆）；**`get_signals_history`** 供後續 Phase 讀取。
- **Pipeline**：於 **Phase 14 之後**、**`whale_layers` 之前** 呼叫（**try/except**，失敗不阻擋主流程）；**`analyze_whale_trajectory`** 新增選用參數 **`stock_name`**，`scraper_chip.py` 傳入正確簡稱。
- **前端**：無變更（純後端／外部檔）。

### Phase 16：共識升級警報與 Dashboard 精簡（V2.0.12）

規格：`phase16_consensus_alert_and_cleanup_spec.md`。

- **T1**：`core/phase16_consensus_alert.py` 以 **`get_signals_history`** 比對今日 **`signals.filtered_resonance`** 與歷史中「非今日」最後一筆；寫入 **`signals.consensus_alert`**（無跳變為 `null`）；歷史快照欄位 **`count`／`total`／`label`** 與即時 **`consensus_count`／`non_dayhop_total`／`severity_label`** 皆支援。
- **Pipeline**：於 **Phase 15 `append_signals_history` 之後**、**`_build_whale_layers_phase0` 之前** 呼叫 **`enrich_phase16_consensus_alert`**（**try/except**，失敗時 **`consensus_alert`** 設為 **`null`**）。
- **前端**：**`getConsensusAlertLED`** 串在 **`getFilteredResonanceLED` 之後**；移除策略顧問面板與 **「TV 主力行為偵測」** 區塊；NetBuy 說明改為與 TV 無關之用語（後端 TV 欄位可仍保留於 JSON）。

### Phase 10 Review（文件）

- `phase10_review_v2_0_6.md`：與規格對照之驗收清單與工程觀察；程式調整已反映於 Phase 10～16 與 `index.html`。

---

python .\sub-py\backtest_signals_60d.py --stock_ids 2338 --days 60 --horizons 5,10,20