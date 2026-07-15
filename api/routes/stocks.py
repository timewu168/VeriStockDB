from __future__ import annotations

from datetime import datetime
import re
import sqlite3
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.deps import read_only_connection, require_permission
from api.disposition_utils import disposition_notice_id
from api.routes.disposal_notices import normalize_interval_minutes
from api.schemas import success_response
from validate.close_rules import _clean_stock_id


router = APIRouter(tags=["stocks"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
PRICE_SCALE = 100
ATTENTION_CLAUSE_PATTERN = re.compile(
    r"[\uff08(](\u7b2c\s*[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+\s*\u6b3e)[\uff09)]"
)


def _taipei_today() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


@router.get("/stocks/{market}/{stock_id}/disposition-detail")
def disposition_detail(
    market: str,
    stock_id: str,
    disposition_id: str | None = None,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
    as_of_date: str = Depends(_taipei_today),
) -> dict:
    market, stock_id = _validate_security(market, stock_id)
    try:
        event = _select_disposition(conn, market, stock_id, as_of_date, disposition_id)
        if event is None:
            raise _api_error(
                "DISPOSITION_NOT_FOUND",
                status.HTTP_404_NOT_FOUND,
                "disposition event was not found",
                {"market": market, "stock_id": stock_id, "disposition_id": disposition_id},
            )
        stock = _select_security_master(conn, market, stock_id, as_of_date)
        if stock is None:
            raise _api_error(
                "SECURITY_NOT_FOUND",
                status.HTTP_404_NOT_FOUND,
                "security master row was not found",
                {"market": market, "stock_id": stock_id},
            )
        ohlcv = _select_recent_ohlcv(conn, market, stock_id, as_of_date)
        first_date = str(ohlcv[0]["trade_date"]) if ohlcv else None
        institutional = _select_institutional(
            conn, market, stock_id, first_date, as_of_date
        )
        margin = _select_margin(conn, market, stock_id, first_date, as_of_date)
        pre_start = _select_pre_start_reference(
            conn, market, stock_id, str(event["disposal_start_date"])
        )
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "stock disposition detail is not readable",
            {"reason": str(exc)},
        ) from exc

    interval = normalize_interval_minutes(str(event["disposal_text"]))
    disposition = _event_to_dict(conn, event, interval, as_of_date)
    return success_response(
        {
            "stock": {
                "stock_id": stock["stock_id"],
                "stock_name": stock["stock_name"],
                "market": stock["market"],
                "industry_name": stock["industry_name"],
                "security_type": "ordinary_stock" if _supports_equity_tick(stock) else "unsupported",
                "price_tick_rule": "TW_EQUITY_V1" if _supports_equity_tick(stock) else None,
            },
            "disposition": disposition,
            "ohlcv": [_ohlcv_to_dict(row) for row in ohlcv],
            "institutional": [_institutional_to_dict(row) for row in institutional],
            "margin": [_margin_to_dict(row) for row in margin],
            "pre_start_reference": pre_start,
        },
        meta={
            "as_of_date": as_of_date,
            "price_scale": PRICE_SCALE,
            "volume_unit": "shares",
            "institutional_unit": "lots",
            "margin_unit": "lots",
            "ohlcv_trading_days": len(ohlcv),
        },
    )


@router.get("/stocks/{market}/{stock_id}/warnings")
def stock_warnings(
    market: str,
    stock_id: str,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
) -> dict:
    market, stock_id = _validate_security(market, stock_id)
    _validate_pagination(limit, offset)
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM attention_notices WHERE market = ? AND stock_id = ?",
            (market, stock_id),
        ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT trade_date, market, stock_id, stock_name, notice_text
            FROM attention_notices
            WHERE market = ? AND stock_id = ?
            ORDER BY trade_date DESC
            LIMIT ? OFFSET ?
            """,
            (market, stock_id, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "stock warning notices are not readable",
            {"reason": str(exc)},
        ) from exc
    items = [
        {
            "announcement_date": row["trade_date"],
            "market": row["market"],
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "clauses": _attention_clauses(str(row["notice_text"])),
            "official_text": row["notice_text"],
        }
        for row in rows
    ]
    return success_response(
        {"total": total, "items": items},
        meta={"pagination": _pagination(total, limit, offset, len(items))},
    )


@router.get("/stocks/{market}/{stock_id}/dispositions")
def stock_dispositions(
    market: str,
    stock_id: str,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    _: None = Depends(require_permission("read")),
    conn: sqlite3.Connection = Depends(read_only_connection),
    as_of_date: str = Depends(_taipei_today),
) -> dict:
    market, stock_id = _validate_security(market, stock_id)
    _validate_pagination(limit, offset)
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM disposal_notices WHERE market = ? AND stock_id = ?",
            (market, stock_id),
        ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT trade_date, market, stock_id, stock_name, disposal_start_date,
                   disposal_end_date, reason_text, disposal_text
            FROM disposal_notices
            WHERE market = ? AND stock_id = ?
            ORDER BY trade_date DESC, disposal_start_date DESC, disposal_end_date DESC
            LIMIT ? OFFSET ?
            """,
            (market, stock_id, limit, offset),
        ).fetchall()
        items = [
            _event_to_dict(
                conn,
                row,
                normalize_interval_minutes(str(row["disposal_text"])),
                as_of_date,
                include_text=True,
            )
            for row in rows
        ]
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "stock disposition notices are not readable",
            {"reason": str(exc)},
        ) from exc
    return success_response(
        {"total": total, "items": items},
        meta={"as_of_date": as_of_date, "pagination": _pagination(total, limit, offset, len(items))},
    )


def _validate_security(market: str, stock_id: str) -> tuple[str, str]:
    if market not in config.MARKETS:
        raise _api_error(
            "INVALID_MARKET",
            status.HTTP_400_BAD_REQUEST,
            f"market must be one of {', '.join(config.MARKETS)}",
            {"market": market},
        )
    normalized_stock_id = _clean_stock_id(stock_id)
    if not normalized_stock_id:
        raise _api_error(
            "INVALID_FIELD",
            status.HTTP_400_BAD_REQUEST,
            "stock_id must not be empty",
            {"stock_id": stock_id},
        )
    return market, normalized_stock_id


def _validate_pagination(limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_PAGE_SIZE or offset < 0:
        raise _api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            f"limit must be 1..{MAX_PAGE_SIZE} and offset must be >= 0",
            {"limit": limit, "offset": offset},
        )


def _select_disposition(
    conn: sqlite3.Connection,
    market: str,
    stock_id: str,
    as_of_date: str,
    requested_id: str | None,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT trade_date, market, stock_id, stock_name, disposal_start_date,
               disposal_end_date, reason_text, disposal_text
        FROM disposal_notices
        WHERE market = ? AND stock_id = ?
        ORDER BY
          CASE WHEN disposal_start_date <= ? AND disposal_end_date >= ? THEN 0 ELSE 1 END,
          trade_date DESC,
          disposal_start_date DESC,
          disposal_end_date DESC
        """,
        (market, stock_id, as_of_date, as_of_date),
    ).fetchall()
    if requested_id is None:
        return rows[0] if rows else None
    for row in rows:
        if _row_disposition_id(row) == requested_id:
            return row
    return None


def _select_security_master(
    conn: sqlite3.Connection, market: str, stock_id: str, as_of_date: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT market, stock_id, stock_name, industry_name
        FROM security_master
        WHERE market = ? AND stock_id = ? AND effective_from <= ?
          AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        (market, stock_id, as_of_date, as_of_date),
    ).fetchone()


def _select_recent_ohlcv(
    conn: sqlite3.Connection, market: str, stock_id: str, as_of_date: str
) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_close
        WHERE market = ? AND stock_id = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 30
        """,
        (market, stock_id, as_of_date),
    ).fetchall()
    return list(reversed(rows))


def _select_institutional(
    conn: sqlite3.Connection,
    market: str,
    stock_id: str,
    first_date: str | None,
    end_date: str,
) -> list[sqlite3.Row]:
    if first_date is None:
        return []
    return conn.execute(
        """
        SELECT trade_date, foreign_net, investment_trust_net, dealer_net
        FROM legal_investors
        WHERE market = ? AND stock_id = ? AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (market, stock_id, first_date, end_date),
    ).fetchall()


def _select_margin(
    conn: sqlite3.Connection,
    market: str,
    stock_id: str,
    first_date: str | None,
    end_date: str,
) -> list[sqlite3.Row]:
    if first_date is None:
        return []
    return conn.execute(
        """
        SELECT trade_date, margin_balance, short_balance
        FROM margin_trading
        WHERE market = ? AND stock_id = ? AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (market, stock_id, first_date, end_date),
    ).fetchall()


def _select_pre_start_reference(
    conn: sqlite3.Connection, market: str, stock_id: str, start_date: str
) -> dict:
    rows = conn.execute(
        """
        SELECT d.trade_date, d.high
        FROM trading_days AS t
        JOIN daily_close AS d ON d.trade_date = t.trade_date
        WHERE t.is_open = 1 AND t.trade_date < ?
          AND d.market = ? AND d.stock_id = ? AND d.high IS NOT NULL
        ORDER BY t.trade_date DESC
        LIMIT 3
        """,
        (start_date, market, stock_id),
    ).fetchall()
    ordered = list(reversed(rows))
    trading_days = [
        {"date": row["trade_date"], "high_cents": row["high"]} for row in ordered
    ]
    return {
        "trading_days": trading_days,
        "three_day_high_cents": max((row["high"] for row in ordered), default=None)
        if len(ordered) == 3
        else None,
        "complete": len(ordered) == 3,
    }


def _supports_equity_tick(stock: sqlite3.Row) -> bool:
    return bool(re.fullmatch(r"\d{4}", str(stock["stock_id"]))) and str(
        stock["industry_name"]
    ) not in {"ETF", "ETN", "存託憑證", "受益證券", "認購權證", "認售權證"}


def _event_to_dict(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    interval_minutes: int | None,
    as_of_date: str,
    *,
    include_text: bool = False,
) -> dict:
    start_date = str(row["disposal_start_date"])
    end_date = str(row["disposal_end_date"])
    event = {
        "id": _row_disposition_id(row),
        "announcement_date": row["trade_date"],
        "start_date": start_date,
        "end_date": end_date,
        "interval_minutes": interval_minutes,
        "business_days": _business_days(conn, start_date, end_date),
        "status": _event_status(start_date, end_date, as_of_date),
        "notice_status": _notice_status(str(row["disposal_text"])),
        "reason": row["reason_text"],
    }
    if include_text:
        event["official_text"] = row["disposal_text"]
    return event


def _business_days(conn: sqlite3.Connection, start_date: str, end_date: str) -> int | None:
    count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM trading_days
        WHERE is_open = 1 AND trade_date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()["count"]
    return int(count) if count else None


def _row_disposition_id(row: sqlite3.Row) -> str:
    return disposition_notice_id(
        str(row["market"]),
        str(row["stock_id"]),
        str(row["trade_date"]),
        str(row["disposal_start_date"]),
        str(row["disposal_end_date"]),
    )


def _event_status(start_date: str, end_date: str, as_of_date: str) -> Literal[
    "upcoming", "active", "ended"
]:
    if as_of_date < start_date:
        return "upcoming"
    if as_of_date > end_date:
        return "ended"
    return "active"


def _notice_status(text: str) -> Literal["published", "corrected", "cancelled", "extended"]:
    if "取消" in text:
        return "cancelled"
    if "更正" in text or "修正" in text:
        return "corrected"
    if re.search(r"延長(?:處置|執行|期間)", text):
        return "extended"
    return "published"


def _attention_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for match in ATTENTION_CLAUSE_PATTERN.findall(text):
        clause = re.sub(r"\s+", "", match)
        if clause not in clauses:
            clauses.append(clause)
    return clauses


def _ohlcv_to_dict(row: sqlite3.Row) -> dict:
    return {
        "date": row["trade_date"],
        "open_cents": row["open"],
        "high_cents": row["high"],
        "low_cents": row["low"],
        "close_cents": row["close"],
        "volume_shares": row["volume"],
    }


def _institutional_to_dict(row: sqlite3.Row) -> dict:
    return {
        "date": row["trade_date"],
        "foreign_net_lots": row["foreign_net"],
        "investment_trust_net_lots": row["investment_trust_net"],
        "dealer_net_lots": row["dealer_net"],
    }


def _margin_to_dict(row: sqlite3.Row) -> dict:
    return {
        "date": row["trade_date"],
        "margin_balance_lots": row["margin_balance"],
        "short_balance_lots": row["short_balance"],
    }


def _pagination(total: int, limit: int, offset: int, returned: int) -> dict:
    return {
        "limit": limit,
        "offset": offset,
        "returned": returned,
        "has_more": offset + returned < total,
    }


def _api_error(
    code: str, http_status: int, message: str, params: dict | None = None
) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "error": {"message": message, "params": params or {}}},
    )
