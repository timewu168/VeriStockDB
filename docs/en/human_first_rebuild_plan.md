# Human-First Rebuild Plan

<!-- i18n-switch -->
[中文](../human_first_rebuild_plan.md) | [English](human_first_rebuild_plan.md)
<!-- /i18n-switch -->

This historical design document explains the project philosophy: keep the data pipeline understandable, operator-controlled, and validation-first.

## Design Intent

- Prefer clear CLI commands over hidden automation.
- Keep every destructive action explicit and reviewable.
- Preserve official source evidence long enough for audit.
- Do not allow official format drift to silently enter canonical tables.
- Make status, errors, and blocked files visible to a human operator.

## Validation Philosophy

The system should fail closed. If a source file has missing columns, shifted values, unexpected dates, wrong encodings, suspicious row counts, or official error pages, it should be blocked and reported instead of imported.

## Operational Philosophy

Automation is useful only after the guardrails are proven. Manual update jobs and health reports exist so the operator can repair transient official-source problems without bypassing validation.

## Current Status

Most goals from this plan are implemented through dataset importers, strict parsers, status commands, PWA manual jobs, backup/restore SOP, schedule health, and all-dataset health checks. Treat this document as historical design context; use `CURRENT_STATE.md` and the roadmap for current state.
