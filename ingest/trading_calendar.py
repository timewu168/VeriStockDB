from __future__ import annotations

from datetime import date
import sqlite3


def is_open(conn: sqlite3.Connection, trade_date: str) -> bool | None:
    row = conn.execute(
        "SELECT is_open FROM trading_days WHERE trade_date = ?",
        (trade_date,),
    ).fetchone()
    if row is None:
        return None
    return bool(row["is_open"])


def trading_days_between(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (start, end),
    ).fetchall()
    return [row["trade_date"] for row in rows]


def rollback_trading_days(
    conn: sqlite3.Connection, target_date: str, count: int = 3
) -> list[str]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (target_date, count),
    ).fetchall()
    return [row["trade_date"] for row in rows]


def validate_iso_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must be YYYY-MM-DD: {value}") from exc
    return parsed.isoformat()
