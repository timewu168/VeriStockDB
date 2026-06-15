# VeriStockDB Project Tasks

產出日期：2026-06-06  
狀態原則：未 commit / 未 tag / 未 server 驗證者，不列為完成。

## 已完成任務

### v0.2.x Close / ops 基礎

狀態：已完成。

內容：

- CLI 裸執行顯示 help + quickstart。
- Close official/local import。
- `update-close`。
- `rollback-close`。
- `import-close-local`。
- `audit-month` / `archive-month` / `finalize-close-months`。
- `backup`。
- 環境變數支援 server 路徑。
- Ubuntu systemd schedule 文件與 server 驗證。
- `ops-check`。

驗收標準：

- `python main.py` 不噴 argparse error。
- `python main.py status --problems --details` 可查問題批次。
- `python main.py update-close` 可依最新資料更新。
- `python main.py rollback-close` 可重查近三個交易日。
- `python main.py ops-check` server 顯示 OK。
- backup restore smoke test 可讀 DB。

證據：

- tags：`v0.2.4`、`v0.2.5`、`v0.2.6`、`v0.2.7`。
- server 曾回報 `ops-check OK`。
- 2026-06-06 unittest：`Ran 95 tests ... OK`。

### v0.3.0 Local Truth API

狀態：已完成。

內容：

- Read-only FastAPI。
- Daily close / trading days / batches / errors / events / ops endpoints。
- API response envelope。
- token auth setting。
- price uses cents。

驗收標準：

- `python -m api.run` 可啟動。
- `/health` 可回應。
- `/api/v1/daily-close` 可查股票資料。
- API 不解析 CLI stdout。
- API tests 通過。

證據：

- tag：`v0.3.0`。
- 使用者 server curl 3090 成功。
- `tests/test_api_attention.py`、`tests/test_api_disposal.py` 與相關 API 測試通過。

### v0.3.1 注意股公告

狀態：已完成。

內容：

- `attention_notices` schema。
- `import-attention`。
- `update-attention`。
- `query-attention`。
- `/api/v1/attention-notices`。
- 支援歷史資料與官方更新。

驗收標準：

- 歷史 TWSE/TPEX 檔案可匯入。
- `status --dataset attention_notice` OK。
- `query-attention` 可依 stock_id/date 查詢。
- API endpoint 可查詢。
- tests 通過。

證據：

- tag：`v0.3.1`。
- 本機匯入輸出：TWSE rows=53041，TPEX rows=48206。
- `status --dataset attention_notice`: OK 2 batches。
- 使用者回報 server 完成。

### v0.3.2 處置股公告

狀態：已完成。

內容：

- `disposal_notices` schema。
- `import-disposal`。
- `update-disposal`。
- `query-disposal`。
- `/api/v1/disposal-notices`。
- 支援 `active_date`。
- server systemd timer `veristockdb-update-disposal.timer` 19:00。

驗收標準：

- 歷史 TWSE/TPEX 檔案可匯入。
- 官方 update 可補到最新。
- `status --dataset disposal_notice --problems --details` 無問題。
- query/API 可查日期範圍與 active date。
- server timer enabled。

證據：

- tag：`v0.3.2`。
- server 匯入輸出：TWSE rows=3436，TPEX rows=4107。
- `update-disposal` 更新至 2026-06-05。
- `status --dataset disposal_notice`: OK 4 batches。
- manual start timer log 顯示 already current。

### v0.3.3 / v0.3.3.1 Telegram 通知

狀態：已完成。

內容：

- Telegram Bot API notification。
- 中文化通知。
- `notify-telegram --test`。
- update/rollback/backup/ops 任務結束通知。
- non-fatal notification failure。

驗收標準：

- token/chat id 由 env 提供。
- 測試通知可送出。
- Telegram 失敗只警告，不改變原任務狀態。
- tests 通過。

證據：

- tags：`v0.3.3`、`v0.3.3.1`。
- 使用者回報測試完成。
- `tests/test_telegram_notifier.py` 通過。

## 進行中任務

### 交易日 TPEx 備援

狀態：進行中；未 commit / 未 tag / 未 push / 未 server 驗證。

目的：

- TWSE FMTQIK 回應慢或空月資料時，使用 TPEx tradingIndex 當備援，避免誤判休市。

已做：

- `config.py` 增加 TPEx tradingIndex URL 設定。
- `ingest/downloader.py` 增加 TPEx trading days download/url helper。
- `ingest/trading_calendar.py` 增加 TPEx parser 與 fallback。
- `docs/URL.txt`、`README.md`、`CHANGELOG.md` 更新。
- 本機 unittest 95 tests OK。

待完成：

- code review。
- commit / tag / push。
- server pull/deploy。
- server 跑 `update-close` 實測。
- Telegram failure notification 實測或確認。

驗收標準：

- `python -m unittest discover -v` OK。
- `git status` 無功能未提交 diff。
- server `update-close --to <today>` 不把有交易日誤判休市。
- `status --problems --details` 無新增問題。

## 未完成任務

### v0.3.4 三大法人

目的：

- 加入三大法人資料，作為後續回測/選股資料。

驗收標準：

- 官方 URL 與欄位已確認。
- sample inspect 完成。
- schema/import/update/query/API/tests/docs 完成。
- status 無問題批次。

### v0.3.5 資券

目的：

- 加入融資融券資料。

驗收標準：

- 同三大法人，另需明確欄位單位與歷史格式差異。

### v0.3.6 當沖

目的：

- 加入當沖資料。

驗收標準：

- schema 與 query/API 能支援回測常用查詢。

### v0.3.7 月營收

目的：

- 加入公司月營收資料。

驗收標準：

- period 採 `YYYY-MM`。
- historical/import/update/query/API/tests/docs 完成。

### v0.3.8 Close 月資料對帳

目的：

- 用官方月資料比對 Close `close` / `volume`。

驗收標準：

- 命令獨立於 `audit-month`。
- 可自選 sample stock。
- mismatch 標示為 `RECHECK`。

### v0.4.0-public-preview

目的：

- 檢查開源前 repo 邊界與文件完整度。

驗收標準：

- 不含 DB/data/token/tmp/logs。
- README/CHANGELOG/API docs 完整。
- license 與 sample data 策略確認。

### v0.5.0 PWA 管理前端

目的：

- 建立真理資料庫管理 PWA。

驗收標準：

- PWA 只走 Local Truth API。
- 不解析 CLI stdout。
- 可看 DB/dataset/batch/error/event/ops 狀態。

## 阻塞任務

### tests 是否追蹤

阻塞原因：

- `.gitignore` 目前排除 `tests/`，但目前大量驗收依賴本機 tests。

需要 PM 決策：

- 繼續不追蹤 tests，僅作本機驗證。
- 或 public preview 前選擇性追蹤可公開 tests。

驗收標準：

- PM 明確決定。
- `.gitignore` 與 release policy 一致。

### Claude implementation plan 路徑

阻塞原因：

- 使用者要求依 Claude implementation plan，但目前未在 repo 盤點中找到明確同名文件。

需要 PM 決策：

- 指定檔案路徑。
- 或確認以現有 `docs/human_first_rebuild_plan.md`、`docs/data_ingestion_global_policy.md`、`docs/local_truth_api_spec.md` 為準。

驗收標準：

- 文件路徑明確。

### 未追蹤 legacy / large files

阻塞原因：

- repo 有多個未追蹤檔案與資料夾，例如 `app.py`、`cleaner.py`、`db_manager.py`、`spider_engine.py`、`web/`、大型 xlsb。

需要 PM 決策：

- 保留為私人參考。
- 移出 repo 工作目錄。
- 或逐一審核後整理。

驗收標準：

- `git status` 不再混淆正式工作項目。
