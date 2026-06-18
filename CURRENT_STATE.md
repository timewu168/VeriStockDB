# CURRENT_STATE.md

## Current Stage

- Current public-preview gate status: gate 1 schedule verification passed, gate 2 API completeness passed, gate 3 DB health check passed, gate 4 README/docs alignment passed, gate 5 v0.4.0 release gate passed.
- Latest pushed release/tag baseline before this gate: `v0.3.8.4` / commit `69037dd Release v0.3.8.4 API errors filters` on `origin/main`.
- Current working tree is ready to commit/tag/push for `v0.4.0 public-preview` with legal/margin update gap recovery and docs alignment.
- Completed production SQLite datasets: `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, `margin_trading`, `trading_days`.
- Completed read-only Local Truth API endpoints: Close, attention notices, disposal notices, legal investors, margin trading, trading days, dataset status, batches, errors, events, and ops summary.
- `v0.3.6` day trading and `v0.3.7` monthly revenue are intentionally deferred.

## Accepted Baseline

- SQLite DB path: `/srv/veristockdb/app/data/db/veristock.db`.
- Latest verified SQLite `PRAGMA integrity_check`: `ok` on 2026-06-18 after legal/margin gap repair.
- Latest verified DB size: `3719970816` bytes.
- Latest schema validation on 2026-06-18: all expected tables and columns OK for `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, `margin_trading`, `trading_days`, `import_batches`, `import_errors`, and `data_events`.
- Latest duplicate key check on 2026-06-18:
  - `daily_close`: `0`
  - `attention_notices`: `0`
  - `disposal_notices`: `0`
  - `legal_investors`: `0`
  - `margin_trading`: `0`
- Latest formal date coverage gaps on 2026-06-18:
  - `daily_close`: TWSE `0`, TPEX `0`.
  - `legal_investors`: TWSE `0`, TPEX `0`.
  - `margin_trading`: TWSE `0`, TPEX `0`.
- Latest non-open/unknown trade-date row check on 2026-06-18: OK for `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, and `margin_trading`.
- Latest recent batch/error state on 2026-06-18: no recent non-OK batches; no recent `import_errors`.
- Verified DB row counts on 2026-06-18:
  - `daily_close`: `8696470`
  - `attention_notices`: `102094`
  - `disposal_notices`: `7664`
  - `legal_investors`: `5813993`
  - `margin_trading`: `8128606`
  - `trading_days`: `6642`
- Verified canonical ranges on 2026-06-18:
  - `daily_close`: TWSE `5230253` rows `2004-02-11..2026-06-18`; TPEX `3466217` rows `2007-07-02..2026-06-18`.
  - `attention_notices`: TWSE `53447` rows `2001-01-02..2026-06-18`; TPEX `48647` rows `2002-02-01..2026-06-18`.
  - `disposal_notices`: TWSE `3476` rows `2001-01-02..2026-06-18`; TPEX `4188` rows `2003-09-04..2026-06-18`.
  - `legal_investors`: TWSE `3416401` rows `2012-05-04..2026-06-18`; TPEX `2397592` rows `2007-04-23..2026-06-18`.
  - `margin_trading`: TWSE `5385630` rows `2001-01-02..2026-06-18`; TPEX `2742976` rows `2008-09-30..2026-06-18`.
  - `trading_days`: `2001-01-02..2026-06-18`, `6266` open days, `376` closed days.
- Verified backups on 2026-06-18:
  - `/app/dirty_box/veristockdb/backup/veristock_pre_margin_import_20260618_074854.db`, integrity `ok`, bytes `2380640256`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_trading_days_backfill_20010102_20040201_20260616_081936.db`, integrity `ok`, bytes `2379722752`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_legal_update_20260615_20260616_071818.db`, integrity `ok`, bytes `2379341824`.
- Latest accepted test validation baseline for `v0.4.0` gate:
  - `python3 -m unittest discover -s tests`: `73` tests run, `11` skipped, OK.
  - Real DB route smoke succeeded for `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, `margin_trading`, `trading_days`, and `errors` on 2026-06-18.
- Latest post-`v0.3.8.4` targeted update-flow validation before full release test:
  - `python3 -m unittest tests.test_update_notifications tests.test_legal_investor tests.test_margin -v`: `47` OK.
  - `python3 -m compileall -q main.py tests/test_update_notifications.py`: OK.

## SQLite/ClickHouse Truth Boundary

- SQLite remains canonical truth for production datasets:
  - `daily_close`
  - `attention_notices`
  - `disposal_notices`
  - `legal_investors`
  - `margin_trading`
  - `trading_days`
  - `import_batches`, `import_errors`, `data_events`, `settings`
- ClickHouse is not touched in this stage.
- No ClickHouse canonical table is accepted for daily close, attention, disposal, legal investor, margin, or trading-day data.
- If ClickHouse is introduced later, it must be analytics/high-volume serving only unless explicitly promoted, and must pass table count, row count, duplicate/sorting-key, and sample aggregation checks before acceptance.

## Data Sources And ETL State

- Daily close, attention notices, disposal notices, legal investors, margin trading, and trading days are canonicalized in SQLite.
- API date query parameters must use strict `YYYY-MM-DD`; compact dates such as `20260615` are rejected and are not used as DB values.
- Close monthly reconciliation source:
  - TWSE: `STOCK_DAY?response=json&date={YYYYMM01}&stockNo={stock_id}`.
  - TPEX: `tradingStock?date={YYYY%2FMM%2F01}&code={stock_id}&response=json`.
  - It compares `close` and `volume` only, records `RECHECK` on mismatch, and never overwrites `daily_close`.
  - TPEX monthly volume is reported as lots and may be rounded; reconciliation allows a `500` share tolerance for TPEX volume only. Prices remain exact.
- Legal investor CSV source root: `/srv/veristockdb/app/data/csv/legal_investor`.
- Legal investor commands are implemented and accepted: `download-legal`, `inspect-legal`, `report-legal`, `import-legal --dry-run`, `import-legal`, `update-legal`.
- `update-legal` now scans missing open trading dates through the target date per market, so internal gaps such as `2026-06-16`/`2026-06-17` are recovered even when `MAX(trade_date)` already reaches the target.
- Margin CSV source root: `/srv/veristockdb/app/data/csv/margin`.
- Margin commands are implemented and accepted: `download-margin`, `inspect-margin`, `import-margin --dry-run`, `import-margin --execute`, `update-margin`.
- `update-margin` now scans missing open trading dates through the target date per market, so internal gaps are recovered even when `MAX(trade_date)` already reaches the target.
- Production systemd schedules currently verified:
  - Close: `Mon..Fri 17:10`.
  - Legal investors: `Mon..Fri 18:00`.
  - Attention notices: `Mon..Fri 19:00`.
  - Disposal notices: `Mon..Fri 19:05`.
  - Margin trading: `Mon..Fri 21:05`.
- Margin official source scope:
  - TWSE from `2001-01-02`: `MI_MARGN?response=csv&date={YYYYMMDD}&selectType=ALL`.
  - TPEX canonical scope from `2008-09-30`: `balance?date={YYYY%2FMM%2FDD}&id=&response=csv`.
  - TPEX pre-`2008-09-30` files may remain on disk but are not accepted for canonical import.
- Historical trading-day command exists: `backfill-trading-days --from YYYY-MM-DD --to YYYY-MM-DD`.

## Schema/Migration State

- Current code version in `config.py`: `APP_VERSION=0.4.0`.
- Current schema version: `SCHEMA_VERSION=0.3-margin-trading`.
- `db/schema.sql` includes accepted tables and indexes for `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, `margin_trading`, `trading_days`, `import_batches`, `import_errors`, `data_events`, and `settings`.
- `legal_investors` canonical key: `PRIMARY KEY (trade_date, market, stock_id)`.
- `margin_trading` canonical key: `PRIMARY KEY (trade_date, market, stock_id)`.
- No SQLite schema migration is pending in the current working tree.
- Current `v0.4.0` release changes are application logic/docs/tests only; no SQLite schema migration is included.

## Modified Files

Current tracked modified files in working tree:

- `config.py`
- `main.py`
- `tests/test_update_notifications.py`
- `README.md`
- `CURRENT_STATE.md`
- `CHANGELOG.md`
- `docs/local_truth_api_spec.md`

Current untracked local files/directories not intended for Git:

- `.venv/`
- `reports/`
- `e --to 2026-06-04`
- `udo systemctl daemon-reload`

## Next Gate

- Commit/tag/push `v0.4.0 public-preview` after user-approved release validation.
- Before `v0.4.0 public-preview`, verify the repo does not include `data/`, SQLite DB files, tokens, private server secrets, or production-only systemd secrets.
- Deferred dataset work remains `v0.3.6` day trading and `v0.3.7` monthly revenue.
- Do not start a new dataset import, schema migration, or production schedule change until explicitly requested.

## Locked Actions

Do not perform any of these without explicit user approval:

- Drop, truncate, delete, or overwrite canonical SQLite data.
- Run destructive SQL against canonical tables.
- Re-import or overwrite canonical `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, or `margin_trading` rows.
- Apply another schema/version bump.
- Enable, disable, or modify production systemd schedules.
- Move SQLite canonical truth to ClickHouse.
- Create or overwrite ClickHouse tables.
- Run ClickHouse backfill or production sync.
- Delete backup, archive, quarantine, CSV, report, or log files.
- Execute formal public-release cleanup that rewrites git history unless explicitly authorized.

## Required Data/DB Validation Checks

Before accepting any future DB-changing work:

- SQLite integrity check: `PRAGMA integrity_check` must return `ok`.
- Backup check: verify current DB backup path, size, timestamp, and readability/integrity.
- Row count check for affected tables before and after change.
- Duplicate key check for affected table primary key scope.
- Date coverage check against expected trading days/source coverage.
- Schema validation against `db/schema.sql` and actual SQLite `sqlite_master`.
- Source coverage report/dry-run for the affected dataset must have `BAD=0`, `MISSING=0`, and `problems=0` unless explicitly accepted as a known gap.
- API changes must include route/query validation checks, strict `YYYY-MM-DD` date validation, field allow-list checks, pagination checks, quality rejection checks, and formal DB route-level smoke tests where applicable.
- Close monthly reconciliation checks must verify official JSON parseability, ROC date conversion, price cents conversion, TWSE volume exactness, TPEX lot-to-share conversion, and TPEX volume rounding tolerance.
- If ClickHouse is touched later:
  - table count check
  - row count check against SQLite/source scope
  - sample aggregation check by date/market/stock
  - duplicate/sorting key validation
  - no ClickHouse result may supersede SQLite until explicitly accepted

## Important Paths / Latest Reports

- Repo: `/srv/veristockdb/app`
- Current state file: `/srv/veristockdb/app/CURRENT_STATE.md`
- SQLite DB: `/srv/veristockdb/app/data/db/veristock.db`
- Hot CSV root: `/srv/veristockdb/app/data/csv`
- Legal investor CSV root: `/srv/veristockdb/app/data/csv/legal_investor`
- Margin CSV root: `/srv/veristockdb/app/data/csv/margin`
- Reports root: `/srv/veristockdb/app/reports`
- Logs: `/srv/veristockdb/logs`
- Backup root: `/app/dirty_box/veristockdb/backup`
- Archive root: `/app/dirty_box/veristockdb/archive`
- Legal investor service/timer:
  - `/etc/systemd/system/veristockdb-update-legal.service`
  - `/etc/systemd/system/veristockdb-update-legal.timer`
- Margin service/timer:
  - `/etc/systemd/system/veristockdb-update-margin.service`
  - `/etc/systemd/system/veristockdb-update-margin.timer`
- Attention timer:
  - `/etc/systemd/system/veristockdb-update-attention.timer`
- Disposal timer:
  - `/etc/systemd/system/veristockdb-update-disposal.timer`
- Margin CSV audits:
  - TWSE: `/srv/veristockdb/app/reports/margin_csv_audit_20260618_072603.txt`
  - TPEX: `/srv/veristockdb/app/reports/margin_csv_audit_20260618_072538.txt`
- Latest margin dry-run/import reports:
  - `/srv/veristockdb/app/reports/margin_import_dry_run_20260618_075908.txt`
  - `/srv/veristockdb/app/reports/margin_import_daily_counts_20260618_075908.csv`
  - `/srv/veristockdb/app/reports/margin_import_problems_20260618_075908.csv`
- Margin pre-import backup:
  - `/app/dirty_box/veristockdb/backup/veristock_pre_margin_import_20260618_074854.db`
