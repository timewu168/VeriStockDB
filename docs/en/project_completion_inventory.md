# Project Completion Inventory

<!-- i18n-switch -->
[中文](../project_completion_inventory.md) | [English](project_completion_inventory.md)
<!-- /i18n-switch -->

This inventory helps PMs and integration owners understand what VeriStockDB currently provides and where its boundaries are.

## Current Conclusion

As of v0.6.5, VeriStockDB has reached a first-stage usable state and is ready for long-running operational observation.

Completed capabilities include official data download, validation, blocking suspicious data, canonical SQLite import, read-only API, local management PWA, manual repair jobs, schedule health, all-dataset health check, backup/restore SOP, documentation boundaries, and repo hygiene.

## Canonical Datasets

- `daily_close`
- `attention_notices`
- `disposal_notices`
- `legal_investors`
- `margin_trading`
- `day_trading`
- `monthly_revenue`
- `trading_days`

## Operational Tables

- `import_batches`
- `import_errors`
- `data_events`
- `settings`
- `ops_jobs`

## Latest v0.6.5 Health Baseline

- `dataset-health-check OK`
- duplicate keys: `0`
- gaps: `0`
- recent errors: `0`

Row-count baseline:

| Dataset | Rows |
| --- | ---: |
| `daily_close` | `8715496` |
| `attention_notices` | `102605` |
| `disposal_notices` | `7716` |
| `legal_investors` | `5832010` |
| `margin_trading` | `8146089` |
| `day_trading` | `4037752` |
| `monthly_revenue` | `280711` |

## Integration Guidance

- Use the Local Truth API for downstream services.
- Do not read hot CSV files directly as canonical data.
- Treat SQLite as the source of truth.
- Keep ClickHouse, if introduced, as an analytical/query layer only.
- Do not expose this local API publicly without authentication, rate limits, and deployment hardening.

## Remaining Risks

- Official source formats may change.
- Production timers need long-running observation.
- Manual repair workflows should be reviewed after real failures.
- Backup retention policy still needs operational ownership.
