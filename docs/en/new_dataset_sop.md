# New Dataset SOP

<!-- i18n-switch -->
[中文](../new_dataset_sop.md) | [English](new_dataset_sop.md)
<!-- /i18n-switch -->

Use this SOP when adding a new official dataset to VeriStockDB.

## 1. Source Discovery

- Identify official TWSE/TPEX/MOPS URLs.
- Record parameters, date range, response type, encoding, and rate limits.
- Check historical format changes and no-data/error responses.

## 2. Downloader

- Save raw official files under `data/csv/<dataset>/<year>/` or an equivalent dataset folder.
- Use deterministic filenames with canonical dates/periods.
- Add retry behavior for transient official errors.
- Validate that downloaded file content matches the requested date/period.

## 3. Inspect Command

Create an inspect command that reports encoding, header location, column count, row count, samples, file date/period, suspicious rows, and official error pages. Inspect must not write to canonical tables.

## 4. Field Mapping and Parser

- Define canonical columns before import.
- Reject missing required headers, shifted rows, invalid dates, blank required values, and unexpected formats.
- Do not infer source values unless the exception is documented and tested.

## 5. Schema and Migration

- Add schema only with explicit authorization.
- Define primary/unique keys.
- Add indexes only where query patterns justify them.
- Validate schema against `db/schema.sql`.

## 6. Dry Run and Full Validation

Dry run must report total files, missing files, bad files, accepted rows, duplicate keys, date/period coverage, and examples of blocked rows. Full validation must finish cleanly before formal import.

## 7. Formal Import

Formal import must be idempotent, guarded, and batch-recorded. Do not overwrite canonical rows without an explicitly authorized repair workflow.

## 8. Update Command and Schedule

The update command should first inspect canonical latest/coverage state and then download/import missing official periods. Schedule activation requires separate operator approval.

## 9. API and PWA

Add read-only API endpoints, status/health support, tests, PWA dataset labels, manual update allow-list entries, and documentation.

## 10. Release Gate

Before release: tests, lint/syntax checks, DB health checks, duplicate/gap checks, API smoke, docs update, changelog update, and git tag/push if requested.
