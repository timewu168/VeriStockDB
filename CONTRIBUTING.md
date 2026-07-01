# Contributing

<!-- i18n-switch -->
[English](CONTRIBUTING.md) | [中文](CONTRIBUTING.zh-TW.md)
<!-- /i18n-switch -->


Thanks for considering a contribution to VeriStockDB.

VeriStockDB treats SQLite as the canonical truth store. Contributions that touch data ingestion, schema, official-source parsing, or scheduling should preserve the project's validation-first behavior.

## Development Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run tests before opening a pull request:

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q api ingest services main.py tests config.py
```

## Pull Request Guidelines

- Keep changes focused and explain the operational impact.
- Add or update tests for parser, importer, API, or scheduler behavior changes.
- Do not commit local databases, CSV downloads, backups, logs, reports, `.env` files, tokens, or credentials.
- Do not include private deployment paths in public documentation; use example paths such as `/opt/veristockdb/app`.
- Do not introduce destructive DB behavior unless the change is explicitly documented, reviewed, and guarded.

## Data Safety Rules

Pull requests must not perform or encourage unguarded:

- `drop`, `truncate`, or destructive `delete`
- overwriting canonical SQLite rows
- schema migrations without a migration plan and validation checks
- production systemd timer changes without explicit operator action
- moving canonical truth from SQLite to another store

## Validation Checklist

For DB-changing work, include evidence for the relevant checks:

- SQLite `PRAGMA integrity_check`
- backup availability
- row counts before and after
- duplicate key checks
- date coverage against `trading_days`
- schema validation against `db/schema.sql`
- source coverage or dry-run reports

If ClickHouse is introduced for a contribution, include table counts, row counts, sample aggregation checks, and sorting or duplicate-key validation.
