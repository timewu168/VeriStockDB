# Local Truth API Spec

<!-- i18n-switch -->
[中文](../local_truth_api_spec.md) | [English](local_truth_api_spec.md)
<!-- /i18n-switch -->

This is the English companion for the Local Truth API contract. The API exposes validated SQLite canonical data and operational status for local tools and the PWA.

## General Rules

- Base path: `/api/v1`.
- Date input for daily datasets: `YYYY-MM-DD`.
- Month input for monthly datasets: `YYYY-MM`.
- Compact dates such as `20260615` are invalid.
- API responses should use structured JSON errors.
- Query endpoints support date/month range, market, stock ID, field selection, limit, and offset where applicable.
- Prices remain integer cents in API/DB contracts; presentation layers may divide by `100`.

## Core Endpoints

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
- `GET /api/v1/batches/{batch_id}`
- `GET /api/v1/errors`
- `GET /api/v1/events`
- `GET /api/v1/ops/summary`
- `GET /api/v1/ops/schedule-health`
- `GET /api/v1/ops/dataset-health-check`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/update-dataset`

## Dataset Query Behavior

- Without `stock_id`, query endpoints return all matching rows for the requested range.
- With `stock_id`, endpoints filter to that security.
- `fields` may restrict returned columns where supported.
- Pagination uses `limit` and `offset`.
- Error responses must identify invalid parameters rather than silently coercing them.

## Manual Update Jobs

`POST /api/v1/jobs/update-dataset` can only run allow-listed update commands. It must not accept arbitrary shell commands. A single-writer guard prevents overlapping manual update jobs.

## Compatibility

Adding fields is usually non-breaking. Removing fields, changing types, changing date formats, or changing canonical units is breaking.
