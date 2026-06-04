from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import read_only_connection, require_permission
from api.schemas import success_response


router = APIRouter(tags=["trading_days"])


@router.get("/trading-days")
def trading_days(
    start: str = Query(alias="from"),
    end: str = Query(alias="to"),
    is_open: str | None = None,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    filters = _validate_filters(start, end, is_open)
    try:
        rows = _query_trading_days(conn, filters)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "trading_days is not readable",
            {"reason": str(exc)},
        ) from exc

    return success_response(
        [_row_to_dict(row) for row in rows],
        meta={
            "filters": filters,
            "pagination": {
                "limit": None,
                "offset": 0,
                "returned": len(rows),
                "has_more": False,
            },
        },
    )


def _validate_filters(start: str, end: str, is_open: str | None) -> dict:
    parsed_start = _validate_date_filter("from", start)
    parsed_end = _validate_date_filter("to", end)
    if parsed_start > parsed_end:
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            "from must not be later than to",
            {"from": start, "to": end},
        )
    parsed_is_open = _parse_is_open(is_open)
    return {
        "from": parsed_start,
        "to": parsed_end,
        "is_open": parsed_is_open,
    }


def _validate_date_filter(name: str, value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            f"{name} must use YYYY-MM-DD",
            {name: value},
        ) from exc


def _parse_is_open(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise _api_error(
        "INVALID_FIELD",
        status.HTTP_400_BAD_REQUEST,
        "is_open must be 1 or 0",
        {"is_open": value},
    )


def _query_trading_days(conn: sqlite3.Connection, filters: dict) -> list[sqlite3.Row]:
    clauses = ["trade_date BETWEEN ? AND ?"]
    params: list[str | int] = [filters["from"], filters["to"]]
    if filters["is_open"] is not None:
        clauses.append("is_open = ?")
        params.append(1 if filters["is_open"] else 0)
    return conn.execute(
        f"""
        SELECT trade_date, is_open, source, note
        FROM trading_days
        WHERE {" AND ".join(clauses)}
        ORDER BY trade_date
        """,
        params,
    ).fetchall()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "trade_date": row["trade_date"],
        "is_open": bool(row["is_open"]),
        "source": row["source"],
        "note": row["note"],
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
