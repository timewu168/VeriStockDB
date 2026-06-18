from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import HTTPException, status

import config
from api.date_utils import validate_api_date

MAX_LIMIT = 10000
DEFAULT_LIMIT = 1000
REQUIRE_QUALITY_VALUES = ("ok", "allow_recheck", "any")
STATUS_VALUES = ("OK", "FIXED", "BLOCKED", "RECHECK", "MISSING")
PROBLEM_STATUS_VALUES = ("BLOCKED", "RECHECK", "MISSING")


def validate_date_stock_filters(
    *,
    start: str,
    end: str,
    stock_id: str | None,
    stock_ids: str | None,
    market: str | None,
    fields: str | None,
    field_sql: dict[str, str],
    require_quality: str,
    limit: int,
    offset: int,
) -> dict:
    parsed_start = _validate_date_filter("from", start)
    parsed_end = _validate_date_filter("to", end)
    if parsed_start > parsed_end:
        raise api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            "from must not be later than to",
            {"from": start, "to": end},
        )
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
    parse_fields(fields, field_sql)
    normalized_quality = require_quality.lower()
    if normalized_quality not in REQUIRE_QUALITY_VALUES:
        raise api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "require_quality must be ok, allow_recheck, or any",
            {"require_quality": require_quality},
        )
    if limit < 1 or limit > MAX_LIMIT or offset < 0:
        raise api_error(
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


def query_date_stock_table(
    conn: sqlite3.Connection,
    *,
    table: str,
    field_sql: dict[str, str],
    filters: dict,
    selected_fields: list[str],
) -> list[sqlite3.Row]:
    select_columns = [f"{field_sql[field]} AS {field}" for field in selected_fields]
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
        FROM {table}
        WHERE {" AND ".join(clauses)}
        ORDER BY trade_date, market, stock_id
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


def parse_fields(fields: str | None, field_sql: dict[str, str]) -> list[str]:
    if not fields:
        return list(field_sql.keys())
    selected = [field.strip() for field in fields.split(",") if field.strip()]
    invalid = [field for field in selected if field not in field_sql]
    if invalid:
        raise api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "fields contains unsupported field names",
            {"fields": fields, "invalid": invalid},
        )
    if not selected:
        raise api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "fields must contain at least one supported field",
            {"fields": fields},
        )
    return selected


def parse_stock_ids(stock_id: str | None, stock_ids: str | None) -> list[str]:
    if stock_id:
        value = stock_id.strip()
        if not value:
            raise api_error(
                "INVALID_FIELD",
                status.HTTP_400_BAD_REQUEST,
                "stock_id must not be empty",
                {"stock_id": stock_id},
            )
        return [value]
    if not stock_ids:
        return []
    values = [value.strip() for value in stock_ids.split(",") if value.strip()]
    if not values:
        raise api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "stock_ids must contain at least one stock id",
            {"stock_ids": stock_ids},
        )
    return values


def row_to_dict(row: sqlite3.Row, selected_fields: list[str]) -> dict:
    return {field: row[field] for field in selected_fields}


def quality_summary(
    conn: sqlite3.Connection, *, dataset: str, start: str, end: str, market: str | None
) -> dict[str, int]:
    clauses = ["dataset = ?", "period BETWEEN ? AND ?"]
    params = [dataset, start, end]
    if market:
        clauses.append("market = ?")
        params.append(market)
    rows = conn.execute(
        f"""
        SELECT status, COUNT(*) AS count
        FROM import_batches
        WHERE {" AND ".join(clauses)}
        GROUP BY status
        """,
        params,
    ).fetchall()
    summary = {status_value: 0 for status_value in STATUS_VALUES}
    for row in rows:
        summary[str(row["status"])] = int(row["count"])
    return summary


def quality_from_summary(summary: dict[str, int]) -> dict:
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


def enforce_quality(require_quality: str, quality: dict) -> None:
    blocked = int(quality["blocked"])
    missing = int(quality["missing"])
    recheck = int(quality["recheck"])
    if require_quality == "ok" and (blocked or missing or recheck):
        raise api_error(
            "QUALITY_REJECTED",
            status.HTTP_409_CONFLICT,
            "query range contains problem batches",
            quality,
        )
    if require_quality == "allow_recheck" and (blocked or missing):
        raise api_error(
            "QUALITY_REJECTED",
            status.HTTP_409_CONFLICT,
            "query range contains blocked or missing batches",
            quality,
        )


def _validate_date_filter(name: str, value: str) -> str:
    try:
        return validate_api_date(value)
    except ValueError as exc:
        raise api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            f"{name} must use YYYY-MM-DD",
            {name: value},
        ) from exc


def api_error(
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
