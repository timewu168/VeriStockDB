
# Changelog

<!-- i18n-switch -->
[中文](CHANGELOG.md) | [English](CHANGELOG.en.md)
<!-- /i18n-switch -->

This file is the English release-history companion. The Chinese `CHANGELOG.md` remains the canonical detailed changelog.

## v0.6.6 - 2026-07-03

- Fixed PWA dataset summary so single-market lag is visible directly in dataset status.
- Fixed schedule-health log parsing so zero-count summaries such as `BLOCKED=0` and `MISSING=0` do not create false warnings.
- Treat resolved log warnings as OK when canonical data is already current.
- Fixed schedule-health data freshness checks to require TWSE and TPEX market coverage for dense datasets.
- Added PWA `WARN` pill styling support and bumped the service worker cache.
- Verification: 118 unit tests OK, `node --check web/app.js` OK, production `schedule-health` OK, and full TWSE/TPEX missing-date checks for close, day trading, legal investors, and margin returned zero missing dates.

## v0.6.5 - 2026-07-02

- Added `dataset-health-check` CLI for all canonical datasets: row count, duplicate keys, latest period, gaps, recent errors, and recent non-OK batches.
- Added `GET /api/v1/ops/dataset-health-check` for structured PWA reporting.
- Added the all-dataset health table to the PWA System page.
- Added `tests/test_dataset_health_check.py`.
- Fixed `GET /api/v1/ops/summary` response behavior.
- Formal DB smoke returned `dataset-health-check OK` with zero duplicate keys, zero gaps, and zero recent errors across seven canonical datasets.

## v0.6.4 - 2026-07-01

- Added `docs/new_dataset_sop.md`, the standard process for future official datasets.
- The SOP covers source discovery, downloader design, inspect command, field mapping, date validation, parser/cleaner, schema, dry-run, full validation, formal import, update command, schedule, API, PWA, docs, and release gates.

## v0.6.3 - 2026-07-01

- Added `docs/backup_restore_sop.md` with DB restore procedure and non-destructive restore drill.
- Rebuilt `veristock_latest_backup.db` and verified restore copy integrity and row/latest-period smoke checks.

## v0.6.2 - 2026-07-01

- Added documentation entrypoint and documentation-boundary rules.
- Marked legacy handoff files as historical reference only.

## v0.6.1 - 2026-07-01

- Added `schedule-health` CLI and API endpoint.
- Added PWA schedule health table.
- Added tests for timer status, log errors, and stale data detection.

## v0.6.0 - 2026-07-01

- Added dataset health drill-down endpoint and PWA detail view.
- Added dataset health route smoke tests.

## v0.5.x Summary

- Added Local Management PWA under `web/`.
- Added manual update jobs, persisted `ops_jobs`, job history/detail APIs, and PWA job detail views.
- Added structured table query results and Chinese table headers.
- Fixed FastAPI SQLite read-only connection thread behavior with `check_same_thread=False`.

## v0.4.x Summary

- Completed public-preview readiness work.
- Added day trading and monthly revenue canonical data flows.
- Added APIs for day trading and monthly revenue.
- Added repo hygiene, README alignment, issue templates, and CI.

## v0.3.x Summary

- Added API foundation, attention notices, disposal notices, Telegram notification behavior, legal investor ingestion, margin trading ingestion, and retry behavior for official downloads.

## v0.2.x Summary

- Established close-price ingestion, trading-day support, rollback, deployment basics, validation boundaries, and operational status commands.
