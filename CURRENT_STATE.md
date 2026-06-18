# CURRENT_STATE.md

## Current Stage

- Latest release: `v0.3.8.1` (`Release v0.3.8.1 API completeness`), prepared for `origin/main` with tag `v0.3.8.1`.
- Completed production SQLite datasets: `daily_close`, `attention_notices`, `disposal_notices`, `legal_investors`, `margin_trading`, `trading_days`.
- Completed read-only Local Truth API endpoints through `v0.3.8.1`: Close, attention notices, disposal notices, legal investors, margin trading, trading days, dataset status, batches, errors, events, and ops summary.
- Completed `reconcile-close-month` for Close monthly cross-source reconciliation using official TWSE/TPEX monthly stock JSON. It does not download CSV and does not overwrite canonical `daily_close` rows.
- `v0.3.6` day trading and `v0.3.7` monthly revenue are intentionally deferred.

## Accepted Baseline

- SQLite DB path: `/srv/veristockdb/app/data/db/veristock.db`.
- Latest verified SQLite `PRAGMA integrity_check`: `ok` on 2026-06-18.
- Latest code/tag baseline: `v0.3.8.1` / `origin/main`.
- Latest API completeness test baseline:
  - `/srv/veristockdb/app/.venv/bin/python -m unittest tests.test_api_core tests.test_api_legal_margin -v`: `10` tests OK.
  - `python3 -m unittest discover -s tests`: `64` tests OK, `10` skipped because system Python lacks FastAPI route dependencies.
  - `/srv/veristockdb/app/.venv/bin/python -m compileall -q api`: OK.
  - Formal DB route-level smoke: `trading-days` pagination OK; compact date `20260615` rejected with `400 INVALID_DATE`.
- Verified DB row counts on 2026-06-18:
  - `daily_close`: `8694093`
  - `legal_investors`: `5807251`
  - `margin_trading`: `8122060`
  - `attention_notices`: `101993`
  - `disposal_notices`: `7653`
  - `trading_days`: `6642`
- Verified canonical ranges:
  - `daily_close`: `2004-02-11..2026-06-17` total; TWSE `5228886` rows `2004-02-11..2026-06-17`; TPEX `3465207` rows `2007-07-02..2026-06-17`.
  - `legal_investors`: `2007-04-23..2026-06-15` total; TWSE `3412437` rows `2012-05-04..2026-06-15`; TPEX `2394814` rows `2007-04-23..2026-06-15`.
  - `margin_trading`: `2001-01-02..2026-06-15` total; TWSE `5381796` rows `2001-01-02..2026-06-15`; TPEX `2740264` rows `2008-09-30..2026-06-15`.
  - `attention_notices`: `2001-01-02..2026-06-17`.
  - `disposal_notices`: `2001-01-02..2026-06-17`.
  - `trading_days`: `2001-01-02..2026-06-18`.
- Verified duplicate key baseline:
  - `legal_investors` PK duplicates: `0`.
  - `margin_trading` PK duplicates: `0`.
- Latest accepted margin import baseline:
  - TWSE CSV audit `2001-01-02..2026-06-15`: `expected=6263`, `actual=6263`, `OK=6263`, `BAD=0`, `MISSING=0`, `EMPTY=0`, `EXTRA=0`.
  - TPEX CSV audit `2008-09-30..2026-06-15`: `expected=4347`, `actual=4347`, `OK=4347`, `BAD=0`, `MISSING=0`, `EMPTY=0`, `EXTRA=0`.
  - Margin dry-run/import report `20260618_075908`: `expected_files=10610`, `parsed_files=10610`, `rows=8122060`, `duplicate_keys=0`, `missing_files=0`, `bad_files=0`, `null_required=0`, `invalid_numeric=0`, `date_coverage_gaps=0`, `problems=0`.
- Latest accepted Close monthly reconciliation smoke test:
  - `reconcile-close-month --month 2026-06 --from 2026-06-01 --to 2026-06-17 --no-cooldown`: TWSE `0050`, TWSE `1101`, TPEX `5483`, all `OK`, `13` rows each.
- Verified backups:
  - `/app/dirty_box/veristockdb/backup/veristock_pre_legal_import_20260616_064815.db`, integrity `ok`, bytes `1447550976`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_legal_update_20260615_20260616_071818.db`, integrity `ok`, bytes `2379341824`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_trading_days_backfill_20010102_20040201_20260616_081936.db`, integrity `ok`, bytes `2379722752`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_margin_import_20260618_074854.db`, integrity `ok`, bytes `2380640256`.

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
- Legal investor systemd schedule is enabled:
  - service: `/etc/systemd/system/veristockdb-update-legal.service`
  - timer: `/etc/systemd/system/veristockdb-update-legal.timer`
  - schedule: `Mon..Fri 18:00`, `Persistent=true`
- Margin CSV source root: `/srv/veristockdb/app/data/csv/margin`.
- Margin commands are implemented and accepted: `download-margin`, `inspect-margin`, `import-margin --dry-run`, `import-margin --execute`, `update-margin`.
- Margin production systemd schedule is enabled:
  - service: `/etc/systemd/system/veristockdb-update-margin.service`
  - timer: `/etc/systemd/system/veristockdb-update-margin.timer`
  - schedule: `Mon..Fri 18:30`, `Persistent=true`
- Disposal update systemd schedule is enabled:
  - timer: `/etc/systemd/system/veristockdb-update-disposal.timer`
  - schedule: `Mon..Fri 19:00`, `Persistent=true`
- Latest observed timers on 2026-06-18:
  - `veristockdb-update-legal.timer`: next `2026-06-18 18:00`, last `2026-06-17 18:00:10`.
  - `veristockdb-update-margin.timer`: next `2026-06-18 18:30`, no last run yet.
  - `veristockdb-update-disposal.timer`: next `2026-06-18 19:00`, last `2026-06-17 19:00:02`.
- Margin official source scope:
  - TWSE from `2001-01-02`: `MI_MARGN?response=csv&date={YYYYMMDD}&selectType=ALL`.
  - TPEX canonical scope from `2008-09-30`: `balance?date={YYYY%2FMM%2FDD}&id=&response=csv`.
  - TPEX pre-`2008-09-30` files may remain on disk but are not accepted for canonical import.
- Historical trading-day command exists: `backfill-trading-days --from YYYY-MM-DD --to YYYY-MM-DD`.

## Schema/Migration State

- Current code version: `APP_VERSION=0.3.8.1`.
- Current schema version: `SCHEMA_VERSION=0.3-margin-trading`.
- `db/schema.sql` includes accepted tables and indexes for `legal_investors` and `margin_trading`.
- `legal_investors` canonical key: `PRIMARY KEY (trade_date, market, stock_id)`.
- `margin_trading` canonical key: `PRIMARY KEY (trade_date, market, stock_id)`.
- `margin_trading` canonical columns: `trade_date`, `market`, `stock_id`, `stock_name`, `margin_buy`, `margin_sell`, `margin_cash_repay`, `previous_margin_balance`, `margin_balance`, `margin_limit`, `short_buy`, `short_sell`, `short_stock_repay`, `previous_short_balance`, `short_balance`, `short_limit`, `offsetting`, `note`.
- API completeness changes are API-only and do not change SQLite schema.

## Modified Files

API completeness/state update files included in `v0.3.8.1`:

- `CHANGELOG.md`
- `CURRENT_STATE.md`
- `README.md`
- `api/date_utils.py`
- `api/routes/attention_notices.py`
- `api/routes/batches.py`
- `api/routes/daily_close.py`
- `api/routes/datasets.py`
- `api/routes/disposal_notices.py`
- `api/routes/events.py`
- `api/routes/table_query.py`
- `api/routes/trading_days.py`
- `docs/local_truth_api_spec.md`
- `tests/test_api_core.py`

Current untracked local files/directories not intended for Git:

- `.venv/`
- `reports/`
- `e --to 2026-06-04`
- `udo systemctl daemon-reload`

## Next Gate

- Next gate is to review and, if accepted, commit/tag/push the uncommitted API completeness changes.
- After API completeness is committed, next accepted planning gate remains `v0.4.0-public-preview` repo safety/documentation audit unless explicitly reprioritized.
- Before `v0.4.0-public-preview`, verify the repo does not include `data/`, SQLite DB files, tokens, private server paths that should not be public, or production-only systemd secrets.
- Deferred dataset work remains `v0.3.6` day trading and `v0.3.7` monthly revenue.
- Do not start a new dataset import, schema migration, or production schedule change until explicitly requested.

## Locked Actions

Do not perform any of these without explicit user approval:

- Drop, truncate, delete, or overwrite canonical SQLite data.
- Run destructive SQL against canonical tables.
- Re-import or overwrite canonical `daily_close`, `legal_investors`, or `margin_trading` rows.
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
