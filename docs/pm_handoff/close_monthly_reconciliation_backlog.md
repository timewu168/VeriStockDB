# Close 月資料對帳功能備忘

狀態：未實作，先保留為未來功能。

## 背景

目前 `audit-month` 的定位是「封存前完整性檢查」，主要確認批次狀態、交易日覆蓋、主表筆數與 rollback 狀態。

當初討論的「月檢」另有一個更嚴格的想法：使用官方個股月資料，回頭比對本地 DB 中該股票整個月份的每日資料。這個功能先不做，等專案完成度更高後再回頭實作。

## 未來命令名稱

可考慮使用以下其中一個正式命令名稱：

```powershell
python main.py reconcile-close-month --month YYYY-MM
python main.py verify-close-month --month YYYY-MM
```

命名方向：

- `reconcile-close-month`：偏向「對帳」。
- `verify-close-month`：偏向「驗證」。

## 預設樣本股

初步預設樣本如下：

| 市場 | 預設樣本 |
| --- | --- |
| TWSE | `0050`, `1101` |
| TPEX | `5483` |

未來實作時不可只寫死這幾檔，必須支援使用者自選股票，例如：

```powershell
python main.py reconcile-close-month --month 2024-06 --stock-id 0050 --stock-id 1101
python main.py reconcile-close-month --month 2024-06 --market TPEX --stock-id 5483
```

## 比對資料來源

目標是拿官方「個股月資料」比對本地 `daily_close` 主表。

比對欄位先保留為：

- `close`
- `volume`

未來若要擴充，可再考慮 `open`、`high`、`low`、`amount`、`transactions`，但第一版不要過度擴大。

## 失敗處理

若官方個股月資料與本地 DB 任一天不一致：

- 該月或受影響批次應標記為 `RECHECK`。
- 錯誤訊息需要指出：
  - 月份
  - 市場
  - 股票代號
  - 日期
  - 欄位名稱
  - DB 值
  - 官方月資料值

範例格式：

```text
2024-06 TWSE 0050 2024-06-03 close mismatch: db=180.50 official=181.00
```

## 與現有月檢的分工

現有 `audit-month` 保留為封存前 gate：

- 檢查交易日是否都有 batch。
- 檢查是否存在 `BLOCKED`、`RECHECK`、`MISSING`。
- 檢查 batch row_count 與主表筆數是否一致。
- 檢查月底 rollback 是否完成。
- 通過後才允許 `archive-month` 或 `finalize-close-months` 封存。

未來 `reconcile-close-month` / `verify-close-month` 則負責跨來源抽樣對帳：

- 對照官方個股月資料。
- 驗證本地每日 `close`、`volume` 是否與官方月資料一致。
- 目標是提高資料正確性信心，而不是取代現有完整性檢查。

## 暫緩原因

先暫緩實作，原因如下：

- 目前主線仍在 Close 歷史資料建庫、月封存與批次狀態整理。
- 官方個股月資料 API 的年代可用性、格式穩定性、休市日處理仍需要另外確認。
- 樣本股應支援自選，不適合匆忙硬寫成固定代號。

等專案完成度更高後，再把這份備忘轉成正式開發規格與測試計畫。
