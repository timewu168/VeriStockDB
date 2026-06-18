from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
import sqlite3
from typing import Iterable

import config
from ingest.downloader import (
    CooldownController,
    FetchCloseMonthJson,
    download_close_month_json,
)
from services import batch_status
from services.monthly_audit import audit_date_range, normalize_markets
from validate.result import ValidationError


DEFAULT_STOCKS: dict[str, tuple[str, ...]] = {
    "TWSE": ("0050", "1101"),
    "TPEX": ("5483",),
}


@dataclass(frozen=True)
class OfficialMonthlyCloseRow:
    trade_date: str
    close: int
    volume: int


@dataclass(frozen=True)
class ReconcileTargetResult:
    market: str
    stock_id: str
    checked_rows: int
    status: str
    errors: tuple[str, ...] = ()


@dataclass
class ReconcileResult:
    month: str
    status: str
    targets: list[ReconcileTargetResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def reconcile_close_month(
    conn: sqlite3.Connection,
    *,
    month: str,
    markets: Iterable[str] | None = None,
    stock_ids: Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    fetcher: FetchCloseMonthJson = download_close_month_json,
    cooldown: CooldownController | None = None,
    log=None,
) -> ReconcileResult:
    start_date, end_date, _ = audit_date_range(month, start, end)
    selected_markets = normalize_markets(markets)
    target_map = _target_map(conn, selected_markets, stock_ids)
    cooldown = cooldown or CooldownController()

    result = ReconcileResult(month=month, status="OK")
    for market in selected_markets:
        for stock_id in target_map[market]:
            if log:
                log(f"INFO reconcile-close-month {month} {market} {stock_id}")
            target = _reconcile_one(
                conn,
                month=month,
                market=market,
                stock_id=stock_id,
                start=start_date,
                end=end_date,
                fetcher=fetcher,
                cooldown=cooldown,
                log=log,
            )
            result.targets.append(target)
            result.errors.extend(target.errors)

    if result.errors:
        result.status = "RECHECK"
    _record_month_batch(conn, result)
    return result


def parse_official_close_month_json(payload: dict, *, market: str) -> list[OfficialMonthlyCloseRow]:
    if market == "TWSE":
        fields = payload.get("fields") or []
        data = payload.get("data") or []
        if payload.get("stat") != "OK":
            raise ValueError(f"TWSE monthly stock response is not OK: {payload.get('stat')}")
        date_idx = _field_index(fields, "日期")
        volume_idx = _field_index(fields, "成交股數")
        close_idx = _field_index(fields, "收盤價")
        return [
            OfficialMonthlyCloseRow(
                trade_date=_parse_roc_date(row[date_idx]),
                close=_parse_price_cents(row[close_idx]),
                volume=_parse_int(row[volume_idx]),
            )
            for row in data
        ]

    if market == "TPEX":
        if str(payload.get("stat", "")).lower() != "ok":
            raise ValueError(f"TPEX monthly stock response is not ok: {payload.get('stat')}")
        tables = payload.get("tables") or []
        if not tables:
            raise ValueError("TPEX monthly stock response has no tables")
        table = tables[0]
        fields = table.get("fields") or []
        data = table.get("data") or []
        date_idx = _field_index(fields, "日 期")
        volume_idx = _field_index(fields, "成交張數")
        close_idx = _field_index(fields, "收盤")
        return [
            OfficialMonthlyCloseRow(
                trade_date=_parse_roc_date(row[date_idx]),
                close=_parse_price_cents(row[close_idx]),
                volume=_parse_int(row[volume_idx]) * 1000,
            )
            for row in data
        ]

    raise ValueError(f"unknown market: {market}")


def _reconcile_one(
    conn: sqlite3.Connection,
    *,
    month: str,
    market: str,
    stock_id: str,
    start: str,
    end: str,
    fetcher: FetchCloseMonthJson,
    cooldown: CooldownController,
    log,
) -> ReconcileTargetResult:
    errors: list[str] = []
    try:
        cooldown.before_request(log)
        payload = fetcher(market, month, stock_id)
        official_rows = parse_official_close_month_json(payload, market=market)
    except Exception as exc:
        message = f"{month} {market} {stock_id} official monthly source failed: {exc}"
        _record_target_batch(conn, month, market, stock_id, "RECHECK", 0, [message])
        return ReconcileTargetResult(market, stock_id, 0, "RECHECK", (message,))

    official_by_date = {
        row.trade_date: row for row in official_rows if start <= row.trade_date <= end
    }
    db_rows = _db_rows(conn, market, stock_id, start, end)

    for trade_date, row in sorted(official_by_date.items()):
        db_row = db_rows.get(trade_date)
        if db_row is None:
            errors.append(f"{month} {market} {stock_id} {trade_date} DB row missing")
            continue
        if db_row["close"] != row.close:
            errors.append(
                f"{month} {market} {stock_id} {trade_date} close mismatch: "
                f"db={db_row['close']} official={row.close}"
            )
        if _volume_mismatch(market, db_row["volume"], row.volume):
            errors.append(
                f"{month} {market} {stock_id} {trade_date} volume mismatch: "
                f"db={db_row['volume']} official={row.volume}"
            )

    for trade_date in sorted(set(db_rows) - set(official_by_date)):
        errors.append(f"{month} {market} {stock_id} {trade_date} official row missing")

    status = "OK" if not errors else "RECHECK"
    _record_target_batch(conn, month, market, stock_id, status, len(official_by_date), errors)
    return ReconcileTargetResult(market, stock_id, len(official_by_date), status, tuple(errors))



def _volume_mismatch(market: str, db_volume: int, official_volume: int) -> bool:
    if market == "TPEX":
        return abs(db_volume - official_volume) > 500
    return db_volume != official_volume


def _record_month_batch(conn: sqlite3.Connection, result: ReconcileResult) -> None:
    errors = [
        ValidationError(
            severity="WARN",
            code="CLOSE_MONTH_RECONCILE_MISMATCH",
            message=message,
        )
        for message in result.errors
    ]
    row_count = sum(target.checked_rows for target in result.targets)
    batch_status.record_batch(
        conn,
        dataset=config.DATASET_DAILY_CLOSE,
        market="ALL",
        period=result.month,
        status=result.status,
        row_count=row_count,
        errors=errors,
        note="monthly_reconcile",
    )


def _record_target_batch(
    conn: sqlite3.Connection,
    month: str,
    market: str,
    stock_id: str,
    status: str,
    row_count: int,
    messages: list[str],
) -> None:
    errors = [
        ValidationError(
            severity="WARN",
            code="CLOSE_MONTH_RECONCILE_MISMATCH",
            message=message,
            sample_stock_id=stock_id,
        )
        for message in messages
    ]
    batch_status.record_batch(
        conn,
        dataset=config.DATASET_DAILY_CLOSE,
        market=market,
        period=f"{month}:{stock_id}",
        status=status,
        row_count=row_count,
        errors=errors,
        note="monthly_reconcile_target",
    )


def _target_map(
    conn: sqlite3.Connection,
    markets: tuple[str, ...],
    stock_ids: Iterable[str] | None,
) -> dict[str, tuple[str, ...]]:
    if stock_ids:
        requested = tuple(dict.fromkeys(stock_ids))
        return {market: _existing_stock_ids(conn, market, requested) for market in markets}
    return {market: DEFAULT_STOCKS[market] for market in markets}


def _existing_stock_ids(
    conn: sqlite3.Connection,
    market: str,
    requested: tuple[str, ...],
) -> tuple[str, ...]:
    existing: list[str] = []
    for stock_id in requested:
        row = conn.execute(
            "SELECT 1 FROM daily_close WHERE market = ? AND stock_id = ? LIMIT 1",
            (market, stock_id),
        ).fetchone()
        if row is not None:
            existing.append(stock_id)
    if not existing:
        raise ValueError(f"no requested stock IDs exist in daily_close for {market}")
    return tuple(existing)


def _db_rows(
    conn: sqlite3.Connection,
    market: str,
    stock_id: str,
    start: str,
    end: str,
) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT trade_date, close, volume
        FROM daily_close
        WHERE market = ? AND stock_id = ? AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (market, stock_id, start, end),
    ).fetchall()
    return {row["trade_date"]: row for row in rows}


def _field_index(fields: list[str], name: str) -> int:
    normalized = [_normalize_field(field) for field in fields]
    target = _normalize_field(name)
    if target not in normalized:
        raise ValueError(f"missing official field: {name}")
    return normalized.index(target)


def _normalize_field(value: str) -> str:
    return re.sub(r"\s+", "", str(value))


def _parse_roc_date(value: str) -> str:
    parts = str(value).strip().split("/")
    if len(parts) != 3:
        raise ValueError(f"invalid ROC date: {value}")
    year = int(parts[0]) + 1911
    return f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def _parse_int(value: str) -> int:
    text = str(value).replace(",", "").strip()
    if not text:
        raise ValueError("blank integer")
    return int(text)


def _parse_price_cents(value: str) -> int:
    text = str(value).replace(",", "").strip()
    if not text or text in {"--", "---"}:
        raise ValueError(f"blank price: {value}")
    try:
        return int((Decimal(text) * Decimal("100")).to_integral_exact())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid price: {value}") from exc
