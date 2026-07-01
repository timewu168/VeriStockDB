# VeriStockDB 文件入口

此目錄分成「目前有效文件」與「歷史封存文件」。下一輪 Codex、PM 或 worker 接手時，請先讀根目錄 `CURRENT_STATE.md`，再依任務讀本目錄的有效文件。

## 目前有效文件

- `../CURRENT_STATE.md`：唯一的下一輪接手狀態摘要。
- `../README.md`：對外專案說明、CLI、API、PWA、資料來源與部署概覽。
- `../CHANGELOG.md`：唯一正式版本紀錄；舊 handoff 內的 `CHANGELOG.md` 不再作為 release history。
- `local_truth_api_spec.md`：Local Truth API 契約。
- `version_roadmap_checklist.md`：版本路線、完成條件與 deferred 工作。
- `data_ingestion_global_policy.md`：資料入庫防禦與驗證原則。
- `URL.txt`：官方資料來源 URL 參考。
- `ubuntu_private_deployment.md`：私有部署範例與 systemd 設定參考。
- `telegram_notification_spec.md`：Telegram 通知規格。
- `pwa_cli_i18n_boundary_note.md`：PWA、CLI、i18n 邊界。
- `close_monthly_reconciliation_backlog.md`：Close 月資料對帳後續事項。
- `legal_investor_ingestion_blockers.md`：法人資料曾遇到的官方 CSV 問題與處理邊界。

## 歷史封存文件

- `pm_handoff/`：舊版交接包與規劃資料，只作歷史參考。

`pm_handoff/` 內文件可能描述舊版本、舊路徑、已完成或已改變的規劃。不得用它取代 `CURRENT_STATE.md`、根目錄 `README.md` 或根目錄 `CHANGELOG.md`。

## 判讀優先順序

1. 根目錄 `CURRENT_STATE.md`
2. 根目錄 `README.md`
3. 根目錄 `CHANGELOG.md`
4. `docs/local_truth_api_spec.md`
5. `docs/version_roadmap_checklist.md`
6. 其他 `docs/` 目前有效文件
7. `docs/pm_handoff/` 歷史封存文件
