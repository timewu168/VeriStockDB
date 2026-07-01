# VeriStockDB Data Ingestion Global Policy

<!-- i18n-switch -->
[中文](../docs/data_ingestion_global_policy.md) | [English](en/data_ingestion_global_policy.md)
<!-- /i18n-switch -->


This policy applies to every official-data table in VeriStockDB: Close, Legal,
Margin, DayTrading, Revenue, Notice, Disposal, and future datasets.

## Non-Negotiable Rules

1. Never invent official data.
   - Do not fill missing official numeric cells with `0`.
   - Do not infer missing official fields from surrounding rows.
   - Do not guess missing stock-code leading zeroes.
   - Only store `0` when the official source explicitly contains `0` or a
     documented domain-specific exception says so.

2. Missing columns and blank source cells are data failures.
   - If a required official column is absent, the cleaner must raise
     `DataPollutionError`.
   - If an official numeric cell is blank, whitespace, `NaN`, `N/A`, or
     otherwise not a real source value, the cleaner must raise
     `CircuitBreakerTripped`.
   - Dataset-specific placeholders such as Close `--`, `---`, and `----` are
     not general missing values. They may be accepted only when a documented
     dataset rule proves the source condition, for example no-trade or
     suspended Close rows.
   - `NULL` in the DB is allowed only when the source format genuinely does not
     provide that optional field for that era; it must not be created by
     silently swallowing a present-but-blank source cell.

3. Retry belongs outside the cleaner.
   - Cleaners must be deterministic: raw bytes in, clean rows or an exception
     out.
   - Batch/import services must catch cleaner failures, re-download the official
     source up to 3 times, and retry cleaning each fresh download.
   - Official requests after the first request in a job must respect the project
     cooldown before connecting again. The default cooldown is a random 10 to 15
     seconds, and the wait must be visible as `INFO` in progress logs. This
     applies across dates, markets, and retry attempts; normal cooldown waits
     must not be logged as warnings.
   - If all 3 official attempts still fail, the import must stop and surface the
     failure in progress logs and reports.

4. Exceptions must be explicit and documented.
   - Close missing OHLC handling is a documented special case because official
     suspended/no-trade rows use dash placeholders. In the human-first rebuild,
     these rows must use the previous valid close when available; if no previous
     close can be proven, the batch must stop for `RECHECK` instead of storing
     `0`.
   - Early Close rows with zero volume, zero amount, zero transactions, and dash
     OHLC may be excluded until the instrument first has a provable valid close.
     This is a row-level cold-start exclusion, not a price fill and not a
     permanent stock-code exclusion.
   - Close rows filled from previous close and Close rows excluded by the
     zero-trade cold-start rule must be recorded in `data_events`, including the
     source dash values, stored value when present, and reference period when a
     previous close was used. This preserves recovery paths if older historical
     data becomes available later.
   - Any future exception must name the dataset, source condition, stored value,
     audit field, and test case before implementation.

5. Tests must lock the policy.
   - Every new dataset importer needs tests for missing required columns, blank
     numeric source cells, official retry on cleaner failure, and stop-after-3
     behavior.
   - A cleaner test is not enough; the importer/service retry behavior must also
     be tested.

## Implementation Anchors

- Shared cleaner guard: `BaseCleaner.reject_blank_numeric_cells()`.
- Retry boundary examples:
  - `services/local_batch_import_service.py` for Close.
  - `services/local_legal_batch_import_service.py` for Legal.
- Error classes:
  - `DataPollutionError` for schema/header/shape pollution.
  - `CircuitBreakerTripped` for blank core fields or blank numeric source cells.

## Review Checklist

Before adding or changing any table ingestion path:

- Required headers are declared and missing headers fail.
- Official numeric columns reject blank source cells before conversion.
- Cleaner never fills missing source data with guessed values.
- Import service retries official download on cleaner failure.
- Official requests after the first request wait for the project cooldown instead
  of hammering the source repeatedly.
- Three failed official attempts stop the job.
- UI/API progress logs expose the failed date, market, table, and reason.
