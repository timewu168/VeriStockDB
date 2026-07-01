
# VeriStockDB

<!-- i18n-switch -->
[中文](README.md) | [English](README.en.md)
<!-- /i18n-switch -->

Version: v0.6.5

VeriStockDB is a local Taiwan stock-market SQLite canonical truth database. It downloads official market data, validates source files, blocks suspicious records, and only then writes accepted data into canonical tables. The goal is to make daily close, attention notices, disposal notices, institutional investors, margin trading, day trading, monthly revenue, and trading-day data stable for local CLI, API, PWA, and analysis workflows.

VeriStockDB is not a trading-advice system, broker integration, order-execution system, or public cloud API.

## Why This Matters

Taiwan market data is distributed across official TWSE, TPEX, and MOPS endpoints with CSV, JSON, HTML, historical format changes, mixed encodings, unit differences, missing files, and short-lived official errors. VeriStockDB puts download, validation, reconciliation, error recording, and canonical SQLite storage in front of analysis so downstream tools can rely on explicit data boundaries.

## Current Scope

Canonical SQLite datasets:

- `daily_close`
- `attention_notices`
- `disposal_notices`
- `legal_investors`
- `margin_trading`
- `day_trading`
- `monthly_revenue`
- `trading_days`

Operational tables:

- `import_batches`
- `import_errors`
- `data_events`
- `settings`
- `ops_jobs`

ClickHouse is not currently the canonical truth store. If introduced later, it must be treated as an analytical or high-volume query layer, not a replacement for SQLite canonical data.

## Core Rules

- Canonical tables store only validated official records.
- Suspicious official source data is blocked instead of overwriting canonical rows.
- Prices are stored as integer cents (`TWD * 100`).
- Stock IDs are text and must preserve leading zeroes.
- Dates use `YYYY-MM-DD`; compact dates such as `20260615` are invalid for public API input.
- CSV files are kept after successful import and may only be archived after monthly audit and ZIP verification.

## System Requirements

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 nodejs npm
```

- `python3`: CLI, ETL, API, and tests.
- `sqlite3`: DB inspection, backup/integrity checks, and release validation.
- `node`: PWA JavaScript syntax checks such as `node --check web/app.js`.
- `npm`: reserved for future PWA tooling; the current PWA has no build step.

## Main CLI Commands

```bash
python3 main.py init-db
python3 main.py status
python3 main.py status --problems --details
python3 main.py ops-check
python3 main.py schedule-health
python3 main.py dataset-health-check
python3 main.py backup
```

Dataset update commands:

```bash
python3 main.py update-close
python3 main.py update-attention
python3 main.py update-disposal
python3 main.py update-legal
python3 main.py update-margin
python3 main.py update-day-trading
python3 main.py update-revenue
```

Historical download/import commands are documented in the Chinese README and dataset SOP. Operators should run dry-run/import commands only after source, schema, and date coverage checks are understood.

## Production Timers

Accepted private deployment schedule:

| Dataset | Schedule |
| --- | --- |
| Close | `Mon..Fri 17:10` |
| Legal investors | `Mon..Fri 18:00` |
| Attention notices | `Mon..Fri 19:00` |
| Disposal notices | `Mon..Fri 19:05` |
| Margin trading | `Mon..Fri 21:05` |
| Day trading | `Mon..Fri 21:10` |
| Monthly revenue | `Mon..Fri *-*-10..12 21:15`, guarded for the 10th or holiday rollover |

Production timer changes require explicit operator approval and manual sudo action.

## Data Sources

- Close: official TWSE/TPEX daily close CSV.
- Trading days: TWSE `FMTQIK` monthly calendar, with TPEX fallback when TWSE is abnormal.
- Attention notices: official TWSE/TPEX attention notice CSV.
- Disposal notices: official TWSE/TPEX disposal notice CSV; update windows extend past the target date to capture newly published notices.
- Legal investors: official TWSE/TPEX institutional-investor CSV.
- Margin trading: TWSE `MI_MARGN` and TPEX `margin/balance` CSV; TPEX canonical scope starts from `2008-09-30`.
- Day trading: TWSE `TWTB4U` and TPEX `intraday/stat` CSV; canonical scope starts from `2014-01-06`.
- Monthly revenue: MOPS `t21sc03_{roc_month}.csv`; canonical scope starts from `2013-01` and follows the monthly publication rule around the 10th.
- Close monthly reconciliation: official TWSE/TPEX per-stock monthly JSON; reconciles only `close` and `volume` and does not overwrite `daily_close`.

### Source Boundary

VeriStockDB v0.6.5 canonical pipeline currently uses verified official CSV/JSON download flows, local cache/archive, and user-supplied CSV import. TWSE/TPEX OpenAPI endpoints are not used as replacements at this stage because their fields, semantics, or coverage may differ from the CSV/JSON sources used by the canonical database. Users must comply with the terms of each data source; VeriStockDB does not grant redistribution rights for official raw data.

## Local Truth API

Start the API:

```bash
pip install -r requirements.txt
python3 -m api
```

Default binding: `127.0.0.1:8000`.

Important endpoints:

- `GET /health`
- `GET /api/v1/info`
- `GET /api/v1/datasets`
- `GET /api/v1/datasets/status-summary`
- `GET /api/v1/datasets/{dataset}/status`
- `GET /api/v1/datasets/{dataset}/health`
- `GET /api/v1/daily-close`
- `GET /api/v1/attention-notices`
- `GET /api/v1/disposal-notices`
- `GET /api/v1/legal-investors`
- `GET /api/v1/margin-trading`
- `GET /api/v1/day-trading`
- `GET /api/v1/monthly-revenue`
- `GET /api/v1/trading-days`
- `GET /api/v1/batches`
- `GET /api/v1/errors`
- `GET /api/v1/events`
- `GET /api/v1/ops/summary`
- `GET /api/v1/ops/schedule-health`
- `GET /api/v1/ops/dataset-health-check`
- `GET /api/v1/jobs`
- `POST /api/v1/jobs/update-dataset`

Full API contract: [docs/en/local_truth_api_spec.md](docs/en/local_truth_api_spec.md).

## Local Management PWA

The PWA lives in `web/` and is served by FastAPI at `/`.

```bash
python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

The PWA is for local data health and manual repair workflows, not stock selection. It shows dataset status, health drill-down, batches, errors, events, schedule health, all-dataset health checks, manual update jobs, and tabular query results.

## Documentation

- [Chinese documentation index](docs/README.md)
- [English documentation index](docs/en/README.md)
- [Chinese changelog](CHANGELOG.md)
- [English changelog](CHANGELOG.en.md)
- [New dataset SOP](docs/en/new_dataset_sop.md)
- [Project completion inventory](docs/en/project_completion_inventory.md)

## Example Paths

```bash
/opt/veristockdb/app                         # repo
/opt/veristockdb/app/data/db/veristock.db    # SQLite canonical DB
/opt/veristockdb/app/data/csv                # hot CSV
/opt/veristockdb/app/reports                 # reports
/var/log/veristockdb                         # systemd logs
/mnt/veristockdb-cold/veristockdb/archive    # cold archive
/mnt/veristockdb-cold/veristockdb/backup     # DB backups
```

## Required Health Checks

Before accepting DB-changing work, run the relevant checks:

- SQLite `PRAGMA integrity_check`
- readable backup and backup integrity check
- row count before/after
- duplicate key check
- date coverage against `trading_days`
- schema validation against `db/schema.sql`
- source coverage or dry-run report
- API route/date/field/pagination/quality checks if API was touched

If ClickHouse is introduced, also validate table count, row count, sample aggregation, duplicate keys, and sorting-key behavior.

## Locked Actions

Do not perform these without explicit authorization:

- drop, truncate, delete, or overwrite canonical SQLite data
- destructive SQL
- schema migrations or version bumps
- enable, disable, or modify production systemd timers
- move SQLite canonical truth to ClickHouse
- create or overwrite ClickHouse tables
- delete backups, archives, CSV files, reports, or logs
- rewrite git history
