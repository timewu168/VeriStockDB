from __future__ import annotations

from datetime import date, timedelta
import sqlite3

from ingest.downloader import (
    CooldownController,
    FetchTradingDaysJson,
    LogFunc,
    download_trading_days_json,
)


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


def latest_calendar_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM trading_days").fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


def ensure_trading_days_current(
    conn: sqlite3.Connection,
    *,
    through_date: str,
    fetcher: FetchTradingDaysJson = download_trading_days_json,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> int:
    through = date.fromisoformat(validate_iso_date(through_date))
    latest = latest_calendar_date(conn)
    if latest and latest >= through.isoformat():
        return 0

    start = date.fromisoformat(latest) + timedelta(days=1) if latest else through.replace(day=1)
    month_starts = _month_starts_between(start, through)
    open_dates: set[str] = set()
    cooldown = cooldown or CooldownController()
    if log:
        log(f"INFO refreshing trading calendar {start.isoformat()} -> {through.isoformat()}")
    for month_start in month_starts:
        cooldown.before_request(log)
        payload = fetcher(month_start.isoformat())
        month_open_dates = parse_twse_fmtqik_open_dates(payload)
        open_dates.update(month_open_dates)
        if log:
            log(f"INFO trading calendar month {month_start.strftime('%Y-%m')} open days={len(month_open_dates)}")

    before = conn.total_changes
    current = start
    while current <= through:
        trade_date = current.isoformat()
        is_open_value = 1 if trade_date in open_dates else 0
        note = (
            "open day from TWSE FMTQIK"
            if is_open_value
            else "closed day inferred from TWSE FMTQIK"
        )
        conn.execute(
            """
            INSERT INTO trading_days(trade_date, is_open, source, note)
            VALUES (?, ?, 'twse_fmtqik', ?)
            ON CONFLICT(trade_date) DO UPDATE SET
              is_open = excluded.is_open,
              source = excluded.source,
              note = excluded.note
            """,
            (trade_date, is_open_value, note),
        )
        current += timedelta(days=1)
    changed = conn.total_changes - before
    if log:
        log(f"INFO trading calendar updated rows={changed} through={through.isoformat()}")
    return changed


def parse_twse_fmtqik_open_dates(payload: dict) -> set[str]:
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE FMTQIK returned non-OK status: {payload.get('stat')}")
    fields = payload.get("fields") or []
    try:
        date_index = fields.index("日期")
    except ValueError:
        date_index = 0
    open_dates = set()
    for row in payload.get("data") or []:
        if len(row) <= date_index:
            continue
        open_dates.add(_roc_date_to_iso(str(row[date_index])))
    return open_dates


def validate_iso_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must be YYYY-MM-DD: {value}") from exc
    return parsed.isoformat()


def _month_starts_between(start: date, end: date) -> list[date]:
    month_start = start.replace(day=1)
    values: list[date] = []
    while month_start <= end:
        values.append(month_start)
        year = month_start.year + (1 if month_start.month == 12 else 0)
        month = 1 if month_start.month == 12 else month_start.month + 1
        month_start = date(year, month, 1)
    return values


def _roc_date_to_iso(value: str) -> str:
    parts = value.split("/")
    if len(parts) != 3:
        raise ValueError(f"TWSE FMTQIK date must be ROC Y/M/D: {value}")
    year = int(parts[0]) + 1911
    month = int(parts[1])
    day = int(parts[2])
    return date(year, month, day).isoformat()
