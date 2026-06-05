# v0.3.3 Telegram Bot API 通知規格

狀態：功能完成，待部署驗證。

建立日期：2026-06-05

## 目標

v0.3.3 只做 VeriStockDB 私有部署的「任務完成後 Telegram 訊息通知」。

第一版不做手機遠端控制、不接收 Telegram 指令、不提供任何可由外部觸發的資料庫操作。Telegram 在這一版只是通知出口，不是控制入口。

## 使用情境

日常排程在 Ubuntu server 上執行後，使用者可以從手機看到結果，不需要登入 SSH 查看 log。

第一版需要通知的任務：

- `update-close`
- `rollback-close`
- `update-attention`
- `update-disposal`
- `backup`
- `ops-check`，僅在 `WARN` 或 `ERROR` 時通知，避免每天發送無意義的正常訊息。

後續可再擴充：

- `archive-month`
- `finalize-close-months`
- 未來法人、資券、當沖、月營收等資料集更新任務。

## 設計原則

- 通知失敗不能讓原本任務失敗。
- token 與 chat id 只能透過環境變數設定，不寫入 repo、不寫入 DB。
- Telegram 傳送錯誤要輸出簡短原因，方便 systemd log 追查。
- 測試不需要真實 Telegram token，也不能真的打到 Telegram API。
- 訊息內容要短、可掃讀，適合手機通知。
- 第一版只支援單一 chat id；多 chat id 留到未來再做。
- 不把 CLI stdout 原文直接貼到 Telegram，而是由 notifier 使用結構化結果組合摘要。

## 環境變數

| 變數 | 預設值 | 用途 |
| --- | --- | --- |
| `VERISTOCK_TELEGRAM_ENABLED` | `0` | 是否啟用 Telegram 通知 |
| `VERISTOCK_TELEGRAM_BOT_TOKEN` | 空 | Telegram bot token |
| `VERISTOCK_TELEGRAM_CHAT_ID` | 空 | 接收通知的 chat id |
| `VERISTOCK_TELEGRAM_TIMEOUT_SECONDS` | `10` | 發送 timeout |
| `VERISTOCK_TELEGRAM_NOTIFY_SUCCESS` | `1` | 任務成功時是否通知 |
| `VERISTOCK_TELEGRAM_NOTIFY_WARNING` | `1` | 任務有警告或需人工注意時是否通知 |
| `VERISTOCK_TELEGRAM_NOTIFY_FAILURE` | `1` | 任務失敗時是否通知 |

Ubuntu server 的 `/etc/veristockdb/veristockdb.env` 可追加：

```text
VERISTOCK_TELEGRAM_ENABLED=1
VERISTOCK_TELEGRAM_BOT_TOKEN=123456:replace-with-real-token
VERISTOCK_TELEGRAM_CHAT_ID=123456789
VERISTOCK_TELEGRAM_TIMEOUT_SECONDS=10
VERISTOCK_TELEGRAM_NOTIFY_SUCCESS=1
VERISTOCK_TELEGRAM_NOTIFY_WARNING=1
VERISTOCK_TELEGRAM_NOTIFY_FAILURE=1
```

repo 內的 `deploy/systemd/veristockdb.env.example` 只放註解範例，不放真實 token。

## 預計 CLI

第一版新增一個手動測試命令：

```powershell
python main.py notify-telegram --test
python main.py notify-telegram --message "VeriStockDB test message"
```

正式任務不要求每次加 `--notify`。只要 `VERISTOCK_TELEGRAM_ENABLED=1` 且 token / chat id 設定完整，支援通知的任務完成後會自動通知。

若使用者不想啟用通知，維持預設環境變數即可，不影響現有 CLI 行為。

## 訊息格式

訊息使用純文字，不使用 MarkdownV2，避免特殊字元 escaping 造成通知失敗。

基本格式：

```text
VeriStockDB update-close OK
time: 2026-06-05 19:30:12 CST
range: 2026-06-03 -> 2026-06-05
stats: OK=4 FIXED=0 BLOCKED=0 RECHECK=0 MISSING=0 SKIPPED=0
db: /srv/veristockdb/app/data/db/veristock.db
```

有問題時：

```text
VeriStockDB update-close RECHECK
time: 2026-06-05 19:30:12 CST
range: 2026-06-03 -> 2026-06-05
stats: OK=3 FIXED=0 BLOCKED=1 RECHECK=0 MISSING=0 SKIPPED=0
errors:
- 2026-06-05 TWSE DOWNLOAD_FAILED: SSL certificate verify failed
```

backup 成功：

```text
VeriStockDB backup OK
time: 2026-06-05 02:30:10 CST
path: /app/dirty_box/veristockdb/backup/veristock_latest_backup.db
size: 1.2GiB
```

ops-check 異常：

```text
VeriStockDB ops-check WARN
time: 2026-06-05 08:00:00 CST
- WARN log:update-disposal.log missing log file
- OK backup readable tables=8 size=1.2GiB
```

## 狀態分類

通知層統一使用以下狀態：

| 狀態 | 意義 |
| --- | --- |
| `OK` | 任務成功，沒有需要人工處理的項目 |
| `WARNING` | 任務完成，但有 `WARN`、`SKIPPED` 或應留意資訊 |
| `RECHECK` | 有批次被標成 `RECHECK` |
| `BLOCKED` | 有批次被標成 `BLOCKED` |
| `MISSING` | 有批次或資料缺漏 |
| `ERROR` | CLI 命令例外或 ops-check 有 ERROR |

Close / attention / disposal update 的統計若有 `BLOCKED`、`RECHECK`、`MISSING`，通知狀態應反映最嚴重狀態。

## 實作邊界

建議新增模組：

```text
services/telegram_notifier.py
```

建議責任：

- 讀取 Telegram 環境變數。
- 判斷通知是否啟用。
- 組合純文字訊息。
- 發送 Telegram `sendMessage` request。
- 捕捉 timeout、HTTP error、JSON error。
- 回傳結構化結果，例如 `NotificationResult(sent, skipped, error)`。

`main.py` 只負責在支援的命令完成後，把任務名稱、狀態、統計與摘要交給 notifier。

## 錯誤處理

- Telegram 未啟用：不輸出錯誤，任務照常完成。
- token 或 chat id 缺失：輸出 `WARN telegram notification skipped: missing token or chat id`。
- Telegram API timeout：輸出 `WARN telegram notification failed: timeout`。
- Telegram API 回傳非 2xx：輸出 `WARN telegram notification failed: HTTP ...`。
- 通知失敗不改變原本命令 exit code。

## 測試策略

單元測試不使用真實 Telegram。

需要涵蓋：

- 未啟用時會 skip。
- 啟用但缺 token / chat id 時會 skip 並回傳 warning。
- 成功時會組出正確 Telegram URL 與 payload。
- timeout 或 HTTP error 時不拋出到主流程。
- update 類任務可把 stats 轉成正確通知狀態。
- `notify-telegram --test` 可在 mock sender 下完成。

## 未來遠端控制保留事項

未來若要讓 Telegram Bot 接收手機指令控制 server，必須另開版本處理，不能混在 v0.3.3。

遠端控制至少需要：

- chat id 白名單。
- admin token 或二次確認機制。
- 危險命令禁止清單。
- 任務佇列與鎖，避免同時跑多個資料更新。
- 所有控制指令寫入 audit log。
- destructive 操作必須要求二次確認。

v0.3.3 不實作上述功能。
