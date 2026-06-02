from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass, field
import sqlite3

import config
from ingest.trading_calendar import validate_iso_date
from services import batch_status


@dataclass
class AuditResult:
    dataset: str
    month: str
    status: str
    errors: list[str] = field(default_factory=list)


def audit_month(
    conn: sqlite3.Connection,
    *,
    dataset: str = config.DATASET_DAILY_CLOSE,
    month: str,
    markets: Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    require_rollback: bool = True,
) -> AuditResult:
    if dataset != config.DATASET_DAILY_CLOSE:
        raise ValueError("v1 monthly audit only supports daily_close")
    errors: list[str] = []
    start_date, end_date, full_month = audit_date_range(month, start, end)
    selected_markets = normalize_markets(markets)
    full_markets = selected_markets == config.MARKETS
    open_days = _open_days(conn, start_date, end_date)
    if not open_days:
        errors.append(f"no open trading days found between {start_date} and {end_date}")

    market_filter = ",".join("?" for _ in selected_markets)
    problem_rows = conn.execute(
        f"""
        SELECT market, period, status, error_summary
        FROM import_batches
        WHERE dataset = ?
          AND period BETWEEN ? AND ?
          AND market IN ({market_filter})
          AND status IN ('BLOCKED', 'RECHECK', 'MISSING')
        ORDER BY period, market
        """,
        (dataset, start_date, end_date, *selected_markets),
    ).fetchall()
    for row in problem_rows:
        errors.append(f"{row['period']} {row['market']} {row['status']}: {row['error_summary'] or ''}".strip())

    for row in conn.execute(
        f"""
        SELECT market, period, row_count
        FROM import_batches
        WHERE dataset = ?
          AND period BETWEEN ? AND ?
          AND market IN ({market_filter})
          AND status IN ('OK', 'FIXED')
        ORDER BY period, market
        """,
        (dataset, start_date, end_date, *selected_markets),
    ):
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM daily_close WHERE trade_date = ? AND market = ?",
            (row["period"], row["market"]),
        ).fetchone()["count"]
        if row["row_count"] != count:
            errors.append(
                f"{row['period']} {row['market']} row_count mismatch: batch={row['row_count']} table={count}"
            )

    if open_days:
        last_open_day = open_days[-1]
        rollback_key = f"rollback:{dataset}:{last_open_day}"
        if require_rollback and batch_status.get_setting(conn, rollback_key) != "OK":
            errors.append(f"last trading day rollback not completed: {last_open_day}")
        for trade_date in open_days:
            for market in selected_markets:
                batch = batch_status.get_batch(conn, dataset, market, trade_date)
                if batch is None:
                    errors.append(f"{trade_date} {market} batch is missing")

    status = "OK" if not errors else "RECHECK"
    audit_key = audit_setting_key(
        dataset,
        month,
        start_date,
        end_date,
        selected_markets,
        full_month=full_month,
        full_markets=full_markets,
        require_rollback=require_rollback,
    )
    batch_status.set_setting(conn, audit_key, status)
    checked_at_key = (
        f"audit_checked_at:{dataset}:{month}"
        if audit_key == f"audit:{dataset}:{month}"
        else f"{audit_key}:checked_at"
    )
    batch_status.set_setting(conn, checked_at_key, batch_status.utc_now_text())
    return AuditResult(dataset=dataset, month=month, status=status, errors=errors)


def _open_days(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
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


def audit_date_range(month: str, start: str | None, end: str | None) -> tuple[str, str, bool]:
    year_text, month_text = month.split("-", 1)
    year = int(year_text)
    month_number = int(month_text)
    default_start = f"{month}-01"
    default_end = f"{month}-{monthrange(year, month_number)[1]:02d}"
    start_date = validate_iso_date(start) if start else default_start
    end_date = validate_iso_date(end) if end else default_end
    if not start_date.startswith(f"{month}-"):
        raise ValueError(f"--from must be within {month}: {start_date}")
    if not end_date.startswith(f"{month}-"):
        raise ValueError(f"--to must be within {month}: {end_date}")
    if start_date > end_date:
        raise ValueError(f"--from must be earlier than or equal to --to: {start_date} > {end_date}")
    return start_date, end_date, start_date == default_start and end_date == default_end


def normalize_markets(markets: Iterable[str] | None) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(markets or config.MARKETS))
    unknown = sorted(set(selected) - set(config.MARKETS))
    if unknown:
        raise ValueError(f"unknown market: {', '.join(unknown)}")
    return selected


def audit_setting_key(
    dataset: str,
    month: str,
    start: str,
    end: str,
    markets: tuple[str, ...],
    *,
    full_month: bool,
    full_markets: bool,
    require_rollback: bool,
) -> str:
    if full_month and full_markets and require_rollback:
        return f"audit:{dataset}:{month}"
    market_scope = ",".join(markets)
    rollback_scope = "with_rollback" if require_rollback else "skip_rollback"
    return f"audit:{dataset}:{month}:{start}:{end}:{market_scope}:{rollback_scope}"
