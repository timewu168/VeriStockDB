# PWA 與 CLI 中文顯示邊界備忘

狀態：已落地到 `v0.5.x` PWA/API。此文件保留為架構邊界備忘。

## 核心結論

PWA 可以把 API/Core 的結構化結果轉成中文顯示，但不應直接解析 CLI stdout 再翻譯。

比較穩定的做法是：

- Core 層負責實際下載、驗證、入庫與狀態計算。
- CLI 層只把 Core 回傳的結果印成命令列文字。
- API / PWA 層使用 Core 回傳的結構化結果，再轉成中文 UI、表格、提示與狀態卡。

也就是說，CLI 與 PWA 應該共用同一套核心函式，而不是讓 PWA 依賴 CLI 的文字輸出。

## 不建議的做法

不建議讓 PWA 執行：

```powershell
python main.py update-close
```

然後解析輸出文字，例如：

```text
OK: 2 FIXED: 0 BLOCKED: 0 RECHECK: 0 MISSING: 0 SKIPPED: 0
```

再把字串翻成中文。

原因是 CLI 文字是給人看的，未來可能因為排版、說明、log 或錯誤訊息調整而改變。PWA 若依賴這些文字，會變得脆弱。

## 建議的資料流

```text
Core function
  -> structured result
  -> CLI formatter
  -> terminal output

Core function
  -> structured result
  -> API JSON
  -> PWA i18n formatter
  -> Chinese UI
```

## API 回傳方向

API 或 Core 結構化結果可以回傳類似以下結構：

```json
{
  "command": "update-close",
  "status": "OK",
  "range": {
    "from": "2026-06-01",
    "to": "2026-06-02"
  },
  "stats": {
    "OK": 2,
    "FIXED": 0,
    "BLOCKED": 0,
    "RECHECK": 0,
    "MISSING": 0,
    "SKIPPED": 0
  },
  "messages": [
    {
      "code": "TRADING_CALENDAR_REFRESHED",
      "level": "INFO",
      "params": {
        "from": "2026-05-30",
        "to": "2026-06-02"
      }
    }
  ]
}
```

PWA 再根據 `code`、`status`、`stats` 與 `params` 顯示中文，例如：

```text
日常更新完成
更新範圍：2026-06-01 至 2026-06-02
成功：2，修復：0，阻擋：0，需複查：0，缺漏：0，略過：0
```

## CLI 可保留原始 log

PWA 管理頁可以保留一個「執行紀錄」區塊顯示 job stdout/stderr tail。

但正式操作狀態、錯誤提示、批次表格與使用者可判斷的結果，應使用結構化資料轉譯，不應依賴 CLI stdout。

## 未來開發原則

- 新增核心流程時，優先讓函式回傳結構化結果。
- CLI formatter 和 PWA formatter 分開維護。
- 錯誤訊息應保留穩定 code，例如 `DOWNLOAD_FAILED`、`TRADING_CALENDAR_REFRESHED`。
- 中文顯示放在 PWA/API 的 i18n 對照表或 formatter。
- 不要把 CLI 文字輸出當成正式 API 契約。

這個決策可以讓 CLI 繼續保持簡潔，也讓 PWA 未來有穩定、可中文化、可表格化的資料來源。
