from __future__ import annotations

import sqlite3
from pathlib import Path

import config


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str | None = None, seed_trading_days: bool = True) -> Path:
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        schema = (config.ROOT_DIR / "db" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema)
        _insert_default_settings(conn)
        if seed_trading_days:
            seed_trading_days_from_legacy_db(conn, config.TRADING_DAY_SEED_DB)
        conn.commit()
    finally:
        conn.close()
    return path


def _insert_default_settings(conn: sqlite3.Connection) -> None:
    defaults = {
        "schema_version": config.SCHEMA_VERSION,
        "app_version": config.APP_VERSION,
        "backup_retention_count": "1",
        "cooldown_min_seconds": str(config.DEFAULT_COOLDOWN_MIN_SECONDS),
        "cooldown_max_seconds": str(config.DEFAULT_COOLDOWN_MAX_SECONDS),
        "delete_loose_csv_after_verified_zip": "1",
    }
    conn.executemany(
        "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
        sorted(defaults.items()),
    )
    conn.executemany(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        [
            ("app_version", config.APP_VERSION),
            ("schema_version", config.SCHEMA_VERSION),
        ],
    )


def seed_trading_days_from_legacy_db(
    conn: sqlite3.Connection, legacy_db_path: Path | str
) -> int:
    legacy_path = Path(legacy_db_path)
    if not legacy_path.exists():
        return 0

    source = sqlite3.connect(legacy_path)
    try:
        source.row_factory = sqlite3.Row
        has_table = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trading_days'"
        ).fetchone()
        if not has_table:
            return 0
        rows = source.execute("SELECT date FROM trading_days ORDER BY date").fetchall()
    finally:
        source.close()

    inserted = 0
    for row in rows:
        trade_date = str(row["date"]).replace("/", "-")
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_days(trade_date, is_open, source, note)
            VALUES (?, 1, 'legacy_seed', 'seeded from data/db/trading_days.db')
            """,
            (trade_date,),
        )
        inserted += conn.total_changes - before
    return inserted
