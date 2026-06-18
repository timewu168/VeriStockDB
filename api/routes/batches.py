from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.date_utils import validate_api_date
from api.dataset_registry import get_dataset_definition
from api.deps import read_only_connection, require_permission
from api.schemas import success_response


router = APIRouter(tags=["batches"])

STATUS_VALUES = ("OK", "FIXED", "BLOCKED", "RECHECK", "MISSING")
MAX_LIMIT = 10000
DEFAULT_LIMIT = 1000
BATCH_DETAIL_ERROR_LIMIT = 20
BATCH_DETAIL_EVENT_LIMIT = 50


@router.get("/batches")
def batches(
    dataset: str | None = None,
    market: str | None = None,
    start: str | None = Query(default=None, alias="from"),
    end: str | None = Query(default=None, alias="to"),
    batch_status: str | None = Query(default=None, alias="status"),
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    filters = _validate_filters(dataset, market, start, end, batch_status, limit, offset)
    try:
        rows = _query_batches(conn, filters)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "import_batches is not readable",
            {"reason": str(exc)},
        ) from exc

    has_more = len(rows) > limit
    returned_rows = rows[:limit]
    return success_response(
        [_batch_to_dict(row) for row in returned_rows],
        meta={
            "filters": filters,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(returned_rows),
                "has_more": has_more,
            },
        },
    )


@router.get("/batches/{batch_id}")
def batch_detail(
    batch_id: str,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    try:
        batch = _get_batch(conn, batch_id)
        if batch is None:
            raise _api_error(
                "NOT_FOUND",
                status.HTTP_404_NOT_FOUND,
                "batch not found",
                {"batch_id": batch_id},
            )
        errors = _batch_errors(conn, batch_id, BATCH_DETAIL_ERROR_LIMIT)
        events = _batch_events(conn, batch_id, BATCH_DETAIL_EVENT_LIMIT)
        error_count = _count_related(conn, "import_errors", batch_id)
        event_count = _count_related(conn, "data_events", batch_id)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "batch detail is not readable",
            {"batch_id": batch_id, "reason": str(exc)},
        ) from exc

    return success_response(
        {
            "batch": _batch_to_dict(batch),
            "errors": [_error_to_dict(row) for row in errors],
            "events": [_event_to_dict(row) for row in events],
            "counts": {
                "errors": error_count,
                "events": event_count,
                "returned_errors": len(errors),
                "returned_events": len(events),
            },
        }
    )


def _validate_filters(
    dataset: str | None,
    market: str | None,
    start: str | None,
    end: str | None,
    batch_status: str | None,
    limit: int,
    offset: int,
) -> dict:
    if dataset and get_dataset_definition(dataset) is None:
        raise _api_error(
            "INVALID_DATASET",
            status.HTTP_400_BAD_REQUEST,
            f"unsupported dataset: {dataset}",
            {"dataset": dataset},
        )
    if market and market not in config.MARKETS:
        raise _api_error(
            "INVALID_MARKET",
            status.HTTP_400_BAD_REQUEST,
            f"market must be one of {', '.join(config.MARKETS)}",
            {"market": market},
        )
    normalized_status = batch_status.upper() if batch_status else None
    if normalized_status and normalized_status not in STATUS_VALUES:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "status must be OK, FIXED, BLOCKED, RECHECK, or MISSING",
            {"status": batch_status},
        )
    parsed_start = _validate_date_filter("from", start)
    parsed_end = _validate_date_filter("to", end)
    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            "from must not be later than to",
            {"from": start, "to": end},
        )
    if limit < 1 or limit > MAX_LIMIT or offset < 0:
        raise _api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            f"limit must be 1..{MAX_LIMIT} and offset must be >= 0",
            {"limit": limit, "offset": offset},
        )
    return {
        "dataset": dataset,
        "market": market,
        "from": parsed_start,
        "to": parsed_end,
        "status": normalized_status,
        "limit": limit,
        "offset": offset,
    }


def _validate_date_filter(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_api_date(value)
    except ValueError as exc:
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            f"{name} must use YYYY-MM-DD",
            {name: value},
        ) from exc


def _query_batches(conn: sqlite3.Connection, filters: dict) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[str | int] = []
    if filters["dataset"]:
        clauses.append("dataset = ?")
        params.append(filters["dataset"])
    if filters["market"]:
        clauses.append("market = ?")
        params.append(filters["market"])
    if filters["from"]:
        clauses.append("period >= ?")
        params.append(filters["from"])
    if filters["to"]:
        clauses.append("period <= ?")
        params.append(filters["to"])
    if filters["status"]:
        clauses.append("status = ?")
        params.append(filters["status"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([int(filters["limit"]) + 1, int(filters["offset"])])
    return conn.execute(
        f"""
        SELECT *
        FROM import_batches
        {where}
        ORDER BY period DESC, dataset, market
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


def _get_batch(conn: sqlite3.Connection, batch_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM import_batches
        WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()


def _batch_errors(
    conn: sqlite3.Connection, batch_id: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM import_errors
        WHERE batch_id = ?
        ORDER BY created_at, severity, code, sample_stock_id
        LIMIT ?
        """,
        (batch_id, limit),
    ).fetchall()


def _batch_events(
    conn: sqlite3.Connection, batch_id: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM data_events
        WHERE batch_id = ?
        ORDER BY created_at, event_type, stock_id
        LIMIT ?
        """,
        (batch_id, limit),
    ).fetchall()


def _count_related(conn: sqlite3.Connection, table: str, batch_id: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    return int(row["count"]) if row else 0


def _batch_to_dict(row: sqlite3.Row) -> dict:
    return {
        "batch_id": row["batch_id"],
        "dataset": row["dataset"],
        "market": row["market"],
        "period": row["period"],
        "status": row["status"],
        "row_count": row["row_count"],
        "error_summary": row["error_summary"],
        "source_file": row["source_file"],
        "source_sha256": row["source_sha256"],
        "retry_count": row["retry_count"],
        "archived_zip": row["archived_zip"],
        "checked_at": row["checked_at"],
        "manual_approved": bool(row["manual_approved"]),
        "manual_approved_at": row["manual_approved_at"],
        "manual_approved_reason": row["manual_approved_reason"],
        "note": row["note"],
    }


def _error_to_dict(row: sqlite3.Row) -> dict:
    return {
        "error_id": row["error_id"],
        "batch_id": row["batch_id"],
        "severity": row["severity"],
        "code": row["code"],
        "message": row["message"],
        "sample_stock_id": row["sample_stock_id"],
        "sample_value": row["sample_value"],
        "created_at": row["created_at"],
    }


def _event_to_dict(row: sqlite3.Row) -> dict:
    return {
        "event_id": row["event_id"],
        "batch_id": row["batch_id"],
        "dataset": row["dataset"],
        "market": row["market"],
        "period": row["period"],
        "stock_id": row["stock_id"],
        "stock_name": row["stock_name"],
        "event_type": row["event_type"],
        "source_open": row["source_open"],
        "source_high": row["source_high"],
        "source_low": row["source_low"],
        "source_close": row["source_close"],
        "stored_open_cents": row["stored_open"],
        "stored_high_cents": row["stored_high"],
        "stored_low_cents": row["stored_low"],
        "stored_close_cents": row["stored_close"],
        "reference_period": row["reference_period"],
        "reference_value_cents": row["reference_value"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def _api_error(
    code: str, http_status: int, message: str, params: dict | None = None
) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "error": {
                "message": message,
                "params": params or {},
            },
        },
    )
