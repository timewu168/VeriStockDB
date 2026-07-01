# Backup and Restore SOP

<!-- i18n-switch -->
[中文](../backup_restore_sop.md) | [English](backup_restore_sop.md)
<!-- /i18n-switch -->

This SOP describes how to verify and restore the SQLite canonical database without corrupting accepted data.

## Principles

- Never overwrite the production DB before confirming a readable backup.
- Always keep the incident DB copy before replacing it.
- Run restore drills against a temporary copy first.
- Use SQLite `PRAGMA integrity_check` and dataset smoke checks before resuming services.

## Standard Restore Flow

1. Stop API and scheduled update services.
2. Copy the current incident DB to a timestamped safe location.
3. Select the intended backup file.
4. Copy the backup to `/tmp` and run a non-destructive restore drill.
5. Run SQLite integrity check.
6. Check row counts and latest periods for core datasets.
7. Replace the production DB only after the temporary copy passes validation.
8. Restart services and run operational health checks.

## Required Checks

```bash
sqlite3 restored.db 'PRAGMA integrity_check;'
python3 main.py --db restored.db dataset-health-check
python3 main.py --db restored.db status --problems --details
```

## Notes

The latest documented v0.6.3 drill rebuilt the latest backup and verified a temporary restore copy with matching row counts and latest periods. Treat backup validation as a recurring operational requirement, not a one-time setup task.
