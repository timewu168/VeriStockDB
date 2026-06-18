# Legal Investor Ingestion Blockers

Last updated: 2026-06-15

## Current Rule

Do not implement or run legal investor DB ingestion until the known bad TWSE CSV files below are resolved and revalidated.

If ingestion is requested before resolution, explicitly warn that legal investor ingestion is blocked because two TWSE CSV files still have malformed/misaligned rows.

## Known Bad Files

| Date | Market | Standard path | Status | Note |
| --- | --- | --- | --- | --- |
| 2012-05-23 | TWSE | `data/csv/legal_investor/2012/20120523LegalSII.csv` | BLOCKED | Official CSV currently has rows with missing foreign-dealer zero columns, causing row misalignment. HTML table is usable for comparison. |
| 2024-03-28 | TWSE | `data/csv/legal_investor/2024/20240328LegalSII.csv` | BLOCKED | Official CSV currently has rows with missing foreign-dealer zero columns, causing row misalignment. HTML table is usable for comparison. |

## Rechecked Files

| Date | Market | Result | Note |
| --- | --- | --- | --- |
| 2014-02-19 | TWSE | Standard CSV replaced with validated re-download | HTML response returned a maintenance page, so no HTML cross-check was available. Previous standard file was backed up under `/mnt/veristockdb-cold/veristockdb/backup/legal_csv_validated_replacement_20260615`. |
| 2025-08-27 | TWSE | Standard CSV replaced with validated re-download and matched HTML after stock-code normalization | Formula-style CSV stock codes such as `="00940"` are equivalent to HTML stock code `00940`. Previous standard file was backed up under `/mnt/veristockdb-cold/veristockdb/backup/legal_csv_validated_replacement_20260615`. |


## Latest Full Report

Command:

```bash
python3 main.py report-legal
```

Result after replacing the validated 2014-02-19 and 2025-08-27 TWSE CSV files:

- Total market-days: 8156
- OK: 8154
- BLOCKED: 2
- MISSING: 0
- Remaining blockers: 2012-05-23 TWSE, 2024-03-28 TWSE

## Required Before Ingestion

1. Re-download the two blocked CSV files later, or generate corrected CSV files from official HTML.
2. Validate each corrected file with `inspect-legal` / `validate_legal_csv_bytes`.
3. Re-run full legal CSV validation and confirm zero bad files.
4. Only after that should legal investor schema/import work proceed.
