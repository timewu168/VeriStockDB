from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Callable

import config
from ingest.csv_reader import read_csv_rows
from validate.result import CloseRow, DataEvent, PreviousClose, ValidationError, ValidationOutcome


DASH_PLACEHOLDERS = {"--", "---", "----"}

COLUMN_ALIASES = {
    "trade_date": {"trade_date", "交易日期", "日期"},
    "stock_id": {"stock_id", "證券代號", "代號", "有價證券代號"},
    "stock_name": {"stock_name", "證券名稱", "名稱", "有價證券名稱"},
    "open": {"open", "開盤價", "開盤"},
    "high": {"high", "最高價", "最高"},
    "low": {"low", "最低價", "最低"},
    "close": {"close", "收盤價", "收盤"},
    "volume": {"volume", "成交股數", "成交股數(股)"},
    "amount": {"amount", "成交金額", "成交金額(元)"},
    "transactions": {"transactions", "成交筆數"},
}

REQUIRED_COLUMNS = (
    "stock_id",
    "stock_name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "transactions",
)

PreviousCloseLookup = Callable[[str, str, str], int | PreviousClose | None]


@dataclass(frozen=True)
class ParsedCloseRow:
    row: CloseRow | None
    event: DataEvent | None = None


def validate_close_csv(
    raw: bytes,
    market: str,
    trade_date: str,
    previous_close_lookup: PreviousCloseLookup | None = None,
    previous_market_row_count: int | None = None,
) -> ValidationOutcome:
    if market not in config.MARKETS:
        return _blocked("INVALID_MARKET", f"market must be one of {config.MARKETS}")

    try:
        rows, _encoding = read_csv_rows(raw)
    except Exception as exc:
        return _blocked("CSV_READ_FAILED", str(exc))

    header_index = _find_header_index(rows)
    if header_index is None:
        return _blocked("HEADER_NOT_FOUND", "required Close CSV header was not found")

    header = [_clean_cell(cell) for cell in rows[header_index]]
    mapping = _build_mapping(header)
    missing = [name for name in REQUIRED_COLUMNS if name not in mapping]
    if missing:
        return _blocked(
            "MISSING_REQUIRED_COLUMNS",
            "missing required columns: " + ", ".join(missing),
        )

    outcome = ValidationOutcome()
    seen_stock_ids: set[str] = set()
    saw_data = False
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if _is_blank_row(row):
            continue
        if _is_known_section_title(row):
            continue
        if _is_known_trailing_note(row):
            if saw_data:
                break
            continue
        if _looks_like_header(row):
            if saw_data:
                continue
            outcome.errors.append(
                ValidationError(
                    "BLOCK",
                    "UNEXPECTED_HEADER_ROW",
                    f"unexpected repeated header at row {row_number}",
                )
            )
            outcome.status = "BLOCKED"
            continue
        if len(row) != len(header):
            outcome.errors.append(
                ValidationError(
                    "BLOCK",
                    "ROW_FIELD_COUNT_MISMATCH",
                    f"row {row_number} has {len(row)} fields but header has {len(header)}",
                )
            )
            outcome.status = "BLOCKED"
            continue

        saw_data = True
        parsed = _parse_row(
            row=row,
            mapping=mapping,
            market=market,
            trade_date=trade_date,
            previous_close_lookup=previous_close_lookup,
        )
        if isinstance(parsed, ValidationError):
            outcome.errors.append(parsed)
            outcome.status = _merge_status(outcome.status, _status_for_error(parsed))
            continue
        if isinstance(parsed, ParsedCloseRow):
            if parsed.event:
                outcome.events.append(parsed.event)
            if parsed.row is None:
                outcome.excluded_count += 1
                continue
            parsed = parsed.row
        if parsed is None:
            outcome.excluded_count += 1
            continue
        if parsed.stock_id in seen_stock_ids:
            outcome.errors.append(
                ValidationError(
                    "BLOCK",
                    "DUPLICATE_STOCK_ID",
                    "same market/date contains duplicate stock_id",
                    parsed.stock_id,
                )
            )
            outcome.status = "BLOCKED"
            continue
        seen_stock_ids.add(parsed.stock_id)
        outcome.rows.append(parsed)

    if not outcome.rows and not outcome.errors and outcome.excluded_count == 0:
        outcome.errors.append(
            ValidationError("BLOCK", "NO_DATA", "Close CSV contains no target rows")
        )
        outcome.status = "MISSING"

    _apply_market_row_count_check(outcome, previous_market_row_count)
    return outcome


def _find_header_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows):
        normalized = {_clean_cell(cell) for cell in row}
        if (
            normalized & COLUMN_ALIASES["stock_id"]
            and normalized & COLUMN_ALIASES["stock_name"]
            and normalized & COLUMN_ALIASES["close"]
            and normalized & COLUMN_ALIASES["transactions"]
        ):
            return index
    return None


def _build_mapping(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for index, name in enumerate(header):
            if name in aliases and canonical not in mapping:
                mapping[canonical] = index
    return mapping


def _parse_row(
    row: list[str],
    mapping: dict[str, int],
    market: str,
    trade_date: str,
    previous_close_lookup: PreviousCloseLookup | None,
) -> CloseRow | ParsedCloseRow | ValidationError | None:
    stock_id = _clean_stock_id(row[mapping["stock_id"]])
    stock_name = _clean_cell(row[mapping["stock_name"]])
    if not stock_id:
        return ValidationError("BLOCK", "BLANK_STOCK_ID", "stock_id is blank")
    if not stock_name:
        return ValidationError("BLOCK", "BLANK_STOCK_NAME", "stock_name is blank", stock_id)
    if not _is_security_id(stock_id):
        return ValidationError(
            "BLOCK",
            "UNEXPECTED_SECURITY_ID",
            "stock_id is not an official security id",
            stock_id,
        )
    if not _is_target_security_id(stock_id, market):
        return None

    if "trade_date" in mapping:
        source_date = _normalize_date(_clean_cell(row[mapping["trade_date"]]))
        if source_date is None:
            return ValidationError("BLOCK", "INVALID_TRADE_DATE", "trade_date is invalid", stock_id)
        if source_date != trade_date:
            return ValidationError(
                "BLOCK",
                "TRADE_DATE_MISMATCH",
                f"row date {source_date} does not match target date {trade_date}",
                stock_id,
                source_date,
            )

    int_fields = {}
    for field in ("volume", "amount", "transactions"):
        parsed_int = _parse_integer(row[mapping[field]])
        if isinstance(parsed_int, ValidationError):
            return ValidationError(
                parsed_int.severity,
                parsed_int.code,
                f"{field}: {parsed_int.message}",
                stock_id,
                _clean_cell(row[mapping[field]]),
            )
        int_fields[field] = parsed_int

    price_cells = {field: _clean_cell(row[mapping[field]]) for field in ("open", "high", "low", "close")}
    has_dash = any(value in DASH_PLACEHOLDERS for value in price_cells.values())
    if has_dash:
        return _parse_dash_price_row(
            stock_id,
            stock_name,
            market,
            trade_date,
            price_cells,
            int_fields,
            previous_close_lookup,
        )

    prices = {}
    for field, value in price_cells.items():
        parsed_price = _parse_price_to_cents(value)
        if isinstance(parsed_price, ValidationError):
            return ValidationError(
                parsed_price.severity,
                parsed_price.code,
                f"{field}: {parsed_price.message}",
                stock_id,
                value,
            )
        prices[field] = parsed_price

    ohlc_error = _validate_ohlc(prices, stock_id)
    if ohlc_error:
        return ohlc_error

    return CloseRow(
        trade_date=trade_date,
        stock_id=stock_id,
        stock_name=stock_name,
        market=market,
        open=prices["open"],
        high=prices["high"],
        low=prices["low"],
        close=prices["close"],
        volume=int_fields["volume"],
        amount=int_fields["amount"],
        transactions=int_fields["transactions"],
    )


def _parse_dash_price_row(
    stock_id: str,
    stock_name: str,
    market: str,
    trade_date: str,
    price_cells: dict[str, str],
    int_fields: dict[str, int],
    previous_close_lookup: PreviousCloseLookup | None,
) -> ParsedCloseRow | ValidationError:
    if not all(value in DASH_PLACEHOLDERS for value in price_cells.values()):
        return ValidationError(
            "BLOCK",
            "MIXED_DASH_PRICE",
            "dash placeholders must occupy all OHLC fields or none",
            stock_id,
            repr(price_cells),
        )
    previous = previous_close_lookup(stock_id, trade_date, market) if previous_close_lookup else None
    previous_close, reference_period = _previous_close_parts(previous)
    if previous_close is None:
        if all(value == 0 for value in int_fields.values()):
            return ParsedCloseRow(
                row=None,
                event=DataEvent(
                    event_type="ZERO_TRADE_DASH_EXCLUDED",
                    trade_date=trade_date,
                    stock_id=stock_id,
                    stock_name=stock_name,
                    market=market,
                    source_open=price_cells["open"],
                    source_high=price_cells["high"],
                    source_low=price_cells["low"],
                    source_close=price_cells["close"],
                    note="zero-trade dash OHLC excluded before first valid close",
                ),
            )
        return ValidationError(
            "BLOCK",
            "MISSING_PREVIOUS_CLOSE",
            "dash OHLC row has no provable previous close",
            stock_id,
        )
    return ParsedCloseRow(
        row=CloseRow(
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name=stock_name,
            market=market,
            open=previous_close,
            high=previous_close,
            low=previous_close,
            close=previous_close,
            volume=int_fields["volume"],
            amount=int_fields["amount"],
            transactions=int_fields["transactions"],
        ),
        event=DataEvent(
            event_type="DASH_FILLED_PREVIOUS_CLOSE",
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name=stock_name,
            market=market,
            source_open=price_cells["open"],
            source_high=price_cells["high"],
            source_low=price_cells["low"],
            source_close=price_cells["close"],
            stored_open=previous_close,
            stored_high=previous_close,
            stored_low=previous_close,
            stored_close=previous_close,
            reference_period=reference_period,
            reference_value=previous_close,
            note="dash OHLC filled from previous valid close",
        ),
    )


def _validate_ohlc(prices: dict[str, int], stock_id: str) -> ValidationError | None:
    if prices["open"] < 0 or prices["high"] < 0 or prices["low"] < 0 or prices["close"] < 0:
        return ValidationError("BLOCK", "NEGATIVE_PRICE", "OHLC cannot be negative", stock_id)
    if prices["high"] < prices["open"] or prices["high"] < prices["close"] or prices["high"] < prices["low"]:
        return ValidationError("BLOCK", "INVALID_OHLC", "high is lower than another OHLC value", stock_id)
    if prices["low"] > prices["open"] or prices["low"] > prices["close"]:
        return ValidationError("BLOCK", "INVALID_OHLC", "low is higher than open/close", stock_id)
    return None


def _previous_close_parts(value: int | PreviousClose | None) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, PreviousClose):
        return value.close, value.trade_date
    return int(value), None


def _parse_price_to_cents(value: str) -> int | ValidationError:
    value = _clean_number(value)
    if not value:
        return ValidationError("BLOCK", "BLANK_NUMERIC_CELL", "price is blank")
    if value in {"NaN", "N/A", "nan", "n/a"}:
        return ValidationError("BLOCK", "BLANK_NUMERIC_CELL", "price is not a real source value")
    if value in DASH_PLACEHOLDERS:
        return ValidationError("BLOCK", "UNHANDLED_DASH_PRICE", "dash price was not handled as a row")
    try:
        cents = Decimal(value) * Decimal("100")
    except InvalidOperation:
        return ValidationError("BLOCK", "INVALID_PRICE", "price is not numeric")
    if cents != cents.to_integral_value():
        return ValidationError("BLOCK", "INVALID_PRICE_PRECISION", "price has more than two decimals")
    return int(cents)


def _parse_integer(value: str) -> int | ValidationError:
    value = _clean_number(value)
    if not value:
        return ValidationError("BLOCK", "BLANK_NUMERIC_CELL", "integer field is blank")
    if value in {"NaN", "N/A", "nan", "n/a"}:
        return ValidationError("BLOCK", "BLANK_NUMERIC_CELL", "integer field is not a real source value")
    if value in DASH_PLACEHOLDERS:
        return ValidationError("BLOCK", "INVALID_INTEGER", "dash is not valid for integer fields")
    if not re.fullmatch(r"-?\d+", value):
        return ValidationError("BLOCK", "INVALID_INTEGER", "integer field is not an integer")
    parsed = int(value)
    if parsed < 0:
        return ValidationError("BLOCK", "NEGATIVE_INTEGER", "integer field cannot be negative")
    return parsed


def _apply_market_row_count_check(
    outcome: ValidationOutcome, previous_market_row_count: int | None
) -> None:
    if outcome.status == "BLOCKED" or not outcome.rows or not previous_market_row_count:
        return
    diff = abs(len(outcome.rows) - previous_market_row_count) / previous_market_row_count
    if diff > 0.10:
        outcome.errors.append(
            ValidationError(
                "BLOCK",
                "MARKET_ROW_COUNT_BLOCKED",
                f"market row count changed by {diff:.1%}",
            )
        )
        outcome.status = "BLOCKED"
    elif diff >= 0.05:
        outcome.errors.append(
            ValidationError(
                "BLOCK",
                "MARKET_ROW_COUNT_RECHECK",
                f"market row count changed by {diff:.1%}",
            )
        )
        outcome.status = "RECHECK"


def _clean_cell(value: str) -> str:
    return str(value).strip().strip("\ufeff").strip()


def _clean_stock_id(value: str) -> str:
    cleaned = _clean_cell(value)
    if cleaned.startswith('="') and cleaned.endswith('"'):
        return cleaned[2:-1].strip()
    return cleaned


def _clean_number(value: str) -> str:
    return _clean_cell(value).replace(",", "")


def _is_blank_row(row: list[str]) -> bool:
    return not any(_clean_cell(cell) for cell in row)


def _is_known_trailing_note(row: list[str]) -> bool:
    first = _clean_cell(row[0]) if row else ""
    return (
        first.startswith("說明")
        or first.startswith("備註")
        or first.startswith("註")
        or first.startswith("Note")
        or first in {"上櫃家數", "總成交金額", "總成交股數", "總成交筆數"}
    )


def _is_known_section_title(row: list[str]) -> bool:
    if len(row) != 1:
        return False
    return _clean_cell(row[0]) in {"管理股票"}


def _looks_like_header(row: list[str]) -> bool:
    normalized = {_clean_cell(cell) for cell in row}
    return bool(normalized & COLUMN_ALIASES["stock_id"] and normalized & COLUMN_ALIASES["close"])


def _is_security_id(stock_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z]+", stock_id))


def _is_target_security_id(stock_id: str, market: str) -> bool:
    return not (market == "TPEX" and stock_id.startswith("7") and len(stock_id) != 4)


def _normalize_date(value: str) -> str | None:
    value = value.strip()
    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.fullmatch(r"(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        roc_year, month, day = (int(part) for part in match.groups())
        return f"{roc_year + 1911:04d}-{month:02d}-{day:02d}"
    return None


def _status_for_error(error: ValidationError) -> str:
    if error.code == "MISSING_PREVIOUS_CLOSE":
        return "RECHECK"
    return "BLOCKED"


def _merge_status(left: str, right: str) -> str:
    order = {"OK": 0, "FIXED": 0, "RECHECK": 1, "MISSING": 2, "BLOCKED": 3}
    return left if order[left] >= order[right] else right


def _blocked(code: str, message: str) -> ValidationOutcome:
    return ValidationOutcome(
        errors=[ValidationError("BLOCK", code, message)],
        status="BLOCKED",
    )
