# Ubuntu Private Deployment Status

<!-- i18n-switch -->
[中文](../ubuntu_private_deployment_status.md) | [English](ubuntu_private_deployment_status.md)
<!-- /i18n-switch -->

This status note records the accepted private deployment shape.

## Accepted State

- SQLite is the canonical DB.
- CSV hot storage contains qualified source files.
- Cold archive and backup directories are separate from the repo.
- systemd timers handle production updates.
- Logs are kept under the deployment log directory.
- PWA/API are local management tools.

## Checks

Use:

```bash
python3 main.py status --problems --details
python3 main.py schedule-health
python3 main.py dataset-health-check
```

Production changes to timers, schema, canonical data, backups, or archive policy require explicit operator approval.
