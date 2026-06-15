# CURRENT_STATE.md

## Current Stage

- VeriStockDB legal investor historical backfill has completed formal SQLite import and post-import validation.
- Formal legal investor DB ingestion for historical TWSE/TPEX source coverage is complete.
- `report-legal` full CSV dry-run reporting completed successfully before import.
- Manual single-day legal investor update/idempotency checks are implemented and validated.
- Legal investor formal schedule is enabled via systemd timer.
- `veristockdb-update-legal.timer` target: `Mon..Fri 18:00`, `Persistent=true`, activates `veristockdb-update-legal.service`.
- Latest observed next run: `Tue 2026-06-16 18:00:00 CST`.

## Accepted Baseline

- Git HEAD: verify with `git rev-parse HEAD`; this state file was updated after the legal investor workflow was pushed to `origin/main`.
- SQLite DB path: `/srv/veristockdb/app/data/db/veristock.db`.
- SQLite DB size verified after 2026-06-15 legal update: `2379722752` bytes.
- SQLite `PRAGMA integrity_check`: `ok`.
- Verified DB row counts:
  - `daily_close`: `8689342`
  - `attention_notices`: `101807`
  - `disposal_notices`: `7628`
  - `legal_investors`: `5807251`
  - `trading_days`: `5514`
  - `import_batches`: `10177`
- Verified duplicate key checks:
  - `daily_close` PK duplicates: `0`
  - `attention_notices` PK duplicates: `0`
  - `disposal_notices` PK duplicates: `0`
  - `legal_investors` PK duplicates: `0`
- Verified date coverage:
  - `daily_close`: `2004-02-11` to `2026-06-15`
  - `attention_notices`: `2001-01-02` to `2026-06-12`
  - `disposal_notices`: `2001-01-02` to `2026-06-12`
  - `trading_days`: `2004-02-02` to `2026-06-16`
  - `legal_investors`: `2007-04-23` to `2026-06-15` overall; TWSE `2012-05-04` to `2026-06-15`; TPEX `2007-04-23` to `2026-06-15`
- Latest successful unit test run: `python3 -m unittest discover -s tests` => `33 tests OK` on 2026-06-16 after `update-legal` implementation.
- Latest completed legal full report after final blocker retry:
  - command: `python3 main.py report-legal`
  - total market-days: `8156`
  - OK: `8156`
  - BLOCKED: `0`
  - MISSING: `0`
  - rows parsed: `5804996`
  - TWSE: `3451` open days, `3451` OK, `0` BLOCKED, `0` MISSING, rows `3411113`
  - TPEX: `4705` open days, `4705` OK, `0` BLOCKED, `0` MISSING, rows `2393883`
- Latest legal investor dry-run:
  - TWSE command: `python3 main.py import-legal --dry-run --from 2012-05-04 --to 2026-06-12 --market TWSE`
  - TWSE result: `OK=3451`, `BLOCKED=0`, `MISSING=0`
  - TPEX command: `python3 main.py import-legal --dry-run --from 2007-04-23 --to 2026-06-12 --market TPEX`
  - TPEX result: `OK=4705`, `BLOCKED=0`, `MISSING=0`
  - Combined source coverage dry-run accepted by market scope; unsplit `2007-04-23 -> 2026-06-12` includes expected TWSE pre-2012 missing files and is not the import gate scope.
- Latest formal legal investor import:
  - Pre-import backup: `/app/dirty_box/veristockdb/backup/veristock_pre_legal_import_20260616_064815.db`, size `1447550976`, integrity `ok`
  - TWSE command: `python3 main.py import-legal --from 2012-05-04 --to 2026-06-12 --market TWSE`
  - TWSE result: `open_days=3451`, rows `3411113`
  - TPEX command: `python3 main.py import-legal --from 2007-04-23 --to 2026-06-12 --market TPEX`
  - TPEX result: `open_days=4705`, rows `2393883`
  - Total `legal_investors` rows after import: `5804996`
  - Duplicate key check after import: `0`
  - SQLite `PRAGMA integrity_check` after import: `ok`
- Latest manual legal investor update:
  - Pre-update backup: `/app/dirty_box/veristockdb/backup/veristock_pre_legal_update_20260615_20260616_071818.db`, size `2379341824`, integrity `ok`
  - Command: `python3 main.py update-legal --date 2026-06-15`
  - Result: `OK=2`, `EXISTS=0`, `CLOSED=0`, `BLOCKED=0`
  - TWSE rows added: `1324`
  - TPEX rows added: `931`
  - Total `legal_investors` rows after update: `5807251`
  - Duplicate key check after update: `0`
  - SQLite `PRAGMA integrity_check` after update: `ok`
- Latest legal investor idempotency/closed-day checks:
  - `python3 main.py update-legal --date 2026-06-15 --no-cooldown` returned `EXISTS=2` and row count stayed `5807251`
  - `python3 main.py update-legal --date 2026-06-12 --market TWSE --no-cooldown` returned `EXISTS=1` and row count stayed unchanged
  - `python3 main.py update-legal --date 2026-06-13 --market TWSE --no-cooldown` returned `CLOSED=1` and row count stayed unchanged
- Final blocker retry after that report:
  - `2012-05-23 TWSE` re-downloaded from official TWSE CSV, validated with `validate_legal_csv_bytes`, old standard file backed up, standard file replaced.
  - `2024-03-28 TWSE` re-downloaded from official TWSE CSV, validated with `validate_legal_csv_bytes`, old standard file backed up, standard file replaced.
  - Full `report-legal` after these replacements completed with `BLOCKED=0` and `MISSING=0`.
- DB backups verified present:
  - `/app/dirty_box/veristockdb/backup/veristock_latest_backup.db` size `1436479488`, timestamp `2026-06-05 14:25`
  - `/app/dirty_box/veristockdb/backup/veristock_pre_notice_weekend_repair_20260613_083347.db` size `1447092224`, timestamp `2026-06-13 08:33`

## SQLite Canonical Truth / ClickHouse Boundary

- SQLite remains canonical truth for current production datasets:
  - `daily_close`
  - `attention_notices`
  - `disposal_notices`
  - `trading_days`
  - `import_batches`, `import_errors`, `data_events`, `settings`
- `legal_investors` is populated in SQLite for accepted historical source coverage and is part of the canonical SQLite dataset after post-import validation.
- ClickHouse is not touched in this stage.
- No ClickHouse canonical table is accepted for legal investor data.
- If ClickHouse is introduced later, it must be high-volume/analytics serving only unless explicitly promoted, and must pass table count and sample aggregation checks before acceptance.

## Data Sources And ETL State

- Daily close, attention notices, and disposal notices are already canonicalized in SQLite with verified row counts above.
- Legal investor CSV source root: `/srv/veristockdb/app/data/csv/legal_investor`.
- Legal investor CSV downloader exists: `download-legal`; it downloads only CSV and does not import to DB.
- Legal investor parser/dry-run exists: `import-legal --dry-run`; latest accepted market-scoped full dry-run returned `BLOCKED=0` and `MISSING=0` for TWSE/TPEX source coverage.
- Legal investor formal import exists: `import-legal` without `--dry-run`; it blocks re-import when target market/date scope already contains rows and uses INSERT only.
- Legal investor manual single-day update exists: `update-legal --date YYYY-MM-DD`; it checks local trading calendar first, blocks existing market/date rows before download, blocks when matching `daily_close` rows are missing, downloads only for clean open days, validates CSV before saving, and inserts only.
- Legal investor full report exists: `report-legal`; latest completed full scan returned `OK=8156`, `BLOCKED=0`, `MISSING=0`.
- Legal investor source file fallback supports standard year folders and historical uploaded folders.
- TWSE/TPEX legal investor parser supports old and new field names, including TPEX `買股數 / 賣股數 / 淨買股數` legacy format.
- Replaced legal CSV source files after individual validation:
  - `/srv/veristockdb/app/data/csv/legal_investor/2012/20120523LegalSII.csv`
  - `/srv/veristockdb/app/data/csv/legal_investor/2024/20240328LegalSII.csv`
- Backup of replaced blocker files:
  - `/app/dirty_box/veristockdb/backup/legal_csv_blocker_retry_20260615/20120523LegalSII.csv`
  - `/app/dirty_box/veristockdb/backup/legal_csv_blocker_retry_20260615/20240328LegalSII.csv`
- Earlier validated replacements:
  - `2014-02-19 TWSE`
  - `2025-08-27 TWSE`
- Backup of earlier replaced files:
  - `/app/dirty_box/veristockdb/backup/legal_csv_validated_replacement_20260615`

## Schema / Migration State

- `db/schema.sql` has been modified to include `legal_investors` table and indexes.
- Main SQLite DB contains populated `legal_investors` table.
- `legal_investors` row count is verified `5807251`.
- Accepted legal investor historical backfill has been run for TWSE/TPEX source coverage.
- No formal schema migration version bump has been accepted in this state file.
- `APP_VERSION` remains previously accepted value; do not assume version bump unless verified separately.

## Modified Files

Tracked modified files:

- `db/schema.sql`
- `ingest/legal_investor.py`
- `main.py`
- `tests/test_legal_investor.py`

Untracked/project context files:

- `docs/legal_investor_ingestion_blockers.md`
- `docs/pm_handoff/`
- `.venv/`
- `e --to 2026-06-04`
- `udo systemctl daemon-reload`

Source CSV files modified by validated replacement:

- `data/csv/legal_investor/2012/20120523LegalSII.csv`
- `data/csv/legal_investor/2024/20240328LegalSII.csv`
- `data/csv/legal_investor/2014/20140219LegalSII.csv`
- `data/csv/legal_investor/2025/20250827LegalSII.csv`

## Next Gate

- Monitor first scheduled `veristockdb-update-legal.service` run at `2026-06-16 18:00 CST`.
- After first run, verify `/srv/veristockdb/logs/update-legal.log`, row count, duplicate key check, latest legal date coverage, and SQLite integrity check.


## Locked Actions

Do not perform any of these without explicit user approval:

- Drop, truncate, delete, or overwrite canonical SQLite data.
- Run destructive SQL against canonical tables.
- Apply formal schema migration/version bump.
- Push to GitHub or create tags/releases.
- Move SQLite canonical truth to ClickHouse.
- Create or overwrite ClickHouse tables.
- Run ClickHouse backfill or production sync.
- Delete backup, archive, or quarantine files.

## Required Data/DB Validation Checks

Before accepting any future DB-changing work:

- SQLite integrity check: `PRAGMA integrity_check` must return `ok`.
- Backup check: verify a current DB backup exists and record path, size, timestamp.
- Row count check for affected tables before and after change.
- Duplicate key check for affected table primary key scope.
- Date coverage check against expected trading days.
- Schema validation against `db/schema.sql` and actual SQLite `sqlite_master`.
- Legal investor source check: completed `python3 main.py report-legal` with `BLOCKED=0` and `MISSING=0` before historical import.
- Legal investor dry-run sample checks across TWSE/TPEX and legacy/current formats.
- Legal investor post-import/update checks: row count, duplicate key, market/date coverage, sample records, idempotency, closed-day behavior, and SQLite integrity check.
- If ClickHouse is touched later:
  - table count check
  - row count check against SQLite/source scope
  - sample aggregation check by date/market/stock
  - duplicate/sorting key validation
  - no ClickHouse result may supersede SQLite until explicitly accepted

## Important Paths / Latest Reports

- Legal investor systemd service: `/etc/systemd/system/veristockdb-update-legal.service`
- Legal investor systemd timer: `/etc/systemd/system/veristockdb-update-legal.timer`

- Repo: `/srv/veristockdb/app`
- Current state file: `/srv/veristockdb/app/CURRENT_STATE.md`
- SQLite DB: `/srv/veristockdb/app/data/db/veristock.db`
- Hot CSV root: `/srv/veristockdb/app/data/csv`
- Legal investor CSV root: `/srv/veristockdb/app/data/csv/legal_investor`
- Logs: `/srv/veristockdb/logs`
- Cold archive root: `/app/dirty_box/veristockdb/archive`
- Backup root: `/app/dirty_box/veristockdb/backup`
- Latest legal blocker doc: `/srv/veristockdb/app/docs/legal_investor_ingestion_blockers.md`
- Latest completed legal report baseline: `python3 main.py report-legal` completed after final blocker retry with `OK=8156`, `BLOCKED=0`, `MISSING=0`, rows `5804996`.
- Latest legal dry-run logs:
  - `/srv/veristockdb/logs/import-legal-dry-run-TWSE-20120504-20260612.log`
  - `/srv/veristockdb/logs/import-legal-dry-run-TPEX-20070423-20260612.log`
- Latest legal formal import logs:
  - `/srv/veristockdb/logs/import-legal-TWSE-20120504-20260612.log`
  - `/srv/veristockdb/logs/import-legal-TPEX-20070423-20260612.log`
- Latest legal update logs:
  - `/srv/veristockdb/logs/update-legal-20260615.log`
  - `/srv/veristockdb/logs/update-legal-idempotency-20260615.log`
  - `/srv/veristockdb/logs/update-legal-idempotency-20260612-TWSE.log`
  - `/srv/veristockdb/logs/update-legal-closed-20260613-TWSE.log`
