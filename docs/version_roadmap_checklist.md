# VeriStockDB 版本路線與檢查清單

狀態：已對齊 `v0.6.3` 實際完成範圍。

更新日期：2026-07-01

## 核心原則

VeriStockDB 的版本推進順序以「資料可信度」優先：

- SQLite canonical truth 先穩定。
- 每個資料集必須有下載、驗證、dry-run、正式入庫、API、排程或明確 deferred 狀態。
- API 與 PWA 必須使用結構化資料，不解析 CLI stdout。
- PWA 是本機資料健康檢查與手動補救工具，不是選股前台。
- 破壞性 DB 操作、schema migration、正式排程變更、ClickHouse 導入，都必須另行明確授權。

## 已完成版本總表

| 版本 | 主題 | 狀態 |
| --- | --- | --- |
| `v0.2.0` | Close CLI、rollback、status、data_events 基礎 | 完成 |
| `v0.2.1` | 本機歷史 Close 匯入 | 完成 |
| `v0.2.2` | Close 月稽核與封存範圍化 | 完成 |
| `v0.2.3` | 交易日補齊與休市略過 | 完成 |
| `v0.2.4` | `update-close` | 完成 |
| `v0.2.5` | Ubuntu 私有部署環境變數與冷熱儲存分離 | 完成 |
| `v0.2.6` | systemd templates 與 rollback 自動日期 | 完成 |
| `v0.2.7` | `ops-check` | 完成 |
| `v0.3.0` | Local Truth API read-only 基礎 | 完成 |
| `v0.3.1` | 注意股公告 | 完成 |
| `v0.3.2` | 處置股公告 | 完成 |
| `v0.3.3` | Telegram 更新通知 | 完成 |
| `v0.3.3.1` | 通知中文化、交易日 fallback、週末防呆 | 完成 |
| `v0.3.4.0` | 三大法人 canonical dataset | 完成 |
| `v0.3.5.0` | 資券 canonical dataset | 完成 |
| `v0.3.5.1` | 處置公告 update horizon 修正 | 完成 |
| `v0.3.8.0` | Close 月資料對帳與法人/資券 API | 完成 |
| `v0.3.8.1` | API 嚴格日期與核心 route tests | 完成 |
| `v0.3.8.2` | 法人/資券/注意/處置三次重試 | 完成 |
| `v0.3.8.3` | 法人/資券 Telegram 通知 | 完成 |
| `v0.3.8.4` | errors API 日期 filter | 完成 |
| `v0.4.0` | public-preview gate | 完成 |
| `v0.4.1` | public repo path polish | 完成 |
| `v0.4.2` | LICENSE、CONTRIBUTING、SECURITY、issue templates、CI | 完成 |
| `v0.4.3` | public README 說明與公開 issues | 完成 |
| `v0.4.4` | 當沖下載/驗證/入庫/API 基礎與月營收 groundwork | 完成 |
| `v0.4.5` | 當沖與月營收 canonical import/update/API | 完成 |
| `v0.4.6` | dataset latest-period canonical fallback | 完成 |
| `v0.4.7` | 當沖與月營收 production schedule 文件狀態 | 完成 |
| `v0.5.0` | Local Management PWA MVP 與手動更新 jobs API | 完成 |
| `v0.5.1` | `ops_jobs` 持久化、PWA 表格查詢、jobs detail | 完成 |
| `v0.5.2` | PWA 手動更新 job list、dashboard job 摘要、smoke tests | 完成 |
| `v0.6.0` | PWA 資料健康 drill-down | 完成 |
| `v0.6.1` | 排程健康報表 | 完成 |
| `v0.6.2` | 文件邊界整理 | 完成 |
| `v0.6.3` | 備份/還原演練文件 | 完成 |

## 目前已接受的 canonical datasets

| Dataset | SQLite table | Period | API | 更新命令 |
| --- | --- | --- | --- | --- |
| Close | `daily_close` | 日 | `/api/v1/daily-close` | `update-close` |
| 注意公告 | `attention_notices` | 日 | `/api/v1/attention-notices` | `update-attention` |
| 處置公告 | `disposal_notices` | 公告日/處置期間 | `/api/v1/disposal-notices` | `update-disposal` |
| 三大法人 | `legal_investors` | 日 | `/api/v1/legal-investors` | `update-legal` |
| 資券 | `margin_trading` | 日 | `/api/v1/margin-trading` | `update-margin` |
| 當沖 | `day_trading` | 日 | `/api/v1/day-trading` | `update-day-trading` |
| 月營收 | `monthly_revenue` | 月 | `/api/v1/monthly-revenue` | `update-revenue` |
| 交易日 | `trading_days` | 日 | `/api/v1/trading-days` | `backfill-trading-days` |

`ops_jobs` 是 PWA/manual-update 營運資料表，不是 canonical market data。

## v0.5.x 已完成範圍

- `web/` 本地管理 PWA 已由 FastAPI 掛載在 `/`。
- PWA 採暗色系，用於資料健康檢查與人工補救。
- PWA 查詢使用表格顯示，空股票代號代表查詢整段全股資料。
- Close 價格在 PWA 顯示層除以 `100`；API/DB 仍是 integer cents。
- 手動更新只透過 `/api/v1/jobs/update-dataset` 觸發 allow-listed `update-*` commands。
- 同一時間只允許一個 manual update job。
- jobs 持久化於 `ops_jobs`，API 重啟後仍可查詢歷史 job。
- PWA 不直接讀 SQLite、不解析 CLI stdout、不執行任意 shell command。

## 每版共同完成條件

每個功能版本完成前至少確認：

- [ ] 規格文件已更新。
- [ ] README / CHANGELOG 視需要更新。
- [ ] schema 變更已寫入 `db/schema.sql` 或明確 migration。
- [ ] 新資料集已接入 batch / error / event 管理。
- [ ] 失敗會留下可追查原因，不只顯示 `MISSING` 或 `BLOCKED`。
- [ ] API 行為有測試或 smoke 覆蓋。
- [ ] `python -m unittest discover -s tests` 通過。
- [ ] 相關 Python 檔案 compile check 通過。
- [ ] 前端變更需跑 `node --check web/app.js`。
- [ ] `git diff --check` 通過。
- [ ] 若改 public docs，需掃描私有路徑與 secret marker。
- [ ] commit 完成。
- [ ] 需要發版時 tag 完成。
- [ ] push 到 GitHub。
- [ ] 若影響 Ubuntu 部署，server 已套用並驗證。

## v0.6.x 收尾路線

`v0.6.x` 目標是把專案推到可長時間運行觀察的狀態。完成後不急著新增資料表，先觀察排程、官方格式、資料缺口與維護流程。

### v0.6.0：PWA 資料健康 drill-down

目標：讓 PWA 更快定位資料問題。

範圍：

- dataset status drill-down。
- 單一 dataset 的 latest period、quality、summary。
- 最近 `import_batches`。
- 問題批次：`BLOCKED`、`RECHECK`、`MISSING`。
- 最近 `import_errors` / `data_events`。
- 最近手動更新 jobs。

完成條件：

- [x] 只走 Local Truth API。
- [x] 不新增破壞性操作。
- [x] 補 API smoke test。
- [x] 更新 `docs/local_truth_api_spec.md`。

### v0.6.1：排程健康報表

目標：將目前靠人工確認的排程狀態整理成可查詢報表。

範圍：

- systemd timer enabled/active/last/next report。
- 最近排程 log tail marker 檢查。
- dataset latest/expected freshness 檢查。
- PWA 系統頁表格顯示。

Deferred：

- Telegram 通知漏發檢查先不做，後續若需要再補。

完成條件：

- [x] 不修改正式排程。
- [x] 不讀任意路徑，只讀設定允許的 log path。
- [x] CLI 有穩定輸出。
- [x] API 有穩定輸出。
- [x] PWA 系統頁可查看。
- [x] 補單元測試。

### v0.6.2：文件邊界整理

目標：降低開源後接手成本。

範圍：

- 整理 `docs/pm_handoff/` 與目前文件的邊界，避免舊 handoff 被誤用為現況。
- 補 `docs/README.md` 作為文件入口與判讀優先順序。
- 明確標示根目錄 `CHANGELOG.md` 是唯一正式版本紀錄。
- 明確標示 `CURRENT_STATE.md` 是下一輪接手唯一狀態摘要。

完成條件：

- [x] 根目錄 `CHANGELOG.md` 持續作為唯一 release history。
- [x] `CURRENT_STATE.md` 只保留下一輪接手必要狀態。
- [x] 舊 handoff 文件標示 archive，不作為現況來源。

### v0.6.3：備份/還原演練文件

目標：確保 DB 出問題時能依照 SOP 回復。

範圍：

- 停服務流程。
- 保留事故當下 DB。
- 指定 backup restore。
- `PRAGMA integrity_check` 驗證。
- row count / latest period smoke check。

完成條件：

- [x] 補 DB restore SOP。
- [x] 使用 `/tmp` restore copy 做非破壞性驗證。
- [x] backup integrity check 通過。
- [x] row count / latest period 與正式 DB 一致。
- [x] restore copy 驗證後移除。

### v0.6.4：全資料集健康檢查

目標：一次檢查所有 canonical datasets。

候選項目：

- row count。
- duplicate key。
- latest date/month。
- gap count。
- recent non-OK batches。
- recent errors/events。

## 暫不做

- 不新增 ClickHouse canonical truth。
- 不做雲端多用戶 PWA。
- 不做選股策略與下單功能。
- 不做任意 SQL / shell command endpoint。
- 不做自動 self-healing retry；目前維持人工手動更新，待穩定後再討論。
- 不做 PWA CSV 匯出與上一頁/下一頁分頁按鈕，除非使用者重新要求。

## 目前下一步

目前 `v0.6.3` 備份/還原演練文件完成。

後續功能 gate：

1. 進入 `v0.6.4` 全資料集健康檢查。
2. 補 row count、duplicate key、latest date/month、gap count、recent non-OK batches、recent errors/events 的一鍵報表。
3. 更新 `CURRENT_STATE.md`、`CHANGELOG.md`、README 或相關 docs。
