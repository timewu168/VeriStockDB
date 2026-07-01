# Legal Investor Ingestion Blockers

<!-- i18n-switch -->
[中文](../legal_investor_ingestion_blockers.md) | [English](legal_investor_ingestion_blockers.md)
<!-- /i18n-switch -->

This document records historical TWSE/TPEX legal-investor CSV problems encountered during ingestion.

## Historical Issue

Some official CSV files temporarily omitted zero-value foreign-dealer columns, causing row shifts. Those files had to be blocked until re-downloaded or verified against official HTML.

## Current Rule

Legal investor CSV import must reject shifted rows, missing required columns, invalid dates, and unexpected formats. Official files should be retried, revalidated, and only then imported.

## Current Status

The v0.6.5 all-dataset health check reports `legal_investors` as OK with zero duplicate keys, zero gaps, and zero recent errors. This file is retained as a historical caution and validation boundary.
