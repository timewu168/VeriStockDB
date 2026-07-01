# 新增資料表 SOP

<!-- i18n-switch -->
[中文](../docs/new_dataset_sop.md) | [English](en/new_dataset_sop.md)
<!-- /i18n-switch -->


本文是 VeriStockDB 之後新增官方資料表時的標準流程。目標是避免重新摸索既有規則，並確保新資料集進入 SQLite canonical truth 前，已完成下載、驗證、dry-run、正式入庫、排程、API、PWA 與文件邊界。

新增資料表時不得跳過本 SOP。若某一步不適用，必須在文件或 release note 中明確標成 deferred 或不適用原因。

## 0. 開工前界線

先確認這次工作只是在「新增資料集」還是會碰到既有 canonical data。

必做：

- 讀 `CURRENT_STATE.md`、`README.md`、`CHANGELOG.md`、`docs/README.md`。
- 讀 `docs/data_ingestion_global_policy.md`。
- 確認 SQLite 仍是 canonical truth；ClickHouse 若有導入，只能是分析/查詢層，不能直接升格為真理來源。
- 確認新資料集是否需要日資料、月資料、公告日、期間資料或其他 period model。
- 確認是否需要 trading day calendar；日資料原則上要用 `trading_days` 做 coverage 驗證。
- 先備份現有 DB，並確認 backup 可讀、`PRAGMA integrity_check` 回傳 `ok`。

未經明確授權不得做：

- drop、truncate、delete、overwrite canonical SQLite data。
- destructive SQL。
- schema migration。
- 啟用、停用或修改正式 systemd timer。
- 刪除 CSV、archive、backup、report、log。
- 將 SQLite canonical truth 移到 ClickHouse。

## 1. 官方來源盤點

先把官方來源查清楚，不要直接寫入庫邏輯。

必做：

- 記錄 TWSE/TPEX/MOPS 或其他來源 URL template。
- 記錄 query parameters、日期格式、民國/西元轉換、market code、response format。
- 確認資料最早可下載日期。
- 確認週末、休市、未公告、未上市、無資料時官方回應長什麼樣子。
- 確認資料單位：股、張、元、千元、百分比、元 * 100 是否需要轉換。
- 確認股票代號欄位必須用文字保存，保留前導零。
- 確認價格類欄位是否要以 cents integer 保存。
- 確認該資料集是日資料、月資料，或公告日/起訖日資料。
- 把 URL 與特殊規則更新到 `docs/URL.txt` 或資料集專屬文件。

建議先做小樣本：

- 早期日期一筆。
- 中期日期一筆。
- 最新日期一筆。
- TWSE/TPEX 各一筆。
- 休市日或未公告日一筆。
- 官方曾改版區間前後各一筆。

## 2. 下載器設計

下載器只負責抓官方原始資料並留存，不做 canonical 入庫。

必做：

- 新增 `download-*` CLI。
- 將 CSV/HTML/JSON 原始檔寫到 `data/csv/<dataset>/<year>/` 或資料集一致的目錄。
- 檔名必須包含可驗證 period、market、dataset；不要只使用官方回傳檔名。
- 下載後要驗證「檔名日期、URL 日期、檔案內容日期」是否一致。
- 對 official request 使用 10 到 15 秒 cooldown；多市場可分開計算，但每個來源都不能連續重打。
- 下載失敗或 cleaner 失敗時最多重試 3 次。
- log 必須能看出 date、market、attempt、cooldown、saved path、failure reason。
- 不可因 0 bytes 以外就視為成功；小檔案、錯誤頁、HTML error body 都要能擋下。

下載器不得做：

- 不得寫 canonical table。
- 不得補值或修資料。
- 不得把官方缺欄當成成功。
- 不得把週末、休市或非交易日當成正式交易日。

## 3. Inspect 工具

在 parser 和入庫前，先做 `inspect-*` 或等價報表。

必做輸出：

- 檔案路徑。
- market。
- period。
- encoding。
- response/content type 判定。
- header row 位置。
- 欄位名稱與欄位數。
- row count。
- 前幾筆樣本。
- 內容日期與預期日期是否一致。
- 是否疑似錯位、缺欄、合計列混入、錯誤頁混入。

Inspect 不入庫。Inspect 發現問題時，先修下載或 parser 判斷，不可直接在入庫時硬補。

## 4. 欄位對應表

在 parser 實作前先寫出欄位對應表，並和使用者確認。

欄位對應表至少包含：

- SQLite column name。
- 官方欄位名稱。
- 是否必要。
- 型別：DATE、TEXT、INTEGER、REAL。
- 單位與轉換規則。
- 空白是否允許。
- 舊格式缺欄時是否允許 `NULL`。
- 是否可由其他欄位推導；原則上不可，例外必須文件化。
- primary key 欄位。
- unique/duplicate 判斷。

規則：

- 官方 numeric 欄位空白不可默默補 `0`。
- 官方缺必要欄位要 fail。
- `NULL` 只允許官方格式真的沒有該 optional 欄位，不能用來吞掉髒資料。
- 合計欄位原則上不入 canonical table，除非該資料集本身就是總表且已明確接受。

## 5. 日期與期間驗證

日期錯誤是 release blocker。

日資料必做：

- API/CLI 接受 `YYYY-MM-DD`；拒絕 `YYYYMMDD` 作為 DB/API 日期值。
- 下載 URL 需要 `YYYYMMDD` 時只在 downloader 轉換。
- 檔案內容日期必須等於請求日期；若官方回傳其他日期，該檔案不可入庫。
- coverage 以 `trading_days` 為準，不可只用週一到週五判斷。
- 早期台股可能有週六交易日，必須相信 `trading_days`，不能硬排除週六。
- 非交易日若官方有回資料，不能當成正式交易日寫入 canonical table，除非該資料集明確是公告日資料。

月資料必做：

- API/CLI 使用 `YYYY-MM`。
- 若官方參數使用民國年月，只能在 downloader/parser 邊界轉換。
- 明確定義「資料月份」與「公告月份」。
- 若有每月固定公告日或順延規則，更新命令要依規則計算 target month。

公告/期間資料必做：

- 明確區分公告日期、處置日期、起始日期、結束日期。
- update horizon 要能涵蓋官方用查詢日回傳期間內資料的情況。
- primary key 不可只憑錯誤日期欄位設計。

## 6. Parser 與 Cleaner

Parser 只把官方原始資料轉為結構化 rows；Cleaner 負責擋髒資料。

必做：

- 支援已知歷史格式版本。
- 對缺 header、缺欄、欄位錯位、錯誤頁、空 numeric 欄位直接 raise。
- 移除總計列、說明列、空列，但要能證明它不是股票資料列。
- 股票代號以文字保存。
- 日期統一轉 `YYYY-MM-DD` 或 `YYYY-MM`。
- 價格若是 DB canonical price，轉成 cents integer。
- 資料品質可疑時回報 `RECHECK`、`BLOCKED` 或 import error，不寫主表。

測試至少覆蓋：

- 正常檔。
- 缺必要欄位。
- numeric 空白。
- 日期不一致。
- 錯位。
- 合計列。
- 休市或無資料檔。
- 歷史格式版本。

## 7. Schema 設計

Schema 先設計，再入庫。

必做：

- 更新 `db/schema.sql`。
- primary key 使用 period + market + stock_id，或資料集合理的唯一鍵。
- index 需支援常用查詢：period range、stock_id、market。
- 註明 canonical 欄位型別與單位。
- 若新增 operational table，要明確標示不是 canonical market data。
- Schema 變更需另行取得授權；不能混在文件或下載工作中偷偷做。

驗證：

- 新 DB 初始化可建立新表。
- 既有 DB migration 路徑清楚，或明確要求人工 migration。
- `sqlite_master` 與 `db/schema.sql` 一致。

## 8. Dry-run 與全量驗證

正式入庫前必須先做 dry-run 和全量報表。

Dry-run 必做：

- 讀所有目標 CSV/HTML/JSON。
- parser/cleaner 全量跑完。
- 不寫 canonical table。
- 輸出 expected rows、accepted rows、skipped rows、problem rows。
- 輸出每 market、每 period row count。
- 輸出 duplicate key 數量。
- 輸出 missing source files。
- 輸出 date coverage gaps。
- 輸出欄位版本分布與異常欄位。
- `BAD=0`、`MISSING=0`、`problems=0` 才能進入正式入庫，除非使用者明確接受已知 gap。

全量驗證必做：

- row count。
- duplicate key。
- latest date/month。
- gap count。
- recent non-OK batches。
- recent errors/events。
- schema validation。
- SQLite `PRAGMA integrity_check`。
- backup 可讀與 integrity check。

## 9. 正式入庫

正式入庫只能在 dry-run 與使用者確認後執行。

必做：

- 入庫前建立 DB backup。
- 入庫前記錄 affected table row count。
- 寫入 `import_batches`。
- parser/cleaner 失敗寫入 `import_errors` 或讓 batch 明確失敗。
- 重要修正、跳過、補救事件寫入 `data_events`。
- 使用 transaction；失敗不可留下半批資料。
- 不覆寫既有 canonical rows，除非使用者明確授權並有 restore path。
- 入庫後跑 integrity check、row count、duplicate key、coverage、latest。
- 入庫後保留 source files，不能立刻刪。

正式入庫完成條件：

- SQLite integrity `ok`。
- row count 符合 dry-run 預期。
- duplicate key `0`。
- coverage gap 符合預期。
- recent non-OK batches 無未解釋問題。
- API smoke 可查到最新資料。

## 10. Update 命令

新增資料集必須有穩定的 `update-*` 命令，除非明確 deferred。

必做：

- 從 DB 最新 canonical period 推導起始點。
- 不能只查 `MAX(period)`；要掃描 latest 前的內部缺口。
- 日資料以 `trading_days` 找應補日期。
- 月資料依公告規則找應補月份。
- 下載、驗證、入庫流程要和歷史匯入共用 parser/cleaner。
- retry 3 次。
- cooldown 10 到 15 秒。
- 失敗時 batch/error/event 有足夠資訊追查 date、market、source、reason。
- 不因某市場缺資料而錯誤寫入另一市場的髒資料。

## 11. 排程

排程必須在資料集正式入庫、update 命令穩定、使用者授權後才建立。

必做：

- 決定 timer 時間，不要和既有資料集打架。
- systemd service 使用固定 WorkingDirectory、EnvironmentFile、log path。
- timer 使用 `Persistent=true`。
- 月資料若需假日順延，用 guard script，不用讓資料流程自己猜測所有排程狀態。
- 排程啟用後至少驗證一次：
  - timer active/enabled。
  - next/last trigger。
  - log 無 ERROR/Traceback/Exception。
  - DB latest 已更新。
  - `schedule-health` 報表狀態合理。

未經授權不得由 Codex 直接 sudo 修改 production systemd。需要時提供指令給使用者手動執行。

## 12. API

新 canonical table 完成後要補 read-only API。

必做：

- 新增 route。
- 支援 date/month range。
- 支援 stock_id。
- 支援 market。
- 支援 fields allow-list。
- 支援 limit/offset。
- 日期格式嚴格驗證：日資料 `YYYY-MM-DD`，月資料 `YYYY-MM`。
- 錯誤格式與既有 API 一致。
- 不回傳未入庫或問題資料作為 canonical result。
- 更新 `docs/local_truth_api_spec.md`。
- 更新 dataset registry/status/health 相關 endpoint。

測試：

- 正常查詢。
- stock_id filter。
- market filter。
- fields allow-list。
- invalid date。
- invalid field。
- pagination。
- quality/problem data rejection。
- concurrent SQLite access smoke。

## 13. PWA

PWA 只透過 Local Truth API，不直接讀 SQLite、不解析 CLI stdout。

必做：

- 加入 dataset status table。
- 加入 dataset health drill-down。
- 加入查詢頁資料集選項。
- 查詢結果表格欄位用中文顯示。
- 若有價格欄位，顯示層依 DB 契約轉換，例如 cents / 100。
- 若要手動更新，必須接到 allow-listed jobs API。
- 不新增任意 shell command 或任意 SQL。
- 更新 service worker cache name，避免舊前端卡住。
- `node --check web/app.js` 通過。

## 14. 文件與發版

每個新增資料表版本至少更新：

- `README.md`
- `CHANGELOG.md`
- `CURRENT_STATE.md`
- `docs/README.md`，若新增專屬文件
- `docs/version_roadmap_checklist.md`
- `docs/local_truth_api_spec.md`
- `docs/URL.txt`
- dataset 專屬 SOP/問題文件，如有必要

發版前檢查：

- `python3 -m unittest discover -s tests`
- 相關 Python compile check
- `node --check web/app.js`，若 PWA 有變更
- `git diff --check`
- public docs 私有路徑/secret 掃描
- DB-changing work 的 integrity、backup、row count、duplicate、coverage、schema checks

Release checklist：

- bump `config.APP_VERSION`
- commit
- tag
- push branch
- push tag

## 15. 最小交接內容

完成後更新 `CURRENT_STATE.md`，只保留下一輪接手必要資訊：

- current stage。
- accepted baseline。
- SQLite/ClickHouse truth boundary。
- data sources and ETL state。
- schema/migration state。
- modified files。
- next gate。
- locked actions。
- required data/db validation checks。
- important paths/latest reports。

不要把聊天歷史、完整 log、推測、secrets 放進交接文件。
