# VeriStockDB Project Handoff

產出日期：2026-06-06  
目前 repo：`D:\project\VeriStockDB`  
目前 HEAD：`201bf41` / `v0.3.3.1` / `main` / `origin/main`  
目前狀態重點：`v0.3.3.1` 已發布；交易日 TPEx 備援修改仍在未提交工作樹中，屬於進行中。

## 1. 專案目標

### VeriStockDB 要解決什麼問題

VeriStockDB 是台股資料的「真理資料庫」。核心目標是把官方資料用可稽核、可追蹤、可回復的方式入庫，供本地選股、回測、管理 PWA、排程與未來資料服務使用。

目前已成形的資料主軸：

- `daily_close`：上市上櫃每日收盤資料。
- `attention_notice`：上市上櫃注意股公告。
- `disposal_notice`：上市上櫃處置股公告。
- `trading_days`：交易日資料。
- `import_batches` / `import_errors` / `data_events`：批次狀態、錯誤與特殊事件記錄。

### 使用者需求

- 以本地 SQLite 為核心，優先確保資料正確、可查、可備份。
- 官方資料有問題時要顯示原因，不能安靜失敗。
- 批次狀態要能被 CLI / API / 未來 PWA 查詢。
- 日常更新要能透過 Ubuntu systemd 排程執行。
- 伺服器要有本機備份、冷資料封存、log、ops-check、Telegram 通知。
- 本地 API 是給真理資料庫管理與本地專案使用，不是公開雲端 API。
- 雲端專案與 VeriStockDB repo 分離；本 repo 只預留本地輸出與對接方向。

### 不可違反的架構限制

- 不要重新設計架構，應沿用既有文件：
  - `docs/human_first_rebuild_plan.md`
  - `docs/data_ingestion_global_policy.md`
  - `docs/local_truth_api_spec.md`
  - `docs/version_roadmap_checklist.md`
  - `docs/telegram_notification_spec.md`
- 不可把官方缺失資料憑空補成 `0`。
- Close 的 `--` / `---` / `----` 不是泛用缺值，必須依資料規則處理。
- 清洗器要 deterministic；重試要在 importer/service 外層處理。
- PWA 不可解析 CLI stdout；PWA/API 應吃 structured JSON / Core result。
- Local Truth API 目前以 read-only 為主，不提供任意 SQL 或 shell endpoint。
- token、DB、`data/`、`tmp/`、`logs/`、歷史 CSV、測試資料不應上傳 GitHub。
- `docs/新增功能規劃書.txt` 是使用者個人想法，不要自動追蹤。

### 已確認事實 / 推測 / 待確認事項

已確認：

- `git log` 顯示 HEAD 為 `201bf41 (tag: v0.3.3.1)`。
- `git status` 顯示有未提交修改：`CHANGELOG.md`、`README.md`、`config.py`、`docs/URL.txt`、`ingest/downloader.py`、`ingest/trading_calendar.py`。
- `.gitignore` 目前排除 `data/`、`tests/`、`tmp/`、`logs/`、DB、zip、Office 檔等。
- `python` 在目前 Codex PowerShell 裡不可用；使用內建 runtime Python 可跑測試。
- 2026-06-06 以內建 Python 執行 `python -m unittest discover -v`，結果 `Ran 95 tests ... OK`。

推測：

- 「Final Spec / Codex Spec / Claude implementation plan」在目前 repo 中最接近的落地文件是 `human_first_rebuild_plan`、`data_ingestion_global_policy`、`local_truth_api_spec`、`version_roadmap_checklist`。未找到明確名為 Claude implementation plan 的檔案。

待確認：

- 交易日 TPEx 備援修改是否要作為 `v0.3.3.2` 或併入下一版。
- 是否要讓 `tests/` 繼續不追蹤，或未來 public preview 前開放部分測試。
- Ubuntu server 是否已套用目前未提交的 TPEx 備援修改：尚未，因為未 commit / tag / push。
- 雲端 GCP / Google Drive 異地備份的實作細節在本 repo 外，需由 ops 文件或 server 實機補證據。

## 2. 目前完成狀態

### Git / release 狀態

已完成：

- `v0.3.0`：Local Truth API。
- `v0.3.1`：注意股公告。
- `v0.3.2`：處置股公告。
- `v0.3.3`：Telegram 任務通知。
- `v0.3.3.1`：Telegram 中文化與 patch release 收尾。

證據：

- `git log --oneline --decorate -12`
  - `201bf41 (HEAD -> main, tag: v0.3.3.1, origin/main) Finalize Telegram notification patch release`
  - `6819fb3 (tag: v0.3.3) Add Telegram task notifications`
  - `733d121 (tag: v0.3.2) Add disposal notice dataset`
  - `3374294 (tag: v0.3.1) Add attention notice dataset`
  - `fd944c3 (tag: v0.3.0) Add Local Truth API`

### CLI 基礎與 Close

已完成：

- 裸執行 `python main.py` 顯示說明與 quickstart，不再噴 argparse error。
- `init-db`、`import-close`、`update-close`、`import-close-local`、`rollback-close`、`status`、`query-close`、`audit-month`、`archive-month`、`finalize-close-months`、`backup` 已形成正式命令。
- Close CSV 官方下載檔名改為 `yyyymmddCloseSII.csv` / `yyyymmddCloseOTC.csv`。
- Close 對 `--` 前收補值與無前收排除會寫入 `data_events`。
- TPEX 7 開頭 4 碼普通股保留，權證型非目標資料排除。
- 三日回滾拆為 `rollback-close`，不綁在每日更新體感流程。

證據：

- `tests/test_cli.py` 測試涵蓋 no-args quickstart、update-close、rollback-close、status。
- `tests/test_close_validation.py` 測試 Close dash、TPEX 7 開頭、stock_id cleaning。
- `tests/test_importer.py` 測試 `data_events`、rollback、update、三次重試。
- 2026-06-06 測試結果：`Ran 95 tests ... OK`。

### 批次與特殊事件表

已完成：

- `db/schema.sql` 有 `import_batches`、`import_errors`、`data_events`。
- `import_batches` 使用 `dataset + market + period` 唯一範圍。
- `data_events` 記錄 Close 前收補值與冷啟動排除。

證據：

- `db/schema.sql`：
  - `CREATE TABLE IF NOT EXISTS import_batches`
  - `CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batches_scope`
  - `CREATE TABLE IF NOT EXISTS import_errors`
  - `CREATE TABLE IF NOT EXISTS data_events`
- `tests/test_schema.py`、`tests/test_importer.py` 通過。

### Ubuntu 私有部署與 ops-check

已完成：

- 支援環境變數設定 DB、CSV、archive、backup、log 路徑。
- `ops-check` 可檢查 DB、backup、archive、log、systemd timer。
- Ubuntu server 已有 `/opt/veristockdb/app` 與 `/var/log/veristockdb`。
- 冷資料/backup 使用 `/mnt/veristockdb-cold/veristockdb/...`。
- backup restore smoke test 曾通過。

證據：

- `config.py` 支援環境變數。
- `tests/test_config.py`、`tests/test_ops_check.py` 通過。
- 使用者提供 server 輸出：
  - `ops-check OK`
  - backup readable size 約 `1.1GiB`
  - `VERISTOCK_DB_PATH=/tmp/veristock_restore_test.db python3 main.py status` 顯示 `daily_close OK 10140 batches`
  - `systemctl list-timers 'veristockdb-*'` 顯示 update/rollback/backup/offsite timers。

### Local Truth API

已完成：

- FastAPI API scaffold 與 read-only endpoints。
- `/health`
- `/api/v1/info`
- `/api/v1/datasets`
- `/api/v1/datasets/{dataset}/status`
- `/api/v1/daily-close`
- `/api/v1/trading-days`
- `/api/v1/batches`
- `/api/v1/errors`
- `/api/v1/events`
- `/api/v1/ops/summary`
- 後續已加入 `/api/v1/attention-notices` 與 `/api/v1/disposal-notices`。

證據：

- `api/` 目錄存在：
  - `api/app.py`
  - `api/run.py`
  - `api/routes/daily_close.py`
  - `api/routes/attention_notices.py`
  - `api/routes/disposal_notices.py`
  - `api/routes/ops.py`
- 使用者 server 測試 3090：
  - `curl -H "Authorization: Bearer read-test" "http://127.0.0.1:8000/api/v1/daily-close?stock_id=3090&from=2026-05-28&to=2026-06-03&limit=5"`
  - 回傳 `ok: true` 與 3090 近幾筆資料。
- 2026-06-06 測試結果：API attention/disposal/close tests 均通過。

尚未驗證：

- 本次 handoff 沒有啟動 API server 做 live curl。
- `web/` 目前是未追蹤資料夾，不能視為正式 PWA。

### 注意股公告 `attention_notice`

已完成：

- 歷史匯入命令 `import-attention`。
- 官方更新命令 `update-attention`。
- 查詢命令 `query-attention`。
- API endpoint `/api/v1/attention-notices`。
- 主鍵含 `trade_date + market + stock_id`。
- 補上 `(trade_date, stock_id)` 查詢 index，支援回測常見不指定 market 查詢。

證據：

- commit/tag：`3374294` / `v0.3.1`。
- `db/schema.sql`：`CREATE TABLE IF NOT EXISTS attention_notices`。
- `ingest/attention_notice.py`。
- `api/routes/attention_notices.py`。
- 使用者本機匯入輸出：
  - `2001-01-02..2026-06-01 TWSE OK rows=53041 no_notice_rows=0 metadata_rows=2`
  - `2002-02-01..2026-06-01 TPEX OK rows=48206 no_notice_rows=121 metadata_rows=1`
  - `status --dataset attention_notice`: `OK 2 batches`
  - `query-attention --stock-id 2330` 與 `3090` 有資料。
- server 後續已完成更新與查詢，使用者回報「server完成」。
- 2026-06-06 測試結果：attention parser/import/API tests 通過。

### 處置股公告 `disposal_notice`

已完成：

- 歷史匯入命令 `import-disposal`。
- 官方更新命令 `update-disposal`。
- 查詢命令 `query-disposal`。
- API endpoint `/api/v1/disposal-notices`，支援 `active_date`。
- 欄位採用：
  - `trade_date`
  - `market`
  - `stock_id`
  - `stock_name`
  - `disposal_start_date`
  - `disposal_end_date`
  - `reason_text`
  - `disposal_text`
- 主鍵含 `trade_date + market + stock_id + disposal_start_date + disposal_end_date`。
- 補上 `(trade_date, stock_id)` 與 active 查詢 index。

證據：

- commit/tag：`733d121` / `v0.3.2`。
- `db/schema.sql`：`CREATE TABLE IF NOT EXISTS disposal_notices`。
- `ingest/disposal_notice.py`。
- `api/routes/disposal_notices.py`。
- server 匯入輸出：
  - `2001-01-02..2026-05-29 TWSE OK rows=3436 no_disposal_rows=0 metadata_rows=2`
  - `2003-09-01..2026-06-01 TPEX OK rows=4107 no_disposal_rows=147 metadata_rows=1`
  - `update-disposal` 更新到 `2026-06-05`，TWSE rows=63，TPEX rows=82。
  - `status --dataset disposal_notice`: `OK 4 batches`
  - `status --dataset disposal_notice --problems --details`: `No problem batches found.`
- `veristockdb-update-disposal.timer` 已在 server 設為每天 19:00，手動 start 後 log 顯示 already current。
- 2026-06-06 測試結果：disposal parser/import/API tests 通過。

### Telegram 通知

已完成：

- `notify-telegram --test` 與 `notify-telegram --message`。
- `update-close`、`rollback-close`、`update-attention`、`update-disposal`、`backup`、`ops-check` 可發送任務通知。
- 通知文字已中文化。
- Telegram 失敗非致命，不改變原任務 exit code。
- token/chat id 透過環境變數，不進 repo。

證據：

- commit/tag：`6819fb3` / `v0.3.3`。
- 中文化 commit：`2242cba`。
- patch release：`201bf41` / `v0.3.3.1`。
- `docs/telegram_notification_spec.md`。
- `tests/test_telegram_notifier.py` 與 CLI Telegram tests 通過。
- 使用者回報 Telegram 測試完成。

### 交易日 TPEx 備援

狀態：進行中，未提交，未發布。

已完成到本機工作樹：

- TWSE FMTQIK 若回傳空月資料，改用 TPEx tradingIndex 作備援。
- 若 TWSE 與 TPEx 都沒有可用資料，拋出明確錯誤，避免把交易日誤判為休市。
- 新增 TPEx URL：
  - `https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingIndex?date=YYYY%2FMM%2FDD&id=&response=json`
- 測試新增並通過：
  - `test_download_tpex_trading_days_json_decodes_official_json`
  - `test_parse_tpex_trading_index_open_dates_converts_roc_dates`
  - `test_ensure_trading_days_current_uses_tpex_fallback_when_twse_has_no_data`
  - `test_ensure_trading_days_current_raises_when_both_sources_have_no_data`

證據：

- `git diff --stat`：
  - `CHANGELOG.md`
  - `README.md`
  - `config.py`
  - `docs/URL.txt`
  - `ingest/downloader.py`
  - `ingest/trading_calendar.py`
  - 151 insertions / 15 deletions。
- 2026-06-06 測試結果：`Ran 95 tests in 4.284s OK`。

不可寫成已完成：

- 尚未 commit。
- 尚未 tag。
- 尚未 push。
- 尚未 server 部署驗證。
- 尚未確認 Telegram 在雙來源失敗時的實際通知內容。

## 3. 尚未完成項目

### P0：收斂交易日 TPEx 備援 patch

目的：避免 TWSE FMTQIK 回應慢或空資料時，`update-close` 把實際交易日誤判為休市。

涉及檔案：

- `config.py`
- `ingest/downloader.py`
- `ingest/trading_calendar.py`
- `README.md`
- `docs/URL.txt`
- `CHANGELOG.md`
- `tests/test_downloader.py`
- `tests/test_trading_calendar.py`
- `tests/test_importer.py`

預期做法：

- code review 目前 diff。
- 確認 `source` 值與 `trading_days.note` 是否符合文件。
- 跑 `python -m unittest discover -v`。
- commit / tag / push，例如 `v0.3.3.2` 或使用者指定版本。
- server pull/tag checkout 後跑 `update-close --to <today>` 與 `ops-check`。

風險：

- TPEx API 格式若改變，fallback 會失效。
- 測試在本機通過但 server 日期/時區或官方 API 行為可能不同。
- tests 目前被 `.gitignore` 排除，若不追蹤測試，GitHub 無法保留這次測試變更。

驗收標準：

- repo 無未提交功能差異。
- 全測試通過。
- server 更新後，`update-close` 不再因 TWSE 空資料把 6/3、6/4 類日期誤判休市。
- `status --problems --details` 無新增 problem batches。
- Telegram 若啟用，任務成功/失敗通知正常。

### P1：v0.3.4 三大法人資料

目的：加入舊專案已做過的三大法人資料，供未來回測與選股。

涉及檔案：

- `docs/URL.txt`
- `db/schema.sql`
- `ingest/`
- `api/routes/`
- `api/dataset_registry.py`
- `main.py`
- `README.md`
- `CHANGELOG.md`
- `tests/`

預期做法：

- 先 inspect 官方近幾日資料，不直接入庫。
- 和 PM 討論欄位。
- 按 close/attention/disposal pattern 做 parser、import、update、query、API。
- 寫 batch/error/event 規則。

風險：

- 法人資料欄位多，市場/自營商拆分規則可能造成 schema 反覆。
- 歷史資料格式可能分時期變動。

驗收標準：

- historical import 與 official update 都可跑。
- `status --dataset <dataset>` OK。
- query by date/stock_id 不指定 market 仍有效率。
- API endpoint 回 structured JSON。
- 全測試通過。

### P2：v0.3.5 資券資料

目的：加入融資融券資料。

風險與驗收：同三大法人，另需注意欄位單位與歷史格式。

### P3：v0.3.6 當沖資料

目的：加入當沖統計資料。

風險與驗收：同三大法人，另需注意現股/資券/交易類別欄位語意。

### P4：v0.3.7 月營收資料

目的：加入月營收資料。

風險：

- period 是 month，不是 trade_date。
- 公司代號可能與交易市場資料 join 需要額外規則。

驗收標準：

- `YYYY-MM` period 規格清楚。
- API/query 支援 stock_id 與月份範圍。

### P5：v0.3.8 Close 月資料對帳

目的：用官方月資料抽樣比對 Close 的 `close` 與 `volume`。

既有文件：

- `docs/close_monthly_reconciliation_backlog.md`

預期：

- 命令可叫 `reconcile-close-month` 或 `verify-close-month`。
- 預設樣本曾討論為 TWSE `0050`、`1101`，TPEX `5483`，但最後希望可自選股票。
- 差異標為 `RECHECK`。
- 不取代目前 `audit-month`，是另一個正式步驟。

驗收標準：

- 比對欄位只含 `close` / `volume`。
- mismatch 可追蹤、可查詢。
- 不混入現有封存 gate 的基本完整性檢查。

### P6：PWA 管理前端

目的：建立真理資料庫管理 PWA，不是雲端多用戶 PWA。

預期：

- 只走 Local Truth API。
- 不解析 CLI stdout。
- 中文 UI 在 API/PWA formatter 做。

驗收標準：

- 能看 DB/dataset/batch/error/event/ops 狀態。
- 能查 Close/注意/處置資料。
- 沒有直接 DB 讀寫。

## 4. 重要決策紀錄

### 已採用架構決策

- 使用本地 SQLite 作為真理資料庫核心。
- 使用 CLI 做人工可讀與日常操作。
- 使用 Local Truth API 做 PWA 與其他本地專案資料接口。
- 使用 `import_batches` 統一管理所有 dataset 批次狀態。
- 使用 `data_events` 記錄特殊資料處理，例如 Close dash 補前收與無前收排除。
- 注意/處置公告主資料表仍保留 `market`，但另建 `(trade_date, stock_id)` index，支援回測不指定 market。
- 官方下載前更新交易日，避免休市日反覆下載。
- 三日回滾獨立為 `rollback-close`，適合半夜排程，不綁每日更新。
- Ubuntu 主 DB 與未封存資料放主硬碟；archive/backup 放冷資料 SSD。
- Telegram 通知只做更新後訊息通知，手機控制 server 為未來預留。

### 為什麼這樣做

- 使用者偏好人本、可查、可恢復，不偏向大型平台化。
- 台股官方資料格式會變，必須靠 batch/error/event 保留審核與修復線索。
- PWA 若解析 CLI 文字會讓中文化與 API contract 互相污染。
- 雲端 VPS 只適合輕量 JSON/API，不適合放真理 DB 與重運算。

### Frozen decisions

不應重新討論或推翻：

- PWA 不解析 CLI stdout。
- Local Truth API 與雲端 Edge API 分離。
- 本 repo 不實作雲端多用戶 PWA / Edge API。
- Close `--` 不可補 `0`。
- 官方缺失 numeric 不可猜。
- `data/`、DB、token、CSV、tmp、logs 不上傳 GitHub。
- 月資料對帳獨立於 `audit-month`。
- 注意/處置先存公告原文，不先解析條款。
- Telegram token 只走環境變數。

## 5. 注意事項與坑

### 曾經出錯的地方

- `python main.py` 裸執行曾因 argparse required subcommand 直接 error，已修。
- 官方 SSL 曾出現 `CERTIFICATE_VERIFY_FAILED Missing Subject Key Identifier`，後續已處理為可下載。
- TPEX 權證/非普通股代號曾導致 `UNEXPECTED_SECURITY_ID`，後續規則改為只排除不該入庫者。
- 2004 初期 Close `--` 無前收，不能補 `0`；應補前收或排除並記錄事件。
- `update-close` 15:30 遇 TWSE FMTQIK 回應慢/空資料，曾把後續日期當成無交易日；TPEx 備援 patch 正在處理。
- server 執行 `python main.py` 前要 `cd /opt/veristockdb/app`，否則會找不到 `main.py`。
- Windows `ssh user@example-host` 可能因 hostname 無法解析，需要使用實際 IP、ZeroTier IP 或設定 hosts。
- `python -m api.run` 若直接回到 prompt，代表 server 沒保持運行；API 測試需在另一個 terminal 保持 server。
- `update-disposal --no-cooldowncurl` 是把兩個命令黏在一起，會被 argparse 視為錯誤參數。

### 不要再做的事

- 不要把 `--` 手動改 `0`。
- 不要全域補股票代號前導零。
- 不要在官方資料缺欄時安靜跳過。
- 不要讓 PWA 呼叫 CLI 或解析 stdout。
- 不要把雲端 Edge API 寫進此 repo 後上傳 GitHub。
- 不要 stage 未追蹤的大型資料檔、CSV、xls/xlsb、tmp、legacy scratch。
- 不要重置或刪除使用者未追蹤檔案。

### 特別小心的路徑

- 本機 DB：`data/db/veristock.db`，被 `.gitignore` 排除。
- server DB：`/opt/veristockdb/app/data/db/veristock.db`。
- server logs：`/var/log/veristockdb`。
- server cold archive：`/mnt/veristockdb-cold/veristockdb/archive`。
- server backup：`/mnt/veristockdb-cold/veristockdb/backup/veristock_latest_backup.db`。
- 歷史 CSV samples：`tmp/...`，不應上傳 GitHub。
- 未追蹤 legacy/reference：`app.py`、`cleaner.py`、`db_manager.py`、`spider_engine.py` 等，待確認用途。

## 6. 專案檔案地圖

### 重要目錄與檔案

- `main.py`：CLI entrypoint。
- `config.py`：版本、路徑、URL、環境變數。
- `db/schema.sql`：SQLite schema 與 indexes。
- `db/connection.py`：DB 連線。
- `ingest/close_importer.py`：Close 匯入/更新/回滾核心。
- `ingest/attention_notice.py`：注意股公告 parser/import/update。
- `ingest/disposal_notice.py`：處置股公告 parser/import/update。
- `ingest/downloader.py`：官方下載 URL 與下載函式。
- `ingest/trading_calendar.py`：交易日更新。
- `api/`：FastAPI Local Truth API。
- `ops/`：ops check / Telegram / deployment helper，具體檔案請以 repo 現況確認。
- `docs/`：規格、部署、roadmap、URL。
- `requirements.txt`：FastAPI / uvicorn。
- `.gitignore`：資料與測試排除規則。

### 可以改的檔案

- 需求相關功能檔案：`ingest/`、`api/`、`main.py`、`config.py`、`db/schema.sql`。
- 對應文件：`README.md`、`CHANGELOG.md`、`docs/*.md`、`docs/URL.txt`。
- 測試：`tests/`，但目前 `.gitignore` 排除，若要上傳需先由 PM 決定。

### 不要碰或改前要確認

- `data/`
- `tmp/`
- `logs/`
- 大型 Office/CSV/archive 檔。
- 未追蹤 legacy 檔案。
- `docs/新增功能規劃書.txt`。
- server `/etc/veristockdb/veristockdb.env` 中的 token/chat id，不要貼進 repo。

### 修改前需要備份

- `data/db/veristock.db`
- server DB。
- server backup/archive 目錄設定。
- schema migration 前的 DB。

## 7. 測試與驗收方式

### 安裝

Windows / local：

```powershell
cd D:\project\VeriStockDB
py -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Ubuntu / server：

```bash
cd /opt/veristockdb/app
. .venv/bin/activate
pip install -r requirements.txt
set -a
. /etc/veristockdb/veristockdb.env
set +a
```

待確認：不同環境可能沒有 `python` alias；目前 Codex shell 需用內建 runtime Python。

### 啟動 CLI

```powershell
python main.py
python main.py status
python main.py update-close
python main.py rollback-close
python main.py update-attention
python main.py update-disposal
python main.py ops-check
```

### 啟動 API

```powershell
python -m api.run
```

查詢範例：

```powershell
curl -H "Authorization: Bearer read-test" "http://127.0.0.1:8000/api/v1/daily-close?stock_id=3090&limit=5"
```

### 執行 pytest / unittest

目前 repo 沒有 pytest 設定，主要使用 unittest：

```powershell
python -m unittest discover -v
```

本次 Codex 環境實際可用命令：

```powershell
& 'C:\Users\time7\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -v
```

已知測試結果：

- 2026-06-06：`Ran 95 tests in 4.284s`，`OK`。
- 直接執行 `python -m unittest discover -v` 在目前 Codex shell 失敗，原因是 `python` command not found。

### 驗證 DB / pipeline

```powershell
python main.py init-db
python main.py status
python main.py status --problems --details
python main.py query-close --stock-id 2330 --from 2026-05-01 --to 2026-06-05
python main.py query-attention --from 2026-06-01 --to 2026-06-05 --limit 5
python main.py query-disposal --from 2026-06-01 --to 2026-06-05 --limit 5
```

### 驗證 scheduler

Ubuntu：

```bash
systemctl list-timers 'veristockdb-*' --all
systemctl is-enabled veristockdb-update-close.timer
systemctl is-enabled veristockdb-rollback-close.timer
systemctl is-enabled veristockdb-backup.timer
tail -n 80 /var/log/veristockdb/update-close.log
tail -n 80 /var/log/veristockdb/rollback-close.log
tail -n 80 /var/log/veristockdb/backup.log
```

### 驗證 backup restore

```bash
cd /opt/veristockdb/app
cp /mnt/veristockdb-cold/veristockdb/backup/veristock_latest_backup.db /tmp/veristock_restore_test.db
VERISTOCK_DB_PATH=/tmp/veristock_restore_test.db python3 main.py status
rm /tmp/veristock_restore_test.db
```

已知 server 證據：

- 使用者曾執行 restore test，`daily_close OK 10140 batches`。

### 驗證 Telegram

```bash
python3 main.py notify-telegram --test
python3 main.py notify-telegram --message "VeriStockDB test message"
```

### 驗證 web app / PWA

目前尚未完成 PWA。`web/` 是未追蹤目錄，不能視為正式交付。Local API 可作為未來 PWA 的資料來源。

## 8. 參考文件

- `README.md`：使用者 quickstart、CLI/API/部署概要。
- `CHANGELOG.md`：版本變更紀錄；目前有未提交 Unreleased fallback section。
- `docs/human_first_rebuild_plan.md`：人本重建方向，架構上限與資料安全精神。
- `docs/data_ingestion_global_policy.md`：所有官方資料 ingestion 的不可違反政策。
- `docs/local_truth_api_spec.md`：Local Truth API contract、PWA/CLI 邊界、read-only API 設計。
- `docs/pwa_cli_i18n_boundary_note.md`：PWA 與 CLI 中文顯示責任分離。
- `docs/close_monthly_reconciliation_backlog.md`：Close 月資料對帳 backlog。
- `docs/telegram_notification_spec.md`：Telegram 通知規格。
- `docs/ubuntu_private_deployment.md`：Ubuntu 私有部署與 systemd。
- `docs/ubuntu_private_deployment_status.md`：部署驗證紀錄。
- `docs/version_roadmap_checklist.md`：版本切法與下一步順序。
- `docs/URL.txt`：官方資料 URL 清單。
- `db/schema.sql`：資料表與 index contract。
- `.gitignore`：不可上傳資料邊界。
- 官方 TWSE FMTQIK：`https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=YYYYMMDD&response=json`
- 官方 TPEx tradingIndex：`https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingIndex?date=YYYY%2FMM%2FDD&id=&response=json`

待確認：

- 明確名為 Final Spec / Codex Spec / Claude implementation plan 的檔案路徑。

## 9. 對 PM 對話的建議

### 拆工方式

1. 先收斂目前未提交 TPEx trading calendar fallback。
2. 再進入 `v0.3.4` 三大法人。
3. 每個新 dataset 都先做 sample inspection，不直接入庫。
4. 每個 dataset 分成欄位決策、schema/import/query/API、official update、server deployment 四段。

### Worker 應收到的上下文

交易日 fallback worker：

- 目前 `git diff --stat`。
- TPEx URL 格式。
- 先前問題：TWSE 空月資料不可當休市。
- 驗收：unittest 95 OK、server update-close 實測。

新 dataset worker：

- `docs/data_ingestion_global_policy.md`
- `docs/version_roadmap_checklist.md`
- `db/schema.sql`
- `ingest/attention_notice.py`
- `ingest/disposal_notice.py`
- `api/routes/attention_notices.py`
- `api/routes/disposal_notices.py`
- PM 已決定欄位前不要建 schema。

ops worker：

- server 路徑 `/opt/veristockdb/app`、`/var/log/veristockdb`、`/mnt/veristockdb-cold/veristockdb/...`。
- `docs/ubuntu_private_deployment.md`
- `ops-check` output。
- timers 與 logs。

PWA worker：

- `docs/local_truth_api_spec.md`
- `docs/pwa_cli_i18n_boundary_note.md`
- Local Truth API only，不碰雲端 Edge API。

### PM 應如何審核完成度

- 不接受「我做完了」但沒有 command output。
- 每個功能至少要有：
  - modified files
  - CLI/API command
  - test result
  - batch/status result
  - README/CHANGELOG/doc 更新
- 若涉及 server，必須有 server command output。
- 若涉及資料入庫，必須有 `status --dataset ... --problems --details`。
- 若涉及官方下載，必須有 cooldown / retry / failure reason 的可見輸出。

## 10. 專案記憶清單

### 已確認

- 使用者偏好簡單、人本、可稽核，不要工程過度複雜。
- API spec/contract first，datasets next，PWA later。
- PWA 不解析 CLI stdout。
- Close dash 不補 `0`。
- 錯誤資料要 block / recheck，不安靜吞掉。
- Telegram 失敗不應使原任務失敗。
- 注意/處置公告先保存原文，不解析條款。
- server 使用主硬碟放 app/DB，冷資料 SSD 放 archive/backup。
- `data/`、`tests/`、`tmp/`、`logs/` 不上傳 GitHub。

### 推測

- `v0.3.4` 會做三大法人，因為 roadmap 寫定且使用者已確認順序。
- 交易日 fallback patch 下一步可能是 patch release，但版本號待 PM 指示。

### 待確認

- 是否追蹤 `tests/`。
- 是否建立正式 migration 機制，或繼續以 `init-db` / schema idempotent 管理。
- 雲端 Edge API 的 export contract 何時開始。
- 未追蹤 `web/` 與 legacy 檔案用途。
