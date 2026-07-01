# Close Monthly Reconciliation Backlog

<!-- i18n-switch -->
[中文](../close_monthly_reconciliation_backlog.md) | [English](close_monthly_reconciliation_backlog.md)
<!-- /i18n-switch -->

This backlog tracks follow-up work for reconciling daily close data against official monthly stock data.

## Scope

- Compare official monthly close and volume values against accepted `daily_close` rows.
- Do not overwrite canonical rows automatically.
- Record mismatches as reports/events for manual review.

## Current Boundary

Monthly reconciliation is a validation and audit workflow. It is not a replacement importer for `daily_close` and must not silently repair accepted rows.

## Future Work

- Keep monthly reconciliation reports easy to inspect.
- Preserve source evidence for mismatches.
- Decide whether repeated official mismatches require a controlled repair command.
