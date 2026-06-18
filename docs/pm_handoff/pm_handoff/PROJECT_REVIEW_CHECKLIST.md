# VeriStockDB Review Checklist

產出日期：2026-06-06  
用途：PM 審核 worker 回報與 release 收斂時使用。

## PM 審核 worker 回報必查

- 是否說明本次任務範圍，且沒有偷做未要求功能。
- 是否列出 modified files。
- 是否列出實際執行命令與結果。
- 是否有 `git status --short --branch`。
- 是否有測試結果，不接受只寫「應該可以」。
- 是否有資料入庫後的 `status --dataset ...` 與 `status --dataset ... --problems --details`。
- 若是 server 任務，是否提供 server 實際輸出。
- 若是 official download 任務，是否顯示 date/market/range 與失敗原因。
- 是否更新 README / CHANGELOG / docs。
- 是否明確標出未驗證項目。
- 是否避免把 user 未追蹤檔案 stage 進 commit。

## 程式碼審核項目

- 是否符合現有 code style 與既有 module pattern。
- 是否沿用 close/attention/disposal 的 import/query/API 結構。
- 是否避免過度抽象與不必要重構。
- 是否沒有任意 SQL endpoint、shell endpoint、或 public admin API。
- 是否沒有讓 PWA/API 解析 CLI stdout。
- 是否沒有把官方缺值補 `0`。
- 是否沒有全域補 stock_id leading zero。
- 是否 market/date/stock_id query index 足夠。
- 是否 batch id / dataset / market / period 規則一致。
- 是否錯誤訊息能顯示日期、市場、資料來源、原因。
- 是否 cooldown/retry 邊界在 importer/service，而不是 cleaner。
- 是否 Telegram 通知失敗保持 non-fatal。
- 是否 token/env/secrets 沒有寫進 repo。

## 測試審核項目

- 是否跑過：

```powershell
python -m unittest discover -v
```

- 若環境沒有 `python`，是否說明替代 Python 路徑。
- 是否新增或更新對應 tests。
- 新 dataset 至少要測：
  - parser 正常資料。
  - 缺必要欄位。
  - 空白 numeric 欄位。
  - 無資料但代表 coverage 的官方檔。
  - official update range。
  - duplicate/upsert 行為。
  - API query by `stock_id` without `market`。
  - `status --dataset`。
- Close 相關修改必測：
  - dash 補前收。
  - dash 無前收排除。
  - `data_events`。
  - rollback。
  - trading calendar update。
- API 修改必測：
  - auth on/off。
  - envelope。
  - invalid params。
  - pagination。
  - `require_quality`。
- Telegram 修改必測：
  - disabled mode 不打網路。
  - missing token/chat id skip。
  - HTTP error returned not raised。
  - 中文訊息格式。

注意：

- 目前 `.gitignore` 排除 `tests/`，PM 必須確認測試是否只作本機驗證，或需另開政策讓 tests 上傳。

## 文件審核項目

- README 是否有新命令 quickstart。
- CHANGELOG 是否記錄版本與未發布變更。
- `docs/URL.txt` 是否加入官方 URL 與日期格式。
- dataset 規格是否說明欄位、主鍵、index、空資料處理。
- API 文件是否加入 endpoint 與 query params。
- Ubuntu 部署文件是否有 service/timer 範例。
- 中文顯示與 machine-readable token 是否分清。
- backlog 功能是否只寫成 backlog，沒有暗示已完成。
- 任何待確認內容是否標示 `待確認`。

## DB / 資料完整性審核項目

- schema 是否 idempotent。
- 是否建立適合回測查詢的 `(trade_date, stock_id)` index。
- 主鍵是否可避免同批資料重複入庫。
- `import_batches` 是否寫入正確 status。
- `import_errors` 是否記錄可追查原因。
- `data_events` 是否記錄人工或規則補值/排除。
- 失敗 import 是否不覆蓋既有正確資料。
- duplicate import 是否不破壞資料。
- `status --problems --details` 是否乾淨。
- DB 修改前是否備份。
- historical CSV 是否匯入後可封存或移出。
- archive zip 是否驗證後才刪 loose CSV。
- backup restore smoke test 是否可讀。

## 架構一致性審核項目

- 本 repo 是否仍定位為 Local Truth DB。
- 雲端 Edge API 是否未混入本 repo。
- PWA 是否只走 Local Truth API。
- API 是否 read-only 為主。
- CLI 是否維持人類可讀，API 是否維持 JSON contract。
- 新 dataset 是否遵守 global ingestion policy。
- 新 dataset 是否有 batch/error/event 設計。
- 新功能是否放在 roadmap 對應版本。
- 未來功能是否未提前實作。
- Telegram 是否只做通知，不做遠端控制，除非新版本明確開始。

## Release 審核項目

- `git status --short --branch` 只包含預期變更。
- `.gitignore` 沒有被放寬到誤傳資料。
- `data/`、`tmp/`、`logs/`、DB、token 未被 stage。
- `README.md` 更新。
- `CHANGELOG.md` 更新。
- docs 更新。
- tests 通過。
- commit message 清楚。
- tag 版本與 `config.APP_VERSION` 一致。
- push main 成功。
- push tag 成功。
- server 更新指令清楚。
- server 實測完成後有紀錄。

## Server / Scheduler 審核項目

- 是否在 `/opt/veristockdb/app` 執行。
- 是否啟用 `.venv`。
- 是否載入 `/etc/veristockdb/veristockdb.env`。
- `config.DB_PATH`、`CSV_DIR`、`ARCHIVE_DIR`、`DEFAULT_BACKUP_PATH` 是否正確。
- `ops-check` 是否 OK。
- timers 是否 enabled。
- logs 是否在 `/var/log/veristockdb`。
- backup 是否在 `/mnt/veristockdb-cold/veristockdb/backup`。
- archive 是否在 `/mnt/veristockdb-cold/veristockdb/archive`。
- restore test 是否可讀 DB。
- update timers 是否時間符合使用者目前設定。
- Telegram test 是否成功。

## Worker 回報模板

```text
任務：
狀態：完成 / 進行中 / 阻塞
修改檔案：
執行命令：
測試結果：
DB/status 結果：
server 結果：
未驗證：
風險：
下一步：
```
