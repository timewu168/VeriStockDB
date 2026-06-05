from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.deps import read_only_connection, require_permission
from api.schemas import success_response
from validate.close_rules import _clean_stock_id


router = APIRouter(tags=["attention_notices"])

DATASET = config.DATASET_ATTENTION_NOTICE
MAX_LIMIT = 10000
DEFAULT_LIMIT = 1000
REQUIRE_QUALITY_VALUES = ("ok", "allow_recheck", "any")
STATUS_VALUES = ("OK", "FIXED", "BLOCKED", "RECHECK", "MISSING")
PROBLEM_STATUS_VALUES = ("BLOCKED", "RECHECK", "MISSING")

FIELD_SQL = {
    "trade_date": "trade_date",
    "market": "market",
    "stock_id": "stock_id",
    "stock_name": "stock_name",
    "notice_text": "notice_text",
}
DEFAULT_FIELDS = tuple(FIELD_SQL.keys())


@router.get("/attention-notices")
def attention_notices(
    start: str = Query(alias="from"),
    end: str = Query(alias="to"),
    stock_id: str | None = None,
    stock_ids: str | None = None,
    market: str | None = None,
    fields: str | None = None,
    require_quality: str = "any",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    filters = _validate_filters(
        start=start,
        end=end,
        stock_id=stock_id,
        stock_ids=stock_ids,
        market=market,
        fields=fields,
        require_quality=require_quality,
        limit=limit,
        offset=offset,
    )
    selected_fields = _parse_fields(fields)
    try:
        quality_summary = _quality_summary(conn, filters["from"], filters["to"], market)
        quality = _quality_from_summary(quality_summary)
        _enforce_quality(filters["require_quality"], quality)
        rows = _query_attention_notices(conn, filters, selected_fields)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "attention_notices is not readable",
            {"reason": str(exc)},
        ) from exc
    has_more = len(rows) > limit
    returned_rows = rows[:limit]
    return success_response(
        [_row_to_dict(row, selected_fields) for row in returned_rows],
        meta={
            "quality": quality,
            "filters": filters,
            "fields": selected_fields,
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
    start: str,
    end: str,
    stock_id: str | None,
    stock_ids: str | None,
    market: str | None,
    fields: str | None,
    require_quality: str,
    limit: int,
    offset: int,
) -> dict:
    parsed_start = _validate_date_filter("from", start)
    parsed_end = _validate_date_filter("to", end)
    if parsed_start > parsed_end:
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            "from must not be later than to",
            {"from": start, "to": end},
        )
    if stock_id and stock_ids:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "stock_id and stock_ids cannot be used together",
            {"stock_id": stock_id, "stock_ids": stock_ids},
        )
    parsed_stock_ids = _parse_stock_ids(stock_id, stock_ids)
    if market and market not in config.MARKETS:
        raise _api_error(
            "INVALID_MARKET",
            status.HTTP_400_BAD_REQUEST,
            f"market must be one of {', '.join(config.MARKETS)}",
            {"market": market},
        )
    _parse_fields(fields)
    normalized_quality = require_quality.lower()
    if normalized_quality not in REQUIRE_QUALITY_VALUES:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "require_quality must be ok, allow_recheck, or any",
            {"require_quality": require_quality},
        )
    if limit < 1 or limit > MAX_LIMIT or offset < 0:
        raise _api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            f"limit must be 1..{MAX_LIMIT} and offset must be >= 0",
            {"limit": limit, "offset": offset},
        )
    return {
        "from": parsed_start,
        "to": parsed_end,
        "stock_id": stock_id,
        "stock_ids": parsed_stock_ids,
        "market": market,
        "require_quality": normalized_quality,
        "limit": limit,
        "offset": offset,
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


def _parse_stock_ids(stock_id: str | None, stock_ids: str | None) -> list[str]:
    if stock_id:
        value = _clean_stock_id(stock_id)
        if not value:
            raise _api_error(
                "INVALID_FIELD",
                status.HTTP_400_BAD_REQUEST,
                "stock_id must not be empty",
                {"stock_id": stock_id},
            )
        return [value]
    if not stock_ids:
        return []
    values = [_clean_stock_id(value) for value in stock_ids.split(",")]
    values = [value for value in values if value]
    if not values:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "stock_ids must contain at least one stock id",
            {"stock_ids": stock_ids},
        )
    return values


def _parse_fields(fields: str | None) -> list[str]:
    if not fields:
        return list(DEFAULT_FIELDS)
    selected = [field.strip() for field in fields.split(",") if field.strip()]
    invalid = [field for field in selected if field not in FIELD_SQL]
    if invalid:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "fields contains unsupported field names",
            {"fields": fields, "invalid": invalid},
        )
    if not selected:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "fields must contain at least one supported field",
            {"fields": fields},
        )
    return selected


def _query_attention_notices(
    conn: sqlite3.Connection, filters: dict, selected_fields: list[str]
) -> list[sqlite3.Row]:
    select_columns = [f"{FIELD_SQL[field]} AS {field}" for field in selected_fields]
    clauses = ["trade_date BETWEEN ? AND ?"]
    params: list[str | int] = [filters["from"], filters["to"]]
    if filters["stock_ids"]:
        placeholders = ", ".join("?" for _ in filters["stock_ids"])
        clauses.append(f"stock_id IN ({placeholders})")
        params.extend(filters["stock_ids"])
    if filters["market"]:
        clauses.append("market = ?")
        params.append(filters["market"])
    params.extend([int(filters["limit"]) + 1, int(filters["offset"])])
    return conn.execute(
        f"""
        SELECT {", ".join(select_columns)}
        FROM attention_notices
        WHERE {" AND ".join(clauses)}
        ORDER BY trade_date, market, stock_id
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


def _row_to_dict(row: sqlite3.Row, selected_fields: list[str]) -> dict:
    return {field: row[field] for field in selected_fields}


def _quality_summary(
    conn: sqlite3.Connection, start: str, end: str, market: str | None
) -> dict[str, int]:
    clauses = ["dataset = ?"]
    params = [DATASET]
    if market:
        clauses.append("market = ?")
        params.append(market)
    rows = conn.execute(
        f"""
        SELECT status, period
        FROM import_batches
        WHERE {" AND ".join(clauses)}
        """,
        params,
    ).fetchall()
    summary = {status_value: 0 for status_value in STATUS_VALUES}
    for row in rows:
        period_start, period_end = _period_range(row["period"])
        if period_start and period_end and period_start <= end and period_end >= start:
            summary[str(row["status"])] = summary.get(str(row["status"]), 0) + 1
    return summary


def _period_range(period: str) -> tuple[str | None, str | None]:
    parts = period.split("..")
    try:
        if len(parts) == 1:
            value = date.fromisoformat(parts[0]).isoformat()
            return value, value
        start = date.fromisoformat(parts[0]).isoformat()
        end = date.fromisoformat(parts[-1]).isoformat()
        return start, end
    except ValueError:
        return None, None


def _quality_from_summary(summary: dict[str, int]) -> dict:
    blocked = summary.get("BLOCKED", 0)
    missing = summary.get("MISSING", 0)
    recheck = summary.get("RECHECK", 0)
    status_value = "OK"
    if blocked:
        status_value = "BLOCKED"
    elif missing:
        status_value = "MISSING"
    elif recheck:
        status_value = "RECHECK"
    return {
        "status": status_value,
        "problem_batches": sum(summary.get(value, 0) for value in PROBLEM_STATUS_VALUES),
        "blocked": blocked,
        "recheck": recheck,
        "missing": missing,
    }


def _enforce_quality(require_quality: str, quality: dict) -> None:
    blocked = int(quality["blocked"])
    missing = int(quality["missing"])
    recheck = int(quality["recheck"])
    if require_quality == "ok" and (blocked or missing or recheck):
        raise _api_error(
            "QUALITY_REJECTED",
            status.HTTP_409_CONFLICT,
            "query range contains problem batches",
            quality,
        )
    if require_quality == "allow_recheck" and (blocked or missing):
        raise _api_error(
            "QUALITY_REJECTED",
            status.HTTP_409_CONFLICT,
            "query range contains blocked or missing batches",
            quality,
        )


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
