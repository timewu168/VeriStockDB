# 版本紀錄

## v0.5.2 - 2026-07-01

### 新增

- 新增 PWA「手動更新」專頁，可查看近期 job 歷史。
- 新增儀表板近期 job 摘要卡片。
- 新增從 job 列點擊開啟詳細抽屜的互動。
- 新增 jobs list/detail 與 PWA 查詢表格契約的 route-level smoke 測試。

### 變更

- PWA 會標示失敗 job，並顯示錯誤摘要。
- 更新 PWA service worker cache，確保靜態資源刷新。

### 驗證

- 單元測試通過：107 tests OK。
- `node --check web/app.js` 通過。
- Python compile check 通過。
- Diff whitespace check 通過。

## v0.5.1 - 2026-07-01

### 新增

- 新增 `ops_jobs` 營運資料表，用於保存 PWA 手動更新 job。
- 新增 `/api/v1/jobs` 與 `/api/v1/jobs/{job_id}` 的持久化 job list/detail 行為。
- 新增 PWA job 詳細資訊顯示：messages、stdout tail、stderr tail、return code、error message。
- 新增查詢結果表格輸出與中文欄位標題。
- 新增查詢 limit/offset 輸入，預設 limit 為 `10000`。
- 新增 OS 依賴文件：`sqlite3`、`nodejs`、`npm`。

### 變更

- 手動更新 jobs 現在可跨 API 重啟保存。
- API 重啟前未完成的 jobs 會標記為 `FAILED`。
- PWA 顯示 Close 價格欄位時，將 API cent values 除以 `100` 顯示為新台幣；DB/API 儲存仍維持 integer cents。

### 驗證

- 使用者已驗證手動更新可建立 job。
- 使用者已驗證 API 重啟後 `/api/v1/jobs` 仍可看到歷史 jobs。
- 單元測試通過：105 tests OK。
- `node --check web/app.js` 通過。
- Python compile check 通過。
- Diff whitespace check 通過。

## v0.5.0 - 2026-07-01

### 新增

- 新增 Local Management PWA，位於 `web/`，由 FastAPI static mount 於 `/` 提供。
- 新增 PWA dashboard、dataset status、batches、errors/events、query、system views。
- 新增手動資料集更新按鈕，背後執行 allow-listed `main.py update-*` commands。
- 新增 job API endpoints：`POST /api/v1/jobs/update-dataset`、`GET /api/v1/jobs`、`GET /api/v1/jobs/{job_id}`。
- 新增 single-writer guard，確保同一時間只執行一個手動更新 job。
- 新增 PWA 使用的 dataset status summary endpoint。

### 變更

- FastAPI read-only SQLite connections 改用 `check_same_thread=False`，避免 threadpool 造成隨機 500/503。
- Dataset latest-period status 優先使用 canonical table max period，再 fallback 到 batch。

### 驗證

- 使用者已驗證 PWA 不再出現初始阻塞 modal，也不再出現隨機 dataset status errors。
- 平行 API smoke 測試 health、datasets、status summary、batches、errors、events、jobs 均回傳 200，且無 SQLite thread errors。
- 單元測試通過：104 tests OK。
- Python compile check 通過。
- Diff whitespace check 通過。

## v0.4.7 - 2026-07-01

### 變更

- 記錄當沖與月營收排程設定的已接受 production schedule 狀態。
- 更新 current-state handoff，反映當沖與月營收排程設定完成。

### 驗證

- 單元測試通過：97 tests OK，15 skipped。
- Python compile check 通過。
- Diff whitespace check 通過。
- Public/private path scan 通過。

## v0.4.6 - 2026-07-01

### 變更

- Dataset `latest_period` status 新增 canonical-table fallback，當資料集已有 accepted rows 但查詢 scope 無 `import_batches` rows 時仍能回傳最新期間。
- 月份型 dataset status filters 新增嚴格 `YYYY-MM` 驗證。

### 驗證

- `GET /api/v1/datasets/revenue/status?from=2026-05&to=2026-05` 回傳 `latest_period=2026-05`。
- `GET /api/v1/datasets/day_trading/status?from=2026-06-30&to=2026-06-30` 回傳 `latest_period=2026-06-30`。
- 專案 virtualenv 中 FastAPI route tests 通過：97 tests OK。
- System Python unit tests 通過：97 tests OK，15 skipped。
- Diff whitespace check 通過。

## v0.4.5 - 2026-07-01

### 新增

- 新增 `monthly_revenue` SQLite canonical table、parser、dry-run、protected execute import 與 `update-revenue`。
- 新增 `GET /api/v1/monthly-revenue`，支援月份區間、股票代號、市場、欄位選擇、品質與分頁 filters。
- 完成月營收歷史正式匯入，範圍 `2013-01` 至 `2026-05`。
- 新增當沖 canonical import/update/API 支援，並完成歷史匯入至 `2026-06-30`。

### 變更

- 更新 README 中的 dataset、CLI、API 與資料來源文件，加入當沖與月營收。

### 驗證

- 月營收正式匯入：`280,711` rows，duplicate keys `0`，required blanks `0`，SQLite integrity `ok`。
- 月營收 update smoke run：TWSE 與 TPEX 最新 market month 仍為 `2026-05`。
- 單元測試通過：95 tests OK，13 skipped。
- Diff whitespace check 通過。

## v0.4.4 - 2026-07-01

### 新增

- 新增當沖 CSV download、validation、parser、dry-run、formal import/update 與 read-only API 支援。
- 新增月營收 CSV download/import 基礎工作，供 `v0.4.5` final canonical API release 使用。

### 變更

- 擴充當沖與月營收 ETL 工作的文件與狀態追蹤。

### 驗證

- 當沖 historical import/update baseline 已接受至 `2026-06-30`。
- Diff whitespace check 通過。

## v0.4.3 - 2026-06-29

### 新增

- README 新增「Why This Matters」段落，說明 VeriStockDB 對台股官方分散資料建立 local、reproducible、validation-first canonical DB 的價值。
- 在公開 GitHub 建立 issues：parser regression fixtures、release workflow automation、repo hygiene scanning、canonical SQLite architecture documentation。

### 驗證

- GitHub repository 已公開，包含 README、MIT license、SECURITY、CONTRIBUTING、issue templates 與公開 issues。
- GitHub profile 可公開存取。
- 單元測試通過：73 tests OK，11 skipped。
- Python compile check 通過。
- Diff whitespace check 通過。

## v0.4.2 - 2026-06-29

### 新增

- 新增 MIT `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md`，補齊 public repository hygiene。
- 新增 GitHub issue templates：bug report 與 feature request。
- 新增 GitHub Actions CI，在 push 與 pull request 時執行 unit tests 與 Python compile checks。

### 驗證

- 單元測試通過：73 tests OK，11 skipped。
- Python compile check 通過。
- Diff whitespace check 通過。
- 新增 repository hygiene files 未包含 private deployment paths 或 secret markers。

## v0.4.1 - 2026-06-18

### 變更

- 將 README、CURRENT_STATE、deployment templates 與 public docs 內的私有部署路徑改為範例路徑，例如 `/opt/veristockdb/app`、`/var/log/veristockdb`、`/mnt/veristockdb-cold/veristockdb`。
- 將私有 systemd user/group 範例替換為通用 `veristock` service account。

### 驗證

- Public path scan 未發現 tracked private host paths 或 private service-account references。

## v0.4.0 - 2026-06-18

### 新增

- 將目前 Close、注意、處置、法人、資券、Local Truth API 與 scheduler baseline 標記為 public-preview release gate。

### 變更

- `update-legal` 與 `update-margin` 會依市場補齊到 target date 之前的內部開市交易日缺口，即使 `MAX(trade_date)` 已到 target。
- README、CURRENT_STATE 與 Local Truth API 文件已對齊 accepted production datasets、schedules、validation checks、locked actions 與 deferred datasets。

### 驗證

- 2026-06-18 SQLite health gate 通過：integrity `ok`、schema validation OK、duplicate keys `0`、Close/legal/margin formal date coverage gaps `0`、無 non-open trade-date rows、無近期 non-OK batches、最新 backup integrity checks OK。

## v0.3.8.4 - 2026-06-18

### 變更

- `GET /api/v1/errors` 新增嚴格 `from` / `to` 日期 filters，並同步 README API endpoint list。

## v0.3.8.3 - 2026-06-18

### 變更

- `update-legal` 與 `update-margin` 新增 Telegram task notifications，包含以正常 command exit code 回傳的 `BLOCKED` 結果。

## v0.3.8.2 - 2026-06-18

### 變更

- 法人、資券、注意與處置下載/匯入流程新增最多三次官方嘗試，包含 parser/validation failures。
- 注意/處置 update retry 時，import batches 會在 `retry_count` 記錄最後一次 official attempt。

## v0.3.8.1 - 2026-06-18

### 變更

- 強化 API 日期驗證，date query parameters 必須使用嚴格 `YYYY-MM-DD` 格式。
- `GET /api/v1/trading-days` 新增 `limit` 與 `offset` 分頁。

### 新增

- 新增 core API route tests，涵蓋 Close、注意公告、處置公告、交易日、batches、errors 與 events。

## v0.3.8.0 - 2026-06-18

### 新增

- 新增 `reconcile-close-month`，用 official TWSE/TPEX monthly stock JSON 對帳 `daily_close` 收盤價與成交量，不下載 CSV、不覆寫 canonical rows。
- 新增 TWSE/TPEX monthly stock JSON fetchers 與 parser tests，包含 TPEX monthly lot rounding tolerance 的成交量檢查。
- 新增 read-only Local Truth API endpoints：`legal_investors` 與 `margin_trading`，支援日期區間、股票代號、市場、欄位選擇、品質與分頁 filters。

## v0.3.5.1 - 2026-06-18

### 變更

- 修正處置公告 update horizon，讓 official range queries 在需要時能超過目前 DB 最新處置日期，以捕捉最新公告。

### 註記

- 官方處置 endpoint 可能回傳查詢日期仍在處置期間中的股票，而不只回傳該日發布的公告；update logic 已用延伸 query end date 處理此行為。

## v0.3.5.0 - 2026-06-18

### 新增

- 新增 canonical SQLite `margin_trading` schema 與 indexes。
- 新增資券 CSV download、inspection、validation、dry-run、formal import 與 update workflows。
- 新增 TPEX 資券 source normalization，採用已接受的 `balance` endpoint，自 `2008-09-30` 起算。
- 新增 read-only margin API：`GET /api/v1/margin-trading`。

### 註記

- TWSE 資券 canonical scope 自 `2001-01-02` 起。
- TPEX 資券 canonical scope 自 `2008-09-30` 起；較早下載檔保留但不接受進 canonical import。

## v0.3.4.0 - 2026-06-16

### 新增

- 新增 canonical SQLite `legal_investors` schema 與 indexes。
- 新增法人 CSV parsing、validation、reporting、dry-run、formal import 與 manual single-day update workflows。
- 新增歷史 TWSE/TPEX 法人回補支援，包含 legacy format normalization。
- `update-legal` 新增 idempotency safeguards，處理既有 rows、休市日與缺少 `daily_close` rows 的情況。
- 新增法人 unit coverage，涵蓋 parser formats、validation blockers、formal imports 與 update behavior。

### 註記

- 歷史法人 SQLite coverage 在 post-import integrity、duplicate-key、coverage 與 idempotency checks 後接受至 2026-06-15。
- `legal_investors` 儲存外陸資、投信、自營商自行買賣與自營商避險欄位；外資自營商與合計欄位刻意不儲存。
- 正式 systemd schedule target 為 `Mon..Fri 18:00`，透過 `veristockdb-update-legal.timer` 執行。

## v0.3.3.1 - 2026-06-05

### 變更

- Telegram task notification messages 中文化，同時保留 `OK`、`BLOCKED`、`RECHECK`、`MISSING`、`ERROR` 等 status codes。
- 官方交易日曆 refresh 在 TWSE FMTQIK 無法使用或無 open days 時，會 fallback 至 TPEx tradingIndex。
- 注意與處置更新改用 `trading_days` 跳過休市 target，避免週末排程讓 coverage 往前推進。
- 新增第一階段法人 CSV download 與 inspect commands，尚不入庫。

## v0.3.3 - 2026-06-05

### 新增

- 新增 Telegram notification settings：`VERISTOCK_TELEGRAM_*` environment variables。
- 新增 `notify-telegram --test` 與 `notify-telegram --message` CLI commands。
- `update-close`、`rollback-close`、`update-attention`、`update-disposal`、`backup` 新增自動 Telegram notifications。
- `ops-check` 的 `WARN` 與 `ERROR` abnormal 結果新增 Telegram notifications。
- 新增 `docs/telegram_notification_spec.md`，定義 v0.3.3 notification-only boundary 與未來 remote-control guardrails。

### 註記

- Telegram failures 只記錄為 warnings，不改變原始 task exit code。
- Tests 使用 mocked senders，不需要真實 Telegram token。

## v0.3.2 - 2026-06-05

### 新增

- 新增 `disposal_notices`，保存上市與上櫃處置公告資料。
- 新增 `inspect-disposal`、`import-disposal`、`update-disposal`、`query-disposal` CLI commands。
- 新增官方 TWSE 與 TPEx 處置公告 CSV downloads。
- 新增 `/api/v1/disposal-notices`，支援 date、stock ID、market、active-date、field、quality 與 pagination filters。
- 新增 `(trade_date, stock_id)` 與 active-period indexes，供處置公告 query/join workflows 使用。

### 註記

- 處置匯入保留官方 reason/condition text 與完整 disposal text，不將措施解析成 derived fields。
- 官方處置更新採用 upsert behavior，因為 official range queries 可能包含 requested range 之前發布但仍在處置期間的公告。
- 歷史 TWSE/TPEX edge cases，例如早期 stock names 空白、disposal text 空白、TPEX reason text 空白、official no-disposal rows，均在 import summaries 追蹤。

## v0.3.1 - 2026-06-05

### 新增

- 新增 `attention_notices`，保存上市與上櫃注意公告資料。
- 新增 `inspect-attention`、`import-attention`、`update-attention`、`query-attention` CLI commands。
- 新增官方 TWSE 與 TPEx 注意公告 CSV downloads。
- Close 與注意公告 query/join workflows 新增 `(trade_date, stock_id)` composite indexes。

### 註記

- 注意公告匯入保留官方 notice text 原文，股票代號維持與 Close 一致的 no-global-zero-padding policy。
- 歷史 CSV imports 與官方 updates 透過 `import_batches` dataset `attention_notice` 追蹤。

## v0.3.0 - 2026-06-04

### 新增

- 新增 Local Truth API read-only 初版，用於 local/private VeriStockDB access。
- 新增 FastAPI endpoints：health、app info、dataset status、daily Close、trading days、batches、import errors、data events、ops summary。
- 新增 API environment variables：host、port、optional Bearer-token auth，以及 read/ops/admin token levels。
- 新增 Local Truth API specification 與 version roadmap checklist documents。

### 註記

- Local Truth API 僅適用 localhost、ZeroTier、VPN 或可信任私有網路；不是 cloud/public Edge API。
- Cloud Edge API、cloud PWA、jobs、exports 保留為未來 private-project 或後續版本工作。

## v0.2.7 - 2026-06-04

### 新增

- 新增 `ops-check`，檢查 DB readability、backup readability、archive directory、logs 與 systemd timers 等部署健康狀態。
- 新增 `VERISTOCK_LOG_DIR`，讓 operational log checks 使用與 Ubuntu deployments 相同的路徑慣例。

## v0.2.6 - 2026-06-02

### 新增

- `rollback-close` 現在可省略 `--date`，自動使用最新匯入的 Close 日期。
- 新增 Ubuntu `systemd` service 與 timer templates：`update-close`、`rollback-close`、`backup`。

## v0.2.5 - 2026-06-02

### 新增

- 新增 `VERISTOCK_*` environment variables，支援私有 Ubuntu deployments 的 hot/cold storage paths 分離。
- Monthly archive ZIP output 現在可透過 `VERISTOCK_ARCHIVE_DIR` 指定，與 hot CSV storage 獨立。

## v0.2.4 - 2026-06-02

### 新增

- 新增 `update-close`，從最新匯入的 `daily_close` 日期起，更新每日官方 Close 至 today。
- `update-close --to YYYY-MM-DD` 可指定特定結束日期，用於 controlled catch-up runs。

## v0.2.3 - 2026-06-02

### 新增

- 官方 Close download 在下載 CSV 前，會先從 TWSE `FMTQIK` market-calendar API refresh 缺少的 `trading_days` rows。
- Trading-calendar refresh 會儲存 open days 與推斷的 closed days 至 requested/current date，讓休市日可略過而不必 probe Close CSV downloads。

## v0.2.2 - 2026-06-02

### 新增

- 新增 scoped historical monthly audit options：`audit-month --market`、`--from`、`--to`、`--skip-rollback`。
- 新增對應 scoped archive options：`archive-month --market`、`--from`、`--to`、`--dir`、`--skip-rollback`。
- 新增 `finalize-close-months`，可用單一 command audit 並 archive Close 月份範圍。
- Scoped audits 不再將 full-month archive audit setting 標為 OK，除非 audit 覆蓋 full month、both markets 與 rollback。

## v0.2.1 - 2026-06-02

### 新增

- 新增正式 `import-close-local` command，用於匯入本機歷史 Close CSV ranges。
- 本機 Close range imports 現在使用 trading calendar 推導 expected CSV files，當 trading-day file 不存在時記錄 `MISSING: LOCAL_CSV_NOT_FOUND`。

## v0.2.0 - 2026-06-02

### 新增

- 新增 human-friendly naked CLI help 與 quickstart output。
- 新增 `rollback-close`，讓三個交易日 Close rollback 可作為獨立 cross-day job 執行。
- 新增 `status --problems --details`，用於檢查 blocked、recheck 與 missing batches。
- 新增 shared sparse `data_events`，追蹤 row-level special handling。
- 新增 `DASH_FILLED_PREVIOUS_CLOSE` events，記錄 Close rows 中 dash OHLC 以 previous valid close 補值的情況。
- 新增 `ZERO_TRADE_DASH_EXCLUDED` events，記錄 first valid close 前早期 zero-trade dash OHLC rows 被排除的情況。

### 變更

- `import-close --date` 現在只匯入指定日期，不再自動執行 rollback。
- 官方 CSV 檔名改用 legacy date-first names：`yyyyMMddCloseSII.csv` 與 `yyyyMMddCloseOTC.csv`。
- 官方 downloader 使用已驗證的 non-strict SSL context，以相容 TWSE/TPEx certificates。
- Close stock-code validation 現在接受官方 alphanumeric IDs，例如 active ETF 與 bond-like IDs。
- TPEX 只在非四碼時排除 warrant-like `7`-prefix IDs。
- TPEX management sections、repeated headers、notes 與 summary rows 不再阻擋 parsing。
- Close dash OHLC handling 遵循文件化政策：可證明時由 previous close 補值、排除 early zero-trade cold-start rows、對 nonzero dash rows without previous close 標記 recheck。
- Batch attempt results 會逐次 official attempt commit，讓中斷的 imports 仍可在 status reports 中看見。

### Release Hygiene

- Public GitHub baseline 排除 local `data/`、`tests/`、`reference/`、caches、DB files、archives、logs 與 temporary outputs。
- Version constants 集中在 `config.py`。
