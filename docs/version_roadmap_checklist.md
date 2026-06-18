# VeriStockDB 版本切法與檢查清單

狀態：規劃中，從目前 `v0.2.7` 之後開始使用。

建立日期：2026-06-04

## 核心順序

先把 API 規範做完整，再新增其它資料表，最後做 PWA 前端。

這裡的「API 規範完整」不是一次實作所有資料，而是先定好穩定契約：

- 路徑命名規則。
- 回傳 JSON 格式。
- 錯誤碼與狀態碼。
- 日期區間、股票代號、市場別查詢規則。
- 分頁與排序規則。
- dataset 狀態查詢。
- batch / error / event 查詢。
- PWA 不解析 CLI stdout，而是使用 API / Core 結構化結果。

## 版本總表

| 版本 | 主題 | 狀態 |
| --- | --- | --- |
| `v0.2.8` | Close 私有部署觀察與小修 | 未開始 |
| `v0.3.0` | API 規範 + read-only API 基礎 + PWA/CLI 中文顯示邊界 | 待發版 |
| `v0.3.1` | 注意股公告 | 完成 |
| `v0.3.2` | 處置股公告 | 完成 |
| `v0.3.3` | Telegram Bot API：更新後訊息通知 | 完成 |
| `v0.3.4` | 三大法人 | 未開始 |
| `v0.3.5` | 資券 | 未開始 |
| `v0.3.6` | 當沖 | 延後 |
| `v0.3.7` | 月營收 | 延後 |
| `v0.3.8` | Close 月資料對帳 `reconcile-close-month` | 已實作，待發版 |
| `v0.4.0-public-preview` | 開源前整理 | 未開始 |
| `v0.5.0` | PWA 前端 | 未開始 |

## 每版共同完成條件

每推進一個版本，都先檢查以下項目：

- [ ] 規格文件已更新。
- [ ] CLI 或 API 行為已有明確範例。
- [ ] schema 變更已寫入正式 migration 或 schema 文件。
- [ ] 新資料集已接入共用 batch / error / event 管理。
- [ ] 失敗時會留下可追查原因，不只顯示 `MISSING` 或 `BLOCKED`。
- [ ] 測試已補上，至少涵蓋成功、缺參數、資料異常。
- [ ] `python -m unittest discover -v` 通過。
- [ ] README / CHANGELOG 視需要更新。
- [ ] commit 完成。
- [ ] 需要發版時 tag 完成。
- [ ] push 到 GitHub。
- [ ] 若影響 Ubuntu 部署，server 已 pull 並驗證。

## v0.2.8 Close 私有部署觀察與小修

目標：讓目前 Close 流程在 Ubuntu 私有部署上多跑幾個交易日，先穩住營運面。

檢查清單：

- [ ] `update-close` 排程正常。
- [ ] `rollback-close` 排程正常。
- [ ] `backup` 排程正常。
- [ ] `ops-check` 為 `OK`。
- [ ] `status --problems --details` 無異常。
- [ ] Google Drive 異地備份正常。
- [ ] GCP VPS 異地備份正常。
- [ ] 若有小修，補測試與文件。

## v0.3.0 API 規範與 read-only API 基礎

目標：先建立未來 PWA 與其它專案可依賴的穩定 API 契約。

範圍：

- API 規格文件。
- read-only API 第一版。
- 健康檢查 endpoint。
- Close 查詢 endpoint。
- trading days 查詢 endpoint。
- batch / status / error / event 查詢 endpoint。
- ops summary endpoint。
- PWA 與 CLI 中文顯示邊界落地到 API 規格。

檢查清單：

- [x] API 路徑命名定案。
- [x] 回傳 JSON envelope 定案。
- [x] 錯誤碼格式定案。
- [x] 日期格式統一為 `YYYY-MM-DD`。
- [x] month 格式統一為 `YYYY-MM`。
- [x] 市場別統一使用 `TWSE` / `TPEX`。
- [x] API 不直接回傳 CLI stdout。
- [x] CLI formatter 與 API response 分離。
- [x] 至少有 `/health`。
- [x] 至少有 Close 查詢 endpoint。
- [x] 至少有 dataset 狀態 endpoint。
- [x] trading days 查詢 endpoint 已建立。
- [x] batch / error / event 查詢 endpoint 已建立。
- [x] ops summary endpoint 已建立。
- [x] API smoke test 已涵蓋基本回應、auth、Close 查詢與 ops summary。

## v0.3.1 注意股公告

目標：優先提供另一個專案需要的注意股公告資料。

資料性質：公告事件型資料。

檢查清單：

- [x] 官方來源 URL 與參數確認。
- [x] schema 定案。
- [x] import command 定案。
- [x] API 查詢 endpoint 定案。
- [x] 支援日期查詢。
- [x] 支援股票代號查詢。
- [x] 支援市場別查詢。
- [x] 公告原因或注意條件可保存。
- [x] 原始來源批次可追查。
- [x] 異常公告格式會寫入 `import_errors` 或 `data_events`。

## v0.3.2 處置股公告

目標：提供另一個專案需要的處置股公告資料。

資料性質：公告事件型資料。

檢查清單：

- [x] 官方來源 URL 與參數確認。
- [x] schema 定案。
- [x] import command 定案。
- [x] update command 定案。
- [x] API 查詢 endpoint 定案。
- [x] 支援日期查詢。
- [x] 支援股票代號查詢。
- [x] 支援市場別查詢。
- [x] 支援處置期間 `active_date` 查詢。
- [x] 生效日、結束日若官方有提供，需要保存。
- [x] 處置原因或處置條件可保存。
- [x] 官方處置內容原文可保存。
- [x] 原始來源批次可追查。
- [x] 異常公告格式會寫入 `import_errors`。

正式命令範例：

```powershell
python main.py import-disposal --twse-file tmp\disposal_notice_samples\punish.csv --tpex-file tmp\disposal_notice_samples\disposal_information_20030901_20260601.csv
python main.py update-disposal
python main.py query-disposal --stock-id 52811 --from 2018-10-01 --to 2018-10-31
python main.py query-disposal --active-date 2026-06-05
```

API 查詢範例：

```text
GET /api/v1/disposal-notices?from=2026-05-01&to=2026-06-05&stock_id=52811
GET /api/v1/disposal-notices?from=2026-05-01&to=2026-06-05&active_date=2026-06-05
```

## v0.3.3 Telegram Bot API 通知

目標：先做更新後訊息通知，預留未來手機傳訊控制 server 的擴充空間。

第一版只做通知，不做遠端控制。

規格文件：

- `docs/telegram_notification_spec.md`

檢查清單：

- [x] 通知規格文件已建立。
- [x] 支援環境變數設定 bot token。
- [x] 支援環境變數設定 chat id。
- [x] `update-close` 完成後可通知。
- [x] `rollback-close` 完成後可通知。
- [x] `update-attention` 完成後可通知。
- [x] `update-disposal` 完成後可通知。
- [x] `backup` 完成後可通知。
- [x] `ops-check` 異常時可通知。
- [x] 通知內容包含狀態、日期範圍、統計數字與錯誤摘要。
- [x] token 不寫入 repo。
- [x] 測試不需要真實 Telegram token。
- [x] 文件註明未來遠端控制需要白名單、權限、確認機制與危險命令限制。
- [x] Telegram 手機通知中文化，並保留 `OK` / `BLOCKED` / `RECHECK` / `MISSING` / `ERROR` 狀態碼。
- [x] Ubuntu server 已實測 Telegram 通知。

預計命令範例：

```powershell
python main.py notify-telegram --test
python main.py notify-telegram --message "VeriStockDB test message"
```

## v0.3.4 三大法人

目標：加入三大法人資料，作為 Close 之外第一個主要交易資料集。

檢查清單：

- [ ] 官方來源 URL 與參數確認。
- [ ] 資料表命名定案，建議避免使用容易誤解的 `legal`。
- [ ] schema 定案。
- [ ] import command 定案。
- [ ] API 查詢 endpoint 定案。
- [ ] 支援日期區間查詢。
- [ ] 支援股票代號查詢。
- [ ] 支援市場別查詢。
- [ ] 買進、賣出、買賣超欄位單位確認。
- [ ] 可與 `daily_close` 用日期與股票代號對齊。

## v0.3.5 資券

目標：加入資券資料。

檢查清單：

- [ ] 官方來源 URL 與參數確認。
- [ ] 資料表命名定案。
- [ ] schema 定案。
- [ ] import command 定案。
- [ ] API 查詢 endpoint 定案。
- [ ] 支援日期區間查詢。
- [ ] 支援股票代號查詢。
- [ ] 支援市場別查詢。
- [ ] 融資、融券、借券或相關欄位定義確認。
- [ ] 單位與正負號規則確認。

## v0.3.6 當沖

目標：加入當沖資料。

檢查清單：

- [ ] 官方來源 URL 與參數確認。
- [ ] schema 定案。
- [ ] import command 定案。
- [ ] API 查詢 endpoint 定案。
- [ ] 支援日期區間查詢。
- [ ] 支援股票代號查詢。
- [ ] 支援市場別查詢。
- [ ] 當沖買進、賣出、成交股數、成交金額等欄位定義確認。
- [ ] 可與 `daily_close` 對齊驗證。

## v0.3.7 月營收

目標：加入月營收資料。

資料性質：月資料，不是每日資料。

檢查清單：

- [ ] 官方來源 URL 與參數確認。
- [ ] month 欄位格式定案。
- [ ] schema 定案。
- [ ] import command 定案。
- [ ] API 查詢 endpoint 定案。
- [ ] 支援月份區間查詢。
- [ ] 支援股票代號查詢。
- [ ] 支援市場別查詢。
- [ ] 當月營收、去年同月、月增率、年增率等欄位定義確認。
- [ ] 公告日與資料月份分開保存。

## v0.3.8 Close 月資料對帳

目標：把 `docs/close_monthly_reconciliation_backlog.md` 轉成正式功能。

狀態：已實作 `reconcile-close-month`，待 commit / tag / push。

預計命令：

```powershell
python main.py reconcile-close-month --month YYYY-MM
```

檢查清單：

- [x] 官方個股月資料 API 確認。
- [x] 預設樣本股確認：TWSE `0050`、`1101`，TPEX `5483`。
- [x] 支援使用者自選 `--stock-id`。
- [x] 支援 `--market`。
- [x] 第一版只比對 `close` 與 `volume`。
- [x] 差異會標記 `RECHECK`。
- [x] 差異訊息包含月份、市場、股票代號、日期、欄位、DB 值、官方值。
- [x] 不取代 `audit-month`，只作為跨來源對帳。

## v0.4.0-public-preview 開源前整理

目標：準備公開預覽版本。

檢查清單：

- [ ] 確認 repo 不包含 `data/`。
- [ ] 確認 repo 不包含 DB。
- [ ] 確認 repo 不包含 token、私有路徑、server 設定。
- [ ] README 更新到公開可讀狀態。
- [ ] CHANGELOG 補齊。
- [ ] 安裝與 quickstart 文件補齊。
- [ ] API 文件補齊。
- [ ] 範例資料策略確認。
- [ ] license 確認。
- [ ] git history 檢查敏感資料。

## v0.5.0 PWA 前端

目標：建立第一版 PWA 管理與查詢介面。

檢查清單：

- [ ] PWA 只使用 API，不解析 CLI stdout。
- [ ] 中文顯示由 PWA/API i18n formatter 處理。
- [ ] 提供 Close 查詢畫面。
- [ ] 提供注意股公告查詢畫面。
- [ ] 提供處置股公告查詢畫面。
- [ ] 提供資料集狀態畫面。
- [ ] 提供 batch / error / event 檢視。
- [ ] 提供 ops-check 顯示。
- [ ] 手機版可用。
- [ ] 桌面版可用。

## 目前下一步

目前 `v0.3.0` 收斂檢查已完成，下一步：

1. 確認 commit 時只 stage API、規格文件、README、設定範例與 requirements。
2. 不追蹤 `data/`、`tests/`、暫存檔與 `docs/新增功能規劃書.txt`。
3. commit / tag / push `v0.3.0`。
