from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from validate.result import ValidationError


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_batch_id(dataset: str, market: str | None, period: str) -> str:
    return f"{dataset}:{market or '-'}:{period}"


def get_batch(
    conn: sqlite3.Connection, dataset: str, market: str | None, period: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM import_batches
        WHERE dataset = ? AND COALESCE(market, '') = COALESCE(?, '') AND period = ?
        """,
        (dataset, market, period),
    ).fetchone()


def is_manual_approved(
    conn: sqlite3.Connection, dataset: str, market: str | None, period: str
) -> bool:
    row = get_batch(conn, dataset, market, period)
    return bool(row and row["manual_approved"] == 1 and row["manual_approved_reason"])


def record_batch(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    market: str | None,
    period: str,
    status: str,
    row_count: int | None,
    errors: list[ValidationError],
    source_file: str | None = None,
    source_sha256: str | None = None,
    retry_count: int = 0,
    archived_zip: str | None = None,
    note: str | None = None,
    clear_manual_approval: bool = False,
) -> str:
    batch_id = make_batch_id(dataset, market, period)
    existing = get_batch(conn, dataset, market, period)
    manual_approved = int(existing["manual_approved"]) if existing else 0
    manual_approved_at = existing["manual_approved_at"] if existing else None
    manual_approved_reason = existing["manual_approved_reason"] if existing else None
    if clear_manual_approval and status in {"OK", "FIXED"}:
        manual_approved = 0
        manual_approved_at = None
        manual_approved_reason = None

    error_summary = "; ".join(_format_error(err) for err in errors[:3]) or None
    checked_at = utc_now_text()
    conn.execute(
        """
        INSERT INTO import_batches(
          batch_id, dataset, market, period, status, row_count, error_summary,
          source_file, source_sha256, retry_count, archived_zip, checked_at,
          manual_approved, manual_approved_at, manual_approved_reason, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset, market, period) DO UPDATE SET
          status = excluded.status,
          row_count = excluded.row_count,
          error_summary = excluded.error_summary,
          source_file = excluded.source_file,
          source_sha256 = excluded.source_sha256,
          retry_count = excluded.retry_count,
          archived_zip = COALESCE(excluded.archived_zip, import_batches.archived_zip),
          checked_at = excluded.checked_at,
          manual_approved = excluded.manual_approved,
          manual_approved_at = excluded.manual_approved_at,
          manual_approved_reason = excluded.manual_approved_reason,
          note = excluded.note
        """,
        (
            batch_id,
            dataset,
            market,
            period,
            status,
            row_count,
            error_summary,
            source_file,
            source_sha256,
            retry_count,
            archived_zip,
            checked_at,
            manual_approved,
            manual_approved_at,
            manual_approved_reason,
            note,
        ),
    )
    conn.execute("DELETE FROM import_errors WHERE batch_id = ?", (batch_id,))
    for error in errors:
        conn.execute(
            """
            INSERT INTO import_errors(
              error_id, batch_id, severity, code, message,
              sample_stock_id, sample_value, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                batch_id,
                error.severity,
                error.code,
                error.message,
                error.sample_stock_id,
                error.sample_value,
                checked_at,
            ),
        )
    return batch_id


def approve_batch(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    market: str | None,
    period: str,
    reason: str,
    note: str | None = None,
) -> None:
    if not reason.strip():
        raise ValueError("manual approval requires a non-empty reason")
    batch_id = make_batch_id(dataset, market, period)
    existing = get_batch(conn, dataset, market, period)
    if existing is None:
        conn.execute(
            """
            INSERT INTO import_batches(
              batch_id, dataset, market, period, status, checked_at,
              manual_approved, manual_approved_at, manual_approved_reason, note
            )
            VALUES (?, ?, ?, ?, 'RECHECK', ?, 1, ?, ?, ?)
            """,
            (batch_id, dataset, market, period, utc_now_text(), utc_now_text(), reason, note),
        )
    else:
        conn.execute(
            """
            UPDATE import_batches
            SET manual_approved = 1,
                manual_approved_at = ?,
                manual_approved_reason = ?,
                note = COALESCE(?, note)
            WHERE batch_id = ?
            """,
            (utc_now_text(), reason, note, existing["batch_id"]),
        )


def status_summary(conn: sqlite3.Connection, dataset: str | None = None) -> list[sqlite3.Row]:
    params: tuple[str, ...] = ()
    where = ""
    if dataset:
        where = "WHERE dataset = ?"
        params = (dataset,)
    return conn.execute(
        f"""
        SELECT dataset, status, COUNT(*) AS count
        FROM import_batches
        {where}
        GROUP BY dataset, status
        ORDER BY dataset, status
        """,
        params,
    ).fetchall()


def latest_problem(conn: sqlite3.Connection, dataset: str | None = None) -> sqlite3.Row | None:
    params: tuple[str, ...] = ()
    where = "WHERE status IN ('BLOCKED', 'RECHECK', 'MISSING')"
    if dataset:
        where += " AND dataset = ?"
        params = (dataset,)
    return conn.execute(
        f"""
        SELECT dataset, market, period, status, error_summary, checked_at
        FROM import_batches
        {where}
        ORDER BY checked_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()


def problem_batches(conn: sqlite3.Connection, dataset: str | None = None) -> list[sqlite3.Row]:
    params: tuple[str, ...] = ()
    where = "WHERE status IN ('BLOCKED', 'RECHECK', 'MISSING')"
    if dataset:
        where += " AND dataset = ?"
        params = (dataset,)
    return conn.execute(
        f"""
        SELECT batch_id, dataset, market, period, status, error_summary, checked_at
        FROM import_batches
        {where}
        ORDER BY period DESC, market
        """,
        params,
    ).fetchall()


def batch_errors(
    conn: sqlite3.Connection, batch_id: str, limit: int = 10
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT severity, code, message, sample_stock_id, sample_value, created_at
        FROM import_errors
        WHERE batch_id = ?
        ORDER BY created_at, code, sample_stock_id
        LIMIT ?
        """,
        (batch_id, limit),
    ).fetchall()


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _format_error(error: ValidationError) -> str:
    parts = [f"{error.code}: {error.message}"]
    if error.sample_stock_id:
        parts.append(f"sample_stock_id={error.sample_stock_id}")
    if error.sample_value:
        parts.append(f"sample_value={error.sample_value}")
    return parts[0] + " (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else parts[0]
