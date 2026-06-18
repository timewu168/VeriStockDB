from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import csv
import hashlib
from pathlib import Path
import re
import sqlite3
import threading

import config
from ingest.downloader import (
    CooldownController,
    FetchMarginFile,
    LogFunc,
    download_margin_file,
    official_margin_file_path,
    save_official_margin_file,
)
from ingest.trading_calendar import trading_days_between, validate_iso_date


DATASET_MARGIN = config.DATASET_MARGIN
TWSE_MARGIN_START = '2001-01-02'
TPEX_MARGIN_START = '2006-01-02'


@dataclass(frozen=True)
class MarginDownloadResult:
    market: str
    trade_date: str
    status: str
    path: str | None
    bytes_written: int
    error: str | None = None


def download_margin_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchMarginFile = download_margin_file,
    cooldown: CooldownController | None = None,
    overwrite: bool = False,
    log: LogFunc | None = None,
) -> list[MarginDownloadResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f'margin start date is after end date: {start} > {end}')
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    open_dates = trading_days_between(conn, start, end)
    return download_margin_dates(
        open_dates,
        start=start,
        end=end,
        markets=selected_markets,
        fetcher=fetcher,
        cooldowns={market: cooldown for market in selected_markets},
        overwrite=overwrite,
        parallel_markets=False,
        log=log,
    )


def download_margin_dates(
    open_dates: list[str],
    *,
    start: str,
    end: str,
    markets: tuple[str, ...],
    fetcher: FetchMarginFile = download_margin_file,
    cooldowns: dict[str, CooldownController] | None = None,
    overwrite: bool = False,
    parallel_markets: bool = True,
    log: LogFunc | None = None,
) -> list[MarginDownloadResult]:
    if log:
        mode = 'parallel' if parallel_markets and len(markets) > 1 else 'serial'
        log(
            f'INFO margin download {start} -> {end} '
            f'open_days={len(open_dates)} markets={",".join(markets)} mode={mode}'
        )
    log_lock = threading.Lock()

    def locked_log(message: str) -> None:
        if log:
            with log_lock:
                log(message)

    if parallel_markets and len(markets) > 1:
        results: list[MarginDownloadResult] = []
        with ThreadPoolExecutor(max_workers=len(markets)) as executor:
            futures = [
                executor.submit(
                    _download_margin_market,
                    market,
                    open_dates,
                    fetcher,
                    (cooldowns or {}).get(market) or CooldownController(),
                    overwrite,
                    locked_log,
                )
                for market in markets
            ]
            for future in futures:
                results.extend(future.result())
        return sorted(results, key=lambda result: (result.trade_date, result.market))

    results: list[MarginDownloadResult] = []
    for market in markets:
        results.extend(
            _download_margin_market(
                market,
                open_dates,
                fetcher,
                (cooldowns or {}).get(market) or CooldownController(),
                overwrite,
                locked_log,
            )
        )
    return results


def _download_margin_market(
    market: str,
    open_dates: list[str],
    fetcher: FetchMarginFile,
    cooldown: CooldownController,
    overwrite: bool,
    log: LogFunc | None,
) -> list[MarginDownloadResult]:
    results: list[MarginDownloadResult] = []
    for trade_date in open_dates:
        try:
            _validate_margin_supported_date(market, trade_date)
            path = margin_file_path(market, trade_date)
            if path.exists() and path.stat().st_size > 0 and not overwrite:
                size = path.stat().st_size
                results.append(
                    MarginDownloadResult(
                        market=market,
                        trade_date=trade_date,
                        status='SKIP',
                        path=str(path),
                        bytes_written=size,
                    )
                )
                if log:
                    log(f'INFO {trade_date} {market} margin file exists {path} bytes={size}')
                continue
            cooldown.before_request(log)
            raw = fetcher(market, trade_date)
            _validate_margin_response(raw, market, trade_date)
            path = save_official_margin_file(raw, market, trade_date)
            results.append(
                MarginDownloadResult(
                    market=market,
                    trade_date=trade_date,
                    status='OK',
                    path=str(path),
                    bytes_written=len(raw),
                )
            )
            if log:
                log(f'INFO {trade_date} {market} margin file saved {path} bytes={len(raw)}')
        except Exception as exc:
            results.append(
                MarginDownloadResult(
                    market=market,
                    trade_date=trade_date,
                    status='MISSING',
                    path=None,
                    bytes_written=0,
                    error=str(exc),
                )
            )
            if log:
                log(f'ERROR {trade_date} {market} margin download failed: {exc}')
    return results


SMALL_FILE_BYTES = 4096
_MARGIN_FILE_RE = re.compile(r"^(?P<date>\d{8})Margin(?P<suffix>SII|OTC)\.csv$")
_ENCODING_CANDIDATES = ("utf-8-sig", "cp950", "big5")


@dataclass(frozen=True)
class MarginCsvInspection:
    market: str
    trade_date: str
    path: str
    status: str
    bytes_size: int
    encoding: str | None
    header_row_index: int | None
    column_count: int
    data_row_count: int
    metadata_row_count: int
    skipped_row_count: int
    invalid_numeric_count: int
    file_date: str | None
    header_signature: str | None
    header: tuple[str, ...]
    errors: tuple[str, ...]



MARGIN_CANONICAL_COLUMNS = (
    "trade_date",
    "market",
    "stock_id",
    "stock_name",
    "margin_buy",
    "margin_sell",
    "margin_cash_repay",
    "previous_margin_balance",
    "margin_balance",
    "margin_limit",
    "short_buy",
    "short_sell",
    "short_stock_repay",
    "previous_short_balance",
    "short_balance",
    "short_limit",
    "offsetting",
    "note",
)

TPEX_FORMAL_MARGIN_START = '2008-09-30'


@dataclass(frozen=True)
class MarginRecord:
    trade_date: str
    market: str
    stock_id: str
    stock_name: str
    margin_buy: int | None
    margin_sell: int | None
    margin_cash_repay: int | None
    previous_margin_balance: int | None
    margin_balance: int | None
    margin_limit: int | None
    short_buy: int | None
    short_sell: int | None
    short_stock_repay: int | None
    previous_short_balance: int | None
    short_balance: int | None
    short_limit: int | None
    offsetting: int | None
    note: str


@dataclass(frozen=True)
class MarginDryRunProblem:
    market: str
    trade_date: str
    stock_id: str | None
    problem: str
    detail: str
    path: str


@dataclass(frozen=True)
class MarginUpdateResult:
    market: str
    trade_date: str
    status: str
    row_count: int
    source_file: str | None
    error: str | None = None


@dataclass(frozen=True)
class MarginImportResult:
    market: str
    start: str
    end: str
    open_days: int
    row_count: int


@dataclass(frozen=True)
class MarginDryRunReport:
    summary_path: Path
    daily_counts_path: Path
    problems_path: Path
    expected_files: int
    parsed_files: int
    rows: int
    duplicate_keys: int
    problems: int
    missing_files: int
    bad_files: int
    null_required: int
    invalid_numeric: int
    date_coverage_gaps: int


@dataclass(frozen=True)
class MarginAuditReport:
    summary_path: Path
    formats_path: Path
    bad_files_path: Path
    expected_files: int
    actual_files: int
    ok_files: int
    bad_files: int
    suspicious_files: int
    missing_files: int
    empty_files: int
    extra_files: int



def inspect_margin_file(path: Path, market: str, trade_date: str) -> MarginCsvInspection:
    errors: list[str] = []
    size = path.stat().st_size if path.exists() else 0
    if not path.exists():
        return MarginCsvInspection(
            market=market,
            trade_date=trade_date,
            path=str(path),
            status="MISSING",
            bytes_size=0,
            encoding=None,
            header_row_index=None,
            column_count=0,
            data_row_count=0,
            metadata_row_count=0,
            skipped_row_count=0,
            invalid_numeric_count=0,
            file_date=None,
            header_signature=None,
            header=(),
            errors=("MISSING_FILE",),
        )
    if size == 0:
        errors.append("EMPTY_FILE")
    elif size < SMALL_FILE_BYTES:
        errors.append("SUSPICIOUS_SMALL_FILE")

    raw = path.read_bytes()
    text, encoding = _decode_margin_csv(raw)
    if text is None:
        errors.append("DECODE_ERROR")
        return MarginCsvInspection(
            market=market,
            trade_date=trade_date,
            path=str(path),
            status="BAD",
            bytes_size=size,
            encoding=None,
            header_row_index=None,
            column_count=0,
            data_row_count=0,
            metadata_row_count=0,
            skipped_row_count=0,
            invalid_numeric_count=0,
            file_date=None,
            header_signature=None,
            header=(),
            errors=tuple(errors),
        )
    lower_sample = text[:1024].lower()
    if "<html" in lower_sample or "<!doctype html" in lower_sample:
        errors.append("HTML_RESPONSE")
    if lower_sample.lstrip().startswith("{") or lower_sample.lstrip().startswith("["):
        errors.append("JSON_RESPONSE")

    rows = list(csv.reader(text.splitlines()))
    header_index = _find_margin_header_index(rows)
    file_date = _extract_margin_file_date(text)
    if file_date and file_date != trade_date:
        errors.append("FILE_DATE_MISMATCH")
    if header_index is None:
        errors.append("HEADER_NOT_FOUND")
        return MarginCsvInspection(
            market=market,
            trade_date=trade_date,
            path=str(path),
            status="BAD" if any(e != "SUSPICIOUS_SMALL_FILE" for e in errors) else "SUSPICIOUS",
            bytes_size=size,
            encoding=encoding,
            header_row_index=None,
            column_count=0,
            data_row_count=0,
            metadata_row_count=len(rows),
            skipped_row_count=0,
            invalid_numeric_count=0,
            file_date=file_date,
            header_signature=None,
            header=(),
            errors=tuple(errors),
        )

    header = tuple(_clean_cell(cell) for cell in rows[header_index])
    header_sig = _header_signature(header)
    data_rows = rows[header_index + 1 :]
    data_count = 0
    metadata_count = header_index
    skipped_count = 0
    invalid_numeric = 0
    numeric_indexes = _numeric_column_indexes(header)
    for row in data_rows:
        cleaned = [_clean_cell(cell) for cell in row]
        if not any(cleaned):
            metadata_count += 1
            continue
        if _is_margin_metadata_row(cleaned):
            metadata_count += 1
            continue
        if not _looks_like_stock_id(cleaned[0] if cleaned else ""):
            skipped_count += 1
            continue
        data_count += 1
        if len(cleaned) < max(2, len(header) - 2):
            skipped_count += 1
            errors.append("SHORT_DATA_ROW")
            continue
        for idx in numeric_indexes:
            if idx < len(cleaned) and not _is_parseable_margin_number(cleaned[idx]):
                invalid_numeric += 1
                if invalid_numeric <= 5:
                    errors.append("INVALID_NUMERIC")
                break
    if data_count == 0:
        errors.append("NO_DATA_ROWS")
    if skipped_count:
        errors.append("UNPARSED_ROWS")
    if invalid_numeric:
        errors.append("INVALID_NUMERIC_ROWS")
    status = "OK"
    blocking = {"EMPTY_FILE", "DECODE_ERROR", "HTML_RESPONSE", "JSON_RESPONSE", "HEADER_NOT_FOUND", "NO_DATA_ROWS", "FILE_DATE_MISMATCH"}
    if any(error in blocking for error in errors):
        status = "BAD"
    elif errors:
        status = "SUSPICIOUS"
    return MarginCsvInspection(
        market=market,
        trade_date=trade_date,
        path=str(path),
        status=status,
        bytes_size=size,
        encoding=encoding,
        header_row_index=header_index,
        column_count=len(header),
        data_row_count=data_count,
        metadata_row_count=metadata_count,
        skipped_row_count=skipped_count,
        invalid_numeric_count=invalid_numeric,
        file_date=file_date,
        header_signature=header_sig,
        header=header,
        errors=tuple(dict.fromkeys(errors)),
    )


def audit_margin_csvs(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> MarginAuditReport:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    selected_markets = markets or config.MARKETS
    report_root = Path(report_dir) if report_dir else config.ROOT_DIR / "reports"
    report_root.mkdir(parents=True, exist_ok=True)
    trading_rows = conn.execute(
        """
        SELECT trade_date, is_open
        FROM trading_days
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (start, end),
    ).fetchall()
    trading_status = {row["trade_date"]: int(row["is_open"]) for row in trading_rows}
    inspections: list[MarginCsvInspection] = []
    expected_keys: set[tuple[str, str]] = set()
    missing_count = 0
    empty_count = 0
    for market in selected_markets:
        market_start = max(start, TWSE_MARGIN_START if market == "TWSE" else TPEX_MARGIN_START)
        for trade_date, is_open_value in trading_status.items():
            if trade_date < market_start or not is_open_value:
                continue
            expected_keys.add((market, trade_date))
            path = margin_file_path(market, trade_date)
            inspection = inspect_margin_file(path, market, trade_date)
            inspections.append(inspection)
            if inspection.status == "MISSING":
                missing_count += 1
            if "EMPTY_FILE" in inspection.errors:
                empty_count += 1
            if log and len(inspections) % 1000 == 0:
                log(f"INFO inspected margin CSV files={len(inspections)}")

    extra_files = _find_extra_margin_files(selected_markets, expected_keys, trading_status, start, end)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = report_root / f"margin_csv_audit_{timestamp}.txt"
    formats_path = report_root / f"margin_csv_formats_{timestamp}.csv"
    bad_files_path = report_root / f"margin_csv_bad_files_{timestamp}.csv"
    _write_margin_summary(summary_path, inspections, extra_files, start, end, selected_markets)
    _write_margin_formats(formats_path, inspections)
    _write_margin_bad_files(bad_files_path, inspections, extra_files)
    ok_files = sum(1 for item in inspections if item.status == "OK")
    bad_files = sum(1 for item in inspections if item.status in {"BAD", "MISSING"})
    suspicious_files = sum(1 for item in inspections if item.status == "SUSPICIOUS")
    actual_files = len(inspections) - missing_count + len(extra_files)
    return MarginAuditReport(
        summary_path=summary_path,
        formats_path=formats_path,
        bad_files_path=bad_files_path,
        expected_files=len(expected_keys),
        actual_files=actual_files,
        ok_files=ok_files,
        bad_files=bad_files,
        suspicious_files=suspicious_files,
        missing_files=missing_count,
        empty_files=empty_count,
        extra_files=len(extra_files),
    )





def update_margin_day(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchMarginFile = download_margin_file,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> list[MarginUpdateResult]:
    trade_date = validate_iso_date(trade_date)
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    open_row = conn.execute(
        'SELECT is_open FROM trading_days WHERE trade_date = ?',
        (trade_date,),
    ).fetchone()
    if open_row is None:
        return [
            MarginUpdateResult(
                market=market,
                trade_date=trade_date,
                status='BLOCKED',
                row_count=0,
                source_file=None,
                error='trading day is missing from trading_days',
            )
            for market in selected_markets
        ]
    if int(open_row['is_open'] if isinstance(open_row, sqlite3.Row) else open_row[0]) != 1:
        return [
            MarginUpdateResult(
                market=market,
                trade_date=trade_date,
                status='CLOSED',
                row_count=0,
                source_file=None,
                error='not an open trading day',
            )
            for market in selected_markets
        ]

    results: list[MarginUpdateResult] = []
    for market in selected_markets:
        try:
            market_start = TWSE_MARGIN_START if market == 'TWSE' else TPEX_FORMAL_MARGIN_START
            if trade_date < market_start:
                results.append(
                    MarginUpdateResult(
                        market=market,
                        trade_date=trade_date,
                        status='CLOSED',
                        row_count=0,
                        source_file=None,
                        error=f'{market} margin canonical scope starts at {market_start}',
                    )
                )
                continue
            existing = margin_row_count(conn, market=market, trade_date=trade_date)
            if existing:
                results.append(
                    MarginUpdateResult(
                        market=market,
                        trade_date=trade_date,
                        status='EXISTS',
                        row_count=existing,
                        source_file=None,
                        error='margin rows already exist; not overwriting',
                    )
                )
                continue
            cooldown.before_request(log)
            raw = fetcher(market, trade_date)
            _validate_margin_response(raw, market, trade_date)
            path = save_official_margin_file(raw, market, trade_date)
            records, problems = parse_margin_file(path, market, trade_date)
            if problems:
                first = problems[0]
                raise ValueError(f'{first.problem} {first.detail}'.strip())
            _insert_margin_rows(conn, records)
            results.append(
                MarginUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status='OK',
                    row_count=len(records),
                    source_file=str(path),
                )
            )
        except Exception as exc:
            results.append(
                MarginUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status='BLOCKED',
                    row_count=0,
                    source_file=None,
                    error=str(exc),
                )
            )
    return results


def margin_row_count(
    conn: sqlite3.Connection,
    *,
    market: str | None = None,
    trade_date: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[str] = []
    if market is not None:
        clauses.append('market = ?')
        params.append(market)
    if trade_date is not None:
        clauses.append('trade_date = ?')
        params.append(validate_iso_date(trade_date))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    row = conn.execute(f'SELECT COUNT(*) FROM margin_trading{where}', params).fetchone()
    return int(row['COUNT(*)'] if isinstance(row, sqlite3.Row) else row[0])


def import_margin_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    twse_start: str = TWSE_MARGIN_START,
    tpex_start: str = TPEX_FORMAL_MARGIN_START,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> list[MarginImportResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    twse_start = validate_iso_date(twse_start)
    tpex_start = validate_iso_date(tpex_start)
    selected_markets = markets or config.MARKETS
    report = dry_run_margin_import(
        conn,
        start=start,
        end=end,
        markets=selected_markets,
        twse_start=twse_start,
        tpex_start=tpex_start,
        report_dir=report_dir,
        log=log,
    )
    if (
        report.problems
        or report.duplicate_keys
        or report.missing_files
        or report.bad_files
        or report.null_required
        or report.invalid_numeric
        or report.date_coverage_gaps
    ):
        raise ValueError(f'margin import blocked by dry-run problems: {report.summary_path}')

    dates_by_market = _formal_margin_dates_by_market(
        conn,
        start=start,
        end=end,
        markets=selected_markets,
        twse_start=twse_start,
        tpex_start=tpex_start,
    )
    _ensure_margin_target_scope_empty(conn, dates_by_market)

    import_results: list[MarginImportResult] = []
    for market in selected_markets:
        row_count = 0
        for trade_date in dates_by_market[market]:
            path = margin_file_path(market, trade_date)
            records, problems = parse_margin_file(path, market, trade_date)
            if problems:
                first = problems[0]
                raise ValueError(
                    f'margin import parse problem after dry-run OK: '
                    f'{first.trade_date} {first.market} {first.problem} {first.detail}'
                )
            _insert_margin_rows(conn, records)
            row_count += len(records)
            if log and row_count and row_count % 500000 < len(records):
                log(f'INFO imported margin rows market={market} rows={row_count}')
        import_results.append(
            MarginImportResult(
                market=market,
                start=start,
                end=end,
                open_days=len(dates_by_market[market]),
                row_count=row_count,
            )
        )
    return import_results


def _formal_margin_dates_by_market(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...],
    twse_start: str,
    tpex_start: str,
) -> dict[str, list[str]]:
    rows = conn.execute(
        """
        SELECT trade_date, is_open
        FROM trading_days
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (start, end),
    ).fetchall()
    dates: dict[str, list[str]] = {market: [] for market in markets}
    for market in markets:
        market_start = max(start, twse_start if market == 'TWSE' else tpex_start)
        for row in rows:
            trade_date = row['trade_date']
            if trade_date >= market_start and int(row['is_open']):
                dates[market].append(trade_date)
    return dates


def _ensure_margin_target_scope_empty(
    conn: sqlite3.Connection,
    dates_by_market: dict[str, list[str]],
) -> None:
    for market, dates in dates_by_market.items():
        if not dates:
            continue
        placeholders = ','.join('?' for _ in dates)
        row = conn.execute(
            f'SELECT COUNT(*) FROM margin_trading WHERE market = ? AND trade_date IN ({placeholders})',
            [market, *dates],
        ).fetchone()
        count = int(row['COUNT(*)'] if isinstance(row, sqlite3.Row) else row[0])
        if count:
            raise ValueError(
                f'margin target scope is not empty: rows={count} '
                f'market={market} dates={dates[0]}..{dates[-1]}'
            )


def _insert_margin_rows(conn: sqlite3.Connection, rows: list[MarginRecord]) -> None:
    sql = """
        INSERT INTO margin_trading (
          trade_date, market, stock_id, stock_name,
          margin_buy, margin_sell, margin_cash_repay,
          previous_margin_balance, margin_balance, margin_limit,
          short_buy, short_sell, short_stock_repay,
          previous_short_balance, short_balance, short_limit,
          offsetting, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(
        sql,
        [
            (
                row.trade_date,
                row.market,
                row.stock_id,
                row.stock_name,
                row.margin_buy,
                row.margin_sell,
                row.margin_cash_repay,
                row.previous_margin_balance,
                row.margin_balance,
                row.margin_limit,
                row.short_buy,
                row.short_sell,
                row.short_stock_repay,
                row.previous_short_balance,
                row.short_balance,
                row.short_limit,
                row.offsetting,
                row.note,
            )
            for row in rows
        ],
    )


def parse_margin_file(path: Path, market: str, trade_date: str) -> tuple[list[MarginRecord], list[MarginDryRunProblem]]:
    trade_date = validate_iso_date(trade_date)
    inspection = inspect_margin_file(path, market, trade_date)
    problems: list[MarginDryRunProblem] = []
    if inspection.status in {"BAD", "MISSING"}:
        problems.append(
            MarginDryRunProblem(
                market=market,
                trade_date=trade_date,
                stock_id=None,
                problem="BAD_SOURCE_FILE",
                detail=";".join(inspection.errors),
                path=str(path),
            )
        )
        return [], problems

    raw = path.read_bytes()
    text, _encoding = _decode_margin_csv(raw)
    if text is None:
        problems.append(MarginDryRunProblem(market, trade_date, None, "DECODE_ERROR", "", str(path)))
        return [], problems
    rows = list(csv.reader(text.splitlines()))
    header_index = _find_margin_header_index(rows)
    if header_index is None:
        problems.append(MarginDryRunProblem(market, trade_date, None, "HEADER_NOT_FOUND", "", str(path)))
        return [], problems
    header = tuple(_clean_cell(cell) for cell in rows[header_index])
    records: list[MarginRecord] = []
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        cleaned = [_clean_cell(cell) for cell in row]
        if not any(cleaned) or _is_margin_metadata_row(cleaned):
            continue
        if not cleaned or not _looks_like_stock_id(cleaned[0]):
            continue
        try:
            record = _map_margin_row(cleaned, header, market, trade_date)
        except ValueError as exc:
            stock_id = cleaned[0] if cleaned else None
            problems.append(
                MarginDryRunProblem(
                    market=market,
                    trade_date=trade_date,
                    stock_id=stock_id,
                    problem="ROW_PARSE_ERROR",
                    detail=f"row={row_number} {exc}",
                    path=str(path),
                )
            )
            continue
        records.append(record)
    if not records:
        problems.append(MarginDryRunProblem(market, trade_date, None, "NO_PARSED_ROWS", "", str(path)))
    return records, problems


def dry_run_margin_import(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    twse_start: str = TWSE_MARGIN_START,
    tpex_start: str = TPEX_FORMAL_MARGIN_START,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> MarginDryRunReport:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    twse_start = validate_iso_date(twse_start)
    tpex_start = validate_iso_date(tpex_start)
    if start > end:
        raise ValueError(f'margin dry-run start date is after end date: {start} > {end}')
    selected_markets = markets or config.MARKETS
    report_root = Path(report_dir) if report_dir else config.ROOT_DIR / "reports"
    report_root.mkdir(parents=True, exist_ok=True)
    trading_rows = conn.execute(
        """
        SELECT trade_date, is_open
        FROM trading_days
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (start, end),
    ).fetchall()
    trading_status = {row["trade_date"]: int(row["is_open"]) for row in trading_rows}

    records_by_day: dict[tuple[str, str], int] = defaultdict(int)
    problem_rows: list[MarginDryRunProblem] = []
    seen_keys: set[tuple[str, str, str]] = set()
    duplicate_keys = 0
    null_required = 0
    invalid_numeric = 0
    expected_files = 0
    parsed_files = 0
    missing_files = 0
    bad_files = 0
    total_rows = 0

    for market in selected_markets:
        market_start = max(start, twse_start if market == "TWSE" else tpex_start)
        for trade_date, is_open_value in trading_status.items():
            if trade_date < market_start or not is_open_value:
                continue
            expected_files += 1
            path = margin_file_path(market, trade_date)
            inspection = inspect_margin_file(path, market, trade_date)
            if inspection.status == "MISSING":
                missing_files += 1
                problem_rows.append(MarginDryRunProblem(market, trade_date, None, "MISSING_FILE", "", str(path)))
                continue
            if inspection.status == "BAD":
                bad_files += 1
                problem_rows.append(MarginDryRunProblem(market, trade_date, None, "BAD_SOURCE_FILE", ";".join(inspection.errors), str(path)))
                continue
            records, parse_problems = parse_margin_file(path, market, trade_date)
            problem_rows.extend(parse_problems)
            if parse_problems:
                bad_files += 1
            parsed_files += 1
            records_by_day[(market, trade_date)] = len(records)
            total_rows += len(records)
            for record in records:
                key = (record.trade_date, record.market, record.stock_id)
                if key in seen_keys:
                    duplicate_keys += 1
                    problem_rows.append(
                        MarginDryRunProblem(record.market, record.trade_date, record.stock_id, "DUPLICATE_KEY", "", str(path))
                    )
                seen_keys.add(key)
                if not record.trade_date or not record.market or not record.stock_id or not record.stock_name:
                    null_required += 1
                    problem_rows.append(
                        MarginDryRunProblem(record.market, record.trade_date, record.stock_id, "NULL_REQUIRED", "", str(path))
                    )
                numeric_values = (
                    record.margin_buy,
                    record.margin_sell,
                    record.margin_cash_repay,
                    record.previous_margin_balance,
                    record.margin_balance,
                    record.margin_limit,
                    record.short_buy,
                    record.short_sell,
                    record.short_stock_repay,
                    record.previous_short_balance,
                    record.short_balance,
                    record.short_limit,
                    record.offsetting,
                )
                if any(value is None for value in numeric_values):
                    invalid_numeric += 1
                    problem_rows.append(
                        MarginDryRunProblem(record.market, record.trade_date, record.stock_id, "INVALID_NUMERIC", "", str(path))
                    )
            if log and parsed_files % 1000 == 0:
                log(f"INFO dry-run parsed margin files={parsed_files} rows={total_rows}")

    date_coverage_gaps = sum(1 for count in records_by_day.values() if count == 0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = report_root / f"margin_import_dry_run_{timestamp}.txt"
    daily_counts_path = report_root / f"margin_import_daily_counts_{timestamp}.csv"
    problems_path = report_root / f"margin_import_problems_{timestamp}.csv"
    _write_margin_dry_run_summary(
        summary_path,
        start,
        end,
        selected_markets,
        twse_start,
        tpex_start,
        expected_files,
        parsed_files,
        total_rows,
        duplicate_keys,
        missing_files,
        bad_files,
        null_required,
        invalid_numeric,
        date_coverage_gaps,
        problem_rows,
    )
    _write_margin_daily_counts(daily_counts_path, records_by_day)
    _write_margin_dry_run_problems(problems_path, problem_rows)
    return MarginDryRunReport(
        summary_path=summary_path,
        daily_counts_path=daily_counts_path,
        problems_path=problems_path,
        expected_files=expected_files,
        parsed_files=parsed_files,
        rows=total_rows,
        duplicate_keys=duplicate_keys,
        problems=len(problem_rows),
        missing_files=missing_files,
        bad_files=bad_files,
        null_required=null_required,
        invalid_numeric=invalid_numeric,
        date_coverage_gaps=date_coverage_gaps,
    )


def margin_file_path(market: str, trade_date: str) -> Path:
    return official_margin_file_path(market, validate_iso_date(trade_date))



def _map_margin_row(row: list[str], header: tuple[str, ...], market: str, trade_date: str) -> MarginRecord:
    if market == "TWSE":
        if len(row) < 17:
            raise ValueError(f"TWSE row has {len(row)} columns, expected 17")
        return MarginRecord(
            trade_date=trade_date,
            market=market,
            stock_id=row[0],
            stock_name=row[1],
            margin_buy=_parse_margin_int(row[2]),
            margin_sell=_parse_margin_int(row[3]),
            margin_cash_repay=_parse_margin_int(row[4]),
            previous_margin_balance=_parse_margin_int(row[5]),
            margin_balance=_parse_margin_int(row[6]),
            margin_limit=_parse_margin_int(row[7]),
            short_buy=_parse_margin_int(row[8]),
            short_sell=_parse_margin_int(row[9]),
            short_stock_repay=_parse_margin_int(row[10]),
            previous_short_balance=_parse_margin_int(row[11]),
            short_balance=_parse_margin_int(row[12]),
            short_limit=_parse_margin_int(row[13]),
            offsetting=_parse_margin_int(row[14]),
            note=row[15] if len(row) > 15 else "",
        )
    if market == "TPEX":
        index = {name: idx for idx, name in enumerate(header)}
        def cell(name: str) -> str:
            idx = index.get(name)
            if idx is None or idx >= len(row):
                raise ValueError(f"missing TPEX column: {name}")
            return row[idx]
        return MarginRecord(
            trade_date=trade_date,
            market=market,
            stock_id=cell("代號"),
            stock_name=cell("名稱"),
            margin_buy=_parse_margin_int(cell("資買")),
            margin_sell=_parse_margin_int(cell("資賣")),
            margin_cash_repay=_parse_margin_int(cell("現償")),
            previous_margin_balance=_parse_margin_int(cell("前資餘額(張)")),
            margin_balance=_parse_margin_int(cell("資餘額")),
            margin_limit=_parse_margin_int(cell("資限額")),
            short_buy=_parse_margin_int(cell("券買")),
            short_sell=_parse_margin_int(cell("券賣")),
            short_stock_repay=_parse_margin_int(cell("券償")),
            previous_short_balance=_parse_margin_int(cell("前券餘額(張)")),
            short_balance=_parse_margin_int(cell("券餘額")),
            short_limit=_parse_margin_int(cell("券限額")),
            offsetting=_parse_margin_int(cell("資券相抵(張)")),
            note=cell("備註") if "備註" in index else "",
        )
    raise ValueError(f"unknown market: {market}")


def _parse_margin_int(value: str) -> int | None:
    cleaned = _clean_cell(value).replace(",", "")
    if cleaned in {"", "--", "-", "N/A", "NA", "X"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        try:
            number = float(cleaned)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
        return None


def _validate_margin_supported_date(market: str, trade_date: str) -> None:
    if market == 'TWSE':
        if trade_date < TWSE_MARGIN_START:
            raise ValueError(f'TWSE margin starts at {TWSE_MARGIN_START}')
        return
    if market == 'TPEX':
        if trade_date < TPEX_MARGIN_START:
            raise ValueError(f'TPEX margin starts at {TPEX_MARGIN_START}')
        return
    raise ValueError(f'unknown market: {market}')


def _validate_margin_response(raw: bytes, market: str, trade_date: str) -> None:
    if not raw or not raw.strip():
        raise ValueError(f'margin CSV is empty: {trade_date} {market}')
    sample = raw[:512].lower()
    if b'<html' in sample and b'<table' not in sample:
        raise ValueError(f'margin endpoint returned non-data HTML: {trade_date} {market}')



def _decode_margin_csv(raw: bytes) -> tuple[str | None, str | None]:
    for encoding in _ENCODING_CANDIDATES:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def _clean_cell(value: str) -> str:
    cleaned = value.replace("\ufeff", "").strip().strip('"').strip()
    if cleaned.startswith('="'):
        cleaned = cleaned[2:].strip().strip('"').strip()
    return cleaned


def _find_margin_header_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows[:20]):
        cleaned = [_clean_cell(cell) for cell in row]
        joined = "|".join(cleaned)
        if "股票代號" in joined:
            return index
        if "代號" in cleaned and ("名稱" in cleaned or any("融資" in cell or "融券" in cell for cell in cleaned)):
            return index
    return None


def _extract_margin_file_date(text: str) -> str | None:
    patterns = [
        r"(?P<roc>\d{2,3})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日",
        r"資料日期[:：](?P<roc>\d{2,3})/(?P<m>\d{1,2})/(?P<d>\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text[:1000])
        if match:
            year = int(match.group("roc")) + 1911
            return f"{year:04d}-{int(match.group('m')):02d}-{int(match.group('d')):02d}"
    return None


def _header_signature(header: tuple[str, ...]) -> str:
    normalized = "|".join(_clean_cell(cell) for cell in header)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _numeric_column_indexes(header: tuple[str, ...]) -> list[int]:
    indexes: list[int] = []
    for index, name in enumerate(header):
        if index == 0:
            continue
        if any(token in name for token in ("名稱", "備註", "註記", "代號", "股票")):
            continue
        indexes.append(index)
    return indexes


def _is_margin_metadata_row(row: list[str]) -> bool:
    first = row[0] if row else ""
    joined = "|".join(row)
    return (
        first.startswith("說明")
        or first.startswith("備註")
        or first.startswith("合計")
        or first.startswith("總計")
        or first.startswith("融資金")
        or first.startswith("共")
        or first.startswith("註")
        or first.startswith("符號說明")
        or first.startswith("限額")
        or first.startswith("融資、融券")
        or first.startswith("當日如有")
        or first.startswith("*****")
        or bool(re.match(r"^\(?\d+\)?[、.)]", first))
        or "資料日期" in joined
        or "信用交易統計" in joined
        or "融資融券彙總" in joined
    )


def _looks_like_stock_id(value: str) -> bool:
    value = value.strip()
    return bool(re.fullmatch(r"[0-9A-Z]{2,12}", value))


def _is_parseable_margin_number(value: str) -> bool:
    value = value.strip().replace(",", "")
    if value in {"", "--", "-", "N/A", "NA", "X"}:
        return True
    try:
        float(value)
        return True
    except ValueError:
        return False



def _write_margin_dry_run_summary(
    path: Path,
    start: str,
    end: str,
    markets: tuple[str, ...],
    twse_start: str,
    tpex_start: str,
    expected_files: int,
    parsed_files: int,
    rows: int,
    duplicate_keys: int,
    missing_files: int,
    bad_files: int,
    null_required: int,
    invalid_numeric: int,
    date_coverage_gaps: int,
    problems: list[MarginDryRunProblem],
) -> None:
    problem_counts: dict[str, int] = defaultdict(int)
    for problem in problems:
        problem_counts[problem.problem] += 1
    lines = [
        "Margin Import Dry Run",
        f"range={start}..{end}",
        f"markets={','.join(markets)}",
        f"twse_start={twse_start}",
        f"tpex_start={tpex_start}",
        f"canonical_key=trade_date,market,stock_id",
        f"canonical_columns={','.join(MARGIN_CANONICAL_COLUMNS)}",
        f"expected_files={expected_files}",
        f"parsed_files={parsed_files}",
        f"rows={rows}",
        f"duplicate_keys={duplicate_keys}",
        f"missing_files={missing_files}",
        f"bad_files={bad_files}",
        f"null_required={null_required}",
        f"invalid_numeric={invalid_numeric}",
        f"date_coverage_gaps={date_coverage_gaps}",
        f"problems={len(problems)}",
        "",
        "Problem Counts",
    ]
    for key in sorted(problem_counts):
        lines.append(f"  {key}: {problem_counts[key]}")
    lines.append("")
    lines.append("Sample Problems")
    for problem in problems[:50]:
        stock_id = problem.stock_id or "-"
        lines.append(f"  {problem.trade_date} {problem.market} {stock_id} {problem.problem} {problem.detail} path={problem.path}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_margin_daily_counts(path: Path, records_by_day: dict[tuple[str, str], int]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["market", "trade_date", "rows"])
        for (market, trade_date), rows in sorted(records_by_day.items(), key=lambda item: (item[0][0], item[0][1])):
            writer.writerow([market, trade_date, rows])


def _write_margin_dry_run_problems(path: Path, problems: list[MarginDryRunProblem]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["market", "trade_date", "stock_id", "problem", "detail", "path"])
        for problem in problems:
            writer.writerow([problem.market, problem.trade_date, problem.stock_id or "", problem.problem, problem.detail, problem.path])


def _find_extra_margin_files(
    markets: tuple[str, ...],
    expected_keys: set[tuple[str, str]],
    trading_status: dict[str, int],
    start: str,
    end: str,
) -> list[dict[str, str]]:
    suffix_market = {"SII": "TWSE", "OTC": "TPEX"}
    extras: list[dict[str, str]] = []
    for path in (config.CSV_DIR / "margin").glob("*/????????Margin*.csv"):
        match = _MARGIN_FILE_RE.match(path.name)
        if not match:
            continue
        market = suffix_market[match.group("suffix")]
        if market not in markets:
            continue
        raw_date = match.group("date")
        trade_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        if trade_date < start or trade_date > end:
            continue
        if (market, trade_date) in expected_keys:
            continue
        reason = "NON_TRADING_DAY"
        if trade_date not in trading_status:
            reason = "DATE_NOT_IN_TRADING_DAYS"
        elif trading_status[trade_date] == 1:
            reason = "OUTSIDE_MARKET_SUPPORTED_RANGE"
        extras.append({"market": market, "trade_date": trade_date, "path": str(path), "reason": reason})
    return sorted(extras, key=lambda item: (item["trade_date"], item["market"], item["path"]))


def _write_margin_summary(
    path: Path,
    inspections: list[MarginCsvInspection],
    extra_files: list[dict[str, str]],
    start: str,
    end: str,
    markets: tuple[str, ...],
) -> None:
    status_counts: dict[str, int] = defaultdict(int)
    error_counts: dict[str, int] = defaultdict(int)
    for item in inspections:
        status_counts[item.status] += 1
        for error in item.errors:
            error_counts[error] += 1
    lines = [
        "Margin CSV Audit",
        f"range={start}..{end}",
        f"markets={','.join(markets)}",
        f"expected_files={len(inspections)}",
        f"ok_files={status_counts['OK']}",
        f"suspicious_files={status_counts['SUSPICIOUS']}",
        f"bad_or_missing_files={status_counts['BAD'] + status_counts['MISSING']}",
        f"extra_files={len(extra_files)}",
        "",
        "Status Counts",
    ]
    for key in sorted(status_counts):
        lines.append(f"  {key}: {status_counts[key]}")
    lines.append("")
    lines.append("Error Counts")
    for key in sorted(error_counts):
        lines.append(f"  {key}: {error_counts[key]}")
    lines.append("")
    lines.append("Sample Problems")
    for item in [i for i in inspections if i.status != "OK"][:50]:
        lines.append(f"  {item.trade_date} {item.market} {item.status} bytes={item.bytes_size} errors={';'.join(item.errors)} path={item.path}")
    for item in extra_files[:50]:
        lines.append(f"  {item['trade_date']} {item['market']} EXTRA {item['reason']} path={item['path']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_margin_formats(path: Path, inspections: list[MarginCsvInspection]) -> None:
    groups: dict[tuple[str, str | None, int, tuple[str, ...]], list[MarginCsvInspection]] = defaultdict(list)
    for item in inspections:
        if item.header_signature:
            groups[(item.market, item.header_signature, item.column_count, item.header)].append(item)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["market", "start_date", "end_date", "files", "column_count", "header_signature", "row_count_min", "row_count_max", "sample_file", "header"])
        for (market, sig, col_count, header), items in sorted(groups.items(), key=lambda kv: (kv[0][0], min(i.trade_date for i in kv[1]))):
            dates = [item.trade_date for item in items]
            rows = [item.data_row_count for item in items]
            writer.writerow([market, min(dates), max(dates), len(items), col_count, sig, min(rows), max(rows), items[0].path, "|".join(header)])


def _write_margin_bad_files(path: Path, inspections: list[MarginCsvInspection], extra_files: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["market", "trade_date", "status", "bytes", "encoding", "header_row", "columns", "data_rows", "metadata_rows", "skipped_rows", "invalid_numeric", "file_date", "errors", "path"])
        for item in inspections:
            if item.status != "OK":
                writer.writerow([item.market, item.trade_date, item.status, item.bytes_size, item.encoding or "", item.header_row_index if item.header_row_index is not None else "", item.column_count, item.data_row_count, item.metadata_row_count, item.skipped_row_count, item.invalid_numeric_count, item.file_date or "", ";".join(item.errors), item.path])
        for item in extra_files:
            writer.writerow([item["market"], item["trade_date"], "EXTRA", "", "", "", "", "", "", "", "", "", item["reason"], item["path"]])
