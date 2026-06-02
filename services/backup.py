from __future__ import annotations

from pathlib import Path
import sqlite3

import config


def backup_database(
    db_path: Path | str | None = None,
    backup_path: Path | str | None = None,
) -> Path:
    source_path = Path(db_path) if db_path is not None else config.DB_PATH
    target_path = Path(backup_path) if backup_path is not None else config.DEFAULT_BACKUP_PATH
    if not source_path.exists():
        raise FileNotFoundError(f"database not found: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return target_path
