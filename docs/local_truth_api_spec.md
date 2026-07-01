# Local Truth API 規格文件

狀態：Local Truth API 已完成至 `v0.5.2`，涵蓋 Close、注意、處置、法人、資券、當沖、月營收、交易日、批次、錯誤、事件、ops summary、dataset status summary 與 PWA 手動更新 jobs。PWA jobs 僅能執行 allow-listed `update-*` 命令，不提供任意 shell command。

建立日期：2026-06-04

## 1. 定位

Local Truth API 是 VeriStockDB 的本地真理資料庫 API。

它只服務本地環境與可信任內網，不是雲端公開 API。它的任務是把 VeriStockDB 中已驗證、可追溯的資料，以穩定 JSON 契約提供給：

- VeriStockDB 本地管理 PWA。
- 本地選股、回測、資料分析專案。
- 未來本地排程或策略模組。

雲端 Edge API、雲端多用戶 PWA、策略產品前台不屬於本 repo 的實作範圍。VeriStockDB 只會預留可輸出的 JSON 契約，讓未來私有雲端專案讀取。

## 2. 核心原則

1. 本地優先。
   - API 預設綁定 `127.0.0.1`。
   - 若需要外出管理，只允許透過 ZeroTier、VPN 或等價安全內網。
   - 不設定 router port forwarding。

2. 真理資料庫優先。
   - API 只回傳 VeriStockDB 已入庫、可追溯的資料。
   - 每個 dataset 都應能追到 `import_batches`、`import_errors`、`data_events`。

3. 讀取與管理分層。
   - 資料查詢 endpoint 仍維持 read-only。
   - PWA 手動更新 endpoint 屬於 ops 管理功能，只能觸發 allow-listed `main.py update-*` commands。
   - 回滾、備份、archive、schema migration、任意 SQL、任意 shell command 不開放。

4. PWA 不解析 CLI stdout。
   - CLI 負責命令列文字。
   - API 負責穩定 JSON。
   - PWA 負責中文 UI 與 i18n formatter。

5. 價格使用整數分。
   - DB 內價格以整數分保存。
   - API 正式欄位使用 `open_cents`、`high_cents`、`low_cents`、`close_cents`。
   - PWA 或外部專案需要顯示時自行除以 `100`。
   - API 不以 float 作為價格真理值。

6. 查詢可以不帶市場，但入庫與索引要保留市場邊界。
   - 主資料表可以用 `trade_date + market + stock_id` 作為安全主鍵，避免特殊跨市場代號碰撞。
   - API / PWA / 回測查詢不得強迫使用者一定要帶 `market`。
   - 所有以交易日和股票代號為主要查詢條件的主資料表，都必須建立 `(trade_date, stock_id)` 複合索引，讓日期加代號查詢與跨資料表 join 成為固定路徑。

## 3. 非目標

目前 Local Truth API 不做以下功能：

- 不實作雲端 Edge API。
- 不實作雲端多用戶 PWA。
- 不提供公開網際網路服務。
- 不提供股票交易建議。
- 不連接券商帳號。
- 不執行下單。
- 不提供任意 SQL 查詢 endpoint。
- 不提供任意 shell command endpoint。
- 不提供任意檔案讀取 endpoint。
- 不觸發 `rollback-close`、`backup`、archive、schema migration 或任意 shell command。
- 不實作 Telegram 手機控制 server。

## 4. 網路與啟動設定

建議環境變數：

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| `VERISTOCK_API_HOST` | `127.0.0.1` | API 綁定地址 |
| `VERISTOCK_API_PORT` | `8000` | API port |
| `VERISTOCK_API_REQUIRE_AUTH` | `0` | 是否要求 token，私有部署可改成 `1` |
| `VERISTOCK_API_READ_TOKEN` | 空 | read 權限 token |
| `VERISTOCK_API_OPS_TOKEN` | 空 | ops 權限 token |
| `VERISTOCK_API_ADMIN_TOKEN` | 空 | admin 權限 token，目前僅預留 |

啟動限制：

- 本地開發：`127.0.0.1:8000`。
- Ubuntu 私有部署：可綁定 `127.0.0.1` 或 ZeroTier IP。
- 不建議綁定 `0.0.0.0`。
- 不做 port forwarding。

## 5. 權限模型

API 使用 Bearer token：

```http
Authorization: Bearer <token>
```

權限分三層：

| 權限 | 用途 | 目前狀態 |
| --- | --- | --- |
| `read` | 查資料、查交易日、查 dataset 狀態 | 實作 |
| `ops` | 查 ops-check、log 摘要、部署狀態 | 可先部分實作 |
| `admin` | 觸發更新、回滾、備份、approve | 僅預留 |

`/health` 可不需要 token。其它 endpoint 若 `VERISTOCK_API_REQUIRE_AUTH=1`，必須提供對應 token。

## 6. API 版本

正式資料 API 使用 `/api/v1` 前綴。

```text
/health
/api/v1/...
```

版本規則：

- 不相容變更必須升到 `/api/v2`。
- 新增欄位通常不視為破壞性變更。
- 移除欄位、改欄位型別、改日期格式，都視為破壞性變更。

## 7. 時間與格式

| 類型 | 格式 |
| --- | --- |
| 交易日期 | `YYYY-MM-DD` |
| 月份 | `YYYY-MM` |
| timestamp | ISO 8601 UTC，例如 `2026-06-04T08:00:00Z` |
| market | `TWSE` 或 `TPEX` |
| dataset | snake_case，例如 `daily_close` |
| status | `OK`、`FIXED`、`BLOCKED`、`RECHECK`、`MISSING`、`SKIPPED` |

交易日期表示台股交易日，不含時間與時區。API date query 必須使用嚴格 `YYYY-MM-DD`，例如 `2026-06-15`；`20260615` 這類 compact date 不接受。

## 8. Response Envelope

所有 `/api/v1` endpoint 使用統一 response envelope。

成功格式：

```json
{
  "ok": true,
  "code": "OK",
  "data": {},
  "meta": {
    "api_version": "v1",
    "request_id": "req_20260604_000001",
    "generated_at": "2026-06-04T08:00:00Z"
  },
  "messages": []
}
```

錯誤格式：

```json
{
  "ok": false,
  "code": "INVALID_DATE",
  "data": null,
  "meta": {
    "api_version": "v1",
    "request_id": "req_20260604_000002",
    "generated_at": "2026-06-04T08:00:00Z"
  },
  "error": {
    "message": "date must use YYYY-MM-DD",
    "params": {
      "field": "from",
      "value": "20260604"
    }
  },
  "messages": []
}
```

`messages` 用於補充可機器判讀的提示：

```json
{
  "level": "INFO",
  "code": "DATASET_STATUS_RECHECK",
  "params": {
    "dataset": "daily_close",
    "problem_batches": 2
  }
}
```

## 9. 錯誤碼

第一版保留以下錯誤碼：

| code | HTTP | 說明 |
| --- | --- | --- |
| `OK` | 200 | 成功 |
| `INVALID_DATE` | 400 | 日期格式錯誤 |
| `INVALID_MONTH` | 400 | 月份格式錯誤 |
| `INVALID_MARKET` | 400 | 市場別錯誤 |
| `INVALID_DATASET` | 400 | dataset 不存在或尚未支援 |
| `INVALID_FIELD` | 400 | 欄位不存在或不可查 |
| `INVALID_PAGINATION` | 400 | limit / offset 錯誤 |
| `JOB_ALREADY_RUNNING` | 409 | 已有手動更新 job 執行中 |
| `AUTH_REQUIRED` | 401 | 需要 token |
| `AUTH_INVALID` | 401 | token 錯誤 |
| `PERMISSION_DENIED` | 403 | 權限不足 |
| `NOT_FOUND` | 404 | 資源不存在 |
| `QUALITY_REJECTED` | 409 | 查詢範圍內資料品質不符合要求 |
| `DB_UNAVAILABLE` | 503 | DB 不可讀或暫時無法取得 |
| `INTERNAL_ERROR` | 500 | 未預期錯誤 |

## 10. 分頁與排序

列表 endpoint 使用：

| 參數 | 預設 | 上限 | 說明 |
| --- | --- | --- | --- |
| `limit` | `1000` | `10000` | 回傳筆數 |
| `offset` | `0` | 無 | 起始位移 |

分頁 meta：

```json
{
  "pagination": {
    "limit": 1000,
    "offset": 0,
    "returned": 1000,
    "has_more": true
  }
}
```

排序預設：

- `daily_close`：`trade_date`, `market`, `stock_id`
- `trading_days`：`trade_date`
- `batches`：`dataset`, `period`, `market`
- `errors`：`created_at`
- `events`：`period`, `market`, `stock_id`

## 11. 資料品質參數

資料查詢 endpoint 可接受：

```text
require_quality=ok
require_quality=allow_recheck
require_quality=any
```

含義：

| 值 | 說明 |
| --- | --- |
| `ok` | 查詢範圍內不得有 `BLOCKED`、`RECHECK`、`MISSING` |
| `allow_recheck` | 允許 `RECHECK`，但不允許 `BLOCKED`、`MISSING` |
| `any` | 不阻擋，但 response meta 必須揭露問題 |

預設值：

```text
require_quality=any
```

若 `require_quality=ok` 但範圍內有問題批次，回傳 `409 QUALITY_REJECTED`。

品質 meta 範例：

```json
{
  "quality": {
    "status": "RECHECK",
    "problem_batches": 2,
    "blocked": 0,
    "recheck": 2,
    "missing": 0
  }
}
```

## 12. Endpoint 總覽

目前 Local Truth API 已落地以下 endpoint。

| Method | Path | 權限 | 狀態 | 說明 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | none | 第一版實作 | API process 健康檢查 |
| `GET` | `/api/v1/info` | read | 第一版實作 | app/schema/API 版本 |
| `GET` | `/api/v1/datasets` | read | 第一版實作 | dataset 清單 |
| `GET` | `/api/v1/datasets/{dataset}/status` | read | 第一版實作 | dataset 批次狀態 |
| `GET` | `/api/v1/datasets/status-summary` | read | `v0.5.0` 實作 | PWA dataset 狀態摘要 |
| `GET` | `/api/v1/daily-close` | read | 第一版實作 | Close 查詢 |
| `GET` | `/api/v1/attention-notices` | read | `v0.3.1` 實作 | 注意股公告查詢 |
| `GET` | `/api/v1/disposal-notices` | read | `v0.3.2` 實作 | 處置股公告查詢 |
| `GET` | `/api/v1/legal-investors` | read | `v0.3.4` 實作 | 三大法人查詢 |
| `GET` | `/api/v1/margin-trading` | read | `v0.3.5` 實作 | 資券查詢 |
| `GET` | `/api/v1/day-trading` | read | `v0.4.5` 實作 | 當沖查詢 |
| `GET` | `/api/v1/monthly-revenue` | read | `v0.4.5` 實作 | 月營收查詢 |
| `GET` | `/api/v1/trading-days` | read | 第一版實作 | 交易日查詢 |
| `GET` | `/api/v1/batches` | read | 第一版實作 | batch 查詢 |
| `GET` | `/api/v1/batches/{batch_id}` | read | 第一版實作 | batch 單筆查詢 |
| `GET` | `/api/v1/errors` | read | 第一版實作 | import_errors 查詢 |
| `GET` | `/api/v1/events` | read | 第一版實作 | data_events 查詢 |
| `GET` | `/api/v1/ops/summary` | ops | 第一版實作 | ops-check 摘要 |
| `POST` | `/api/v1/jobs/update-dataset` | ops | `v0.5.0` 實作 | 觸發 allow-listed dataset 更新 |
| `GET` | `/api/v1/jobs` | ops | `v0.5.1` 實作 | 查詢手動更新 job 歷史 |
| `GET` | `/api/v1/jobs/{job_id}` | ops | `v0.5.1` 實作 | 查詢單一手動更新 job |

以下 endpoint 僅預留，不在目前 API 實作：

| Method | Path | 權限 | 說明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/jobs/rollback-close` | admin | 觸發三日回滾 |
| `POST` | `/api/v1/jobs/backup` | admin | 觸發 backup |
| `POST` | `/api/v1/exports/pwa-results` | admin | 產出給雲端私有專案的 JSON |

## 13. Endpoint 詳細規格

### 13.1 `GET /health`

用途：確認 API process 是否存活。

不要求 token。

範例 response：

```json
{
  "ok": true,
  "code": "OK",
  "status": "healthy",
  "app": "VeriStockDB",
  "api": "local-truth",
  "version": "v1"
}
```

### 13.2 `GET /api/v1/info`

用途：查詢版本資訊。

範例 data：

```json
{
  "app_name": "VeriStockDB",
  "app_version": "0.5.2",
  "schema_version": "0.4-monthly-revenue",
  "api_version": "v1",
  "mode": "local_truth"
}
```

### 13.3 `GET /api/v1/datasets`

用途：列出目前 API 支援的 dataset。

第一版至少包含：

```json
[
  {
    "dataset": "daily_close",
    "title": "Daily Close",
    "period_type": "date",
    "markets": ["TWSE", "TPEX"],
    "status_endpoint": "/api/v1/datasets/daily_close/status"
  }
]
```

目前已包含：

- `daily_close`
- `attention_notice`
- `disposal_notice`
- `legal_investor`
- `margin`
- `day_trading`
- `revenue`

### 13.4 `GET /api/v1/datasets/{dataset}/status`

用途：查詢 dataset 批次狀態摘要。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `from` | 否 | 開始日期或月份 |
| `to` | 否 | 結束日期或月份 |
| `market` | 否 | `TWSE` / `TPEX` |

範例 data：

```json
{
  "dataset": "daily_close",
  "summary": {
    "OK": 10140,
    "FIXED": 0,
    "BLOCKED": 0,
    "RECHECK": 0,
    "MISSING": 0
  },
  "latest_period": "2026-06-02",
  "quality": {
    "status": "OK",
    "problem_batches": 0
  }
}
```

### 13.4a `GET /api/v1/datasets/status-summary`

用途：PWA 首頁與資料集狀態頁使用的全資料集摘要。

回傳內容以目前支援的 datasets 為單位，摘要每個資料集的最新期間、品質狀態與問題批次數。此 endpoint 是 read-only，不觸發下載或入庫。

目前涵蓋：

- `daily_close`
- `attention_notice`
- `disposal_notice`
- `legal_investor`
- `margin`
- `day_trading`
- `revenue`

範例 request：

```text
GET /api/v1/datasets/status-summary
```

### 13.4b PWA 查詢共通規則

PWA 查詢畫面使用既有資料查詢 API，不直接讀 SQLite。

規則：

- 日資料使用 `YYYY-MM-DD`。
- 月營收使用 `YYYY-MM`。
- 股票代號空白時，查詢指定日期或月份區間內的所有股票。
- 股票代號有值時，只查詢該股票。
- 表格顯示使用 API 欄位資料加上 PWA 中文欄名對照，不改變 API 欄位名稱。
- `daily_close` 的價格 API 欄位仍為 cents；PWA 顯示時將 `open_cents`、`high_cents`、`low_cents`、`close_cents` 除以 `100`。
- PWA 目前不提供上一頁/下一頁按鈕與 CSV 匯出；使用 `limit` / `offset` 控制資料量。

### 13.5 `GET /api/v1/daily-close`

用途：查詢 Close 主表。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `from` | 是 | 開始交易日，`YYYY-MM-DD` |
| `to` | 是 | 結束交易日，`YYYY-MM-DD` |
| `stock_id` | 否 | 單一股票代號 |
| `stock_ids` | 否 | 多股票代號，逗號分隔 |
| `market` | 否 | `TWSE` / `TPEX` |
| `fields` | 否 | 欄位清單，逗號分隔 |
| `require_quality` | 否 | `ok` / `allow_recheck` / `any` |
| `limit` | 否 | 預設 `1000` |
| `offset` | 否 | 預設 `0` |

規則：

- `stock_id` 與 `stock_ids` 不可同時使用。
- `from` 不可晚於 `to`。
- `fields` 不可要求不存在或未開放的欄位。
- 價格欄位一律使用整數分。

允許欄位：

- `trade_date`
- `market`
- `stock_id`
- `stock_name`
- `open_cents`
- `high_cents`
- `low_cents`
- `close_cents`
- `volume`
- `amount`
- `transactions`

範例 request：

```text
GET /api/v1/daily-close?stock_id=2330&from=2026-05-01&to=2026-06-02&require_quality=ok
```

範例 data：

```json
[
  {
    "trade_date": "2026-06-02",
    "market": "TWSE",
    "stock_id": "2330",
    "stock_name": "台積電",
    "open_cents": 239000,
    "high_cents": 240000,
    "low_cents": 236000,
    "close_cents": 238000,
    "volume": 41532527,
    "amount": 98885005900,
    "transactions": 99496
  }
]
```

範例 meta：

```json
{
  "price_scale": 100,
  "quality": {
    "status": "OK",
    "problem_batches": 0
  },
  "pagination": {
    "limit": 1000,
    "offset": 0,
    "returned": 1,
    "has_more": false
  }
}
```

### 13.5a `GET /api/v1/legal-investors`

用途：查詢三大法人每日買賣超資料。

Query 與 `daily-close` 相同，支援 `from`、`to`、`stock_id`、`stock_ids`、`market`、`fields`、`require_quality`、`limit`、`offset`。

允許欄位：

- `trade_date`
- `market`
- `stock_id`
- `stock_name`
- `foreign_buy`
- `foreign_sell`
- `foreign_net`
- `investment_trust_buy`
- `investment_trust_sell`
- `investment_trust_net`
- `dealer_buy`
- `dealer_sell`
- `dealer_net`
- `dealer_hedge_buy`
- `dealer_hedge_sell`
- `dealer_hedge_net`

範例 request：

```text
GET /api/v1/legal-investors?stock_id=2330&from=2026-06-15&to=2026-06-15&market=TWSE&require_quality=ok
```

### 13.5b `GET /api/v1/margin-trading`

用途：查詢信用交易資券餘額資料。

Query 與 `daily-close` 相同，支援 `from`、`to`、`stock_id`、`stock_ids`、`market`、`fields`、`require_quality`、`limit`、`offset`。

允許欄位：

- `trade_date`
- `market`
- `stock_id`
- `stock_name`
- `margin_buy`
- `margin_sell`
- `margin_cash_repay`
- `previous_margin_balance`
- `margin_balance`
- `margin_limit`
- `short_buy`
- `short_sell`
- `short_stock_repay`
- `previous_short_balance`
- `short_balance`
- `short_limit`
- `offsetting`
- `note`

範例 request：

```text
GET /api/v1/margin-trading?stock_id=2330&from=2026-06-15&to=2026-06-15&market=TWSE&require_quality=ok
```

### 13.5c `GET /api/v1/day-trading`

用途：查詢當沖資料。

Query 與 `daily-close` 相同，支援 `from`、`to`、`stock_id`、`stock_ids`、`market`、`fields`、`require_quality`、`limit`、`offset`。

允許欄位：

- `trade_date`
- `market`
- `stock_id`
- `stock_name`
- `suspend_sell_note`
- `day_trade_volume`
- `day_trade_buy_amount`
- `day_trade_sell_amount`

回傳 meta：

- `unit`: `shares`

範例 request：

```text
GET /api/v1/day-trading?stock_id=2330&from=2026-06-30&to=2026-06-30&market=TWSE&require_quality=ok
```

### 13.5d `GET /api/v1/monthly-revenue`

用途：查詢月營收資料。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `from` | 是 | 開始月份，`YYYY-MM` |
| `to` | 是 | 結束月份，`YYYY-MM` |
| `stock_id` | 否 | 單一股票代號 |
| `stock_ids` | 否 | 多股票代號，逗號分隔 |
| `market` | 否 | `TWSE` / `TPEX` |
| `fields` | 否 | 欄位清單，逗號分隔 |
| `require_quality` | 否 | `ok` / `allow_recheck` / `any` |
| `limit` | 否 | 預設 `1000`，最大 `10000` |
| `offset` | 否 | 預設 `0` |

允許欄位：

- `revenue_month`
- `market`
- `stock_id`
- `stock_name`
- `industry`
- `report_date`
- `roc_period`
- `current_month_revenue`
- `previous_month_revenue`
- `previous_year_month_revenue`
- `month_over_month_pct`
- `year_over_year_pct`
- `cumulative_revenue`
- `previous_year_cumulative_revenue`
- `cumulative_growth_pct`
- `note`

回傳 meta：

- `unit`: `thousand_twd`

範例 request：

```text
GET /api/v1/monthly-revenue?stock_id=2330&from=2026-05&to=2026-05&market=TWSE&require_quality=ok
```

### 13.6 `GET /api/v1/trading-days`

用途：查詢交易日曆。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `from` | 是 | 開始日期，`YYYY-MM-DD` |
| `to` | 是 | 結束日期，`YYYY-MM-DD` |
| `is_open` | 否 | `1` / `0` |
| `limit` | 否 | 預設 `1000`，最大 `10000` |
| `offset` | 否 | 預設 `0` |

範例 data：

```json
[
  {
    "trade_date": "2026-06-01",
    "is_open": true,
    "source": "twse_fmtqik",
    "note": null
  }
]
```

### 13.6a `GET /api/v1/attention-notices`

用途：查詢注意股公告。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `from` | 是 | 起始日期，`YYYY-MM-DD` |
| `to` | 是 | 結束日期，`YYYY-MM-DD` |
| `stock_id` | 否 | 單一股票代號 |
| `stock_ids` | 否 | 多股票代號，逗號分隔 |
| `market` | 否 | `TWSE` 或 `TPEX` |
| `fields` | 否 | 欄位白名單，逗號分隔 |
| `require_quality` | 否 | `ok` / `allow_recheck` / `any`，預設 `any` |
| `limit` | 否 | 預設 `1000`，最大 `10000` |
| `offset` | 否 | 預設 `0` |

回傳欄位：

- `trade_date`
- `market`
- `stock_id`
- `stock_name`
- `notice_text`

注意：

- 查詢不強迫帶 `market`，但回傳會包含 `market`。
- `notice_text` 保留官方原文，不在 API 層拆條款。

### 13.6b `GET /api/v1/disposal-notices`

用途：查詢處置股公告。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `from` | 是 | 公布日期起始日，`YYYY-MM-DD` |
| `to` | 是 | 公布日期結束日，`YYYY-MM-DD` |
| `stock_id` | 否 | 單一股票代號 |
| `stock_ids` | 否 | 多股票代號，逗號分隔 |
| `market` | 否 | `TWSE` 或 `TPEX` |
| `active_date` | 否 | 只回傳該日仍在處置期間內的資料，`YYYY-MM-DD` |
| `fields` | 否 | 欄位白名單，逗號分隔 |
| `require_quality` | 否 | `ok` / `allow_recheck` / `any`，預設 `any` |
| `limit` | 否 | 預設 `1000`，最大 `10000` |
| `offset` | 否 | 預設 `0` |

回傳欄位：

- `trade_date`
- `market`
- `stock_id`
- `stock_name`
- `disposal_start_date`
- `disposal_end_date`
- `reason_text`
- `disposal_text`

注意：

- 查詢不強迫帶 `market`，但回傳會包含 `market`。
- `trade_date` 是官方公布日期。
- `disposal_start_date` / `disposal_end_date` 是處置起迄期間。
- `reason_text` 統一保存 TWSE 的「處置條件」或 TPEX 的「處置原因」。
- `disposal_text` 保留官方處置內容原文，不在 API 層解析條款或措施。

### 13.7 `GET /api/v1/batches`

用途：查詢 `import_batches`。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `dataset` | 否 | dataset |
| `market` | 否 | market |
| `from` | 否 | period 起始 |
| `to` | 否 | period 結束 |
| `status` | 否 | 批次狀態 |
| `limit` | 否 | 分頁 |
| `offset` | 否 | 分頁 |

範例 data：

```json
[
  {
    "batch_id": "daily_close:TWSE:2026-06-02",
    "dataset": "daily_close",
    "market": "TWSE",
    "period": "2026-06-02",
    "status": "OK",
    "row_count": 1250,
    "error_summary": null,
    "source_file": "20260602CloseSII.csv",
    "checked_at": "2026-06-02T12:00:00Z",
    "manual_approved": false
  }
]
```

### 13.8 `GET /api/v1/batches/{batch_id}`

用途：查詢單一批次，並可包含錯誤與特殊事件摘要。

範例 data：

```json
{
  "batch": {
    "batch_id": "daily_close:TWSE:2026-06-02",
    "dataset": "daily_close",
    "market": "TWSE",
    "period": "2026-06-02",
    "status": "OK"
  },
  "errors": [],
  "events": []
}
```

### 13.9 `GET /api/v1/errors`

用途：查詢 `import_errors`。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `dataset` | 否 | dataset |
| `batch_id` | 否 | batch id |
| `severity` | 否 | `WARN` / `BLOCK` |
| `code` | 否 | error code |
| `from` | 否 | `created_at` 日期起始，`YYYY-MM-DD` |
| `to` | 否 | `created_at` 日期結束，`YYYY-MM-DD` |
| `limit` | 否 | 分頁 |
| `offset` | 否 | 分頁 |

範例 data：

```json
[
  {
    "error_id": "err_...",
    "batch_id": "daily_close:TWSE:2004-02-11",
    "severity": "WARN",
    "code": "ZERO_TRADE_DASH_EXCLUDED",
    "message": "early cold-start row was excluded",
    "sample_stock_id": "0000",
    "sample_value": "--",
    "created_at": "2026-06-04T08:00:00Z"
  }
]
```

### 13.10 `GET /api/v1/events`

用途：查詢 `data_events`，例如補前收、早期無前收排除等稀疏事件。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `dataset` | 否 | dataset |
| `market` | 否 | market |
| `from` | 否 | period 起始 |
| `to` | 否 | period 結束 |
| `stock_id` | 否 | 股票代號 |
| `event_type` | 否 | 事件類型 |
| `limit` | 否 | 分頁 |
| `offset` | 否 | 分頁 |

常見 `event_type`：

- `DASH_FILLED_PREVIOUS_CLOSE`
- `ZERO_TRADE_DASH_EXCLUDED`

範例 data：

```json
[
  {
    "event_id": "evt_...",
    "batch_id": "daily_close:TWSE:2004-02-11",
    "dataset": "daily_close",
    "market": "TWSE",
    "period": "2004-02-11",
    "stock_id": "0000",
    "stock_name": "範例",
    "event_type": "ZERO_TRADE_DASH_EXCLUDED",
    "source_close": "--",
    "stored_close_cents": null,
    "reference_period": null,
    "reference_value_cents": null,
    "note": "excluded because no previous close exists",
    "created_at": "2026-06-04T08:00:00Z"
  }
]
```

### 13.11 `GET /api/v1/ops/summary`

用途：查詢部署狀態摘要。

此 endpoint 權限為 `ops`。第一版只使用目前 config 內的 DB、backup、archive、log 路徑，不接受任意路徑參數。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `skip_systemd` | 否 | `true` 時略過 systemd timer 檢查，方便 Windows 開發環境使用 |

範例 data：

```json
{
  "status": "OK",
  "items": [
    {
      "name": "db",
      "status": "OK",
      "message": "readable tables=6 daily_close=present"
    },
    {
      "name": "backup",
      "status": "OK",
      "message": "readable size=1.1GiB"
    }
  ]
}
```

### 13.12 `POST /api/v1/jobs/update-dataset`

用途：由 PWA 觸發單一資料集的手動更新。

權限：`ops`。

Request body：

```json
{
  "dataset": "daily_close"
}
```

允許的 dataset：

- `daily_close` -> `python3 main.py update-close`
- `attention_notice` -> `python3 main.py update-attention`
- `disposal_notice` -> `python3 main.py update-disposal`
- `legal_investor` -> `python3 main.py update-legal`
- `margin` -> `python3 main.py update-margin`
- `day_trading` -> `python3 main.py update-day-trading`
- `revenue` -> `python3 main.py update-revenue`

規則：

- 只允許上列 dataset，不接受任意 command。
- subprocess 使用 list args，不透過 shell。
- 同一時間只允許一個非 terminal job。
- 若已有 job 執行中，回傳 `409 JOB_ALREADY_RUNNING`。
- job 會寫入 `ops_jobs`，API 重啟後仍可查詢歷史紀錄。

範例 data：

```json
{
  "job_id": "job_20260701090000_1234abcd",
  "dataset": "daily_close",
  "command": ["python3", "main.py", "update-close"],
  "status": "QUEUED",
  "created_at": "2026-07-01T01:00:00Z",
  "started_at": null,
  "finished_at": null,
  "returncode": null,
  "stdout_tail": "",
  "stderr_tail": "",
  "error_message": null,
  "messages": [
    {
      "code": "MANUAL_UPDATE_REQUESTED",
      "level": "INFO",
      "message": "manual dataset update queued"
    }
  ],
  "terminal": false
}
```

### 13.13 `GET /api/v1/jobs`

用途：查詢手動更新 job 歷史。

權限：`ops`。

Query：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `limit` | 否 | 預設 `50`，範圍 `1..200` |

回傳 meta：

- `running_job_id`: 目前執行中或排隊中的 job id；沒有時為 `null`。

### 13.14 `GET /api/v1/jobs/{job_id}`

用途：查詢單一手動更新 job 詳細狀態。

權限：`ops`。

狀態值：

- `QUEUED`
- `RUNNING`
- `DONE`
- `FAILED`

欄位：

- `job_id`
- `dataset`
- `command`
- `status`
- `created_at`
- `started_at`
- `finished_at`
- `returncode`
- `stdout_tail`
- `stderr_tail`
- `error_message`
- `messages`
- `terminal`

API 啟動時若發現重啟前未完成的 job，會標記為 `FAILED`，`error_message` 為 `API restarted before manual update completed`。

## 14. DB 連線與併發

目前 API 原則：

- API 以 read-only 查詢為主。
- 讀取 DB 時優先使用 SQLite read-only URI。
- FastAPI read-only SQLite connections 使用 `check_same_thread=False`，避免 dependency enter/exit 落在不同 thread 時造成隨機 500/503。
- 避免 API endpoint 長時間持有 DB connection。
- 不提供任意 SQL endpoint。
- PWA 手動更新透過 background task 執行 allow-listed `update-*` command。
- 手動更新採 single-writer guard，同一時間只能有一個 `QUEUED` 或 `RUNNING` job。
- 每個手動更新任務回傳 `job_id`，狀態保存在 `ops_jobs`。
- 不開放 rollback、backup、archive、schema migration 或任意 command endpoint。

## 15. 本地管理 PWA 邊界

VeriStockDB PWA 是本地管理控制台，不是雲端多用戶前台。

它可以使用 Local Truth API 顯示：

- DB 狀態。
- dataset 狀態。
- batch 狀態。
- 錯誤與特殊事件。
- 交易日曆。
- Close、注意、處置、法人、資券、當沖、月營收查詢。
- ops-check 摘要。
- 手動更新 job 狀態。

它可以透過 `POST /api/v1/jobs/update-dataset` 執行 allow-listed dataset 更新：

- 使用者手動點擊資料集更新。
- job 寫入 `ops_jobs`。
- PWA 顯示最近 jobs、stdout/stderr tail、return code、error summary。

它不應：

- 解析 CLI stdout。
- 直接連 SQLite。
- 繞過 Local Truth API 讀寫資料。
- 承擔雲端多用戶前台功能。
- 提供任意 command、任意 SQL、回滾、備份、archive 或 schema migration 按鈕。

## 16. 雲端私有專案邊界

雲端 Edge API 與雲端 PWA 是另一個私有專案，不放進 VeriStockDB repo。

VeriStockDB 只預留 export contract：

- `manifest.json`
- `results.json`
- `schema_version`
- `generated_at`
- `trade_date`
- `data_quality`
- `strategies`
- `signals`

雲端私有專案只讀這些精簡 JSON，不連接 VeriStockDB DB，不觸發本地任務，不保存敏感設定。

## 17. 目前實作結構

目前 FastAPI 檔案：

```text
api/
  __init__.py
  __main__.py
  app.py
  dataset_registry.py
  deps.py
  run.py
  schemas.py
  routes/
    __init__.py
    attention_notices.py
    health.py
    info.py
    datasets.py
    daily_close.py
    legal_investors.py
    margin_trading.py
    day_trading.py
    monthly_revenue.py
    disposal_notices.py
    trading_days.py
    table_query.py
    batches.py
    errors.py
    events.py
    ops.py
    jobs.py
```

目前 PWA 靜態檔案：

```text
web/
  index.html
  app.js
  styles.css
  manifest.webmanifest
  service-worker.js
  icons/
```

後續若需要雲端私有專案輸出，可另行加入：

```text
api/routes/exports.py
```

## 18. Local Truth API 規格完成條件

Local Truth API 收斂時應確認：

- [x] 本地 API 與雲端私有專案邊界清楚。
- [x] VeriStockDB PWA 定位為本地管理控制台。
- [x] response envelope 定案。
- [x] 錯誤碼定案。
- [x] 權限模型定案。
- [x] 已完成 dataset endpoint 清單定案。
- [x] `daily_close` 價格欄位使用整數分定案。
- [x] `require_quality` 行為定案。
- [x] 手動更新 jobs 只允許 allow-listed `update-*` commands。
- [x] 手動更新 jobs 有 single-writer guard。
- [x] 手動更新 jobs 持久化到 `ops_jobs`。
- [x] PWA 查詢表格不直接讀 SQLite。
- [x] FastAPI endpoint 已建立。
- [x] `ops/summary` 已納入 ops 權限 endpoint。
