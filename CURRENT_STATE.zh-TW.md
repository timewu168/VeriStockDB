# CURRENT_STATE.md

<!-- i18n-switch -->
[English](CURRENT_STATE.md) | [中文](CURRENT_STATE.zh-TW.md)
<!-- /i18n-switch -->

## 目前階段

- 最新完成版本目標：`v0.7.0`，新增官方證券主檔與 active disposal API 契約。
- 已完成 public preview、repo hygiene、Local Truth API、Local Management PWA、手動更新 jobs、排程健康、restore SOP、新資料集 SOP 與全資料集健康檢查。
- SQLite 仍是 canonical truth；ClickHouse 尚未成為真理資料庫。
- PWA 只透過 Local Truth API，不直接讀 SQLite、不解析 CLI stdout、不執行任意 shell command。
- 後續階段建議先進入長時間運行觀察，不急著新增資料表或改架構。

## 已接受基準

完成並接受的 canonical SQLite datasets：

- `daily_close`
- `attention_notices`
- `disposal_notices`
- `security_master`
- `legal_investors`
- `margin_trading`
- `day_trading`
- `monthly_revenue`
- `trading_days`

營運資料表：

- `import_batches`
- `import_errors`
- `data_events`
- `settings`
- `ops_jobs`

`v0.7.0` 正式 DB smoke：

- `dataset-health-check OK`
- duplicate keys：`0`
- gaps：`0`
- recent errors：`0`
- `security_master`：TWSE `1089`、TPEX `891`，合計 `1980` 筆。
- `GET /api/v1/disposal-notices/active` 於 `2026-07-15` 回傳 `27` 檔有效股票，另排除 `10` 筆非股票商品。

最新 row count baseline：

| Dataset | Rows |
| --- | ---: |
| `daily_close` | `8715496` |
| `attention_notices` | `102605` |
| `disposal_notices` | `7716` |
| `legal_investors` | `5832010` |
| `margin_trading` | `8146089` |
| `day_trading` | `4037752` |
| `monthly_revenue` | `280711` |

最新期間 baseline：

| Dataset | Latest |
| --- | --- |
| Close | `2026-07-01` |
| 注意公告 | `2026-07-01` |
| 處置公告 | TWSE `2026-07-01`，TPEX `2026-06-30` |
| 法人 | `2026-07-01` |
| 資券 | `2026-07-01` |
| 當沖 | `2026-07-01` |
| 月營收 | `2026-05` |

## SQLite / ClickHouse 邊界

- SQLite 是目前 production canonical truth。
- ClickHouse 目前未導入 canonical role。
- 若未來導入 ClickHouse，只能先作為分析或高流量查詢層，不能取代 SQLite canonical data。
- ClickHouse 導入前必須通過 table count、row count、sample aggregation、duplicate/sorting-key validation。

## 資料來源與 ETL 狀態

- Close、注意、處置、證券主檔、法人、資券、當沖、月營收、交易日都已 canonicalized in SQLite。
- `security_master` 僅取 TWSE/TPEX 官方 OpenAPI 公司基本資料，並以 effective period 保存名稱與產業異動。
- 日資料 API 日期格式為 `YYYY-MM-DD`。
- 月資料 API 日期格式為 `YYYY-MM`。
- `20260615` 這類 compact date 應拒絕。
- `update-legal`、`update-margin`、`update-day-trading` 會掃描目標日前所有「交易日但該市場缺 row」的日期，不只看 `MAX(trade_date)`。
- `update-revenue` 依每月 10 號公開規則判斷最新可用月份，從各市場最後月份 + 1 補到目標月份。

## Schema / Migration 狀態

- `APP_VERSION=0.7.0`。
- `SCHEMA_VERSION=0.5-security-master`。
- `db/schema.sql` 已包含所有已接受 canonical 與 operational tables。
- 目前沒有待執行 SQLite schema migration。

## 重要文件

- `README.md` / `README.en.md`：公開專案說明。
- `CHANGELOG.md` / `CHANGELOG.en.md`：版本紀錄。
- `docs/README.md` / `docs/en/README.md`：文件入口。
- `docs/new_dataset_sop.md` / `docs/en/new_dataset_sop.md`：新增資料集 SOP。
- `docs/project_completion_inventory.md` / `docs/en/project_completion_inventory.md`：PM/整合盤點。
- `docs/backup_restore_sop.md` / `docs/en/backup_restore_sop.md`：備份還原 SOP。
- `docs/security_master.md`：官方證券主檔來源、欄位與品質邊界。

## 下一道關卡

- `v0.7.0` 待完成 Git commit、push 與 draft PR。
- 下一階段應優先做長時間排程觀察與手動補救流程驗證。
- 不要在未明確授權下新增資料集、改 schema、改正式排程或執行破壞性 DB 操作。

## 鎖定操作

未經明確授權不得執行：

- drop、truncate、delete 或 overwrite canonical SQLite data。
- 破壞性 SQL。
- schema migration 或版本 bump。
- 啟用、停用或修改 production systemd schedules。
- 新增任意 command execution。
- 將 SQLite canonical truth 移到 ClickHouse。
- 刪除 backup、archive、CSV、report、log。
- 改寫 git history。

## 必要驗證

涉及 DB 或資料流程變更時，至少要做：

- SQLite `PRAGMA integrity_check`
- backup check
- row count
- duplicate key check
- date coverage
- schema validation
- source coverage / dry-run report
- API smoke checks if API touched
- 若碰 ClickHouse，還要 table count / row count / sample aggregation check。
