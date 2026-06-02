# Changelog

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
