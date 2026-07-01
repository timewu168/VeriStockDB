from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query, status

import config
from api.deps import read_only_connection, require_permission
from api.routes.table_query import (
    DEFAULT_LIMIT,
    api_error,
    enforce_quality,
    parse_fields,
    quality_from_summary,
    quality_summary,
    query_date_stock_table,
    row_to_dict,
    validate_date_stock_filters,
)
from api.schemas import success_response


router = APIRouter(tags=["day_trading"])

DATASET = config.DATASET_DAY_TRADING
TABLE = "day_trading"
FIELD_SQL = {
    "trade_date": "trade_date",
    "market": "market",
    "stock_id": "stock_id",
    "stock_name": "stock_name",
    "suspend_sell_note": "suspend_sell_note",
    "day_trade_volume": "day_trade_volume",
    "day_trade_buy_amount": "day_trade_buy_amount",
    "day_trade_sell_amount": "day_trade_sell_amount",
}


@router.get("/day-trading")
def day_trading(
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
    filters = validate_date_stock_filters(
        start=start,
        end=end,
        stock_id=stock_id,
        stock_ids=stock_ids,
        market=market,
        fields=fields,
        field_sql=FIELD_SQL,
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
        rows = query_date_stock_table(
            conn, table=TABLE, field_sql=FIELD_SQL, filters=filters, selected_fields=selected_fields
        )
    except sqlite3.Error as exc:
        raise api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "day_trading is not readable",
            {"reason": str(exc)},
        ) from exc
    has_more = len(rows) > limit
    returned_rows = rows[:limit]
    return success_response(
        [row_to_dict(row, selected_fields) for row in returned_rows],
        meta={
            "unit": "shares",
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
