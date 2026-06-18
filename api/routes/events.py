from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.date_utils import validate_api_date
from api.dataset_registry import get_dataset_definition
from api.deps import read_only_connection, require_permission
from api.schemas import success_response


router = APIRouter(tags=["events"])

MAX_LIMIT = 10000
DEFAULT_LIMIT = 1000


@router.get("/events")
def events(
    dataset: str | None = None,
    market: str | None = None,
    start: str | None = Query(default=None, alias="from"),
    end: str | None = Query(default=None, alias="to"),
    stock_id: str | None = None,
    event_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    filters = _validate_filters(
        dataset=dataset,
        market=market,
        start=start,
        end=end,
        stock_id=stock_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    try:
        rows = _query_events(conn, filters)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "data_events is not readable",
            {"reason": str(exc)},
        ) from exc

    has_more = len(rows) > limit
    returned_rows = rows[:limit]
    return success_response(
        [_event_to_dict(row) for row in returned_rows],
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
    *,
    dataset: str | None,
    market: str | None,
    start: str | None,
    end: str | None,
    stock_id: str | None,
    event_type: str | None,
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
    parsed_start = _validate_date_filter("from", start)
    parsed_end = _validate_date_filter("to", end)
    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            "from must not be later than to",
            {"from": start, "to": end},
        )
    parsed_stock_id = stock_id.strip() if stock_id else None
    parsed_event_type = event_type.strip() if event_type else None
    if stock_id is not None and not parsed_stock_id:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "stock_id must not be empty",
            {"stock_id": stock_id},
        )
    if event_type is not None and not parsed_event_type:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "event_type must not be empty",
            {"event_type": event_type},
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
        "stock_id": parsed_stock_id,
        "event_type": parsed_event_type,
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


def _query_events(conn: sqlite3.Connection, filters: dict) -> list[sqlite3.Row]:
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
    if filters["stock_id"]:
        clauses.append("stock_id = ?")
        params.append(filters["stock_id"])
    if filters["event_type"]:
        clauses.append("event_type = ?")
        params.append(filters["event_type"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([int(filters["limit"]) + 1, int(filters["offset"])])
    return conn.execute(
        f"""
        SELECT *
        FROM data_events
        {where}
        ORDER BY period DESC, market, event_type, stock_id
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


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
