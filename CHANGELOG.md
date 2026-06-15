# Changelog

## v0.3.4.0 - 2026-06-16

### Added

- Added canonical SQLite `legal_investors` schema and indexes.
- Added legal investor CSV parsing, validation, reporting, dry-run, formal import, and manual single-day update workflows.
- Added historical TWSE/TPEX legal investor backfill support with legacy format normalization.
- Added `update-legal` idempotency safeguards for existing rows, closed days, and missing `daily_close` rows.
- Added legal investor unit coverage for parser formats, validation blockers, formal imports, and update behavior.

### Notes

- Historical legal investor SQLite coverage is accepted through 2026-06-15 after post-import integrity, duplicate-key, coverage, and idempotency checks.
- `legal_investors` stores foreign, investment trust, dealer self-trading, and dealer hedge columns; foreign dealer and total columns are intentionally not stored.
- Formal systemd schedule target is `Mon..Fri 18:00` via `veristockdb-update-legal.timer`.

## v0.3.3.1 - 2026-06-05

### Changed

- Localized Telegram task notification messages in Chinese while preserving status codes such as `OK`, `BLOCKED`, `RECHECK`, `MISSING`, and `ERROR`.
- Official trading-calendar refresh now falls back from TWSE FMTQIK to TPEx tradingIndex when TWSE is unavailable or returns no open days.
- Attention and disposal notice updates now use `trading_days` to skip closed targets and avoid advancing coverage from weekend scheduler runs.
- Added first-stage legal investor CSV download and inspect commands without database import.

## v0.3.3 - 2026-06-05

### Added

- Added Telegram notification settings via `VERISTOCK_TELEGRAM_*` environment variables.
- Added `notify-telegram --test` and `notify-telegram --message` CLI commands.
- Added automatic Telegram notifications for `update-close`, `rollback-close`, `update-attention`, `update-disposal`, and `backup`.
- Added abnormal `ops-check` Telegram notifications for `WARN` and `ERROR` results.
- Added `docs/telegram_notification_spec.md` for the v0.3.3 notification-only boundary and future remote-control guardrails.

### Notes

- Telegram failures are logged as warnings and do not change the original task exit code.
- Tests use mocked senders and do not require a real Telegram token.

## v0.3.2 - 2026-06-05

### Added

- Added `disposal_notices` for listed and OTC disposal announcement records.
- Added `inspect-disposal`, `import-disposal`, `update-disposal`, and `query-disposal` CLI commands.
- Added official TWSE and TPEx disposal announcement CSV downloads.
- Added `/api/v1/disposal-notices` with date, stock ID, market, active-date, field, quality, and pagination filters.
- Added `(trade_date, stock_id)` and active-period indexes for disposal announcement query/join workflows.

### Notes

- Disposal imports preserve official reason/condition text and full disposal text without parsing measures into derived fields.
- Official disposal updates use upsert behavior because official range queries can include announcements published before the requested range while still active during it.
- Historical TWSE/TPEX edge cases such as blank early stock names, blank disposal text, blank TPEX reason text, and official no-disposal rows are tracked in import summaries.

## v0.3.1 - 2026-06-05

### Added

- Added `attention_notices` for listed and OTC attention announcement records.
- Added `inspect-attention`, `import-attention`, `update-attention`, and `query-attention` CLI commands.
- Added official TWSE and TPEx attention announcement CSV downloads.
- Added `(trade_date, stock_id)` composite indexes for Close and attention announcement query/join workflows.

### Notes

- Attention announcement imports keep official notice text as-is and preserve stock IDs using the same no-global-zero-padding policy as Close.
- Historical CSV imports and official updates are tracked through `import_batches` as dataset `attention_notice`.

## v0.3.0 - 2026-06-04

### Added

- Added the Local Truth API read-only first version for local/private VeriStockDB access.
- Added FastAPI endpoints for health, app info, dataset status, daily Close, trading days, batches, import errors, data events, and ops summary.
- Added API environment variables for host, port, optional Bearer-token auth, and read/ops/admin token levels.
- Added Local Truth API specification and version roadmap checklist documents.

### Notes

- Local Truth API is intended for localhost, ZeroTier, VPN, or trusted private networks only; it is not the cloud/public Edge API.
- Cloud Edge API, cloud PWA, jobs, and exports remain future private-project or later-version work.

## v0.2.7 - 2026-06-04

### Added

- Added `ops-check` to verify deployment health across DB readability, backup readability, archive directory, logs, and systemd timers.
- Added `VERISTOCK_LOG_DIR` so operational log checks can use the same path conventions as Ubuntu deployments.

## v0.2.6 - 2026-06-02

### Added

- `rollback-close` can now omit `--date` and automatically use the latest imported Close date.
- Added Ubuntu `systemd` service and timer templates for `update-close`, `rollback-close`, and `backup`.

## v0.2.5 - 2026-06-02

### Added

- Added `VERISTOCK_*` environment variables for private Ubuntu deployments with separate hot and cold storage paths.
- Monthly archive ZIP output can now be routed through `VERISTOCK_ARCHIVE_DIR`, independent of hot CSV storage.

## v0.2.4 - 2026-06-02

### Added

- Added `update-close` for daily official Close updates from the latest imported `daily_close` date through today.
- `update-close --to YYYY-MM-DD` can target a specific end date for controlled catch-up runs.

## v0.2.3 - 2026-06-02

### Added

- Official Close downloads now refresh missing `trading_days` rows from the TWSE `FMTQIK` market-calendar API before downloading CSV files.
- The trading-calendar refresh stores both open days and inferred closed days through the requested/current date, so closed days can be skipped without probing Close CSV downloads.

## v0.2.2 - 2026-06-02

### Added

- Added scoped historical monthly audit options: `audit-month --market`, `--from`, `--to`, and `--skip-rollback`.
- Added matching scoped archive options: `archive-month --market`, `--from`, `--to`, `--dir`, and `--skip-rollback`.
- Added `finalize-close-months` to audit and archive a range of Close months with one command.
- Scoped audits no longer mark the full-month archive audit setting as OK unless the audit covers the full month, both markets, and rollback.

## v0.2.1 - 2026-06-02

### Added

- Added formal `import-close-local` command for importing local historical Close CSV ranges.
- Local Close range imports now use the trading calendar to derive expected CSV files and record `MISSING: LOCAL_CSV_NOT_FOUND` when a trading-day file is absent.

## v0.2.0 - 2026-06-02

### Added

- Added human-friendly naked CLI help and quickstart output.
- Added `rollback-close` so the three-trading-day Close rollback can run as a separate cross-day job.
- Added `status --problems --details` for inspecting blocked, recheck, and missing batches.
- Added shared sparse `data_events` tracking for row-level special handling.
- Added `DASH_FILLED_PREVIOUS_CLOSE` events for Close rows where dash OHLC is filled from the previous valid close.
- Added `ZERO_TRADE_DASH_EXCLUDED` events for early zero-trade dash OHLC rows excluded before the first valid close.

### Changed

- `import-close --date` now imports only the requested date instead of automatically running rollback.
- Official CSV filenames now use the legacy date-first names: `yyyyMMddCloseSII.csv` and `yyyyMMddCloseOTC.csv`.
- Official downloader uses a verified non-strict SSL context for TWSE/TPEx certificate compatibility.
- Close stock-code validation now accepts official alphanumeric IDs such as active ETF and bond-like IDs.
- TPEX only excludes warrant-like `7`-prefix IDs when they are not four characters.
- TPEX management sections, repeated headers, notes, and summary rows no longer block parsing.
- Close dash OHLC handling follows documented policy: fill from previous close when provable, exclude early zero-trade cold-start rows, and recheck nonzero dash rows without a previous close.
- Batch attempt results are committed per official attempt so interrupted imports remain visible in status reports.

### Release Hygiene

- Public GitHub baseline excludes local `data/`, `tests/`, `reference/`, caches, DB files, archives, logs, and temporary outputs.
- Version constants are centralized in `config.py`.
