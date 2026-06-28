# Security Policy

## Supported Versions

Security updates are handled on the `main` branch and the latest tagged public-preview release.

## Reporting a Vulnerability

Please do not open a public issue for a sensitive vulnerability.

Report security concerns through a private GitHub security advisory when available, or contact the repository maintainer through the contact channel listed on the GitHub repository profile.

Include:

- affected version or commit
- reproduction steps
- expected and actual impact
- whether credentials, local data, or systemd deployment files are involved

## Secrets and Local Data

Never commit:

- `.env` files or production environment files
- Telegram tokens or chat IDs
- SQLite databases
- downloaded CSV files
- backup archives
- logs or reports containing private operational paths

The public repository should use example paths and sample configuration only.
