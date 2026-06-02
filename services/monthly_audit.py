from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3

import config
from services import batch_status


@dataclass
class AuditResult:
    dataset: str
    month: str
    status: str
    errors: list[str] = field(default_factory=list)


def audit_month(
    conn: sqlite3.Connection, *, dataset: str = config.DATASET_DAILY_CLOSE, month: str
) -> AuditResult:
    if dataset != config.DATASET_DAILY_CLOSE:
        raise ValueError("v1 monthly audit only supports daily_close")
    errors: list[str] = []
    month_prefix = f"{month}-"
    open_days = _open_days(conn, month_prefix)
    if not open_days:
        errors.append(f"no open trading days found for {month}")

    problem_rows = conn.execute(
        """
        SELECT market, period, status, error_summary
        FROM import_batches
        WHERE dataset = ? AND period LIKE ? AND status IN ('BLOCKED', 'RECHECK', 'MISSING')
        ORDER BY period, market
        """,
        (dataset, month_prefix + "%"),
    ).fetchall()
    for row in problem_rows:
        errors.append(f"{row['period']} {row['market']} {row['status']}: {row['error_summary'] or ''}".strip())

    for row in conn.execute(
        """
        SELECT market, period, row_count
        FROM import_batches
        WHERE dataset = ? AND period LIKE ? AND status IN ('OK', 'FIXED')
        ORDER BY period, market
        """,
        (dataset, month_prefix + "%"),
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
        if batch_status.get_setting(conn, rollback_key) != "OK":
            errors.append(f"last trading day rollback not completed: {last_open_day}")
        for trade_date in open_days:
            for market in config.MARKETS:
                batch = batch_status.get_batch(conn, dataset, market, trade_date)
                if batch is None:
                    errors.append(f"{trade_date} {market} batch is missing")

    status = "OK" if not errors else "RECHECK"
    batch_status.set_setting(conn, f"audit:{dataset}:{month}", status)
    batch_status.set_setting(conn, f"audit_checked_at:{dataset}:{month}", batch_status.utc_now_text())
    return AuditResult(dataset=dataset, month=month, status=status, errors=errors)


def _open_days(conn: sqlite3.Connection, month_prefix: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date LIKE ?
        ORDER BY trade_date
        """,
        (month_prefix + "%",),
    ).fetchall()
    return [row["trade_date"] for row in rows]
