from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
import csv
import re
import sqlite3

import config
from ingest.downloader import (
    CooldownController,
    FetchAttentionCsv,
    LogFunc,
    download_attention_csv,
    save_official_attention_csv,
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


DATASET_ATTENTION_NOTICE = config.DATASET_ATTENTION_NOTICE
SUPPORTED_ENCODINGS = ("utf-8-sig", "cp950", "big5")


@dataclass(frozen=True)
class AttentionNoticeRow:
    trade_date: str
    market: str
    stock_id: str
    stock_name: str
    notice_text: str


@dataclass(frozen=True)
class AttentionNoticeParseResult:
    market: str
    source_file: str
    rows: list[AttentionNoticeRow]
    source_dates: list[str]
    skipped_rows: int
    no_notice_rows: int
    metadata_rows: int
    encoding: str


@dataclass(frozen=True)
class AttentionNoticeSummary:
    market: str
    source_file: str
    encoding: str
    row_count: int
    skipped_rows: int
    no_notice_rows: int
    metadata_rows: int
    first_date: str | None
    last_date: str | None
    unique_stock_ids: int
    duplicate_keys: int


@dataclass(frozen=True)
class AttentionNoticeImportResult:
    batch_id: str
    market: str
    period: str
    status: str
    row_count: int
    duplicate_keys: int
    skipped_rows: int
    no_notice_rows: int
    metadata_rows: int
    source_file: str


def parse_attention_notice_file(path: Path | str, market: str) -> AttentionNoticeParseResult:
    if market not in config.MARKETS:
        raise ValueError(f"unknown market: {market}")
    source = Path(path)
    text, encoding = _read_text(source)
    csv_rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(csv_rows)
    mapping = _header_mapping(csv_rows[header_index])

    parsed_rows: list[AttentionNoticeRow] = []
    source_dates: list[str] = _source_dates_from_title(csv_rows[:header_index])
    skipped_rows = 0
    no_notice_rows = 0
    metadata_rows = 0
    for raw_row in csv_rows[header_index + 1 :]:
        if _is_blank_row(raw_row):
            continue
        if _is_no_notice_row(raw_row, mapping):
            notice_date = _normalize_notice_date(_get(raw_row, mapping["trade_date"]))
            if notice_date:
                source_dates.append(notice_date)
            no_notice_rows += 1
            continue
        if _is_metadata_row(raw_row):
            metadata_rows += 1
            continue
        if not _is_data_row(raw_row):
            skipped_rows += 1
            continue
        try:
            parsed = _parse_row(raw_row, mapping, market)
            parsed_rows.append(parsed)
            source_dates.append(parsed.trade_date)
        except ValueError:
            skipped_rows += 1

    return AttentionNoticeParseResult(
        market=market,
        source_file=str(source),
        rows=parsed_rows,
        source_dates=source_dates,
        skipped_rows=skipped_rows,
        no_notice_rows=no_notice_rows,
        metadata_rows=metadata_rows,
        encoding=encoding,
    )


def summarize_attention_notice(result: AttentionNoticeParseResult) -> AttentionNoticeSummary:
    dates = result.source_dates or [row.trade_date for row in result.rows]
    stock_ids = {row.stock_id for row in result.rows}
    keys = [(row.trade_date, row.market, row.stock_id) for row in result.rows]
    duplicate_keys = len(keys) - len(set(keys))
    return AttentionNoticeSummary(
        market=result.market,
        source_file=result.source_file,
        encoding=result.encoding,
        row_count=len(result.rows),
        skipped_rows=result.skipped_rows,
        no_notice_rows=result.no_notice_rows,
        metadata_rows=result.metadata_rows,
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        unique_stock_ids=len(stock_ids),
        duplicate_keys=duplicate_keys,
    )


def import_attention_notice_file(
    conn: sqlite3.Connection,
    *,
    path: Path | str,
    market: str,
) -> AttentionNoticeImportResult:
    source_path = Path(path)
    raw = source_path.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    result = parse_attention_notice_file(source_path, market)
    summary = summarize_attention_notice(result)
    period = _period_from_summary(summary, source_path)
    existing = batch_status.get_batch(conn, DATASET_ATTENTION_NOTICE, market, period)
    errors = _summary_errors(summary)

    if errors:
        batch_id = batch_status.record_batch(
            conn,
            dataset=DATASET_ATTENTION_NOTICE,
            market=market,
            period=period,
            status="BLOCKED",
            row_count=None,
            errors=errors,
            source_file=str(source_path),
            source_sha256=source_sha256,
            retry_count=0,
            note=_summary_note(summary),
        )
        return AttentionNoticeImportResult(
            batch_id=batch_id,
            market=market,
            period=period,
            status="BLOCKED",
            row_count=0,
            duplicate_keys=summary.duplicate_keys,
            skipped_rows=summary.skipped_rows,
            no_notice_rows=summary.no_notice_rows,
            metadata_rows=summary.metadata_rows,
            source_file=str(source_path),
        )

    status = "OK"
    if existing and existing["status"] in {"BLOCKED", "RECHECK", "MISSING"}:
        status = "FIXED"
    _replace_attention_notice_rows(conn, market, summary.first_date, summary.last_date, result.rows)
    batch_id = batch_status.record_batch(
        conn,
        dataset=DATASET_ATTENTION_NOTICE,
        market=market,
        period=period,
        status=status,
        row_count=len(result.rows),
        errors=[],
        source_file=str(source_path),
        source_sha256=source_sha256,
        retry_count=0,
        note=_summary_note(summary),
        clear_manual_approval=True,
    )
    return AttentionNoticeImportResult(
        batch_id=batch_id,
        market=market,
        period=period,
        status=status,
        row_count=len(result.rows),
        duplicate_keys=summary.duplicate_keys,
        skipped_rows=summary.skipped_rows,
        no_notice_rows=summary.no_notice_rows,
        metadata_rows=summary.metadata_rows,
        source_file=str(source_path),
    )


def import_attention_notice_official(
    conn: sqlite3.Connection,
    *,
    market: str,
    start: str,
    end: str,
    fetcher: FetchAttentionCsv = download_attention_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> AttentionNoticeImportResult:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f"attention notice start date is after end date: {start} > {end}")
    cooldown = cooldown or CooldownController()
    raw: bytes | None = None
    source_path: Path | None = None
    try:
        cooldown.before_request(log)
        raw = fetcher(market, start, end)
        source_path = save_official_attention_csv(raw, market, start, end)
        return import_attention_notice_file(conn, path=source_path, market=market)
    except Exception as exc:
        return _record_official_failure(
            conn,
            market=market,
            start=start,
            end=end,
            exc=exc,
            raw=raw,
            source_path=source_path,
        )


def import_attention_notice_update(
    conn: sqlite3.Connection,
    *,
    through_date: str | None = None,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchAttentionCsv = download_attention_csv,
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
    target = latest_open_trading_day_on_or_before(conn, requested_target)
    if target is None:
        raise ValueError(
            f"no open trading day found on or before attention_notice target {requested_target}"
        )

    for market in selected_markets:
        latest = latest_attention_notice_date(conn, market)
        if latest is None:
            raise ValueError(
                f"no existing attention_notice coverage for {market}; seed with import-attention first"
            )
        latest_open = latest_open_trading_day_on_or_before(conn, latest)
        if latest_open is None:
            raise ValueError(
                f"no open trading day found on or before attention_notice latest {latest} for {market}"
            )
        if latest_open >= target:
            if log:
                log(
                    f"INFO attention_notice {market} already current: "
                    f"latest_open={latest_open} target_open={target} requested_target={requested_target}"
                )
            stats["SKIPPED"] += 1
            continue
        first_open = next_open_trading_day_after(conn, latest_open, target)
        if first_open is None:
            if log:
                log(
                    f"INFO attention_notice {market} no open trading days to update: "
                    f"latest_open={latest_open} target_open={target} requested_target={requested_target}"
                )
            stats["SKIPPED"] += 1
            continue
        if log:
            log(
                f"Update Attention: {market} latest={latest} latest_open={latest_open} "
                f"range={first_open} -> {target} requested_target={requested_target}"
            )
        result = import_attention_notice_official(
            conn,
            market=market,
            start=first_open,
            end=target,
            fetcher=fetcher,
            cooldown=cooldown,
            log=log,
        )
        stats[result.status] += 1
        if log:
            log(
                f"INFO {result.period} {result.market} attention import {result.status} "
                f"rows={result.row_count}"
            )
    return stats


def latest_attention_notice_date(conn: sqlite3.Connection, market: str | None = None) -> str | None:
    dates: list[str] = []
    if market:
        row = conn.execute(
            "SELECT MAX(trade_date) AS trade_date FROM attention_notices WHERE market = ?",
            (market,),
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM attention_notices").fetchone()
    if row and row["trade_date"]:
        dates.append(row["trade_date"])

    params: list[str] = [DATASET_ATTENTION_NOTICE]
    where = "dataset = ? AND status IN ('OK', 'FIXED')"
    if market:
        where += " AND market = ?"
        params.append(market)
    rows = conn.execute(
        f"""
        SELECT period
        FROM import_batches
        WHERE {where}
        """,
        params,
    ).fetchall()
    dates.extend(
        period_end
        for row in rows
        if (period_end := _period_end(row["period"])) is not None
    )
    return max(dates) if dates else None


def query_attention_notices(
    conn: sqlite3.Connection,
    *,
    market: str | None = None,
    stock_id: str | None = None,
    trade_date: str | None = None,
    start: str | None = None,
    end: str | None = None,
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
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return conn.execute(
        f"""
        SELECT trade_date, market, stock_id, stock_name, notice_text
        FROM attention_notices
        {where}
        ORDER BY trade_date, market, stock_id
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
    raise ValueError(f"cannot decode attention notice CSV: {path}") from last_error


def _find_header_index(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        cleaned = {_clean_cell(cell) for cell in row}
        if {"證券代號", "證券名稱", "注意交易資訊"} <= cleaned and (
            "日期" in cleaned or "公告日期" in cleaned
        ):
            return index
    raise ValueError("attention notice CSV header not found")


def _header_mapping(header: list[str]) -> dict[str, int]:
    cleaned = [_clean_cell(cell) for cell in header]

    def find(name: str) -> int:
        try:
            return cleaned.index(name)
        except ValueError as exc:
            raise ValueError(f"attention notice CSV missing column: {name}") from exc

    date_column = "日期" if "日期" in cleaned else "公告日期"
    return {
        "trade_date": find(date_column),
        "stock_id": find("證券代號"),
        "stock_name": find("證券名稱"),
        "notice_text": find("注意交易資訊"),
    }


def _parse_row(row: list[str], mapping: dict[str, int], market: str) -> AttentionNoticeRow:
    trade_date = _normalize_notice_date(_get(row, mapping["trade_date"]))
    stock_id = _clean_stock_id(_get(row, mapping["stock_id"]))
    stock_name = _clean_cell(_get(row, mapping["stock_name"]))
    notice_text = _clean_cell(_get(row, mapping["notice_text"]))
    if not trade_date:
        raise ValueError("invalid notice date")
    if not stock_id:
        raise ValueError("blank stock_id")
    if not stock_name:
        raise ValueError("blank stock_name")
    if not notice_text:
        raise ValueError("blank notice_text")
    return AttentionNoticeRow(
        trade_date=trade_date,
        market=market,
        stock_id=stock_id,
        stock_name=stock_name,
        notice_text=notice_text,
    )


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
        start = _roc_parts_to_iso(parts[0], parts[1], parts[2])
        end = _roc_parts_to_iso(parts[3], parts[4], parts[5])
        dates.extend([start, end])
        break
    return dates


def _roc_parts_to_iso(roc_year: int, month: int, day: int) -> str:
    return date(roc_year + 1911, month, day).isoformat()


def _normalize_notice_date(value: str) -> str | None:
    return _normalize_date(_clean_cell(value).replace(".", "/"))


def _get(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _clean_cell(value: str) -> str:
    return str(value).strip().strip("\ufeff").strip()


def _is_blank_row(row: list[str]) -> bool:
    return not any(_clean_cell(cell) for cell in row)


def _is_data_row(row: list[str]) -> bool:
    return bool(row and _clean_cell(row[0]).isdigit())


def _is_no_notice_row(row: list[str], mapping: dict[str, int]) -> bool:
    notice_text = _clean_cell(_get(row, mapping["notice_text"])).replace(
        "\u516c\u4f48", "\u516c\u5e03"
    )
    return (
        _clean_stock_id(_get(row, mapping["stock_id"])) == ""
        and _clean_cell(_get(row, mapping["stock_name"])) == ""
        and notice_text.startswith("\u672c\u65e5\u7121\u516c\u5e03")
        and "\u6ce8\u610f" in notice_text
        and "\u8cc7\u8a0a" in notice_text
    )


def _is_metadata_row(row: list[str]) -> bool:
    first = _clean_cell(row[0]) if row else ""
    return first.startswith("\u7e3d\u7d2f\u8a08\u6b21\u6578") or first.startswith(
        "\u8b49\u5238\u500b\u6578"
    )


def _period_from_summary(summary: AttentionNoticeSummary, source_path: Path) -> str:
    if summary.first_date and summary.last_date:
        if summary.first_date == summary.last_date:
            return summary.first_date
        return f"{summary.first_date}..{summary.last_date}"
    return source_path.stem


def _summary_errors(summary: AttentionNoticeSummary) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if summary.skipped_rows:
        errors.append(
            ValidationError(
                "BLOCK",
                "ATTENTION_SKIPPED_ROWS",
                f"attention notice CSV has {summary.skipped_rows} unparsed rows",
            )
        )
    if summary.duplicate_keys:
        errors.append(
            ValidationError(
                "BLOCK",
                "DUPLICATE_ATTENTION_NOTICE",
                f"attention notice CSV has {summary.duplicate_keys} duplicate date/market/stock_id keys",
            )
        )
    if summary.row_count == 0 and summary.no_notice_rows == 0 and not (
        summary.first_date and summary.last_date
    ):
        errors.append(
            ValidationError(
                "BLOCK",
                "NO_ATTENTION_NOTICE_ROWS",
                "attention notice CSV contains no announcement rows or official no-notice rows",
            )
        )
    return errors


def _record_official_failure(
    conn: sqlite3.Connection,
    *,
    market: str,
    start: str,
    end: str,
    exc: Exception,
    raw: bytes | None,
    source_path: Path | None,
) -> AttentionNoticeImportResult:
    status = "MISSING" if raw is None else "BLOCKED"
    code = "DOWNLOAD_FAILED" if raw is None else "ATTENTION_IMPORT_FAILED"
    period = _period_from_dates(start, end)
    source_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
    batch_id = batch_status.record_batch(
        conn,
        dataset=DATASET_ATTENTION_NOTICE,
        market=market,
        period=period,
        status=status,
        row_count=None,
        errors=[ValidationError("BLOCK", code, str(exc))],
        source_file=str(source_path) if source_path else None,
        source_sha256=source_sha256,
        retry_count=0,
        note="official_download",
    )
    return AttentionNoticeImportResult(
        batch_id=batch_id,
        market=market,
        period=period,
        status=status,
        row_count=0,
        duplicate_keys=0,
        skipped_rows=0,
        no_notice_rows=0,
        metadata_rows=0,
        source_file=str(source_path) if source_path else "",
    )


def _replace_attention_notice_rows(
    conn: sqlite3.Connection,
    market: str,
    first_date: str | None,
    last_date: str | None,
    rows: list[AttentionNoticeRow],
) -> None:
    if first_date and last_date:
        conn.execute(
            """
            DELETE FROM attention_notices
            WHERE market = ? AND trade_date >= ? AND trade_date <= ?
            """,
            (market, first_date, last_date),
        )
    else:
        conn.execute("DELETE FROM attention_notices WHERE market = ?", (market,))
    conn.executemany(
        """
        INSERT INTO attention_notices(
          trade_date, market, stock_id, stock_name, notice_text
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (row.trade_date, row.market, row.stock_id, row.stock_name, row.notice_text)
            for row in rows
        ],
    )


def _summary_note(summary: AttentionNoticeSummary) -> str:
    parts = [
        f"encoding={summary.encoding}",
        f"no_notice_rows={summary.no_notice_rows}",
        f"metadata_rows={summary.metadata_rows}",
    ]
    if summary.skipped_rows:
        parts.append(f"skipped_rows={summary.skipped_rows}")
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
