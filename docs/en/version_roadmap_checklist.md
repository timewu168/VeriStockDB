# Version Roadmap Checklist

<!-- i18n-switch -->
[中文](../version_roadmap_checklist.md) | [English](version_roadmap_checklist.md)
<!-- /i18n-switch -->

This checklist summarizes the version roadmap and completion gates.

## Completed Stages

- v0.2.x: close data, trading days, rollback, deployment foundation.
- v0.3.x: API, attention/disposal notices, Telegram, legal investors, margin, retry behavior.
- v0.4.x: public preview readiness, repo hygiene, day trading, monthly revenue.
- v0.5.x: Local Management PWA and manual update jobs.
- v0.6.x: dataset drill-down, schedule health, documentation boundary, restore SOP, new dataset SOP, all-dataset health check.

## Current Stage

The project is ready for long-running observation. New major features should wait until schedule stability, official source behavior, manual repair flows, and backup policy have been observed in production.

## Standard Release Gate

- tests pass
- syntax checks pass
- DB health checks pass
- duplicate/gap checks pass
- API smoke checks pass if API changed
- docs and changelog updated
- no secrets or private paths in public docs
- commit/tag/push only when requested
