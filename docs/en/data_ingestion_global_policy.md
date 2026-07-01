# Data Ingestion Global Policy

<!-- i18n-switch -->
[中文](../data_ingestion_global_policy.md) | [English](data_ingestion_global_policy.md)
<!-- /i18n-switch -->

This policy defines the common safety rules for all VeriStockDB official-source ingestion flows.

## Core Rules

- Official source data must be downloaded and validated before import.
- Missing official numeric cells must not be guessed or filled with `0` unless the dataset has a documented historical-format exception.
- Required headers and field counts must be validated.
- Stock IDs are text and must preserve leading zeroes.
- Dates must match the canonical period format for the dataset.
- Suspicious rows, shifted columns, HTML error pages, JSON error pages, and no-data responses must be blocked.

## Import Behavior

- Dry-run first for new or changed parsers.
- Formal import must be idempotent and guarded by primary/unique keys.
- Canonical rows must not be overwritten without explicit repair authorization.
- Problems should be written to batch/error/event records or reports.

## Tests

Every new dataset importer should include tests for missing required columns, blank required fields, shifted rows, invalid dates, duplicate keys, and official error pages.
