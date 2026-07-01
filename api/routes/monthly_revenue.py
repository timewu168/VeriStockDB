from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, Query, status

import config
from api.deps import read_only_connection, require_permission
from api.routes.table_query import (
    DEFAULT_LIMIT,
    api_error,
    enforce_quality,
    parse_fields,
    parse_stock_ids,
    quality_from_summary,
    quality_summary,
    row_to_dict,
)
from api.schemas import success_response


router = APIRouter(tags=["monthly_revenue"])

DATASET = config.DATASET_REVENUE
TABLE = "monthly_revenue"
FIELD_SQL = {
    "revenue_month": "revenue_month",
    "market": "market",
    "stock_id": "stock_id",
    "stock_name": "stock_name",
    "industry": "industry",
    "report_date": "report_date",
    "roc_period": "roc_period",
    "current_month_revenue": "current_month_revenue",
    "previous_month_revenue": "previous_month_revenue",
    "previous_year_month_revenue": "previous_year_month_revenue",
    "month_over_month_pct": "month_over_month_pct",
    "year_over_year_pct": "year_over_year_pct",
    "cumulative_revenue": "cumulative_revenue",
    "previous_year_cumulative_revenue": "previous_year_cumulative_revenue",
    "cumulative_growth_pct": "cumulative_growth_pct",
    "note": "note",
}


@router.get("/monthly-revenue")
def monthly_revenue(
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
    filters = _validate_month_stock_filters(
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
    selected_fields = parse_fields(fields, FIELD_SQL)
    try:
        quality = quality_from_summary(
            quality_summary(conn, dataset=DATASET, start=filters["from"], end=filters["to"], market=market)
        )
        enforce_quality(filters["require_quality"], quality)
        rows = _query_month_stock_table(conn, filters=filters, selected_fields=selected_fields)
    except sqlite3.Error as exc:
        raise api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "monthly_revenue is not readable",
            {"reason": str(exc)},
        ) from exc
    has_more = len(rows) > limit
    returned_rows = rows[:limit]
    return success_response(
        [row_to_dict(row, selected_fields) for row in returned_rows],
        meta={
            "unit": "thousand_twd",
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


def _validate_month_stock_filters(
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
    parsed_start = _validate_month_filter("from", start)
    parsed_end = _validate_month_filter("to", end)
    if parsed_start > parsed_end:
        raise api_error("INVALID_DATE", status.HTTP_400_BAD_REQUEST, "from must not be later than to", {"from": start, "to": end})
    if stock_id and stock_ids:
        raise api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "stock_id and stock_ids cannot be used together",
            {"stock_id": stock_id, "stock_ids": stock_ids},
        )
    parsed_stock_ids = parse_stock_ids(stock_id, stock_ids)
    if market and market not in config.MARKETS:
        raise api_error(
            "INVALID_MARKET",
            status.HTTP_400_BAD_REQUEST,
            f"market must be one of {', '.join(config.MARKETS)}",
            {"market": market},
        )
    parse_fields(fields, FIELD_SQL)
    normalized_quality = require_quality.lower()
    if normalized_quality not in {"ok", "allow_recheck", "any"}:
        raise api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "require_quality must be ok, allow_recheck, or any",
            {"require_quality": require_quality},
        )
    if limit < 1 or limit > 10000 or offset < 0:
        raise api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            "limit must be 1..10000 and offset must be >= 0",
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


def _query_month_stock_table(
    conn: sqlite3.Connection,
    *,
    filters: dict,
    selected_fields: list[str],
) -> list[sqlite3.Row]:
    select_columns = [f"{FIELD_SQL[field]} AS {field}" for field in selected_fields]
    clauses = ["revenue_month BETWEEN ? AND ?"]
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
        FROM {TABLE}
        WHERE {" AND ".join(clauses)}
        ORDER BY revenue_month, market, stock_id
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


def _validate_month_filter(name: str, value: str) -> str:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value):
        raise api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            f"{name} must use YYYY-MM",
            {name: value},
        )
    return value
