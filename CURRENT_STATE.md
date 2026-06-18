# CURRENT_STATE.md

## Current Stage

- Legal investor (`legal_investors`) historical import, manual update, idempotency checks, release, GitHub push, and weekday 18:00 systemd timer are complete.
- Margin (`margin_trading`) raw CSV download, validation, parser dry-run, schema creation, formal SQLite import, and post-import validation are complete.
- Formal code release in progress: `APP_VERSION=0.3.5.0`, `SCHEMA_VERSION=0.3-margin-trading`, target tag `v0.3.5.0`.
- Margin incremental update command `update-margin` is implemented and verified with existing-date idempotency.
- Margin production systemd timer is not yet enabled because this Codex session cannot provide sudo password interactively; requested schedule is after legal investor, planned `Mon..Fri 18:30`.

## Accepted Baseline

- Previous Git release baseline: `6dad12e` / tag `v0.3.4.0` / `origin/main`.
- SQLite DB path: `/srv/veristockdb/app/data/db/veristock.db`.
- SQLite `PRAGMA integrity_check` after margin import: `ok`.
- Latest full unit test run after margin import work: `python3 -m unittest discover -s tests` => `48 tests OK`.
- Verified DB row counts after margin import on `2026-06-18`:
  - `daily_close`: `8694093`
  - `legal_investors`: `5807251`
  - `margin_trading`: `8122060`
  - `trading_days`: `6642`
- Verified latest/range dates:
  - `daily_close`: latest `2026-06-17`
  - `legal_investors`: latest `2026-06-15`
  - `margin_trading`: TWSE `2001-01-02..2026-06-15`, TPEX `2008-09-30..2026-06-15`
  - `trading_days`: `2001-01-02..2026-06-18`
- Verified duplicate key checks:
  - `legal_investors` PK duplicates: `0`
  - `margin_trading` PK duplicates: `0`
- Margin accepted checks:
  - TWSE CSV audit `2001-01-02..2026-06-15`: `expected=6263`, `actual=6263`, `OK=6263`, `BAD=0`, `MISSING=0`, `EMPTY=0`, `EXTRA=0`.
  - TPEX CSV audit `2008-09-30..2026-06-15`: `expected=4347`, `actual=4347`, `OK=4347`, `BAD=0`, `MISSING=0`, `EMPTY=0`, `EXTRA=0`.
  - Margin dry-run/import report `20260618_075908`: `expected_files=10610`, `parsed_files=10610`, `rows=8122060`, `duplicate_keys=0`, `missing_files=0`, `bad_files=0`, `null_required=0`, `invalid_numeric=0`, `date_coverage_gaps=0`, `problems=0`.
  - Formal import rows: TWSE `5381796`, TPEX `2740264`, total `8122060`.
- Verified backups:
  - `/app/dirty_box/veristockdb/backup/veristock_pre_legal_import_20260616_064815.db`, integrity `ok`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_legal_update_20260615_20260616_071818.db`, integrity `ok`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_trading_days_backfill_20010102_20040201_20260616_081936.db`, integrity `ok`.
  - `/app/dirty_box/veristockdb/backup/veristock_pre_margin_import_20260618_074854.db`, integrity `ok`, bytes `2380640256`.

## SQLite/ClickHouse Truth Boundary

- SQLite remains canonical truth for current production datasets:
  - `daily_close`
  - `attention_notices`
  - `disposal_notices`
  - `legal_investors`
  - `margin_trading`
  - `trading_days`
  - `import_batches`, `import_errors`, `data_events`, `settings`
- ClickHouse is not touched in this stage.
- No ClickHouse canonical table is accepted for daily close, legal investor, or margin data.
- If ClickHouse is introduced later, it must be analytics/high-volume serving only unless explicitly promoted, and must pass table count, row count, duplicate/sorting-key, and sample aggregation checks before acceptance.

## Data Sources And ETL State

- Daily close, attention notices, disposal notices, legal investors, margin trading, and trading days are canonicalized in SQLite.
- Legal investor CSV source root: `/srv/veristockdb/app/data/csv/legal_investor`.
- Legal investor commands are implemented and accepted: `download-legal`, `inspect-legal`, `report-legal`, `import-legal --dry-run`, `import-legal`, `update-legal --date YYYY-MM-DD`.
- Legal investor systemd schedule is enabled:
  - service: `/etc/systemd/system/veristockdb-update-legal.service`
  - timer: `/etc/systemd/system/veristockdb-update-legal.timer`
  - schedule: `Mon..Fri 18:00`, `Persistent=true`
- Margin CSV source root: `/srv/veristockdb/app/data/csv/margin`.
- Margin commands implemented and accepted:
  - `download-margin`: downloads official raw CSV only.
  - `inspect-margin`: audits downloaded CSV coverage, encoding, date, header, row count, numeric parseability, small-file/error-page cases, extra non-trading-day files, and format signatures.
  - `import-margin --dry-run`: parses and validates canonical mapping without DB writes.
  - `import-margin --execute`: writes to SQLite only after dry-run validation and empty target-scope check.
  - `update-margin`: increments one trading day, defaults to today, returns `CLOSED` for closed days and `EXISTS` for already imported dates.
- Margin official source scope:
  - TWSE from `2001-01-02`: `MI_MARGN?response=csv&date={YYYYMMDD}&selectType=ALL`.
  - TPEX accepted canonical scope from `2008-09-30`: `balance?date={YYYY%2FMM%2FDD}&id=&response=csv`.
  - TPEX `2008-09-30` before files may remain on disk but are not accepted for canonical import.
- Historical trading-day command exists:
  - `backfill-trading-days --from YYYY-MM-DD --to YYYY-MM-DD`.
  - Source: TWSE FMTQIK monthly endpoint with `date=YYYYMM01`.

## Schema/Migration State

- `db/schema.sql` includes `legal_investors` and `margin_trading` tables and indexes.
- Main SQLite DB contains populated `legal_investors` and `margin_trading` tables.
- Current code version: `APP_VERSION=0.3.5.0`, `SCHEMA_VERSION=0.3-margin-trading`.
- Margin canonical key: `PRIMARY KEY (trade_date, market, stock_id)`.
- Margin canonical table columns: `trade_date`, `market`, `stock_id`, `stock_name`, `margin_buy`, `margin_sell`, `margin_cash_repay`, `previous_margin_balance`, `margin_balance`, `margin_limit`, `short_buy`, `short_sell`, `short_stock_repay`, `previous_short_balance`, `short_balance`, `short_limit`, `offsetting`, `note`.

## Modified Files

Files intended for the `v0.3.5.0` commit:

- `.gitignore`
- `CURRENT_STATE.md`
- `config.py`
- `db/schema.sql`
- `docs/URL.txt`
- `ingest/downloader.py`
- `ingest/margin.py`
- `ingest/trading_calendar.py`
- `main.py`
- `tests/test_margin.py`
- `tests/test_trading_calendar_fallback.py`

Untracked files/directories not intended for commit:

- `.venv/`
- `reports/`
- `e --to 2026-06-04`
- `udo systemctl daemon-reload`

Data files created by downloads/audits are under data/log/report paths and are not accepted for Git unless explicitly requested.

## Next Gate

- Enable margin systemd service/timer manually with sudo.
- Planned margin schedule: `Mon..Fri 18:30`, `Persistent=true`, service command `/usr/bin/python3 /srv/veristockdb/app/main.py update-margin`.
- `update-margin --date 2026-06-15 --no-cooldown` verified idempotency: TWSE/TPEX returned `EXISTS` without overwriting.

## Locked Actions

Do not perform any of these without explicit user approval:

- Drop, truncate, delete, or overwrite canonical SQLite data.
- Run destructive SQL against canonical tables.
- Re-import or overwrite `margin_trading` canonical rows.
- Apply another schema/version bump.
- Enable, disable, or modify production systemd schedules beyond the requested margin timer work.
- Move SQLite canonical truth to ClickHouse.
- Create or overwrite ClickHouse tables.
- Run ClickHouse backfill or production sync.
- Delete backup, archive, quarantine, CSV, report, or log files.

## Required Data/DB Validation Checks

Before accepting any future DB-changing work:

- SQLite integrity check: `PRAGMA integrity_check` must return `ok`.
- Backup check: verify current DB backup path, size, timestamp, and readability/integrity.
- Row count check for affected tables before and after change.
- Duplicate key check for affected table primary key scope.
- Date coverage check against expected trading days/source coverage.
- Schema validation against `db/schema.sql` and actual SQLite `sqlite_master`.
- Source coverage report/dry-run for the affected dataset must have `BAD=0`, `MISSING=0`, and `problems=0` unless explicitly accepted as a known gap.
- For margin specifically:
  - validate content date, header location, row count, numeric fields, duplicate stock IDs, and unit normalization.
  - validate TWSE 17-column mapping and TPEX 20-column `balance` mapping.
  - ensure TPEX pre-`2008-09-30` files are excluded from canonical scope.
  - verify `margin_trading` duplicate key count is `0` after writes.
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
- Legal investor service: `/etc/systemd/system/veristockdb-update-legal.service`
- Legal investor timer: `/etc/systemd/system/veristockdb-update-legal.timer`
- Margin CSV audits:
  - TWSE: `/srv/veristockdb/app/reports/margin_csv_audit_20260618_072603.txt`
  - TPEX: `/srv/veristockdb/app/reports/margin_csv_audit_20260618_072538.txt`
- Latest margin dry-run/import reports:
  - `/srv/veristockdb/app/reports/margin_import_dry_run_20260618_075908.txt`
  - `/srv/veristockdb/app/reports/margin_import_daily_counts_20260618_075908.csv`
  - `/srv/veristockdb/app/reports/margin_import_problems_20260618_075908.csv`
- Margin pre-import backup:
  - `/app/dirty_box/veristockdb/backup/veristock_pre_margin_import_20260618_074854.db`
