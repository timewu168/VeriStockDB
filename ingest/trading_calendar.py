from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import sqlite3

from ingest.downloader import (
    CooldownController,
    FetchTradingDaysJson,
    LogFunc,
    download_tpex_trading_days_json,
    download_trading_days_json,
)


@dataclass(frozen=True)
class TradingCalendarMonth:
    source: str
    open_dates: set[str]


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


def latest_open_trading_day_on_or_before(
    conn: sqlite3.Connection, target_date: str
) -> str | None:
    target = validate_iso_date(target_date)
    row = conn.execute(
        """
        SELECT MAX(trade_date) AS trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date <= ?
        """,
        (target,),
    ).fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


def next_open_trading_day_after(
    conn: sqlite3.Connection, trade_date: str, through_date: str
) -> str | None:
    start = validate_iso_date(trade_date)
    through = validate_iso_date(through_date)
    row = conn.execute(
        """
        SELECT MIN(trade_date) AS trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date > ? AND trade_date <= ?
        """,
        (start, through),
    ).fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


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
    refresh_from: str | None = None,
    fetcher: FetchTradingDaysJson = download_trading_days_json,
    fallback_fetcher: FetchTradingDaysJson = download_tpex_trading_days_json,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> int:
    through = date.fromisoformat(validate_iso_date(through_date))
    latest = latest_calendar_date(conn)
    refresh_start = (
        date.fromisoformat(validate_iso_date(refresh_from))
        if refresh_from
        else through.replace(day=1)
    )
    if refresh_start > through:
        refresh_start = through

    has_missing_tail = not latest or latest < through.isoformat()
    has_inferred_closed_rows = _has_inferred_closed_days(
        conn, refresh_start.isoformat(), through.isoformat()
    )
    if latest and not has_missing_tail and not has_inferred_closed_rows:
        return 0

    start = through.replace(day=1)
    if latest and has_missing_tail:
        next_missing = date.fromisoformat(latest) + timedelta(days=1)
        start = next_missing
    if has_inferred_closed_rows and refresh_start < start:
        start = refresh_start
    month_starts = _month_starts_between(start, through)
    open_dates: set[str] = set()
    month_sources: dict[str, str] = {}
    cooldown = cooldown or CooldownController()
    if log:
        log(f"INFO refreshing trading calendar {start.isoformat()} -> {through.isoformat()}")
    for month_start in month_starts:
        cooldown.before_request(log)
        month_calendar = _fetch_trading_calendar_month(
            month_start.isoformat(),
            fetcher=fetcher,
            fallback_fetcher=fallback_fetcher,
            log=log,
        )
        month_open_dates = month_calendar.open_dates
        month_source = month_calendar.source
        open_dates.update(month_open_dates)
        month_sources[month_start.isoformat()] = month_source
        if log:
            log(
                f"INFO trading calendar month {month_start.strftime('%Y-%m')} "
                f"source={month_source} open days={len(month_open_dates)}"
            )

    before = conn.total_changes
    current = start
    while current <= through:
        trade_date = current.isoformat()
        month_source = month_sources[current.replace(day=1).isoformat()]
        source_label = _trading_calendar_source_label(month_source)
        is_open_value = 1 if trade_date in open_dates else 0
        note = (
            f"open day from {source_label}"
            if is_open_value
            else f"closed day inferred from {source_label}"
        )
        conn.execute(
            """
            INSERT INTO trading_days(trade_date, is_open, source, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
              is_open = excluded.is_open,
              source = excluded.source,
              note = excluded.note
            """,
            (trade_date, is_open_value, month_source, note),
        )
        current += timedelta(days=1)
    changed = conn.total_changes - before
    if log:
        log(f"INFO trading calendar updated rows={changed} through={through.isoformat()}")
    return changed


def _fetch_trading_calendar_month(
    month_start: str,
    *,
    fetcher: FetchTradingDaysJson,
    fallback_fetcher: FetchTradingDaysJson,
    log: LogFunc | None = None,
) -> TradingCalendarMonth:
    primary_error: Exception | None = None
    try:
        twse_open_dates = parse_twse_fmtqik_open_dates(fetcher(month_start))
        if twse_open_dates:
            return TradingCalendarMonth("twse_fmtqik", twse_open_dates)
        primary_error = ValueError("TWSE FMTQIK returned 0 open days")
    except Exception as exc:
        primary_error = exc

    if log:
        log(
            "WARN TWSE FMTQIK trading calendar unavailable for "
            f"{month_start}: {primary_error}; trying TPEx tradingIndex"
        )

    try:
        tpex_open_dates = parse_tpex_trading_index_open_dates(fallback_fetcher(month_start))
    except Exception as exc:
        raise ValueError(
            "trading calendar unavailable from TWSE FMTQIK and TPEx "
            f"tradingIndex for {month_start}"
        ) from exc
    if not tpex_open_dates:
        raise ValueError(
            "trading calendar has no open days from TWSE FMTQIK or TPEx "
            f"tradingIndex for {month_start}"
        ) from primary_error
    return TradingCalendarMonth("tpex_trading_index", tpex_open_dates)


def _has_inferred_closed_days(conn: sqlite3.Connection, start: str, end: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM trading_days
        WHERE trade_date BETWEEN ? AND ?
          AND is_open = 0
          AND source IN ('twse_fmtqik', 'tpex_trading_index')
          AND (
            note LIKE 'closed day inferred from TWSE FMTQIK%'
            OR note LIKE 'closed day inferred from TPEx tradingIndex%'
          )
        LIMIT 1
        """,
        (start, end),
    ).fetchone()
    return row is not None



def backfill_trading_days_from_twse(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    fetcher: FetchTradingDaysJson = download_trading_days_json,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> int:
    start_date = date.fromisoformat(validate_iso_date(start))
    end_date = date.fromisoformat(validate_iso_date(end))
    if start_date > end_date:
        raise ValueError(f"trading calendar start date is after end date: {start} > {end}")
    month_starts = _month_starts_between(start_date, end_date)
    cooldown = cooldown or CooldownController()
    before = conn.total_changes
    if log:
        log(f"INFO backfilling TWSE trading calendar {start_date.isoformat()} -> {end_date.isoformat()}")
    for month_start in month_starts:
        cooldown.before_request(log)
        payload = fetcher(month_start.isoformat())
        open_dates = parse_twse_fmtqik_open_dates(payload)
        if not open_dates:
            raise ValueError(f"TWSE FMTQIK returned 0 open days for {month_start.strftime('%Y-%m')}")
        month_end = _month_end(month_start)
        current = max(start_date, month_start)
        stop = min(end_date, month_end)
        while current <= stop:
            trade_date = current.isoformat()
            is_open_value = 1 if trade_date in open_dates else 0
            note = "open day from TWSE FMTQIK" if is_open_value else "closed day inferred from TWSE FMTQIK"
            conn.execute(
                """
                INSERT INTO trading_days(trade_date, is_open, source, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                  is_open = excluded.is_open,
                  source = excluded.source,
                  note = excluded.note
                """,
                (trade_date, is_open_value, "twse_fmtqik", note),
            )
            current += timedelta(days=1)
        if log:
            log(
                f"INFO TWSE FMTQIK month {month_start.strftime('%Y-%m')} "
                f"open days={len(open_dates)}"
            )
    changed = conn.total_changes - before
    if log:
        log(f"INFO TWSE trading calendar backfilled rows={changed}")
    return changed


def _month_end(month_start: date) -> date:
    year = month_start.year + (1 if month_start.month == 12 else 0)
    month = 1 if month_start.month == 12 else month_start.month + 1
    return date(year, month, 1) - timedelta(days=1)

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


def parse_tpex_trading_index_open_dates(payload: dict) -> set[str]:
    if payload.get("stat") != "ok":
        raise ValueError(f"TPEx tradingIndex returned non-ok status: {payload.get('stat')}")

    open_dates = set()
    tables = payload.get("tables") or []
    if tables:
        for table in tables:
            if not isinstance(table, dict):
                continue
            open_dates.update(
                _parse_tpex_trading_index_rows(
                    table.get("data") or [], table.get("fields") or []
                )
            )
        return open_dates

    return _parse_tpex_trading_index_rows(
        payload.get("data") or [], payload.get("fields") or []
    )


def _parse_tpex_trading_index_rows(rows: list, fields: list) -> set[str]:
    date_index = 0
    for candidate in ("日期", "Date"):
        if candidate in fields:
            date_index = fields.index(candidate)
            break

    open_dates = set()
    for row in rows:
        if isinstance(row, dict):
            value = row.get("日期") or row.get("Date") or row.get("date")
        else:
            if len(row) <= date_index:
                continue
            value = row[date_index]
        if value:
            open_dates.add(_roc_date_to_iso(str(value)))
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


def _trading_calendar_source_label(source: str) -> str:
    if source == "twse_fmtqik":
        return "TWSE FMTQIK"
    if source == "tpex_trading_index":
        return "TPEx tradingIndex"
    return source
