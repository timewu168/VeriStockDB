# VeriStockDB 專案完成度總盤點

更新日期：2026-07-02

適用版本：`v0.6.5`

本文給 PM、整合工程師或後續服務 owner 使用，用來判斷 VeriStockDB 目前能提供什麼、不能提供什麼、如何接入其他專案，以及長時間運行時應觀察哪些風險。

## 1. 結論

VeriStockDB 已完成第一階段可用狀態。

目前它是一個本機台股 SQLite canonical truth database，已完成官方資料下載、驗證、擋錯、正式入庫、查詢 API、本地管理 PWA、手動補救、排程健康、全資料集健康檢查、備份/還原 SOP、文件邊界與開源 repo hygiene。

專案目前適合進入長時間運行觀察期。短期不建議急著新增資料表或改架構，應先觀察排程穩定性、官方來源格式變化、資料缺口、PWA 手動修復流程與備份可用性。

## 2. 專案定位

VeriStockDB 的定位：

- 本機台股官方資料真理資料庫。
- SQLite 是目前 canonical truth。
- 官方資料進 DB 前必須先下載、驗證、擋錯。
- API 與 PWA 只讀 canonical data 或觸發 allow-listed 更新流程。
- PWA 是資料健康檢查與人工補救工具，不是選股工具。

VeriStockDB 不是：

- 交易建議系統。
- 券商下單系統。
- 公開雲端 API。
- 多用戶 SaaS。
- 任意 SQL 或任意 shell execution 平台。
- ClickHouse canonical truth。

## 3. 已完成版本狀態

最新已發版：

- `v0.6.5`
- 最新主題：全資料集健康檢查
- GitHub main/tag 已完成到 `v0.6.5`

主要階段：

| 階段 | 狀態 | 說明 |
| --- | --- | --- |
| v0.2.x | 完成 | Close、交易日、回滾、部署基礎 |
| v0.3.x | 完成 | API、注意、處置、Telegram、法人、資券、重試 |
| v0.4.x | 完成 | public preview、repo hygiene、當沖、月營收 |
| v0.5.x | 完成 | Local Management PWA、手動更新 jobs |
| v0.6.x | 完成 | drill-down、排程健康、文件邊界、restore SOP、新資料集 SOP、全資料集健康檢查 |

## 4. Canonical SQLite 資料表

已接受的 canonical datasets：

| Dataset | SQLite table | Period | 起始範圍摘要 | 更新命令 | API |
| --- | --- | --- | --- | --- | --- |
| 日收盤 Close | `daily_close` | 日 | TWSE `2004-02-11` 起；TPEX `2007-07-02` 起 | `update-close` | `/api/v1/daily-close` |
| 注意公告 | `attention_notices` | 日/公告 | TWSE/TPEX 官方注意公告 | `update-attention` | `/api/v1/attention-notices` |
| 處置公告 | `disposal_notices` | 公告日/處置期間 | TWSE/TPEX 官方處置公告 | `update-disposal` | `/api/v1/disposal-notices` |
| 三大法人 | `legal_investors` | 日 | TWSE `2012-05-04` 起；TPEX `2007-04-23` 起 | `update-legal` | `/api/v1/legal-investors` |
| 資券 | `margin_trading` | 日 | TWSE `2001-01-02` 起；TPEX `2008-09-30` 起 | `update-margin` | `/api/v1/margin-trading` |
| 當沖 | `day_trading` | 日 | `2014-01-06` 起 | `update-day-trading` | `/api/v1/day-trading` |
| 月營收 | `monthly_revenue` | 月 | `2013-01` 起 | `update-revenue` | `/api/v1/monthly-revenue` |
| 交易日 | `trading_days` | 日 | `2001-01-02` 起 | `backfill-trading-days` | `/api/v1/trading-days` |

Operational tables：

- `import_batches`：批次狀態。
- `import_errors`：匯入錯誤。
- `data_events`：特殊資料事件。
- `settings`：設定。
- `ops_jobs`：PWA 手動更新 job history，不是市場資料。

## 5. 最新資料健康基準

`v0.6.5` 正式 DB smoke 結果：

- `dataset-health-check OK`
- 七個 canonical datasets：
  - duplicate keys：`0`
  - gaps：`0`
  - recent errors：`0`

最新 smoke row count：

| Table | Rows |
| --- | ---: |
| `daily_close` | `8715496` |
| `attention_notices` | `102605` |
| `disposal_notices` | `7716` |
| `legal_investors` | `5832010` |
| `margin_trading` | `8146089` |
| `day_trading` | `4037752` |
| `monthly_revenue` | `280711` |

最新期間：

| Dataset | Latest |
| --- | --- |
| Close | `2026-07-01` |
| 注意公告 | `2026-07-01` |
| 處置公告 | TWSE `2026-07-01`，TPEX `2026-06-30` |
| 三大法人 | `2026-07-01` |
| 資券 | `2026-07-01` |
| 當沖 | `2026-07-01` |
| 月營收 | `2026-05` |

## 6. Local Truth API 完成度

已完成 read-only / ops endpoints：

- `GET /health`
- `GET /api/v1/info`
- `GET /api/v1/datasets`
- `GET /api/v1/datasets/status-summary`
- `GET /api/v1/datasets/{dataset}/status`
- `GET /api/v1/datasets/{dataset}/health`
- `GET /api/v1/daily-close`
- `GET /api/v1/attention-notices`
- `GET /api/v1/disposal-notices`
- `GET /api/v1/legal-investors`
- `GET /api/v1/margin-trading`
- `GET /api/v1/day-trading`
- `GET /api/v1/monthly-revenue`
- `GET /api/v1/trading-days`
- `GET /api/v1/batches`
- `GET /api/v1/batches/{batch_id}`
- `GET /api/v1/errors`
- `GET /api/v1/events`
- `GET /api/v1/ops/summary`
- `GET /api/v1/ops/schedule-health`
- `GET /api/v1/ops/dataset-health-check`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/update-dataset`

API 整合規則：

- 日資料日期使用 `YYYY-MM-DD`。
- 月資料日期使用 `YYYY-MM`。
- Compact date，例如 `20260615`，應視為 invalid。
- 價格欄位在 DB/API 仍是 cents integer；PWA 顯示時才除以 `100`。
- 查詢資料可使用 date/month range、stock_id、market、fields、limit、offset。
- API error 格式已結構化。

## 7. PWA 完成度

PWA 位於 `web/`，由 FastAPI static mount 提供。

已完成：

- Dashboard。
- Dataset status。
- Dataset health drill-down。
- Batch list。
- Import errors / data events。
- Table query。
- Manual update jobs。
- Job detail drawer。
- System info。
- Schedule health。
- All-dataset health check。

PWA 設計邊界：

- 只透過 Local Truth API。
- 不直接讀 SQLite。
- 不解析 CLI stdout。
- 不執行任意 shell command。
- 手動更新只允許 allow-listed dataset update commands。
- 同一時間只允許一個 manual update job。

## 8. 排程與更新

目前 production timer 規劃：

| Dataset | Timer |
| --- | --- |
| Close | `Mon..Fri 17:10` |
| Legal investors | `Mon..Fri 18:00` |
| Attention notices | `Mon..Fri 19:00` |
| Disposal notices | `Mon..Fri 19:05` |
| Margin trading | `Mon..Fri 21:05` |
| Day trading | `Mon..Fri 21:10` |
| Monthly revenue | `Mon..Fri *-*-10..12 21:15`，guard script 判斷 10 號或假日順延 |

已完成：

- `schedule-health` CLI。
- `/api/v1/ops/schedule-health`。
- PWA 系統頁排程健康表格。

仍需長時間觀察：

- 每個 timer 是否實際在 production 時段跑完。
- Telegram 通知是否有漏發。
- 官方短暫異常時，手動更新是否足以處理。
- 月營收 10 號遇假日順延 guard 是否持續符合需求。

## 9. 維運能力

已完成：

- `ops-check`。
- `schedule-health`。
- `dataset-health-check`。
- `backup`。
- Backup/restore SOP。
- 非破壞性 restore drill 文件。
- 新增資料表 SOP。

建議日常巡檢：

```bash
python3 main.py status --problems --details
python3 main.py schedule-health
python3 main.py dataset-health-check
python3 main.py ops-check
```

DB restore 文件：

- `docs/backup_restore_sop.md`

新增資料表流程：

- `docs/new_dataset_sop.md`

## 10. 整合其它專案或服務的方式

建議整合方式：

1. 優先使用 Local Truth API。
2. 需要大量分析時，再討論匯出或 ClickHouse 分析層。
3. 不建議其他服務直接寫 SQLite。
4. 不建議其他服務直接讀 raw CSV 當正式資料。
5. 不建議外部服務直接呼叫 shell command；手動更新應透過 jobs API。

推薦整合場景：

- 內部 dashboard 讀 `/api/v1/datasets/status-summary`。
- 監控服務讀 `/api/v1/ops/schedule-health` 與 `/api/v1/ops/dataset-health-check`。
- 分析服務讀各 dataset query endpoint。
- 管理後台使用 PWA 或 jobs API 觸發 allow-listed update。

不建議整合場景：

- 對外公開無 token API。
- 直接把 PWA 當多用戶 SaaS。
- 讓外部服務寫入 canonical SQLite。
- 讓外部服務自行修補 canonical rows。

## 11. 安全與破壞性操作邊界

未經明確授權不得執行：

- drop/truncate/delete/overwrite canonical SQLite data。
- destructive SQL。
- schema migration。
- 啟用、停用或修改 production systemd timer。
- 刪除 backup、archive、CSV、report、log。
- 新增任意 shell command endpoint。
- 新增任意 SQL endpoint。
- 將 SQLite canonical truth 搬到 ClickHouse。
- 建立或覆寫 ClickHouse canonical table。
- 改寫 git history。

## 12. 目前不足與風險

目前仍需觀察或後續決策的項目：

- Production timer 長時間穩定性尚需持續觀察。
- Telegram 通知漏發檢查尚未做成正式健康檢查。
- 官方來源偶發格式異常仍可能需要人工重試或等待官方修復。
- 自動 self-healing retry 尚未啟用，目前先保留人工手動更新。
- PWA 是本地管理工具，不是多用戶權限系統。
- ClickHouse 尚未導入；若未來資料查詢壓力變大，需另做分析層設計。
- API 尚未做雲端公開服務 hardening。
- 報表/監控可再接 Grafana、Prometheus 或外部告警，但目前未實作。

## 13. 建議後續節奏

短期建議：

1. 不新增功能，進入 2 到 4 週運行觀察。
2. 每個交易日確認 `schedule-health` 與 `dataset-health-check`。
3. 留意 PWA 手動更新是否能處理官方短暫異常。
4. 確認 backup 檔案持續更新且可 restore。

中期再評估：

1. 是否需要 Telegram 通知健康檢查。
2. 是否需要自動 self-healing retry。
3. 是否需要 ClickHouse 分析層。
4. 是否需要給其他專案一份正式 OpenAPI client 或 SDK。
5. 是否需要把 PWA 拆成更正式的管理後台。

## 14. PM 接手檢查清單

PM 或整合 owner 接手時，先確認：

- GitHub latest tag 是否為 `v0.6.5`。
- `CURRENT_STATE.md` 是否與本文件一致。
- `python3 main.py dataset-health-check` 是否為 `OK`。
- `python3 main.py schedule-health` 是否無 ERROR。
- PWA 是否可打開並讀取 dataset status。
- 手動更新 job 是否可建立且可查歷史。
- Backup latest file 是否存在且 restore SOP 可執行。
- 是否有新的官方資料來源異常或缺檔。

## 15. 判讀文件順序

後續工作請依序閱讀：

1. `CURRENT_STATE.md`
2. `README.md`
3. `CHANGELOG.md`
4. `docs/project_completion_inventory.md`
5. `docs/local_truth_api_spec.md`
6. `docs/version_roadmap_checklist.md`
7. `docs/new_dataset_sop.md`
8. `docs/backup_restore_sop.md`
9. 其他 `docs/` 目前有效文件

`docs/pm_handoff/` 是歷史封存，只能作參考，不能取代目前狀態。
