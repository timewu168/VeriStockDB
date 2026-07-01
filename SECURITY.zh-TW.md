
# 安全政策

<!-- i18n-switch -->
[English](SECURITY.md) | [中文](SECURITY.zh-TW.md)
<!-- /i18n-switch -->

## 支援版本

安全修正會在 `main` branch 與最新 tagged public-preview release 上處理。

## 回報漏洞

請不要用公開 issue 回報敏感漏洞。

可使用 GitHub private security advisory；若不可用，請透過 GitHub repository profile 中列出的 maintainer 聯絡方式回報。

請包含：

- 受影響版本或 commit
- 重現步驟
- 預期與實際影響
- 是否涉及 credentials、本機資料或 systemd 部署檔案

## Secrets 與本機資料

永遠不要提交：

- `.env` 或 production environment files
- Telegram tokens 或 chat IDs
- SQLite databases
- 已下載 CSV 檔
- backup archives
- 含有私有營運路徑的 logs 或 reports

公開 repo 只能使用範例路徑與 sample configuration。
