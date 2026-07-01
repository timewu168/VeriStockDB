# PWA, CLI, and i18n Boundary Note

<!-- i18n-switch -->
[中文](../pwa_cli_i18n_boundary_note.md) | [English](pwa_cli_i18n_boundary_note.md)
<!-- /i18n-switch -->

This note defines the boundary between the CLI, API, PWA, and documentation language support.

## Boundaries

- CLI commands own ingestion, validation, import, backup, and operational checks.
- API exposes structured local truth data and operational status.
- PWA consumes API responses and never parses CLI stdout directly.
- PWA does not run arbitrary shell commands.
- Manual update buttons call allow-listed job APIs only.

## Language Policy

- Public documentation should have Chinese and English entry points.
- API field names remain stable machine-readable identifiers.
- PWA display labels may be localized separately from API keys.
- Logs and internal diagnostic codes should stay stable and searchable.
