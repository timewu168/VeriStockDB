# Telegram Notification Spec

<!-- i18n-switch -->
[中文](../telegram_notification_spec.md) | [English](telegram_notification_spec.md)
<!-- /i18n-switch -->

This spec describes Telegram notification behavior for VeriStockDB operations.

## Purpose

Telegram notifications report scheduled update results, failures, blocked data, and health warnings to the operator.

## Rules

- Do not include secrets in logs or notifications.
- Missing token/chat ID should skip notification with a warning, not fail the data job.
- Notifications should summarize success, blocked rows/files, missing data, retry behavior, and required operator action.
- Schedule health should detect timer/log/data freshness problems even if a notification was missed.

## Operational Notes

Telegram is an alerting layer, not the source of truth. The canonical status remains in SQLite operational tables, logs, and health-check commands.
