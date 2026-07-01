from __future__ import annotations

import sqlite3
from datetime import date
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.date_utils import validate_api_date
from api.dataset_registry import get_dataset_definition, list_datasets
from api.deps import read_only_connection, require_permission
from api.schemas import success_response


router = APIRouter(tags=["datasets"])

STATUS_VALUES = ("OK", "FIXED", "BLOCKED", "RECHECK", "MISSING")
PROBLEM_STATUS_VALUES = ("BLOCKED", "RECHECK", "MISSING")
CANONICAL_PERIOD_COLUMNS = {
    config.DATASET_DAILY_CLOSE: ("daily_close", "trade_date"),
    config.DATASET_ATTENTION_NOTICE: ("attention_notices", "trade_date"),
    config.DATASET_DISPOSAL_NOTICE: ("disposal_notices", "trade_date"),
    config.DATASET_LEGAL_INVESTOR: ("legal_investors", "trade_date"),
    config.DATASET_MARGIN: ("margin_trading", "trade_date"),
    config.DATASET_DAY_TRADING: ("day_trading", "trade_date"),
    config.DATASET_REVENUE: ("monthly_revenue", "revenue_month"),
}


@router.get("/datasets")
def datasets(_: None = Depends(require_permission("read"))) -> dict:
    return success_response([_dataset_to_dict(dataset) for dataset in list_datasets()])


@router.get("/datasets/{dataset}/status")
def dataset_status(
    dataset: str,
    start: str | None = Query(default=None, alias="from"),
    end: str | None = Query(default=None, alias="to"),
    market: str | None = None,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    definition = get_dataset_definition(dataset)
    if definition is None:
        raise _api_error(
            "INVALID_DATASET",
            status.HTTP_400_BAD_REQUEST,
            f"unsupported dataset: {dataset}",
            {"dataset": dataset},
        )

    filters = _validate_filters(definition.period_type, start, end, market)
    try:
        summary = _status_summary(conn, dataset, start, end, market)
        latest_period = _latest_period(conn, dataset, start, end, market)
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "dataset status is not readable",
            {"dataset": dataset, "reason": str(exc)},
        ) from exc

    return success_response(
        {
            "dataset": definition.dataset,
            "title": definition.title,
            "period_type": definition.period_type,
            "markets": list(definition.markets),
            "summary": summary,
            "latest_period": latest_period,
            "quality": _quality_from_summary(summary),
            "filters": filters,
        }
    )


def _dataset_to_dict(dataset) -> dict:
    return {
        "dataset": dataset.dataset,
        "title": dataset.title,
        "period_type": dataset.period_type,
        "markets": list(dataset.markets),
        "status_endpoint": dataset.status_endpoint,
    }


def _validate_filters(
    period_type: str, start: str | None, end: str | None, market: str | None
) -> dict:
    if market and market not in config.MARKETS:
        raise _api_error(
            "INVALID_MARKET",
            status.HTTP_400_BAD_REQUEST,
            f"market must be one of {', '.join(config.MARKETS)}",
            {"market": market},
        )
    if period_type == "date":
        parsed_start = _validate_date_filter("from", start)
        parsed_end = _validate_date_filter("to", end)
        if parsed_start and parsed_end and parsed_start > parsed_end:
            raise _api_error(
                "INVALID_DATE",
                status.HTTP_400_BAD_REQUEST,
                "from must not be later than to",
                {"from": start, "to": end},
            )
    elif period_type == "month":
        parsed_start = _validate_month_filter("from", start)
        parsed_end = _validate_month_filter("to", end)
        if parsed_start and parsed_end and parsed_start > parsed_end:
            raise _api_error(
                "INVALID_DATE",
                status.HTTP_400_BAD_REQUEST,
                "from must not be later than to",
                {"from": start, "to": end},
            )
    else:
        parsed_start = start
        parsed_end = end
    return {"from": parsed_start, "to": parsed_end, "market": market}


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


def _validate_month_filter(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value):
        raise _api_error(
            "INVALID_DATE",
            status.HTTP_400_BAD_REQUEST,
            f"{name} must use YYYY-MM",
            {name: value},
        )
    return value


def _status_summary(
    conn: sqlite3.Connection,
    dataset: str,
    start: str | None,
    end: str | None,
    market: str | None,
) -> dict[str, int]:
    where, params = _batch_filters(dataset, start, end, market)
    rows = conn.execute(
        f"""
        SELECT status, COUNT(*) AS count
        FROM import_batches
        WHERE {where}
        GROUP BY status
        """,
        params,
    ).fetchall()
    summary = {status_value: 0 for status_value in STATUS_VALUES}
    for row in rows:
        summary[str(row["status"])] = int(row["count"])
    return summary


def _latest_period(
    conn: sqlite3.Connection,
    dataset: str,
    start: str | None,
    end: str | None,
    market: str | None,
) -> str | None:
    where, params = _batch_filters(dataset, start, end, market)
    row = conn.execute(
        f"""
        SELECT MAX(period) AS latest_period
        FROM import_batches
        WHERE {where}
        """,
        params,
    ).fetchone()
    if row and row["latest_period"]:
        return row["latest_period"]
    return _latest_canonical_period(conn, dataset, start, end, market)


def _latest_canonical_period(
    conn: sqlite3.Connection,
    dataset: str,
    start: str | None,
    end: str | None,
    market: str | None,
) -> str | None:
    scope = CANONICAL_PERIOD_COLUMNS.get(dataset)
    if scope is None:
        return None
    table, period_column = scope
    clauses: list[str] = []
    params: list[str] = []
    if start:
        clauses.append(f"{period_column} >= ?")
        params.append(start)
    if end:
        clauses.append(f"{period_column} <= ?")
        params.append(end)
    if market:
        clauses.append("market = ?")
        params.append(market)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    row = conn.execute(
        f"SELECT MAX({period_column}) AS latest_period FROM {table} {where}",
        params,
    ).fetchone()
    return row["latest_period"] if row and row["latest_period"] else None


def _batch_filters(
    dataset: str, start: str | None, end: str | None, market: str | None
) -> tuple[str, list[str]]:
    clauses = ["dataset = ?"]
    params = [dataset]
    if start:
        clauses.append("period >= ?")
        params.append(start)
    if end:
        clauses.append("period <= ?")
        params.append(end)
    if market:
        clauses.append("market = ?")
        params.append(market)
    return " AND ".join(clauses), params


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
