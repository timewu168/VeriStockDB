# VeriStockDB 人本重做規劃書

<!-- i18n-switch -->
[中文](../docs/human_first_rebuild_plan.md) | [English](en/human_first_rebuild_plan.md)
<!-- /i18n-switch -->


版本：v0.2-rebuild-plan  
日期：2026-06-02  
定位：重新規劃一個人用得懂、資料乾淨、能擋官方錯誤的台股 SQLite 資料庫。

## 1. 一句話目標

VeriStockDB 要做的是：

> 把官方台股資料下載回來，先檢查明顯錯誤，錯的擋住，對的才進 SQLite，讓使用者查到的是乾淨可信的資料。

這不是資料工程展示系統，不是倉庫進銷存，也不是每筆資料都要背一堆工程欄位的治理平台。

## 2. 這次重做的核心原則

### 2.0 全局資料入庫規範

這是所有資料表都必須遵守的全局規範，不因 Close、法人、融資、注意股或其他資料種類而例外。

只要官方資料或 CSV 內容出現任何資料品質問題，系統只能做三件事：

1. 發出警告。
2. 停止該批資料入庫。
3. 記錄問題，等待人工檢驗。

系統絕對不能自作主張做以下事情：

- 不能把有問題的資料降級成可入庫資料。
- 不能因為錯誤看起來很小就自動放行。
- 不能自動補值後入庫。
- 不能自動把空白、缺欄、格式漂移、價格異常、家數異常當成可接受資料。
- 不能用 `WARN` 當作「可以入庫」的理由。
- 不能把 CSV 結構問題統一轉成 `NaN` 後再補 0 通過。
- 不能在原始列欄位數不足時，用 pandas 讀取後的 `NaN` 取代原始錯誤。

官方下載或資料檢查失敗時，系統必須先執行最多 3 次重新下載與重新檢查：

```text
第 1 次下載/檢查失敗
  -> 重新下載第 1 次
  -> 重新下載第 2 次
  -> 重新下載第 3 次
  -> 仍失敗才標記 BLOCKED 或 MISSING
```

三次重抓都必須重新取得官方來源，不可重用同一份已知有問題的 CSV。三次後仍有問題，系統只能停止入庫並等待人工檢驗。

只有在使用者人工檢驗後明確判定沒問題，該批資料才可以被人工放行。人工放行必須留下紀錄，至少包含：

- 放行日期時間。
- 放行原因。
- 放行者備註。
- 原本被擋下的原因。

這條規則優先於所有 cleaner、validator、pipeline、importer 的內部邏輯。

最高真理：

> 存進主資料表的資料一定要是正確資料。  
> 只要不能確認正確，就不要入庫。

因此重做版寧可停住、警告、等待人工，也不能為了流程順利而把可疑資料放進主表。

### 2.1 使用者是人，不是機器

使用者需要知道：

- 今天資料有沒有成功入庫。
- 哪一天、哪個資料源有問題。
- 問題是官方檔案缺欄、數字異常、家數不合理，還是下載失敗。
- 哪些資料可以放心查。

使用者不需要在主資料表看到：

- `source_file_id`
- `truth_status`
- `price_status`
- `created_at`
- `updated_at`
- 每筆資料的驗證日期
- 每筆資料的入庫日期
- SF 代碼或工程用追蹤代碼

這些資訊若真的需要，只能放在批次狀態或系統日誌，不能污染主要查詢資料。

### 2.2 主資料表只放「人想查的股票資料」

例如 Close 日收盤資料表，只應該像這樣：

```text
trade_date
stock_id
stock_name
market
open
high
low
close
volume
amount
transactions
```

主資料表的責任只有一個：提供乾淨資料。

驗證狀態、來源檔案、錯誤原因、重抓次數，都放在旁邊的批次表，不放進主資料表。

### 2.3 用一個批次狀態代表資料是否可用

資料是否正確、是否驗證、是否需要月復驗，不應該拆成很多欄位。對使用者來說，一個狀態就夠。

建議狀態：

| 狀態 | 意義 | 主資料是否可用 |
|---|---|---|
| `OK` | 已通過檢查並入庫 | 可用 |
| `BLOCKED` | 官方資料有問題，已擋下 | 不可用 |
| `RECHECK` | 資料可疑，已停止入庫，等待人工檢驗或後續官方資料 | 不可用 |
| `FIXED` | 曾有問題，經人工確認或後續官方資料修正後重新入庫 | 可用 |
| `MISSING` | 官方資料尚未提供或下載失敗 | 不可用 |

狀態粒度是「批次」，不是每筆股票資料。

範例：

```text
2024-06-03 daily_close TWSE = OK
2024-06-03 daily_close TPEX = BLOCKED
2024-06 monthly_revenue TWSE = RECHECK
```

### 2.4 防線不可裁剪清單

重做是為了砍掉過度工程化，不是砍掉資料防線。以下防線缺一不可：

| 防線 | 人本版做法 | 不要變成 |
|---|---|---|
| 原始 CSV 結構檢查 | pandas 之前先逐列檢查欄位數 | 讀進 DataFrame 後用 NaN 掩蓋 |
| 有問題資料重抓 | 官方來源最多重新下載 3 次 | 同一壞檔重試或直接跳過 |
| 重抓節流 | 官方請求之間保留冷卻時間並顯示進度 | 背景狂打官方 API |
| Fail-fast | 三次仍失敗就停止該批或該段匯入 | 繼續跑到後面才發現中間破洞 |
| 三日回滾 | 每日更新重檢 `T / T-1 / T-2` | 只抓今天 |
| 交易日判斷 | 非交易日不下載、不入庫 | 空資料也當成正常批次 |
| 代號保真 | stock_id 永遠當文字，保留前導零 | 轉數字或自動補零 |
| 家數波動 | 異常就停止，人工確認才放行 | 歷史資料自動降級成 WARN |
| 官方 double-check | 可取得第二官方資料時要交叉核對 | 只相信單一解析結果 |
| 月度零容忍 | 月度檢查必須完全一致才封存 | 日常容忍沿用到最終資料 |
| ZIP 後刪 CSV | 月檢查通過、ZIP 驗證成功後才刪 loose CSV | 入庫成功就刪 |
| 交易式寫入 | 整批通過才覆蓋正式資料 | 部分成功部分寫入 |
| 防線測試 | 每條防線都要有回歸測試 | 只靠人工記憶 |

## 3. data 目錄重新設計

重做後只保留三個主要資料夾：

```text
data/
  csv/
  db/
  backup/
```

### 3.1 `data/csv`

用途：放官方下載 CSV。

規則：

- 只存「必要保留」的官方來源檔。
- 成功入庫後，原始 CSV 先留存，不立刻刪除。
- 等後續月度檢查完成，並且該月份 CSV 已加入 ZIP 封存後，才刪除 loose CSV。
- 被擋下的問題 CSV 必須保留，直到人工檢驗或官方資料修正完成。
- 不再建立多層 raw、archive、tmp、reports 結構。
- 不讓 CSV 永久無限制累積。

建議結構：

```text
data/csv/
  daily_close/
    2024/
      20240603CloseSII.csv
      20240603CloseOTC.csv
  monthly_zip/
    daily_close_2024_06.zip
```

CSV 處理順序固定為：

```text
下載 CSV
  -> 檢查
  -> 成功入庫
  -> loose CSV 先留存
  -> 月度檢查通過
  -> 加入 ZIP 封存
  -> ZIP 驗證成功
  -> 刪除 loose CSV
```

禁止在「成功入庫」當下直接刪 CSV。

### 3.2 `data/db`

用途：放正式 SQLite DB。

建議：

```text
data/db/
  veristock.db
```

不要同時放一堆正式 DB、副本 DB、測試 DB。測試 DB 應放在測試暫存位置，不放進正式 data。

### 3.3 `data/backup`

用途：放 DB 備份。

規則：

- 預設只保留 1 份最新備份。
- 做重大重建或 schema 變更時，可以手動多留一份。
- 不產生每個月、每個流程、每次 VACUUM 都一份的備份海。

建議：

```text
data/backup/
  veristock_latest_backup.db
```

## 4. SQLite schema 重新設計

### 4.1 核心資料表：`daily_close`

```sql
CREATE TABLE daily_close (
  trade_date TEXT NOT NULL,
  stock_id TEXT NOT NULL,
  stock_name TEXT,
  market TEXT NOT NULL CHECK (market IN ('TWSE', 'TPEX')),
  open INTEGER,
  high INTEGER,
  low INTEGER,
  close INTEGER,
  volume INTEGER,
  amount INTEGER,
  transactions INTEGER,
  PRIMARY KEY (trade_date, stock_id, market)
);

CREATE INDEX idx_daily_close_date ON daily_close(trade_date);
CREATE INDEX idx_daily_close_stock ON daily_close(stock_id);
CREATE INDEX idx_daily_close_date_stock ON daily_close(trade_date, stock_id);
```

設計理由：

- 價格一律用「元價 * 100」後的整數分儲存，避免浮點誤差；這是不變鐵律。
- CLI、匯出報表或 read-only view 可以顯示 `/ 100` 後的人可讀元價，但主資料表儲存永遠是整數分。
- 不可把價格改成 SQLite `REAL`。
- 不放工程欄位。
- `stock_id` 必須是 `TEXT`，不能轉成整數，避免 `006201` 類型前導零被吃掉。
- 以交易日和股票代號為主要查詢條件的主資料表，都必須建立 `(trade_date, stock_id)` 複合索引。
  這是回測、選股與跨資料表 join 的固定索引規範；未來注意股、處置股、法人、資券、當沖、月營收等資料表也要比照辦理。

### 4.2 批次狀態表：`import_batches`

```sql
CREATE TABLE import_batches (
  batch_id TEXT PRIMARY KEY,
  dataset TEXT NOT NULL,
  market TEXT,
  period TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OK', 'BLOCKED', 'RECHECK', 'FIXED', 'MISSING')),
  row_count INTEGER,
  error_summary TEXT,
  source_file TEXT,
  source_sha256 TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  archived_zip TEXT,
  checked_at TEXT NOT NULL,
  manual_approved INTEGER NOT NULL DEFAULT 0,
  manual_approved_at TEXT,
  manual_approved_reason TEXT,
  note TEXT
);

CREATE UNIQUE INDEX uq_import_batches_scope
ON import_batches(dataset, market, period);
```

範例：

| dataset | market | period | status | error_summary |
|---|---|---|---|---|
| daily_close | TWSE | 2024-06-03 | OK | |
| daily_close | TPEX | 2024-06-03 | BLOCKED | close price is blank |
| daily_close | TWSE | 2024-06-04 | MISSING | download failed |

這張表是使用者判斷資料可不可用的入口。

這也是重做版的來源追蹤邊界：  
**來源追蹤放在批次層級，不放進每一筆股價資料。**

人工放行規則：

- `manual_approved = 1` 只能由人工操作設定。
- `manual_approved_reason` 不可空白。
- 系統自動流程不能把 `manual_approved` 從 0 改成 1。
- 人工放行後若要入庫，必須重新跑同一批匯入流程，不能直接把被擋資料硬塞進主表。

### 4.3 錯誤明細表：`import_errors`

```sql
CREATE TABLE import_errors (
  error_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('WARN', 'BLOCK')),
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  sample_stock_id TEXT,
  sample_value TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id)
);
```

這張表只在要查問題時使用。一般使用者不用看。

### 4.4 系統設定表：`settings`

```sql
CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

用途：

- 備份保留份數。
- loose CSV 刪除條件：跨月、該月最後交易日的三日回滾完成、月度檢查通過、ZIP 封存與驗證成功。
- 官方請求冷卻秒數範圍：預設 10 到 15 秒隨機。
- 月度 ZIP 封存完成後是否刪除 loose CSV，預設是刪除。
- 目前資料庫版本。

CSV 不採用「保留 N 天」作為主要刪除規則。  
刪除必須跟資料正確性流程綁定，而不是跟時間長短綁定。

### 4.4 特殊事件表：`data_events`

`data_events` 是共用的稀疏事件表，只記錄特殊列，不記錄正常列。
它用來保留補值、排除、人工修正等 row-level provenance，避免污染主資料表。

```sql
CREATE TABLE data_events (
  event_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  dataset TEXT NOT NULL,
  market TEXT,
  period TEXT NOT NULL,
  stock_id TEXT,
  stock_name TEXT,
  event_type TEXT NOT NULL,
  source_open TEXT,
  source_high TEXT,
  source_low TEXT,
  source_close TEXT,
  stored_open INTEGER,
  stored_high INTEGER,
  stored_low INTEGER,
  stored_close INTEGER,
  reference_period TEXT,
  reference_value INTEGER,
  note TEXT,
  created_at TEXT NOT NULL
);
```

Close `--` 規則至少要記錄兩種事件：
- `DASH_FILLED_PREVIOUS_CLOSE`：OHLC 由前一個有效收盤價承接入庫。
- `ZERO_TRADE_DASH_EXCLUDED`：成交股數、成交金額、成交筆數皆為 0，且無前收可承接，因此該列排除入庫。

這張表的目的，是讓未來若找到更早的歷史資料庫，可以回頭辨識哪些資料曾被排除或補值，並規劃恢復流程。

### 4.5 交易日表：`trading_days`

三日回滾、歷史建庫、非交易日略過，都需要穩定的交易日來源。這是支援表，不是使用者主要查詢表。

```sql
CREATE TABLE trading_days (
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
);
```

規則：

- 非交易日不下載、不入庫、不產生 `OK` 批次。
- 歷史區間進度必須以交易日計算，不用日曆日假裝進度。
- 交易日來源有問題時，停止匯入，不能猜。

## 5. 匯入流程重新設計

### 5.1 Close 匯入流程

```text
取得 CSV
  -> 來源可以是官方下載，也可以是使用者上傳或指定舊 CSV
  -> 官方下載失敗或檔案異常時，最多重新下載 3 次
  -> 本地舊 CSV 檔案異常時，不重抓，直接標記 BLOCKED 或 RECHECK
  -> 每次官方請求遵守 10 到 15 秒隨機冷卻時間
  -> 先檢查原始 CSV 每列欄位數
  -> 檢查檔案是否存在、是否空檔
  -> 檢查欄位是否符合預期
  -> 檢查股票代號、日期、市場
  -> 檢查價格欄位
  -> 檢查 OHLC 合理性
  -> 檢查家數是否異常
  -> 可取得第二官方來源時執行 double-check
  -> 有 BLOCK 就不寫入 daily_close
  -> 通過才用交易式寫入 daily_close
  -> 寫一筆 import_batches 狀態
```

核心規則：

- 任何會污染正式資料表的錯誤，一律擋在入庫前。
- 入庫失敗時，只更新批次狀態，不動正式資料。
- 同一批資料重跑時，用同一個 `(dataset, market, period)` 覆蓋批次狀態。
- `WARN` 只代表警告與停止，不代表可入庫。
- 只有 `OK` 或人工放行後的批次可以寫入主資料表。
- 人工放行必須留下 `manual_approved` 紀錄，不能只改狀態。
- 寫入必須是 all-or-nothing：整個日期、市場批次通過後才替換正式資料。
- 新資料沒有完整通過前，不可覆蓋舊的正確資料。

CSV 來源規則：

- 官方下載 CSV 和使用者上傳/指定的舊 CSV，都必須走同一套檢查流程。
- 舊 CSV 不因為是本地檔案就跳過原始欄位數、欄位名稱、價格、家數、代號污染等檢查。
- 舊 CSV 若檢查失敗，不能自動入庫；只有官方下載來源才有「重新下載 3 次」。
- 舊 CSV 若失敗，標記 `BLOCKED` 或 `RECHECK`，等待人工處理。

重抓與節流規則：

- 第一次官方請求後，後續重抓或跨日期下載都必須等待冷卻時間。
- 預設冷卻時間改為 10 到 15 秒隨機，避免對官方來源造成壓力，也避免固定節奏請求。
- 冷卻等待要在 CLI 進度中顯示為一般資訊，不要讓使用者以為卡住。
- 冷卻不是警告；資料問題才是警告。

### 5.2 三日回滾防線

三日回滾是第一版就要保留的基本防線，不是進階功能。

每日更新某一天 `T` 的 Close 時，系統不只檢查 `T`，也要重新下載並重檢最近三個交易日：

```text
T
T-1
T-2
```

目的：

- 官方日資料有時會延遲修正。
- 前兩個交易日可能在後續下載時變成正確版本。
- 可以抓出前一天已入庫、但後來官方修正的資料。

三日回滾規則：

- 每個交易日、每個市場都走同一套「最多重抓 3 次」規則。
- 回滾重檢發現資料仍一致，批次維持 `OK`。
- 回滾重檢發現資料被官方修正，重新驗證後更新主表，批次狀態記為 `FIXED`。
- 回滾重檢發現新問題，標記 `RECHECK` 或 `BLOCKED`，並停止該批資料使用。
- 不因為資料已經入庫過，就跳過檢查。

這裡的回滾只保留三天，先不做複雜自癒系統。

### 5.3 官方 double-check 防線

double-check 不是大型量化公司的功能，而是個人用戶避免髒資料入庫的保險。

規則：

- 若官方提供第二種可取得的資料來源，匯入後、寫入前要做交叉核對。
- Close 價格欄必須完全一致。
- 列存在性必須一致：不能本地有、官方沒有，或官方有、本地沒有。
- 日常成交量若官方來源本身存在暫時差異，可以標記 `RECHECK`，但不能當成 `OK` 入庫。
- 月度檢查不得使用日常容忍，必須零容忍。

如果 double-check 失敗：

```text
RECHECK 或 BLOCKED
停止入庫
保留 CSV
等待後續官方修正或人工檢驗
```

### 5.4 月復驗重新定義

月復驗不要是一堆欄位，也不要讓使用者被迫理解生命週期。

新的定義：

> 月復驗只是一次「批次狀態重新確認」。

如果月資料確認日資料沒問題：

```text
OK 維持 OK
```

如果月資料發現日資料有問題：

```text
OK -> RECHECK 或 BLOCKED，並停止使用該批資料
```

如果重新下載後修好：

```text
RECHECK/BLOCKED -> FIXED
```

如果人工檢驗後確認官方資料雖然觸發警告但可接受：

```text
RECHECK/BLOCKED -> OK，並記錄人工放行原因
```

主資料表不需要多一個月復驗欄位。

月度檢查必須保留原本專案討論出的零容忍原則：

- 月度資料與本地日資料做完整比對。
- 日期、股票代號、市場、OHLC、成交股數、成交金額、成交筆數都必須一致。
- 任何差異都不能封存，必須標記 `RECHECK` 或 `BLOCKED`。
- 月度檢查通過後才可以 ZIP 封存。
- ZIP 必須檢查可開啟、檔案清單一致、CRC 正常，才能刪 loose CSV。

這是「最終資料」的防線，不是工程裝飾。

## 6. 使用者入口

重做後先不要做複雜 PWA。先做三個清楚入口即可。

### 6.1 CLI

```powershell
python main.py init-db
python main.py import-close --date 2024-06-03
python main.py rollback-close --date 2024-06-03
python main.py import-close --from 2010-01-01 --to 2024-12-31
python main.py status
python main.py status --dataset daily_close
python main.py audit-month --dataset daily_close --month 2024-06
python main.py archive-month --dataset daily_close --month 2024-06
python main.py backup
```

### 6.2 狀態輸出

`status` 應該讓人一眼看懂：

```text
daily_close
  OK       3650 batches
  BLOCKED 2 batches
  RECHECK 1 batch
  MISSING 0 batches

Latest problem:
  2024-06-03 TPEX BLOCKED close price is blank
```

### 6.3 查資料

最基本查詢：

```powershell
python main.py query-close --stock-id 2330 --from 2024-01-01 --to 2024-12-31
python main.py query-close --date 2024-06-03
```

或者之後再加簡單 localhost API。API 是後面再做，不是第一階段核心。

## 7. 第一版只做 Close

重做第一版只做：

- `daily_close`
- `import_batches`
- `import_errors`
- `settings`
- CSV 下載、本地舊 CSV 上傳/指定匯入
- 入庫前驗證
- 交易日判斷
- 三日回滾
- 官方 double-check
- 月度零容忍檢查
- 狀態查詢
- 單一 DB 備份
- CSV 入庫後留存，等待月度檢查與 ZIP 封存

先不要做：

- 法人
- 融資融券
- 當沖
- 月營收
- 注意股
- 處置股
- PWA
- ClickHouse
- API gateway
- 多機部署
- 複雜封存 manifest
- 每筆資料 source id
- 多階段 truth status

理由很簡單：如果 Close 這個核心資料都不能做到簡單可信，其他功能只會放大混亂。

## 8. 程式結構重新設計

建議新專案結構：

```text
VeriStockDB/
  main.py
  config.py
  db/
    schema.sql
    connection.py
  ingest/
    close_importer.py
    downloader.py
    csv_reader.py
    trading_calendar.py
  validate/
    close_rules.py
    result.py
  services/
    batch_status.py
    monthly_audit.py
    monthly_archive.py
    backup.py
  tests/
  data/
    csv/
    db/
    backup/
  docs/
    human_first_rebuild_plan.md
  README.md
```

不要再拆成過多層：

- `core`
- `pipelines`
- `orchestrator`
- `healer`
- 大型 `archive` lifecycle 平台
- `source_file_service`
- `monthly_finalization_policy`

這些概念不是永遠不能有，而是第一版不需要。

注意：`monthly_audit.py` 和 `monthly_archive.py` 只做月度零容忍與 ZIP，不恢復舊版大型 lifecycle / manifest 平台。

## 9. 驗證規則

第一版 Close 只做必要防線。

### 9.1 原始 CSV 結構檢查

原始 CSV 結構檢查必須在 pandas 或任何資料框架讀取之前完成。

原因：

> 表頭有 10 個欄位，但某一檔股票只有 9 個欄位，這是 CSV 結構錯誤或官方匯出問題，不是普通 `NaN`。

必須明確區分：

| 類型 | 意義 | 處理方式 |
|---|---|---|
| 空值 | 欄位存在，但內容是空字串或空白 | BLOCK，停止入庫 |
| 空欄位 | 該列欄位數少於表頭欄位數 | BLOCK，停止入庫 |
| 沒數據 | 官方回傳空檔、無資料頁、或只有表頭沒有資料列 | MISSING 或 BLOCK，停止入庫 |
| NaN | 程式讀取後的內部表示 | 不可直接當成原始問題類型 |

檢查規則：

- 先用原始文字逐列檢查欄位數。
- 每一列欄位數必須等於表頭欄位數。
- 欄位數不足或多出欄位，都視為 CSV 結構異常。
- CSV 結構異常時，最多重新下載 3 次。
- 三次後仍異常，標記 `BLOCKED`，不可入庫。
- 不可把少欄位產生的 `NaN` 補成 0。
- 一般缺值記號不可自動轉成 0。
- Close 價格欄的 `--`、`---`、`----` 是專屬規則，依「9.4 Close 無成交與停交易記號」處理。

錯誤範例：

```text
表頭：日期,代號,名稱,開盤,最高,最低,收盤,成交股數,成交金額,成交筆數
資料：2024-06-03,2330,台積電,839,846,837,846,12345678,987654321
```

這列只有 9 個資料欄位，缺少 `成交筆數`。  
這是 `EMPTY_COLUMN` 或 `ROW_FIELD_COUNT_MISMATCH`，不是可以補 0 的 `NaN`。

### 9.2 檔案級檢查

- 檔案存在。
- 檔案非空。
- 可解碼。
- 欄位名稱可辨識。
- CSV 列數合理。

### 9.3 欄位級檢查

- 股票代號不可空白。
- 股票名稱不可空白。
- 日期必須等於目標日期。
- 市場只能是 TWSE 或 TPEX。
- OHLC 不可為負。
- volume、amount、transactions 不可為負。

欄位級檢查是在原始 CSV 結構檢查通過後才執行。  
如果原始列已經少欄或破列，不可進入數值轉換階段。

### 9.4 Close 無成交與停交易記號

Close 日收盤資料有一個重要例外：  
當天有開市，但某檔股票沒交易或停止交易時，官方可能在價格欄位使用：

```text
--
---
----
```

這不是 CSV 結構錯誤，也不是可以補 0 的缺值。  
這是官方表示「該股票當天無成交或停止交易」的資料語意。

處理規則：

- 只在 Close 的價格欄位套用此規則。
- 必須先確認原始 CSV 欄位數正確，不能用這條規則掩蓋少欄或破列。
- `--`、`---`、`----` 不可轉成 0。
- `--`、`---`、`----` 不可一律視為 `BLOCKED`。
- 若該股票當天無成交或停止交易，OHLC 應依既有 Close 規則使用前一個有效收盤價承接。
- 若 OHLC 由前收承接入庫，必須在 `data_events` 記錄 `DASH_FILLED_PREVIOUS_CLOSE`。
- 成交股數、成交金額、成交筆數若官方表示無交易，才可依規則記為 0。
- 若找不到前一個有效收盤價，該批資料標記 `RECHECK`，停止入庫，等待人工檢驗。
- 但早期冷啟動資料若同一列成交股數、成交金額、成交筆數皆為 0，且 OHLC 全為 `--` / `---` / `----`，代表該標的尚未出現可用價格；該列可排除入庫並記錄排除數量，不可填 0，也不是永久排除該代號。
- 若早期冷啟動列被排除，必須在 `data_events` 記錄 `ZERO_TRADE_DASH_EXCLUDED`。
- 如果 `--`、`---`、`----` 出現在非 Close 價格欄，不能套用本例外，必須按一般資料異常處理。

這條規則的目的不是放寬防線，而是避免把官方正常的無成交表示誤判成髒資料。

### 9.5 價格合理性

- high >= open
- high >= close
- high >= low
- low <= open
- low <= close
- open、high、low、close 不可全部空白

價格合理性檢查應在 Close 無成交與停交易記號轉換後執行。  
如果是有效無成交情境，OHLC 承接後仍必須滿足價格合理性。

### 9.6 市場家數檢查

同一市場的家數若相對前一交易日變動過大，標記 `RECHECK` 或 `BLOCKED`。

第一版可以採保守規則：

- 變動小於 5%：OK
- 變動 5% 到 10%：RECHECK，停止入庫，等待人工檢驗
- 變動超過 10%：BLOCKED

注意：`RECHECK` 不是降級入庫。只要進入 `RECHECK`，該批資料就不能寫入主資料表，除非人工檢驗後明確放行。

### 9.7 代號污染檢查

必須保留這條防線，因為過去已經發生 `6201 / 006201` 類型問題。

規則：

- 股票代號以官方原文讀入。
- 不全域自動補零。
- 同日同市場同代號只能有一筆。
- 同日跨市場若代號衝突，必須確認是否為合法情境，不能直接合併。

### 9.8 資料列篩選規則

官方 Close 來源可能混入非目標資料，例如權證、標頭殘列、說明列。

規則：

- 篩選規則必須白紙黑字寫在文件與測試裡。
- TPEX 權證等非目標列可依明確規則排除。
- 資料區中突然插入說明列、公告文字、非證券代號列，不可靜默略過。
- 不確定是不是官方正常列時，停止並交給人工檢驗。

這條防線是為了避免「看起來可以 parse」的髒列混進資料庫。

### 9.9 回歸測試清單

重做版不能只靠規劃書記憶，以下案例必須有測試：

- 表頭 10 欄、資料列 9 欄時阻斷，不可補 0。
- Close `--`、`---`、`----` 可依前收承接，不可當 0。
- Close 找不到前收時 `RECHECK`，不可用 0 入庫。
- `6201` 不可變成 `006201`。
- `006201` 前導零不可被吃掉。
- TPEX 權證依規則排除。
- 家數異常不可因歷史資料自動降級入庫。
- 官方下載或驗證失敗最多重抓 3 次，仍失敗就停止。
- 三日回滾會重檢 `T / T-1 / T-2`。
- double-check 價格不一致時停止。
- 月度零容忍不通過時不可 ZIP 封存。
- ZIP 驗證失敗時不可刪 loose CSV。
- 匯入失敗不可覆蓋既有正確資料。

## 10. 重做階段

### Phase 0：凍結舊專案

目的：停止在舊架構上繼續加功能。

產出：

- 保留舊 repo 作參考。
- 新開乾淨資料夾或乾淨分支。
- 只搬必要規則，不搬複雜架構。

### Phase 1：建立最小 DB

產出：

- `data/db/veristock.db`
- `daily_close`
- `import_batches`
- `import_errors`
- `settings`
- `trading_days`

驗收：

- 可以初始化 DB。
- schema 人看得懂。
- 沒有工程欄位污染主資料表。

### Phase 2：本地 CSV 匯入 Close

產出：

- 從 `data/csv/daily_close` 匯入本地舊 CSV，或由使用者指定 CSV 檔案。
- 通過驗證才寫入 `daily_close`。
- 失敗只寫入 `import_batches` / `import_errors`。

驗收：

- 錯資料不會進主表。
- 舊 CSV 和官方下載 CSV 使用同一套檢查規則。
- 狀態查詢能說明哪一天、哪個市場出錯。

### Phase 3：官方下載 Close

產出：

- TWSE Close 下載。
- TPEX Close 下載。
- 下載後走同一套本地匯入流程。
- 下載失敗、空檔、格式異常或驗證失敗時，最多重新下載 3 次。
- 官方請求遵守 10 到 15 秒隨機冷卻時間，進度要讓人看得懂。

驗收：

- 下載失敗標記 `MISSING`。
- 官方格式異常標記 `BLOCKED`。
- 不因為下載成功就直接入庫。
- 三次重抓後仍失敗才停止並記錄最終狀態。

### Phase 4：歷史 Close 建庫

產出：

- 指定日期區間批次匯入。
- 進度清楚顯示起訖日、目前日期、總數、成功/失敗數。

驗收輸出範例：

```text
Range: 2010-01-01 -> 2024-12-31
Progress: 120 / 3650
Current: 2010-06-30 TWSE
OK: 238
BLOCKED: 1
MISSING: 1
```

### Phase 5：三日回滾更新

產出：

- 每日更新時自動重檢 `T / T-1 / T-2` 三個交易日。
- 三天內官方修正資料時，重新驗證後更新主表。
- 三天內資料變成有問題時，停止使用並標記批次狀態。

驗收：

- 不因為某日資料已入庫就跳過重檢。
- 每個回滾日都遵守最多重抓 3 次規則。
- 發現差異時有清楚狀態：`OK`、`FIXED`、`RECHECK`、`BLOCKED` 或 `MISSING`。

### Phase 6：月度零容忍與 ZIP 封存

產出：

- `python main.py audit-month --dataset daily_close --month YYYY-MM`
- 跨月後，確認該月最後交易日的三日回滾已完成。
- 月度資料完整比對。
- 月度檢查通過後才允許 ZIP 封存。
- ZIP 驗證成功後才允許刪 loose CSV。

驗收：

- 不以 CSV 保留天數決定刪除。
- 月度差異一律 `RECHECK` 或 `BLOCKED`。
- 不接受日常容忍延伸到月度最終資料。
- ZIP 壞掉、內容不一致、CRC 失敗時，不刪 CSV。

### Phase 7：備份與清理

產出：

- `python main.py backup`
- 預設只保留 1 份最新備份。
- CSV 成功入庫後先留存。
- 跨月且該月最後交易日三日回滾完成後，才做月度檢查。
- 月度檢查通過後，把該月份 CSV 加入 ZIP 封存。
- ZIP 驗證成功後，才刪除 loose CSV。

驗收：

- `data/` 不會無限制膨脹。
- 使用者知道哪些檔案可以刪、哪些不能刪。
- 系統不會在入庫成功當下刪除官方 CSV。

## 11. 明確砍掉的舊設計

以下內容不進入重做第一版：

| 舊設計 | 新決策 |
|---|---|
| 每筆資料 `truth_status` | 改為批次狀態 |
| 每筆資料 `source_file_id` | 改為批次來源檔 |
| 每筆資料 `created_at` / `updated_at` | 不放主資料表 |
| `price_status` | 不放主資料表 |
| 多階段 RAW/CLEANED/VALIDATED/ARCHIVED | 改為 OK/BLOCKED/RECHECK/FIXED/MISSING |
| `data/raw` | 合併到 `data/csv` |
| `data/archive` | 不另開資料夾；月度 CSV ZIP 放在 `data/csv/monthly_zip` |
| `data/reports` | 錯誤寫 DB，需要時再輸出 |
| 每月 ZIP manifest | 第一版只做簡單 ZIP 與驗證，不做複雜 manifest |
| PWA 控制台 | 第一版不做 |
| 多資料表骨架 | 第一版只做 Close |
| ClickHouse | 第一版不做 |
| 多機部署 | 第一版不做 |

## 12. 成功標準

重做版成功，不是因為功能多，而是因為它符合以下條件：

1. 使用者打開 DB，看得懂主要資料表。
2. 官方資料錯誤時，錯資料不會進主表。
3. 使用者能用一個狀態知道資料可不可用。
4. `data/` 目錄不會失控膨脹。
5. Close 歷史資料可以重建。
6. 有問題資料會最多重新下載 3 次，仍失敗才停止並記錄。
7. 每日更新會回滾三個交易日重檢，抓出官方後續修正。
8. 月度檢查零容忍，通過後才 ZIP 封存並刪 loose CSV。
9. 每條核心防線都有測試，不靠人腦記。
10. 程式碼少、入口少、狀態少。
11. 未來要加法人、融資、注意股時，複製同一套簡單模型，而不是引入大型平台。

## 13. 開源版邊界

這個專案是要開源給個人用戶，不是給大型量化交易公司。

開源版應該做到：

- clone 下來後能看懂資料夾。
- 不需要多機、不需要 ClickHouse、不需要 API gateway。
- 不需要理解資料工程術語才能使用。
- 預設只在本機跑。
- repo 只放程式、文件、少量測試樣本。
- 不把個人 DB、完整 CSV、備份檔、ZIP 封存推上 GitHub。
- README 第一屏就說明：這是一個乾淨台股資料庫，不是交易建議系統。

個人用戶需要的是可信資料和清楚狀態，不是大型平台。

## 14. 最終結論

VeriStockDB 應該重做成一個「乾淨資料庫」，而不是「資料治理平台」。

第一版只要把 Close 做到：

- 可下載
- 可檢查
- 可擋錯
- 可入庫
- 可查狀態
- 可備份

就已經符合原始需求。

其他功能等這個核心穩定後再加。不要讓未來可能需要的架構，壓垮今天真正要用的人。
