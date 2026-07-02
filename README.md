# VeriStockDB

<!-- i18n-switch -->
[中文](README.md) | [English](README.en.md)
<!-- /i18n-switch -->


Version: v0.6.6

VeriStockDB 是本機台股 SQLite 真理資料庫。它把官方資料下載、驗證、擋錯後才寫入主表，目標是讓 Close、注意、處置、法人、資券、當沖、月營收與交易日資料可被本地 CLI、API、PWA 或分析程式穩定查詢。

VeriStockDB 不是交易建議系統，不連接券商，不下單，也不是公開雲端 API。

## Why This Matters

台股官方資料分散在不同市場、端點、CSV/JSON/HTML 形態與歷史格式中，欄位、日期、單位、編碼與缺檔狀態都可能隨時間變化。這讓長期歷史資料的重現、驗證與修復變得困難。VeriStockDB 的價值是把官方來源先下載、檢查、對帳與記錄問題，再寫入本地可重現、驗證優先的 canonical SQLite DB，讓後續查詢與分析建立在清楚的資料邊界上。

## Current Scope

已完成並入 SQLite canonical truth 的資料表：

- `daily_close`
- `attention_notices`
- `disposal_notices`
- `legal_investors`
- `margin_trading`
- `day_trading`
- `monthly_revenue`
- `trading_days`
- `import_batches`, `import_errors`, `data_events`, `settings`
- `ops_jobs` for PWA manual-update job history; not canonical market data

ClickHouse 目前沒有被啟用為真理資料庫；若之後導入，只能先作為分析或高流量查詢層，不能取代 SQLite canonical data。

## Core Rules

- 主資料表只放已驗證、可查詢的正式資料。
- 可疑官方資料一律擋下，不覆寫 canonical rows。
- 價格以「元 * 100」整數分儲存。
- 股票代號永遠當文字處理，保留前導零。
- 日期格式統一使用 `YYYY-MM-DD`；API 拒絕 `20260615` 這類 compact date。
- CSV 成功入庫後先留存，只有在月檢與 ZIP 驗證完成後才可封存 loose CSV。

## System Requirements

Ubuntu deployment expects these OS-level commands to be available:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 nodejs npm
```

- `python3`: CLI, ETL, API, and tests.
- `sqlite3`: DB inspection, backup/integrity checks, and release validation.
- `node`: PWA JavaScript syntax checks such as `node --check web/app.js`.
- `npm`: available for future PWA tooling; the current PWA has no build step.

## CLI Commands

裸執行會顯示 help，不會初始化 DB 或啟動資料流程：

```bash
python3 main.py
```

初始化與狀態：

```bash
python3 main.py init-db
python3 main.py status
python3 main.py status --problems --details
python3 main.py ops-check
python3 main.py schedule-health
python3 main.py dataset-health-check
python3 main.py backup
```

DB restore SOP 與最近一次演練結果見 `docs/backup_restore_sop.md`。

交易日：

```bash
python3 main.py backfill-trading-days --from 2001-01-02 --to 2026-06-18
```

日收盤 Close：

```bash
python3 main.py update-close
python3 main.py import-close --date 2026-06-18
python3 main.py import-close --from 2026-06-01 --to 2026-06-18
python3 main.py import-close --file data/csv/daily_close/2024/20240603CloseSII.csv --date 2024-06-03 --market TWSE
python3 main.py import-close-local --dir data/csv/Close --from 2004-02-11 --to 2004-12-31 --market TWSE
python3 main.py rollback-close
python3 main.py query-close --stock-id 2330 --from 2026-06-01 --to 2026-06-18
```

注意股公告：

```bash
python3 main.py inspect-attention --twse-file path/to/twse.csv --tpex-file path/to/tpex.csv
python3 main.py import-attention --file path/to/attention.csv --market TWSE
python3 main.py update-attention
python3 main.py query-attention --stock-id 2330 --from 2026-06-01 --to 2026-06-18
```

處置股公告：

```bash
python3 main.py inspect-disposal --twse-file path/to/twse.csv --tpex-file path/to/tpex.csv
python3 main.py import-disposal --file path/to/disposal.csv --market TWSE
python3 main.py update-disposal
python3 main.py query-disposal --stock-id 2330 --from 2026-06-01 --to 2026-06-18
```

三大法人：

```bash
python3 main.py download-legal --from 2019-08-21 --to 2026-06-18
python3 main.py inspect-legal --date 2026-06-18 --market TWSE
python3 main.py report-legal --from 2012-05-04 --to 2026-06-18
python3 main.py import-legal --dry-run --from 2012-05-04 --to 2026-06-18
python3 main.py import-legal --from 2012-05-04 --to 2026-06-18
python3 main.py update-legal
```

`update-legal` 會掃描目標日前所有「交易日但該市場缺 row」的日期並補齊，不只看今天或 `MAX(trade_date)`。

資券：

```bash
python3 main.py download-margin --from 2001-01-02 --to 2026-06-18 --market TWSE
python3 main.py download-margin --from 2008-09-30 --to 2026-06-18 --market TPEX
python3 main.py inspect-margin --from 2001-01-02 --to 2026-06-18
python3 main.py import-margin --dry-run --from 2001-01-02 --to 2026-06-18
python3 main.py import-margin --execute --from 2001-01-02 --to 2026-06-18
python3 main.py update-margin
```

`update-margin` 會掃描目標日前所有「交易日但該市場缺 row」的日期並補齊，不只看今天或 `MAX(trade_date)`。

當沖：

```bash
python3 main.py download-day-trading --from 2014-01-06 --to 2026-06-30
python3 main.py inspect-day-trading --date 2026-06-30 --market TWSE
python3 main.py import-day-trading --dry-run --from 2014-01-06 --to 2026-06-30
python3 main.py import-day-trading --execute --from 2014-01-06 --to 2026-06-30
python3 main.py update-day-trading
```

`update-day-trading` 會掃描目標日前所有「交易日但該市場缺 row」的日期並補齊，不覆寫既有資料。

月營收：

```bash
python3 main.py download-revenue --from 2013-01 --to 2026-05
python3 main.py import-revenue --dry-run --from 2013-01 --to 2026-05
python3 main.py import-revenue --execute --from 2013-01 --to 2026-05
python3 main.py update-revenue
```

`update-revenue` 依每月 10 號公開規則判定最新可用月份，從各市場 DB 內最後 `revenue_month + 1` 補到目標月份，不覆寫既有資料。

Close 月資料對帳與封存：

```bash
python3 main.py reconcile-close-month --month 2026-06
python3 main.py reconcile-close-month --month 2026-06 --market TWSE --stock-id 2330 --from 2026-06-01 --to 2026-06-18
python3 main.py audit-month --dataset daily_close --month 2026-06
python3 main.py archive-month --dataset daily_close --month 2026-06
python3 main.py finalize-close-months --from 2024-01 --to 2024-12
```

Telegram：

```bash
python3 main.py notify-telegram --test
python3 main.py notify-telegram --message "VeriStockDB test message"
```

## Production Timers

目前私有部署排程：

- Close：`Mon..Fri 17:10`
- Legal investors：`Mon..Fri 18:00`
- Attention notices：`Mon..Fri 19:00`
- Disposal notices：`Mon..Fri 19:05`
- Margin trading：`Mon..Fri 21:05`
- Day trading：`Mon..Fri 21:10`
- Monthly revenue：`Mon..Fri *-*-10..12 21:15`，由 guard script 判斷 10 號或遇假日順延

Timer 使用 `Persistent=true`。修改 production systemd timer 需要人工 sudo，不能未授權改動。

## Local Truth API

Local Truth API 已完成以下端點：

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

啟動：

```bash
pip install -r requirements.txt
python3 -m api
```

預設綁定 `127.0.0.1:8000`。完整 API 契約見 `docs/local_truth_api_spec.md`。

## Local Management PWA

`v0.5.x` 起提供本地管理 PWA，靜態檔位於 `web/`，由 FastAPI 掛載在 `/`。`v0.6.0` 起加入資料集健康 drill-down。

啟動範例：

```bash
python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

PWA 目前用於本機資料健康檢查與人工補救，不是選股工具：

- 查看資料集最新日期與問題批次。
- 點選資料集查看 latest、quality、recent batches、problem batches、recent errors、recent events、recent jobs。
- 在系統頁查看排程健康：timer 是否啟用、log tail 是否有錯、資料 latest 是否追上 expected。
- 在系統頁查看全資料集健康檢查：row count、duplicate key、latest、gap、recent errors。
- 手動執行 allow-listed `update-*` jobs。
- 查看最近手動更新 job、錯誤摘要、stdout/stderr tail。
- 使用 Local Truth API 查詢正式資料；查詢結果以表格顯示。
- Close 價格在 PWA 顯示層會把 API 的 cents 整數除以 `100` 顯示為元；API 與 DB 契約仍是 cents。

PWA 不直接讀 SQLite、不解析 CLI stdout、不執行任意 shell command。

## Data Sources

- Close：TWSE/TPEX 官方日收盤 CSV。
- Trading days：TWSE `FMTQIK` 月曆，TWSE 異常時使用 TPEX 備援。
- Attention notices：TWSE/TPEX 官方注意股公告 CSV。
- Disposal notices：TWSE/TPEX 官方處置公告 CSV；查詢區間會延伸到目標日後方以取得最新公告。
- Legal investors：TWSE/TPEX 官方三大法人 CSV。
- Margin trading：TWSE `MI_MARGN`，TPEX `margin/balance` CSV；TPEX canonical scope 從 `2008-09-30` 開始。
- Day trading：TWSE `TWTB4U`、TPEX `intraday/stat` CSV，canonical scope 從 `2014-01-06` 開始。
- Monthly revenue：MOPS `t21sc03_{roc_month}.csv`，canonical scope 從 `2013-01` 開始，依每月 10 號公開規則更新。
- Close monthly reconciliation：TWSE/TPEX 官方個股月資料 JSON，只對帳 `close` 與 `volume`，不覆寫 `daily_close`。

### 資料源邊界

VeriStockDB v0.6.6 的 canonical pipeline 目前使用已驗證的官方 CSV/JSON 下載流程、本機 cache/archive，以及使用者提供的 CSV 匯入。TWSE/TPEX OpenAPI 端點在現階段不作為 canonical database 既有 CSV/JSON 來源的替代品，因為其欄位、語意或涵蓋範圍可能與目前驗證流程使用的來源不同。使用者必須自行遵守各資料來源的使用條款；VeriStockDB 不授予官方原始資料的再散布權利。

## Documentation Boundary

- `CURRENT_STATE.md` 是下一輪 Codex/PM/worker 接手的唯一狀態摘要。
- `CHANGELOG.md` 是唯一正式版本紀錄。
- `docs/README.md` 是文件入口與判讀優先順序。
- `docs/new_dataset_sop.md` 是未來新增官方資料表時的標準流程。
- 舊版 handoff/archive 已移出 repo 工作樹並保留於冷封存區，只作歷史參考，不可視為目前狀態來源。

## Paths

```bash
/opt/veristockdb/app                         # repo
/opt/veristockdb/app/data/db/veristock.db    # SQLite canonical DB
/opt/veristockdb/app/data/csv                # hot CSV
/opt/veristockdb/app/reports                 # reports
/var/log/veristockdb                        # systemd logs
/mnt/veristockdb-cold/veristockdb/archive           # cold ZIP archive
/mnt/veristockdb-cold/veristockdb/backup            # DB backups
```

## Required Health Checks

接受任何 DB-changing work 前至少要完成：

- SQLite `PRAGMA integrity_check`
- backup 可讀與 integrity check
- row count before/after
- duplicate key check
- date coverage against `trading_days`
- schema validation against `db/schema.sql`
- source coverage/dry-run report
- API route/date/field/pagination/quality checks if API touched

如果之後碰 ClickHouse，還要做 table count、row count、sample aggregation、duplicate/sorting-key validation。

## Locked Actions

未經明確授權不得執行：

- drop、truncate、delete、overwrite canonical SQLite data
- destructive SQL
- schema migration 或版本 bump
- 啟用、停用或修改正式 systemd 排程
- 將 SQLite canonical truth 移到 ClickHouse
- 建立或覆寫 ClickHouse tables
- 刪除 backup、archive、CSV、report、log
- 改寫 git history

## Deferred Work

- `v0.4.0 public-preview` release gate 已完成；後續新增資料集仍需重新通過 DB/API/docs/repo safety gate。
- 全資料集健康檢查一鍵報表移至 `v0.6.5`。
