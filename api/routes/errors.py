from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from api.dataset_registry import get_dataset_definition
from api.deps import read_only_connection, require_permission
from api.schemas import success_response


router = APIRouter(tags=["errors"])

SEVERITY_VALUES = ("WARN", "BLOCK")
MAX_LIMIT = 10000
DEFAULT_LIMIT = 1000


@router.get("/errors")
def errors(
    dataset: str | None = None,
    batch_id: str | None = None,
    severity: str | None = None,
    code: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    filters = _validate_filters(dataset, batch_id, severity, code, limit, offset)
    try:
        rows = _query_errors(conn, filters)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "import_errors is not readable",
            {"reason": str(exc)},
        ) from exc

    has_more = len(rows) > limit
    returned_rows = rows[:limit]
    return success_response(
        [_error_to_dict(row) for row in returned_rows],
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


def _validate_filters(
    dataset: str | None,
    batch_id: str | None,
    severity: str | None,
    code: str | None,
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
    normalized_severity = severity.upper() if severity else None
    if normalized_severity and normalized_severity not in SEVERITY_VALUES:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "severity must be WARN or BLOCK",
            {"severity": severity},
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
        "batch_id": batch_id,
        "severity": normalized_severity,
        "code": code,
        "limit": limit,
        "offset": offset,
    }


def _query_errors(conn: sqlite3.Connection, filters: dict) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[str | int] = []
    if filters["dataset"]:
        clauses.append("b.dataset = ?")
        params.append(filters["dataset"])
    if filters["batch_id"]:
        clauses.append("e.batch_id = ?")
        params.append(filters["batch_id"])
    if filters["severity"]:
        clauses.append("e.severity = ?")
        params.append(filters["severity"])
    if filters["code"]:
        clauses.append("e.code = ?")
        params.append(filters["code"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([int(filters["limit"]) + 1, int(filters["offset"])])
    return conn.execute(
        f"""
        SELECT
          e.error_id, e.batch_id, b.dataset, b.market, b.period,
          e.severity, e.code, e.message, e.sample_stock_id,
          e.sample_value, e.created_at
        FROM import_errors AS e
        LEFT JOIN import_batches AS b ON b.batch_id = e.batch_id
        {where}
        ORDER BY e.created_at DESC, e.severity, e.code, e.sample_stock_id
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


def _error_to_dict(row: sqlite3.Row) -> dict:
    return {
        "error_id": row["error_id"],
        "batch_id": row["batch_id"],
        "dataset": row["dataset"],
        "market": row["market"],
        "period": row["period"],
        "severity": row["severity"],
        "code": row["code"],
        "message": row["message"],
        "sample_stock_id": row["sample_stock_id"],
        "sample_value": row["sample_value"],
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
