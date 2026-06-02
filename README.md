# VeriStockDB

Version: v0.2.4

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
# 若 trading_days 落後，會先用 TWSE FMTQIK 大盤 API 補齊交易日曆
python main.py import-close --date 2026-06-02
python main.py import-close --from 2026-06-01 --to 2026-06-02

# 半夜或跨日執行三日回滾檢查
python main.py rollback-close --date 2026-06-02

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
