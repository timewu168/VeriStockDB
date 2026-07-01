
# 貢獻指南

<!-- i18n-switch -->
[English](CONTRIBUTING.md) | [中文](CONTRIBUTING.zh-TW.md)
<!-- /i18n-switch -->

感謝你考慮為 VeriStockDB 貢獻。

VeriStockDB 將 SQLite 視為 canonical truth store。任何涉及資料下載、parser、schema、官方來源解析或排程的變更，都必須保留「驗證優先、可疑資料先擋下」的行為。

## 開發環境

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

送出 pull request 前請先執行：

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q api ingest services main.py tests config.py
```

## Pull Request 原則

- 變更範圍要集中，並說明營運影響。
- 若修改 parser、importer、API 或 scheduler 行為，請新增或更新測試。
- 不要提交本機 DB、CSV 下載檔、backup、log、report、`.env`、token 或 credentials。
- 公開文件不要包含私有部署路徑；請使用 `/opt/veristockdb/app` 這類範例路徑。
- 除非有明確文件、review 與防護，否則不要加入破壞性 DB 行為。

## 資料安全規則

Pull request 不得執行或鼓勵未防護的：

- `drop`、`truncate` 或破壞性 `delete`
- 覆寫 canonical SQLite rows
- 沒有 migration plan 與驗證檢查的 schema migration
- 未經 operator 明確操作的 production systemd timer 變更
- 將 canonical truth 從 SQLite 移到其他儲存系統

## 驗證清單

涉及 DB 變更時，請提供相關檢查證據：

- SQLite `PRAGMA integrity_check`
- backup 可用性
- row count before/after
- duplicate key checks
- date coverage against `trading_days`
- schema validation against `db/schema.sql`
- source coverage 或 dry-run reports

若貢獻引入 ClickHouse，請另外提供 table count、row count、sample aggregation checks、sorting 或 duplicate-key validation。
