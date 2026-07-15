from __future__ import annotations

import sqlite3
from datetime import date, datetime
import re
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.date_utils import validate_api_date
from api.deps import read_only_connection, require_permission
from api.disposition_utils import disposition_notice_id
from api.schemas import success_response
from validate.close_rules import _clean_stock_id


router = APIRouter(tags=["disposal_notices"])

DATASET = config.DATASET_DISPOSAL_NOTICE
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
    "disposal_start_date": "disposal_start_date",
    "disposal_end_date": "disposal_end_date",
    "reason_text": "reason_text",
    "disposal_text": "disposal_text",
}
DEFAULT_FIELDS = tuple(FIELD_SQL.keys())
ACTIVE_SORT = "announcement_date_desc"
INTERVAL_PATTERNS = {
    5: re.compile(r"每\s*(?:5|５|五)\s*分鐘"),
    20: re.compile(r"每\s*(?:20|２０|二十)\s*分鐘"),
}


def _taipei_today() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


@router.get("/disposal-notices/active")
def active_disposal_notices(
    interval: Literal["all", "5", "20"] = "all",
    limit: int = 100,
    offset: int = 0,
    sort: Literal["announcement_date_desc"] = ACTIVE_SORT,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
    as_of_date: str = Depends(_taipei_today),
) -> dict:
    if limit < 1 or limit > MAX_LIMIT or offset < 0:
        raise _api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            f"limit must be 1..{MAX_LIMIT} and offset must be >= 0",
            {"limit": limit, "offset": offset},
        )
    as_of_date = _validate_date_filter("as_of_date", as_of_date)
    try:
        master_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM security_master
            WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
            """,
            (as_of_date, as_of_date),
        ).fetchone()["count"]
        if not master_count:
            raise _api_error(
                "DATA_UNAVAILABLE",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "security_master has no effective rows for as_of_date",
                {"as_of_date": as_of_date},
            )
        rows = _query_active_disposal_notices(conn, as_of_date)
        generated_at = _active_generated_at(conn)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "active disposal notices are not readable",
            {"reason": str(exc)},
        ) from exc

    normalized, messages = _normalize_active_rows(rows)
    if interval != "all":
        normalized = [item for item in normalized if item["interval_minutes"] == int(interval)]
    total = len(normalized)
    items = normalized[offset : offset + limit]
    warning_count = sum(
        int(message["count"]) for message in messages if message["level"] == "warning"
    )
    excluded_count = sum(
        int(message["count"])
        for message in messages
        if message["code"] == "NON_STOCK_SECURITY_EXCLUDED"
    )
    meta = {
        "filters": {
            "as_of_date": as_of_date,
            "interval": interval,
            "sort": sort,
        },
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(items),
            "has_more": offset + len(items) < total,
        },
        "quality": {
            "status": "WARN" if warning_count else "OK",
            "rejected": warning_count,
            "excluded": excluded_count,
        },
    }
    if generated_at:
        meta["generated_at"] = generated_at
    return success_response(
        {"as_of_date": as_of_date, "total": total, "items": items},
        meta=meta,
        messages=messages,
    )


@router.get("/disposal-notices")
def disposal_notices(
    start: str = Query(alias="from"),
    end: str = Query(alias="to"),
    stock_id: str | None = None,
    stock_ids: str | None = None,
    market: str | None = None,
    active_date: str | None = None,
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
        active_date=active_date,
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
        rows = _query_disposal_notices(conn, filters, selected_fields)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "disposal_notices is not readable",
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
    active_date: str | None,
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
    parsed_active_date = _validate_date_filter("active_date", active_date) if active_date else None
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
        "active_date": parsed_active_date,
        "require_quality": normalized_quality,
        "limit": limit,
        "offset": offset,
    }


def _validate_date_filter(name: str, value: str) -> str:
    try:
        return validate_api_date(value)
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


def _query_disposal_notices(
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
    if filters["active_date"]:
        clauses.append("disposal_start_date <= ? AND disposal_end_date >= ?")
        params.extend([filters["active_date"], filters["active_date"]])
    params.extend([int(filters["limit"]) + 1, int(filters["offset"])])
    return conn.execute(
        f"""
        SELECT {", ".join(select_columns)}
        FROM disposal_notices
        WHERE {" AND ".join(clauses)}
        ORDER BY trade_date, market, stock_id, disposal_start_date, disposal_end_date
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()


def _query_active_disposal_notices(
    conn: sqlite3.Connection, as_of_date: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          d.trade_date AS announcement_date,
          d.market,
          d.stock_id,
          COALESCE(sm.stock_name, d.stock_name) AS stock_name,
          sm.industry_name,
          d.disposal_start_date,
          d.disposal_end_date,
          d.disposal_text
        FROM disposal_notices AS d
        LEFT JOIN security_master AS sm
          ON sm.market = d.market
         AND sm.stock_id = d.stock_id
         AND sm.effective_from <= ?
         AND (sm.effective_to IS NULL OR sm.effective_to >= ?)
        WHERE d.disposal_start_date <= ? AND d.disposal_end_date >= ?
        ORDER BY
          d.trade_date DESC,
          d.disposal_start_date DESC,
          d.market ASC,
          d.stock_id ASC
        """,
        (as_of_date, as_of_date, as_of_date, as_of_date),
    ).fetchall()


def normalize_interval_minutes(disposal_text: str) -> int | None:
    matches = {
        interval
        for interval, pattern in INTERVAL_PATTERNS.items()
        if pattern.search(disposal_text)
    }
    return matches.pop() if len(matches) == 1 else None


def _normalize_active_rows(rows: list[sqlite3.Row]) -> tuple[list[dict], list[dict]]:
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    problems: dict[str, dict] = {}
    for row in rows:
        key = (str(row["market"]), str(row["stock_id"]))
        if key in seen:
            continue
        seen.add(key)
        interval = normalize_interval_minutes(str(row["disposal_text"]))
        if not row["industry_name"]:
            code = (
                "NON_STOCK_SECURITY_EXCLUDED"
                if len(str(row["stock_id"])) > 4
                else "MISSING_SECURITY_MASTER"
            )
            _record_active_problem(problems, code, key)
            continue
        if interval is None:
            _record_active_problem(problems, "UNRESOLVED_INTERVAL", key)
            continue
        items.append(
            {
                "disposition_id": disposition_notice_id(
                    str(row["market"]),
                    str(row["stock_id"]),
                    str(row["announcement_date"]),
                    str(row["disposal_start_date"]),
                    str(row["disposal_end_date"]),
                ),
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "market": row["market"],
                "industry_name": row["industry_name"],
                "interval_minutes": interval,
                "announcement_date": row["announcement_date"],
                "disposal_start_date": row["disposal_start_date"],
                "disposal_end_date": row["disposal_end_date"],
            }
        )
    messages = [problems[code] for code in sorted(problems)]
    return items, messages


def _record_active_problem(
    problems: dict[str, dict], code: str, key: tuple[str, str]
) -> None:
    problem = problems.setdefault(
        code,
        {
            "code": code,
            "level": "info" if code == "NON_STOCK_SECURITY_EXCLUDED" else "warning",
            "message": {
                "MISSING_SECURITY_MASTER": "active stock has no effective security master row",
                "NON_STOCK_SECURITY_EXCLUDED": "active non-stock security is excluded from the stock list",
                "UNRESOLVED_INTERVAL": "active notice interval cannot be normalized to 5 or 20 minutes",
            }[code],
            "count": 0,
            "samples": [],
        },
    )
    problem["count"] += 1
    if len(problem["samples"]) < 5:
        problem["samples"].append({"market": key[0], "stock_id": key[1]})


def _active_generated_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(checked_at) AS checked_at
        FROM import_batches
        WHERE dataset IN (?, ?) AND status IN ('OK', 'FIXED')
        """,
        (config.DATASET_DISPOSAL_NOTICE, config.DATASET_SECURITY_MASTER),
    ).fetchone()
    if not row or not row["checked_at"]:
        return None
    return str(row["checked_at"]).replace("+00:00", "Z")


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
