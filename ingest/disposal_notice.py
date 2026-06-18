from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import csv
import hashlib
import re
import sqlite3

import config
from ingest.downloader import (
    CooldownController,
    FetchDisposalCsv,
    LogFunc,
    download_disposal_csv,
    save_official_disposal_csv,
)
from ingest.trading_calendar import (
    ensure_trading_days_current,
    latest_open_trading_day_on_or_before,
    next_open_trading_day_after,
    validate_iso_date,
)
from services import batch_status
from validate.close_rules import _clean_stock_id, _normalize_date
from validate.result import ValidationError


DATASET_DISPOSAL_NOTICE = config.DATASET_DISPOSAL_NOTICE
SUPPORTED_ENCODINGS = ("utf-8-sig", "cp950", "big5")

COL_INDEX = "\u7de8\u865f"
COL_ANNOUNCE_DATE = "\u516c\u5e03\u65e5\u671f"
COL_STOCK_ID = "\u8b49\u5238\u4ee3\u865f"
COL_STOCK_NAME = "\u8b49\u5238\u540d\u7a31"
COL_TWSE_PERIOD = "\u8655\u7f6e\u8d77\u8fc4\u6642\u9593"
COL_TPEX_PERIOD = "\u8655\u7f6e\u8d77\u8a16\u6642\u9593"
COL_TWSE_REASON = "\u8655\u7f6e\u689d\u4ef6"
COL_TPEX_REASON = "\u8655\u7f6e\u539f\u56e0"
COL_DISPOSAL_TEXT = "\u8655\u7f6e\u5167\u5bb9"
COL_TOTAL_COUNT = "\u7e3d\u7d2f\u8a08\u6b21\u6578"
COL_SECURITY_COUNT = "\u8b49\u5238\u500b\u6578"


@dataclass(frozen=True)
class DisposalNoticeRow:
    trade_date: str
    market: str
    stock_id: str
    stock_name: str
    disposal_start_date: str
    disposal_end_date: str
    reason_text: str
    disposal_text: str


@dataclass(frozen=True)
class DisposalNoticeParseResult:
    market: str
    source_file: str
    rows: list[DisposalNoticeRow]
    source_dates: list[str]
    skipped_rows: int
    no_disposal_rows: int
    invalid_period_rows: int
    metadata_rows: int
    encoding: str


@dataclass(frozen=True)
class DisposalNoticeSummary:
    market: str
    source_file: str
    encoding: str
    row_count: int
    skipped_rows: int
    no_disposal_rows: int
    invalid_period_rows: int
    metadata_rows: int
    blank_stock_name_rows: int
    blank_reason_text_rows: int
    blank_disposal_text_rows: int
    first_date: str | None
    last_date: str | None
    first_disposal_date: str | None
    last_disposal_date: str | None
    unique_stock_ids: int
    duplicate_keys: int
    duplicate_date_stock_keys: int


@dataclass(frozen=True)
class DisposalNoticeImportResult:
    batch_id: str
    market: str
    period: str
    status: str
    row_count: int
    duplicate_keys: int
    skipped_rows: int
    no_disposal_rows: int
    invalid_period_rows: int
    metadata_rows: int
    blank_stock_name_rows: int
    blank_reason_text_rows: int
    blank_disposal_text_rows: int
    source_file: str


def parse_disposal_notice_file(path: Path | str, market: str) -> DisposalNoticeParseResult:
    if market not in config.MARKETS:
        raise ValueError(f"unknown market: {market}")
    source = Path(path)
    text, encoding = _read_text(source)
    csv_rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(csv_rows)
    mapping = _header_mapping(csv_rows[header_index], market)

    parsed_rows: list[DisposalNoticeRow] = []
    source_dates: list[str] = _source_dates_from_title(csv_rows[:header_index])
    skipped_rows = 0
    no_disposal_rows = 0
    invalid_period_rows = 0
    metadata_rows = 0
    for raw_row in csv_rows[header_index + 1 :]:
        if _is_blank_row(raw_row):
            continue
        if _is_metadata_row(raw_row):
            metadata_rows += 1
            continue
        if _is_no_disposal_row(raw_row, mapping):
            trade_date = _normalize_disposal_date(_get(raw_row, mapping["trade_date"]))
            if trade_date:
                source_dates.append(trade_date)
            no_disposal_rows += 1
            continue
        if not _is_data_row(raw_row):
            skipped_rows += 1
            continue
        try:
            parsed = _parse_row(raw_row, mapping, market)
            parsed_rows.append(parsed)
            source_dates.append(parsed.trade_date)
        except _InvalidPeriodError:
            invalid_period_rows += 1
            skipped_rows += 1
        except ValueError:
            skipped_rows += 1

    return DisposalNoticeParseResult(
        market=market,
        source_file=str(source),
        rows=parsed_rows,
        source_dates=source_dates,
        skipped_rows=skipped_rows,
        no_disposal_rows=no_disposal_rows,
        invalid_period_rows=invalid_period_rows,
        metadata_rows=metadata_rows,
        encoding=encoding,
    )


def summarize_disposal_notice(result: DisposalNoticeParseResult) -> DisposalNoticeSummary:
    trade_dates = result.source_dates or [row.trade_date for row in result.rows]
    start_dates = [row.disposal_start_date for row in result.rows]
    end_dates = [row.disposal_end_date for row in result.rows]
    stock_ids = {row.stock_id for row in result.rows}
    blank_stock_name_rows = sum(1 for row in result.rows if not row.stock_name)
    blank_reason_text_rows = sum(1 for row in result.rows if not row.reason_text)
    blank_disposal_text_rows = sum(1 for row in result.rows if not row.disposal_text)
    keys = [
        (
            row.trade_date,
            row.market,
            row.stock_id,
            row.disposal_start_date,
            row.disposal_end_date,
        )
        for row in result.rows
    ]
    date_stock_keys = [(row.trade_date, row.market, row.stock_id) for row in result.rows]
    return DisposalNoticeSummary(
        market=result.market,
        source_file=result.source_file,
        encoding=result.encoding,
        row_count=len(result.rows),
        skipped_rows=result.skipped_rows,
        no_disposal_rows=result.no_disposal_rows,
        invalid_period_rows=result.invalid_period_rows,
        metadata_rows=result.metadata_rows,
        blank_stock_name_rows=blank_stock_name_rows,
        blank_reason_text_rows=blank_reason_text_rows,
        blank_disposal_text_rows=blank_disposal_text_rows,
        first_date=min(trade_dates) if trade_dates else None,
        last_date=max(trade_dates) if trade_dates else None,
        first_disposal_date=min(start_dates) if start_dates else None,
        last_disposal_date=max(end_dates) if end_dates else None,
        unique_stock_ids=len(stock_ids),
        duplicate_keys=len(keys) - len(set(keys)),
        duplicate_date_stock_keys=len(date_stock_keys) - len(set(date_stock_keys)),
    )


def import_disposal_notice_file(
    conn: sqlite3.Connection,
    *,
    path: Path | str,
    market: str,
    retry_count: int = 0,
) -> DisposalNoticeImportResult:
    source_path = Path(path)
    raw = source_path.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    result = parse_disposal_notice_file(source_path, market)
    summary = summarize_disposal_notice(result)
    period = _period_from_summary(summary, source_path)
    return _record_disposal_import(
        conn,
        source_path=source_path,
        source_sha256=source_sha256,
        result=result,
        summary=summary,
        period=period,
        replace_existing=True,
        retry_count=retry_count,
    )


def import_disposal_notice_official(
    conn: sqlite3.Connection,
    *,
    market: str,
    start: str,
    end: str,
    fetcher: FetchDisposalCsv = download_disposal_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    max_attempts: int = 3,
) -> DisposalNoticeImportResult:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f"disposal notice start date is after end date: {start} > {end}")
    cooldown = cooldown or CooldownController()
    last_result: DisposalNoticeImportResult | None = None
    for attempt in range(1, max_attempts + 1):
        raw: bytes | None = None
        source_path: Path | None = None
        try:
            cooldown.before_request(log)
            raw = fetcher(market, start, end)
            source_path = save_official_disposal_csv(raw, market, start, end)
            source_sha256 = hashlib.sha256(raw).hexdigest()
            result = parse_disposal_notice_file(source_path, market)
            summary = summarize_disposal_notice(result)
            import_result = _record_disposal_import(
                conn,
                source_path=source_path,
                source_sha256=source_sha256,
                result=result,
                summary=summary,
                period=_period_from_dates(start, end),
                replace_existing=False,
                retry_count=attempt - 1,
            )
            last_result = import_result
            if import_result.status in {"OK", "FIXED"}:
                if log:
                    log(
                        f"INFO {import_result.period} {market} disposal "
                        f"attempt {attempt} {import_result.status}"
                    )
                return import_result
            if log:
                message = (
                    f"INFO {import_result.period} {market} disposal "
                    f"attempt {attempt} {import_result.status}"
                )
                log(f"{message}; retrying" if attempt < max_attempts else message)
        except Exception as exc:
            last_result = _record_official_failure(
                conn,
                market=market,
                start=start,
                end=end,
                exc=exc,
                raw=raw,
                source_path=source_path,
                retry_count=attempt - 1,
            )
            if log:
                message = (
                    f"ERROR {_period_from_dates(start, end)} {market} "
                    f"disposal attempt {attempt} failed: {exc}"
                )
                log(f"{message}; retrying" if attempt < max_attempts else message)
    if last_result is None:
        raise RuntimeError("disposal notice official import did not run")
    return last_result


def import_disposal_notice_update(
    conn: sqlite3.Connection,
    *,
    through_date: str | None = None,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchDisposalCsv = download_disposal_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    today: str | None = None,
) -> dict[str, int]:
    target_source = through_date or today or date.today().isoformat()
    requested_target = validate_iso_date(target_source)
    selected_markets = markets or config.MARKETS
    stats = _empty_stats()
    cooldown = cooldown or CooldownController()
    ensure_trading_days_current(
        conn,
        through_date=requested_target,
        cooldown=cooldown,
        log=log,
    )
    official_end = (date.fromisoformat(requested_target) + timedelta(days=15)).isoformat()

    for market in selected_markets:
        latest = latest_disposal_notice_date(conn, market)
        if latest is None:
            raise ValueError(
                f"no existing disposal_notice coverage for {market}; seed with import-disposal first"
            )
        if latest >= requested_target:
            if log:
                log(
                    f"INFO disposal_notice {market} already current: "
                    f"latest={latest} requested_target={requested_target}"
                )
            stats["SKIPPED"] += 1
            continue
        if log:
            log(
                f"Update Disposal: {market} latest={latest} "
                f"range={latest} -> {official_end} requested_target={requested_target}"
            )
        result = import_disposal_notice_official(
            conn,
            market=market,
            start=latest,
            end=official_end,
            fetcher=fetcher,
            cooldown=cooldown,
            log=log,
        )
        stats[result.status] += 1
        if log:
            log(
                f"INFO {result.period} {result.market} disposal import {result.status} "
                f"rows={result.row_count}"
            )
    return stats


def latest_disposal_notice_date(conn: sqlite3.Connection, market: str | None = None) -> str | None:
    if market:
        row = conn.execute(
            "SELECT MAX(trade_date) AS trade_date FROM disposal_notices WHERE market = ?",
            (market,),
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM disposal_notices").fetchone()
    if row and row["trade_date"]:
        return row["trade_date"]
    return None


def _record_disposal_import(
    conn: sqlite3.Connection,
    *,
    source_path: Path,
    source_sha256: str,
    result: DisposalNoticeParseResult,
    summary: DisposalNoticeSummary,
    period: str,
    replace_existing: bool,
    retry_count: int = 0,
) -> DisposalNoticeImportResult:
    existing = batch_status.get_batch(conn, DATASET_DISPOSAL_NOTICE, summary.market, period)
    errors = _summary_errors(summary)

    if errors:
        batch_id = batch_status.record_batch(
            conn,
            dataset=DATASET_DISPOSAL_NOTICE,
            market=summary.market,
            period=period,
            status="BLOCKED",
            row_count=None,
            errors=errors,
            source_file=str(source_path),
            source_sha256=source_sha256,
            retry_count=retry_count,
            note=_summary_note(summary),
        )
        return _import_result(
            batch_id=batch_id,
            period=period,
            status="BLOCKED",
            summary=summary,
            row_count=0,
        )

    status = "OK"
    if existing and existing["status"] in {"BLOCKED", "RECHECK", "MISSING"}:
        status = "FIXED"
    if replace_existing:
        _replace_disposal_notice_rows(conn, summary.market, summary.first_date, summary.last_date, result.rows)
    else:
        _upsert_disposal_notice_rows(conn, result.rows)
    batch_id = batch_status.record_batch(
        conn,
        dataset=DATASET_DISPOSAL_NOTICE,
        market=summary.market,
        period=period,
        status=status,
        row_count=len(result.rows),
        errors=[],
        source_file=str(source_path),
        source_sha256=source_sha256,
        retry_count=retry_count,
        note=_summary_note(summary),
        clear_manual_approval=True,
    )
    return _import_result(
        batch_id=batch_id,
        period=period,
        status=status,
        summary=summary,
        row_count=len(result.rows),
    )


def query_disposal_notices(
    conn: sqlite3.Connection,
    *,
    market: str | None = None,
    stock_id: str | None = None,
    trade_date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    active_date: str | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list[str] = []
    if market:
        clauses.append("market = ?")
        params.append(market)
    if stock_id:
        clauses.append("stock_id = ?")
        params.append(_clean_stock_id(stock_id))
    if trade_date:
        clauses.append("trade_date = ?")
        params.append(trade_date)
    if start:
        clauses.append("trade_date >= ?")
        params.append(start)
    if end:
        clauses.append("trade_date <= ?")
        params.append(end)
    if active_date:
        clauses.append("disposal_start_date <= ? AND disposal_end_date >= ?")
        params.extend([active_date, active_date])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return conn.execute(
        f"""
        SELECT
          trade_date, market, stock_id, stock_name,
          disposal_start_date, disposal_end_date, reason_text, disposal_text
        FROM disposal_notices
        {where}
        ORDER BY trade_date, market, stock_id, disposal_start_date, disposal_end_date
        """,
        params,
    ).fetchall()


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    last_error: Exception | None = None
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"cannot decode disposal notice CSV: {path}") from last_error


def _find_header_index(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        cleaned = {_clean_cell(cell) for cell in row}
        if {COL_INDEX, COL_ANNOUNCE_DATE, COL_STOCK_ID, COL_STOCK_NAME} <= cleaned and (
            COL_TWSE_PERIOD in cleaned or COL_TPEX_PERIOD in cleaned
        ):
            return index
    raise ValueError("disposal notice CSV header not found")


def _header_mapping(header: list[str], market: str) -> dict[str, int]:
    cleaned = [_clean_cell(cell) for cell in header]

    def find(name: str) -> int:
        try:
            return cleaned.index(name)
        except ValueError as exc:
            raise ValueError(f"disposal notice CSV missing column: {name}") from exc

    if market == "TWSE":
        period_col = COL_TWSE_PERIOD
        reason_col = COL_TWSE_REASON
    else:
        period_col = COL_TPEX_PERIOD
        reason_col = COL_TPEX_REASON
    return {
        "trade_date": find(COL_ANNOUNCE_DATE),
        "stock_id": find(COL_STOCK_ID),
        "stock_name": find(COL_STOCK_NAME),
        "period": find(period_col),
        "reason_text": find(reason_col),
        "disposal_text": find(COL_DISPOSAL_TEXT),
    }


def _parse_row(row: list[str], mapping: dict[str, int], market: str) -> DisposalNoticeRow:
    trade_date = _normalize_disposal_date(_get(row, mapping["trade_date"]))
    stock_id = _clean_stock_id(_get(row, mapping["stock_id"]))
    stock_name = _clean_cell(_get(row, mapping["stock_name"]))
    reason_text = _clean_cell(_get(row, mapping["reason_text"]))
    disposal_text = _clean_cell(_get(row, mapping["disposal_text"]))
    disposal_start_date, disposal_end_date = _parse_period(_get(row, mapping["period"]))
    if not trade_date:
        raise ValueError("invalid trade_date")
    if not stock_id:
        raise ValueError("blank stock_id")
    return DisposalNoticeRow(
        trade_date=trade_date,
        market=market,
        stock_id=stock_id,
        stock_name=stock_name,
        disposal_start_date=disposal_start_date,
        disposal_end_date=disposal_end_date,
        reason_text=reason_text,
        disposal_text=disposal_text,
    )


def _parse_period(value: str) -> tuple[str, str]:
    cleaned = _clean_cell(value)
    parts = [part for part in re.split(r"\s*(?:~|\uff5e|\u81f3)\s*", cleaned, maxsplit=1) if part]
    if len(parts) != 2:
        raise _InvalidPeriodError(f"invalid disposal period: {cleaned}")
    start = _normalize_disposal_date(parts[0])
    end = _normalize_disposal_date(parts[1])
    if not start or not end:
        raise _InvalidPeriodError(f"invalid disposal period: {cleaned}")
    if start > end:
        raise _InvalidPeriodError(f"disposal start date is after end date: {cleaned}")
    return start, end


def _source_dates_from_title(rows: list[list[str]]) -> list[str]:
    dates: list[str] = []
    text = " ".join(_clean_cell(cell) for row in rows for cell in row if _clean_cell(cell))
    patterns = [
        r"(\d{2,3})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5\s*\u81f3\s*(\d{2,3})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5",
        r"\u671f\u9593\s*:\s*(\d{2,3})/(\d{1,2})/(\d{1,2})~(\d{2,3})/(\d{1,2})/(\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        dates.extend(
            [
                _roc_parts_to_iso(parts[0], parts[1], parts[2]),
                _roc_parts_to_iso(parts[3], parts[4], parts[5]),
            ]
        )
        break
    return dates


def _roc_parts_to_iso(roc_year: int, month: int, day: int) -> str:
    return date(roc_year + 1911, month, day).isoformat()


def _normalize_disposal_date(value: str) -> str | None:
    return _normalize_date(_clean_cell(value).replace(".", "/"))


def _get(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _clean_cell(value: str) -> str:
    return str(value).strip().strip("\ufeff").strip()


def _is_blank_row(row: list[str]) -> bool:
    return not any(_clean_cell(cell) for cell in row)


def _is_data_row(row: list[str]) -> bool:
    return bool(row and _clean_cell(row[0]).isdigit())


def _is_metadata_row(row: list[str]) -> bool:
    first = _clean_cell(row[0]) if row else ""
    return first.startswith(COL_TOTAL_COUNT) or first.startswith(COL_SECURITY_COUNT)


def _is_no_disposal_row(row: list[str], mapping: dict[str, int]) -> bool:
    stock_id = _clean_stock_id(_get(row, mapping["stock_id"]))
    stock_name = _clean_cell(_get(row, mapping["stock_name"]))
    period = _clean_cell(_get(row, mapping["period"])).lower()
    disposal_text = _clean_cell(_get(row, mapping["disposal_text"]))
    return (
        not stock_id
        and not stock_name
        and period == "null~null"
        and disposal_text.startswith("\u672c\u65e5\u7121\u8655\u7f6e\u8cc7\u6599")
    )


def _period_from_summary(summary: DisposalNoticeSummary, source_path: Path) -> str:
    if summary.first_date and summary.last_date:
        if summary.first_date == summary.last_date:
            return summary.first_date
        return f"{summary.first_date}..{summary.last_date}"
    return source_path.stem


def _summary_errors(summary: DisposalNoticeSummary) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if summary.skipped_rows:
        errors.append(
            ValidationError(
                "BLOCK",
                "DISPOSAL_SKIPPED_ROWS",
                f"disposal notice CSV has {summary.skipped_rows} unparsed rows",
            )
        )
    if summary.duplicate_keys:
        errors.append(
            ValidationError(
                "BLOCK",
                "DUPLICATE_DISPOSAL_NOTICE",
                f"disposal notice CSV has {summary.duplicate_keys} duplicate full keys",
            )
        )
    if summary.row_count == 0 and summary.no_disposal_rows == 0 and not (
        summary.first_date and summary.last_date
    ):
        errors.append(
            ValidationError(
                "BLOCK",
                "NO_DISPOSAL_NOTICE_ROWS",
                "disposal notice CSV contains no announcement rows or official no-disposal rows",
            )
        )
    return errors


def _replace_disposal_notice_rows(
    conn: sqlite3.Connection,
    market: str,
    first_date: str | None,
    last_date: str | None,
    rows: list[DisposalNoticeRow],
) -> None:
    if first_date and last_date:
        conn.execute(
            """
            DELETE FROM disposal_notices
            WHERE market = ? AND trade_date >= ? AND trade_date <= ?
            """,
            (market, first_date, last_date),
        )
    else:
        conn.execute("DELETE FROM disposal_notices WHERE market = ?", (market,))
    conn.executemany(
        """
        INSERT INTO disposal_notices(
          trade_date, market, stock_id, stock_name,
          disposal_start_date, disposal_end_date, reason_text, disposal_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.trade_date,
                row.market,
                row.stock_id,
                row.stock_name,
                row.disposal_start_date,
                row.disposal_end_date,
                row.reason_text,
                row.disposal_text,
            )
            for row in rows
        ],
    )


def _upsert_disposal_notice_rows(
    conn: sqlite3.Connection,
    rows: list[DisposalNoticeRow],
) -> None:
    conn.executemany(
        """
        INSERT INTO disposal_notices(
          trade_date, market, stock_id, stock_name,
          disposal_start_date, disposal_end_date, reason_text, disposal_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, market, stock_id, disposal_start_date, disposal_end_date)
        DO UPDATE SET
          stock_name = excluded.stock_name,
          reason_text = excluded.reason_text,
          disposal_text = excluded.disposal_text
        """,
        [
            (
                row.trade_date,
                row.market,
                row.stock_id,
                row.stock_name,
                row.disposal_start_date,
                row.disposal_end_date,
                row.reason_text,
                row.disposal_text,
            )
            for row in rows
        ],
    )


def _record_official_failure(
    conn: sqlite3.Connection,
    *,
    market: str,
    start: str,
    end: str,
    exc: Exception,
    raw: bytes | None,
    source_path: Path | None,
    retry_count: int = 0,
) -> DisposalNoticeImportResult:
    status = "MISSING" if raw is None else "BLOCKED"
    code = "DOWNLOAD_FAILED" if raw is None else "DISPOSAL_IMPORT_FAILED"
    period = _period_from_dates(start, end)
    source_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
    batch_id = batch_status.record_batch(
        conn,
        dataset=DATASET_DISPOSAL_NOTICE,
        market=market,
        period=period,
        status=status,
        row_count=None,
        errors=[ValidationError("BLOCK", code, str(exc))],
        source_file=str(source_path) if source_path else None,
        source_sha256=source_sha256,
        retry_count=retry_count,
        note="official_download",
    )
    summary = DisposalNoticeSummary(
        market=market,
        source_file=str(source_path) if source_path else "",
        encoding="",
        row_count=0,
        skipped_rows=0,
        no_disposal_rows=0,
        invalid_period_rows=0,
        metadata_rows=0,
        blank_stock_name_rows=0,
        blank_reason_text_rows=0,
        blank_disposal_text_rows=0,
        first_date=None,
        last_date=None,
        first_disposal_date=None,
        last_disposal_date=None,
        unique_stock_ids=0,
        duplicate_keys=0,
        duplicate_date_stock_keys=0,
    )
    return _import_result(
        batch_id=batch_id,
        period=period,
        status=status,
        summary=summary,
        row_count=0,
    )


def _summary_note(summary: DisposalNoticeSummary) -> str:
    parts = [
        f"encoding={summary.encoding}",
        f"no_disposal_rows={summary.no_disposal_rows}",
        f"metadata_rows={summary.metadata_rows}",
        f"blank_stock_name_rows={summary.blank_stock_name_rows}",
        f"blank_reason_text_rows={summary.blank_reason_text_rows}",
        f"blank_disposal_text_rows={summary.blank_disposal_text_rows}",
    ]
    if summary.skipped_rows:
        parts.append(f"skipped_rows={summary.skipped_rows}")
    if summary.invalid_period_rows:
        parts.append(f"invalid_period_rows={summary.invalid_period_rows}")
    if summary.duplicate_keys:
        parts.append(f"duplicate_keys={summary.duplicate_keys}")
    return "; ".join(parts)


def _period_from_dates(start: str, end: str) -> str:
    return start if start == end else f"{start}..{end}"


def _period_end(period: str) -> str | None:
    value = period.split("..")[-1]
    try:
        return validate_iso_date(value)
    except ValueError:
        return None


def _empty_stats() -> dict[str, int]:
    return {"OK": 0, "FIXED": 0, "BLOCKED": 0, "RECHECK": 0, "MISSING": 0, "SKIPPED": 0}


def _import_result(
    *,
    batch_id: str,
    period: str,
    status: str,
    summary: DisposalNoticeSummary,
    row_count: int,
) -> DisposalNoticeImportResult:
    return DisposalNoticeImportResult(
        batch_id=batch_id,
        market=summary.market,
        period=period,
        status=status,
        row_count=row_count,
        duplicate_keys=summary.duplicate_keys,
        skipped_rows=summary.skipped_rows,
        no_disposal_rows=summary.no_disposal_rows,
        invalid_period_rows=summary.invalid_period_rows,
        metadata_rows=summary.metadata_rows,
        blank_stock_name_rows=summary.blank_stock_name_rows,
        blank_reason_text_rows=summary.blank_reason_text_rows,
        blank_disposal_text_rows=summary.blank_disposal_text_rows,
        source_file=summary.source_file,
    )


class _InvalidPeriodError(ValueError):
    pass
