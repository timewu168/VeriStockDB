# VeriStockDB

Version: v0.3.3.1

VeriStockDB 是一個本機台股 SQLite 資料庫專案，目標是把官方資料下載、檢查、擋錯後才入庫，讓使用者查到乾淨可信的資料。

這不是交易建議系統，也不是大型資料治理平台。第一版只專注 Close 日收盤資料。

## 規格優先順序

1. `docs/human_first_rebuild_plan.md`
2. `docs/data_ingestion_global_policy.md`
3. `docs/URL.txt`
4. `reference/股市資料庫代碼.txt` 只作舊系統參考，不可覆蓋新規格

## 第一版入口

裸執行 `python main.py` 會顯示可用命令與 quickstart，不會初始化 DB 或啟動資料流程。

```powershell
# 初始化 SQLite 資料庫與必要資料表
python main.py init-db

# 日常更新：從 DB 目前最後一筆 Close 日期自動補到今天
# 全新 DB 需先用 import-close 建立 Close 起點
python main.py update-close

# 匯入指定日期的官方 Close 日收盤資料，不會執行三日回滾檢查
# 若 trading_days 落後，會先用 TWSE FMTQIK 大盤 API 補齊交易日曆；TWSE 異常時改用 TPEx tradingIndex 備援
python main.py import-close --date 2026-06-02
python main.py import-close --from 2026-06-01 --to 2026-06-02

# 半夜或跨日執行三日回滾檢查
python main.py rollback-close

# 批次下載指定日期區間內的交易日官方 Close 資料
python main.py import-close --from 2024-01-01 --to 2024-12-31

# 匯入本地既有 CSV 檔案，需指定日期與市場
python main.py import-close --file data/csv/daily_close/2024/20240603CloseSII.csv --date 2024-06-03 --market TWSE

# 批次匯入本地歷史 Close CSV，依交易日曆檢查缺檔
# 檔名需為 yyyyMMddCloseSII.csv / yyyyMMddCloseOTC.csv
python main.py import-close-local --dir data/csv/Close --from 2004-02-11 --to 2004-12-31
python main.py import-close-local --dir data/csv/Close --from 2004-02-11 --to 2004-12-31 --market TWSE

# 查看各批次資料狀態與最新問題
python main.py status

# 檢查私有部署健康狀態：DB、backup、archive、log、systemd timer
python main.py ops-check

# 測試 Telegram 通知，需先設定 VERISTOCK_TELEGRAM_* 環境變數
python main.py notify-telegram --test
python main.py notify-telegram --message "VeriStockDB test message"

# 列出所有被擋下、需複查或缺漏的批次與原因
python main.py status --problems

# 列出問題批次與錯誤樣本，適合追查被擋原因
python main.py status --problems --details

# 查詢特定股票在指定期間的 Close 資料
python main.py query-close --stock-id 2330 --from 2024-01-01 --to 2024-12-31

# 執行指定月份的零容忍月度檢查
python main.py audit-month --dataset daily_close --month 2024-06

# 歷史起點或單市場資料可指定月檢範圍，避免把未匯入市場或起點前交易日列為缺漏
python main.py audit-month --dataset daily_close --month 2004-02 --market TWSE --from 2004-02-11 --skip-rollback

# 月檢通過後，將該月 CSV 打包成 ZIP 並驗證後刪除 loose CSV
python main.py archive-month --dataset daily_close --month 2024-06

# 歷史本地 CSV 使用與月檢相同的 scope 封存
python main.py archive-month --dataset daily_close --month 2004-02 --market TWSE --from 2004-02-11 --dir data/csv/Close --skip-rollback

# 一次對多個月份執行月檢與封存，遇到第一個失敗月份會停止
python main.py finalize-close-months --from 2004-02 --to 2004-12 --market TWSE --start-date 2004-02-11 --dir data/csv/Close --skip-rollback

# 建立最新 SQLite DB 備份，預設只保留一份
python main.py backup
```

## 核心原則

- 主資料表只放人想查的股票資料。
- 任何可疑官方資料都先停止入庫，記錄狀態，等待人工檢驗。
- 價格以「元 * 100」的整數分儲存。
- 股票代號永遠當文字處理，保留官方原文與前導零。
- CSV 入庫成功後先留存，月度零容忍檢查與 ZIP 驗證成功後才刪 loose CSV。

## Ubuntu 私有部署路徑

Ubuntu server 可用環境變數把熱資料與冷資料分到不同硬碟。主 DB 與未封存 CSV 建議放 M.2，封存 ZIP 與 DB backup 建議放冷資料 SSD。

```bash
export VERISTOCK_DB_PATH=/srv/veristockdb/app/data/db/veristock.db
export VERISTOCK_CSV_DIR=/srv/veristockdb/app/data/csv
export VERISTOCK_ARCHIVE_DIR=/app/dirty_box/veristockdb/archive
export VERISTOCK_BACKUP_DIR=/app/dirty_box/veristockdb/backup
export VERISTOCK_LOG_DIR=/srv/veristockdb/logs
```

完整部署備忘見 `docs/ubuntu_private_deployment.md`。

## Telegram 通知

`v0.3.3` 起可透過 Telegram 接收排程完成通知。第一版只做通知，不做遠端控制。

```bash
export VERISTOCK_TELEGRAM_ENABLED=1
export VERISTOCK_TELEGRAM_BOT_TOKEN=your-bot-token
export VERISTOCK_TELEGRAM_CHAT_ID=your-chat-id
```

支援通知的任務包含 `update-close`、`rollback-close`、`update-attention`、`update-disposal`、`backup`；`ops-check` 只在 `WARN` 或 `ERROR` 時通知。通知失敗不會改變原本任務的 exit code。

## Local Truth API

`v0.3.0` 開始建立本地 Local Truth API。這套 API 只供本機、ZeroTier 或可信任內網使用，定位是 VeriStockDB 真理資料庫的管理與查詢入口，不是雲端公開 API。

目前 `v0.3.0` read-only 第一版包含：

- `GET /health`
- `GET /api/v1/info`
- `GET /api/v1/datasets`
- `GET /api/v1/datasets/{dataset}/status`
- `GET /api/v1/daily-close`
- `GET /api/v1/trading-days`
- `GET /api/v1/batches`
- `GET /api/v1/batches/{batch_id}`
- `GET /api/v1/errors`
- `GET /api/v1/events`
- `GET /api/v1/ops/summary`

安裝 API 依賴：

```powershell
pip install -r requirements.txt
```

啟動本地 API：

```powershell
python -m api
```

預設綁定 `127.0.0.1:8000`。可用環境變數調整：

```powershell
$env:VERISTOCK_API_HOST = "127.0.0.1"
$env:VERISTOCK_API_PORT = "8000"
```

完整規格見 `docs/local_truth_api_spec.md`。
