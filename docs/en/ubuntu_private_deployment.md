# Ubuntu Private Deployment

<!-- i18n-switch -->
[中文](../ubuntu_private_deployment.md) | [English](ubuntu_private_deployment.md)
<!-- /i18n-switch -->

This document provides example Ubuntu deployment guidance for a private VeriStockDB instance.

## Example Layout

```bash
/opt/veristockdb/app
/opt/veristockdb/app/data/db/veristock.db
/opt/veristockdb/app/data/csv
/var/log/veristockdb
/mnt/veristockdb-cold/veristockdb/archive
/mnt/veristockdb-cold/veristockdb/backup
```

## Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 nodejs npm
```

## Environment

Use an environment file for private paths and notification settings. Do not commit production environment files.

## systemd

Production timers should run update commands at the accepted schedule. Timer creation/modification requires manual operator approval and sudo action.

## API/PWA

For local-only use, bind FastAPI to loopback or a trusted LAN address. Do not expose it publicly without authentication and deployment hardening.
