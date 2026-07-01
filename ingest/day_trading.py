from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import csv
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import threading

import config
from ingest.downloader import (
    CooldownController,
    FetchDayTradingFile,
    LogFunc,
    download_day_trading_file,
    official_day_trading_file_path,
    save_official_day_trading_file,
)
from ingest.trading_calendar import trading_days_between, validate_iso_date


DATASET_DAY_TRADING = config.DATASET_DAY_TRADING
DAY_TRADING_START = "2014-01-06"
DAY_TRADING_NUMERIC_COLUMNS = (
    "當日沖銷交易成交股數",
    "當日沖銷交易買進成交金額",
    "當日沖銷交易賣出成交金額",
)
DAY_TRADING_KNOWN_NAME_FIXES = {
    ("2021-08-27", "TWSE", "911616"): "杜康-DR",
    ("2021-08-30", "TWSE", "911616"): "杜康-DR",
}


@dataclass(frozen=True)
class DayTradingDownloadResult:
    market: str
    trade_date: str
    status: str
    path: str | None
    bytes_written: int
    error: str | None = None


@dataclass(frozen=True)
class DayTradingCsvInspection:
    market: str
    trade_date: str
    path: str
    status: str
    encoding: str | None
    bytes_size: int
    header_index: int | None
    columns: tuple[str, ...]
    row_count: int
    sample_rows: tuple[tuple[str, ...], ...]
    error: str | None = None


@dataclass(frozen=True)
class DayTradingRecord:
    trade_date: str
    market: str
    stock_id: str
    stock_name: str
    suspend_sell_note: str | None
    day_trade_volume: int
    day_trade_buy_amount: int
    day_trade_sell_amount: int


@dataclass(frozen=True)
class DayTradingProblem:
    market: str
    trade_date: str
    stock_id: str | None
    problem: str
    detail: str
    path: str


@dataclass(frozen=True)
class DayTradingDryRunReport:
    start: str
    end: str
    expected_files: int
    parsed_files: int
    missing_files: int
    bad_files: int
    total_rows: int
    duplicate_keys: int
    problems: list[DayTradingProblem]
    summary_path: str | None = None


@dataclass(frozen=True)
class DayTradingImportResult:
    market: str
    start: str
    end: str
    open_days: int
    row_count: int


@dataclass(frozen=True)
class DayTradingUpdateResult:
    market: str
    trade_date: str
    status: str
    row_count: int
    source_file: str | None
    error: str | None = None


def download_day_trading_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchDayTradingFile = download_day_trading_file,
    cooldown: CooldownController | None = None,
    overwrite: bool = False,
    log: LogFunc | None = None,
    max_attempts: int = 3,
) -> list[DayTradingDownloadResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f"day-trading start date is after end date: {start} > {end}")
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    open_dates = trading_days_between(conn, start, end)
    return download_day_trading_dates(
        open_dates,
        start=start,
        end=end,
        markets=selected_markets,
        fetcher=fetcher,
        cooldowns={market: cooldown for market in selected_markets},
        overwrite=overwrite,
        parallel_markets=False,
        log=log,
        max_attempts=max_attempts,
    )


def download_day_trading_dates(
    open_dates: list[str],
    *,
    start: str,
    end: str,
    markets: tuple[str, ...],
    fetcher: FetchDayTradingFile = download_day_trading_file,
    cooldowns: dict[str, CooldownController] | None = None,
    overwrite: bool = False,
    parallel_markets: bool = True,
    log: LogFunc | None = None,
    max_attempts: int = 3,
) -> list[DayTradingDownloadResult]:
    if log:
        mode = "parallel" if parallel_markets and len(markets) > 1 else "serial"
        log(
            f"INFO day-trading download {start} -> {end} "
            f"open_days={len(open_dates)} markets={','.join(markets)} mode={mode}"
        )
    log_lock = threading.Lock()

    def locked_log(message: str) -> None:
        if log:
            with log_lock:
                log(message)

    if parallel_markets and len(markets) > 1:
        results: list[DayTradingDownloadResult] = []
        with ThreadPoolExecutor(max_workers=len(markets)) as executor:
            futures = [
                executor.submit(
                    _download_day_trading_market,
                    market,
                    open_dates,
                    fetcher,
                    (cooldowns or {}).get(market) or CooldownController(),
                    overwrite,
                    locked_log,
                    max_attempts,
                )
                for market in markets
            ]
            for future in futures:
                results.extend(future.result())
        return sorted(results, key=lambda result: (result.trade_date, result.market))

    results: list[DayTradingDownloadResult] = []
    for market in markets:
        results.extend(
            _download_day_trading_market(
                market,
                open_dates,
                fetcher,
                (cooldowns or {}).get(market) or CooldownController(),
                overwrite,
                locked_log,
                max_attempts,
            )
        )
    return results


def _download_day_trading_market(
    market: str,
    open_dates: list[str],
    fetcher: FetchDayTradingFile,
    cooldown: CooldownController,
    overwrite: bool,
    log: LogFunc | None,
    max_attempts: int = 3,
) -> list[DayTradingDownloadResult]:
    results: list[DayTradingDownloadResult] = []
    for trade_date in open_dates:
        try:
            _validate_day_trading_supported_date(trade_date)
            path = day_trading_file_path(market, trade_date)
            if path.exists() and path.stat().st_size > 0 and not overwrite:
                existing = path.read_bytes()
                try:
                    _validate_day_trading_response(existing, market, trade_date)
                    size = path.stat().st_size
                    results.append(
                        DayTradingDownloadResult(
                            market=market,
                            trade_date=trade_date,
                            status="SKIP",
                            path=str(path),
                            bytes_written=size,
                        )
                    )
                    if log:
                        log(f"INFO {trade_date} {market} day-trading file exists {path} bytes={size}")
                    continue
                except Exception as exc:
                    if log:
                        log(
                            f"WARN {trade_date} {market} existing day-trading file invalid; "
                            f"redownloading: {exc}"
                        )
        except Exception as exc:
            results.append(
                DayTradingDownloadResult(
                    market=market,
                    trade_date=trade_date,
                    status="MISSING",
                    path=None,
                    bytes_written=0,
                    error=str(exc),
                )
            )
            if log:
                log(f"ERROR {trade_date} {market} day-trading download unsupported: {exc}")
            continue

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                cooldown.before_request(log)
                raw = fetcher(market, trade_date)
                _validate_day_trading_response(raw, market, trade_date)
                path = save_official_day_trading_file(raw, market, trade_date)
                results.append(
                    DayTradingDownloadResult(
                        market=market,
                        trade_date=trade_date,
                        status="OK",
                        path=str(path),
                        bytes_written=len(raw),
                    )
                )
                if log:
                    log(
                        f"INFO {trade_date} {market} day-trading file saved {path} "
                        f"bytes={len(raw)} attempt={attempt}"
                    )
                break
            except Exception as exc:
                last_error = exc
                if log:
                    message = f"ERROR {trade_date} {market} day-trading attempt {attempt} failed: {exc}"
                    log(f"{message}; retrying" if attempt < max_attempts else message)
        else:
            results.append(
                DayTradingDownloadResult(
                    market=market,
                    trade_date=trade_date,
                    status="MISSING",
                    path=None,
                    bytes_written=0,
                    error=str(last_error) if last_error else "day-trading download failed",
                )
            )
    return results


def day_trading_file_path(market: str, trade_date: str) -> Path:
    return official_day_trading_file_path(market, validate_iso_date(trade_date))


def inspect_day_trading_file(
    path: Path,
    market: str,
    trade_date: str,
    *,
    sample_size: int = 3,
) -> DayTradingCsvInspection:
    trade_date = validate_iso_date(trade_date)
    if sample_size < 0:
        raise ValueError("sample_size must be >= 0")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return DayTradingCsvInspection(
            market=market,
            trade_date=trade_date,
            path=str(path),
            status="MISSING",
            encoding=None,
            bytes_size=0,
            header_index=None,
            columns=(),
            row_count=0,
            sample_rows=(),
            error="file not found",
        )

    text, encoding = _decode_day_trading_csv(raw)
    if text is None:
        return DayTradingCsvInspection(
            market=market,
            trade_date=trade_date,
            path=str(path),
            status="BAD",
            encoding=None,
            bytes_size=len(raw),
            header_index=None,
            columns=(),
            row_count=0,
            sample_rows=(),
            error="unable to decode CSV",
        )

    rows = [_clean_day_trading_row(row) for row in csv.reader(text.splitlines())]
    header_index = _find_day_trading_header_index(rows)
    if header_index is None:
        return DayTradingCsvInspection(
            market=market,
            trade_date=trade_date,
            path=str(path),
            status="BAD",
            encoding=encoding,
            bytes_size=len(raw),
            header_index=None,
            columns=(),
            row_count=0,
            sample_rows=(),
            error="header not found",
        )

    columns = tuple(rows[header_index])
    data_rows: list[tuple[str, ...]] = []
    for row in rows[header_index + 1:]:
        if not any(row):
            continue
        if _is_day_trading_metadata_row(row):
            continue
        if not row[0].isdigit():
            continue
        data_rows.append(tuple(row[: len(columns)]))

    return DayTradingCsvInspection(
        market=market,
        trade_date=trade_date,
        path=str(path),
        status="OK",
        encoding=encoding,
        bytes_size=len(raw),
        header_index=header_index,
        columns=columns,
        row_count=len(data_rows),
        sample_rows=tuple(data_rows[:sample_size]),
    )


def dry_run_day_trading_import(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> DayTradingDryRunReport:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f"day-trading dry-run start date is after end date: {start} > {end}")
    selected_markets = markets or config.MARKETS
    dates_by_market = _day_trading_dates_by_market(conn, start=start, end=end, markets=selected_markets)
    report_root = Path(report_dir) if report_dir else config.ROOT_DIR / "reports"
    report_root.mkdir(parents=True, exist_ok=True)

    expected_files = 0
    parsed_files = 0
    missing_files = 0
    bad_files = 0
    total_rows = 0
    duplicate_keys = 0
    problems: list[DayTradingProblem] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for market in selected_markets:
        for trade_date in dates_by_market[market]:
            expected_files += 1
            path = day_trading_file_path(market, trade_date)
            inspection = inspect_day_trading_file(path, market, trade_date)
            if inspection.status == "MISSING":
                missing_files += 1
                problems.append(DayTradingProblem(market, trade_date, None, "MISSING_FILE", "", str(path)))
                continue
            if inspection.status == "BAD":
                bad_files += 1
                problems.append(DayTradingProblem(market, trade_date, None, "BAD_SOURCE_FILE", inspection.error or "", str(path)))
                continue
            records, parse_problems = parse_day_trading_file(path, market, trade_date)
            parsed_files += 1
            total_rows += len(records)
            problems.extend(parse_problems)
            if parse_problems:
                bad_files += 1
            for record in records:
                key = (record.trade_date, record.market, record.stock_id)
                if key in seen_keys:
                    duplicate_keys += 1
                    problems.append(
                        DayTradingProblem(
                            record.market,
                            record.trade_date,
                            record.stock_id,
                            "DUPLICATE_KEY",
                            "",
                            str(path),
                        )
                    )
                seen_keys.add(key)
            if log and parsed_files % 1000 == 0:
                log(f"INFO dry-run parsed day-trading files={parsed_files} rows={total_rows}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = report_root / f"day_trading_import_dry_run_{timestamp}.txt"
    problems_path = report_root / f"day_trading_import_problems_{timestamp}.csv"
    _write_day_trading_dry_run_summary(
        summary_path,
        start=start,
        end=end,
        expected_files=expected_files,
        parsed_files=parsed_files,
        missing_files=missing_files,
        bad_files=bad_files,
        total_rows=total_rows,
        duplicate_keys=duplicate_keys,
        problems=problems,
    )
    _write_day_trading_problems(problems_path, problems)
    return DayTradingDryRunReport(
        start=start,
        end=end,
        expected_files=expected_files,
        parsed_files=parsed_files,
        missing_files=missing_files,
        bad_files=bad_files,
        total_rows=total_rows,
        duplicate_keys=duplicate_keys,
        problems=problems,
        summary_path=str(summary_path),
    )


def import_day_trading_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> list[DayTradingImportResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    selected_markets = markets or config.MARKETS
    report = dry_run_day_trading_import(
        conn,
        start=start,
        end=end,
        markets=selected_markets,
        report_dir=report_dir,
        log=log,
    )
    if report.problems or report.duplicate_keys or report.missing_files or report.bad_files:
        raise ValueError(f"day-trading import blocked by dry-run problems: {report.summary_path}")

    dates_by_market = _day_trading_dates_by_market(conn, start=start, end=end, markets=selected_markets)
    _ensure_day_trading_target_scope_empty(conn, dates_by_market)
    results: list[DayTradingImportResult] = []
    for market in selected_markets:
        row_count = 0
        for trade_date in dates_by_market[market]:
            records, problems = parse_day_trading_file(day_trading_file_path(market, trade_date), market, trade_date)
            if problems:
                first = problems[0]
                raise ValueError(
                    f"day-trading import parse problem after dry-run OK: "
                    f"{first.trade_date} {first.market} {first.problem} {first.detail}"
                )
            _insert_day_trading_rows(conn, records)
            row_count += len(records)
            if log and row_count and row_count % 500000 < len(records):
                log(f"INFO imported day-trading rows market={market} rows={row_count}")
        results.append(
            DayTradingImportResult(
                market=market,
                start=start,
                end=end,
                open_days=len(dates_by_market[market]),
                row_count=row_count,
            )
        )
    return results


def update_day_trading_day(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchDayTradingFile = download_day_trading_file,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    max_attempts: int = 3,
) -> list[DayTradingUpdateResult]:
    trade_date = validate_iso_date(trade_date)
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    open_row = conn.execute(
        "SELECT is_open FROM trading_days WHERE trade_date = ?",
        (trade_date,),
    ).fetchone()
    if open_row is None:
        return [
            DayTradingUpdateResult(
                market=market,
                trade_date=trade_date,
                status="BLOCKED",
                row_count=0,
                source_file=None,
                error="trading day is missing from trading_days",
            )
            for market in selected_markets
        ]
    if int(open_row["is_open"] if hasattr(open_row, "keys") else open_row[0]) != 1:
        return [
            DayTradingUpdateResult(
                market=market,
                trade_date=trade_date,
                status="CLOSED",
                row_count=0,
                source_file=None,
                error="not an open trading day",
            )
            for market in selected_markets
        ]

    results: list[DayTradingUpdateResult] = []
    for market in selected_markets:
        try:
            if trade_date < DAY_TRADING_START:
                results.append(
                    DayTradingUpdateResult(
                        market=market,
                        trade_date=trade_date,
                        status="CLOSED",
                        row_count=0,
                        source_file=None,
                        error=f"day-trading starts at {DAY_TRADING_START}",
                    )
                )
                continue
            existing = day_trading_row_count(conn, market=market, trade_date=trade_date)
            if existing:
                results.append(
                    DayTradingUpdateResult(
                        market=market,
                        trade_date=trade_date,
                        status="EXISTS",
                        row_count=existing,
                        source_file=None,
                        error="day-trading rows already exist; not overwriting",
                    )
                )
                continue
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    cooldown.before_request(log)
                    raw = fetcher(market, trade_date)
                    _validate_day_trading_response(raw, market, trade_date)
                    path = save_official_day_trading_file(raw, market, trade_date)
                    records, problems = parse_day_trading_file(path, market, trade_date)
                    if problems:
                        first = problems[0]
                        raise ValueError(f"{first.problem} {first.detail}".strip())
                    _insert_day_trading_rows(conn, records)
                    results.append(
                        DayTradingUpdateResult(
                            market=market,
                            trade_date=trade_date,
                            status="OK",
                            row_count=len(records),
                            source_file=str(path),
                        )
                    )
                    if log:
                        log(f"INFO {trade_date} {market} day-trading update attempt {attempt} OK")
                    break
                except Exception as exc:
                    last_error = exc
                    if log:
                        message = f"ERROR {trade_date} {market} day-trading update attempt {attempt} failed: {exc}"
                        log(f"{message}; retrying" if attempt < max_attempts else message)
            else:
                results.append(
                    DayTradingUpdateResult(
                        market=market,
                        trade_date=trade_date,
                        status="BLOCKED",
                        row_count=0,
                        source_file=None,
                        error=str(last_error) if last_error else "day-trading update failed",
                    )
                )
        except Exception as exc:
            results.append(
                DayTradingUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status="BLOCKED",
                    row_count=0,
                    source_file=None,
                    error=str(exc),
                )
            )
    return results


def day_trading_row_count(
    conn: sqlite3.Connection,
    *,
    market: str | None = None,
    trade_date: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[str] = []
    if market is not None:
        clauses.append("market = ?")
        params.append(market)
    if trade_date is not None:
        clauses.append("trade_date = ?")
        params.append(validate_iso_date(trade_date))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) FROM day_trading{where}", params).fetchone()
    return int(row["COUNT(*)"] if hasattr(row, "keys") else row[0])


def parse_day_trading_file(path: Path, market: str, trade_date: str) -> tuple[list[DayTradingRecord], list[DayTradingProblem]]:
    trade_date = validate_iso_date(trade_date)
    inspection = inspect_day_trading_file(path, market, trade_date)
    problems: list[DayTradingProblem] = []
    if inspection.status in {"BAD", "MISSING"}:
        problems.append(
            DayTradingProblem(market, trade_date, None, "BAD_SOURCE_FILE", inspection.error or "", str(path))
        )
        return [], problems
    raw = path.read_bytes()
    try:
        _validate_day_trading_response(raw, market, trade_date)
    except Exception as exc:
        problems.append(DayTradingProblem(market, trade_date, None, "BAD_SOURCE_FILE", str(exc), str(path)))
        return [], problems
    text, _encoding = _decode_day_trading_csv(raw)
    if text is None:
        problems.append(DayTradingProblem(market, trade_date, None, "DECODE_ERROR", "", str(path)))
        return [], problems
    rows = [_clean_day_trading_row(row) for row in csv.reader(text.splitlines())]
    header_index = _find_day_trading_header_index(rows)
    if header_index is None:
        problems.append(DayTradingProblem(market, trade_date, None, "HEADER_NOT_FOUND", "", str(path)))
        return [], problems
    header = rows[header_index]
    records: list[DayTradingRecord] = []
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(row) or _is_day_trading_metadata_row(row):
            continue
        if not row or not _looks_like_stock_id(row[0]):
            continue
        try:
            records.append(_map_day_trading_row(row, header, market, trade_date))
        except ValueError as exc:
            problems.append(
                DayTradingProblem(
                    market,
                    trade_date,
                    row[0] if row else None,
                    "ROW_PARSE_ERROR",
                    f"row={row_number} {exc}",
                    str(path),
                )
            )
    if not records:
        problems.append(DayTradingProblem(market, trade_date, None, "NO_PARSED_ROWS", "", str(path)))
    return records, problems


def _map_day_trading_row(
    row: list[str],
    header: list[str],
    market: str,
    trade_date: str,
) -> DayTradingRecord:
    if len(row) != len(header):
        raise ValueError(f"column count {len(row)} != header {len(header)}")
    values = dict(zip(header, row))
    stock_id = values.get("證券代號", "").strip()
    stock_name = values.get("證券名稱", "").strip()
    if not _looks_like_stock_id(stock_id):
        raise ValueError(f"suspicious stock id: {stock_id}")
    if not stock_name:
        stock_name = DAY_TRADING_KNOWN_NAME_FIXES.get((trade_date, market, stock_id), "")
    if not stock_name:
        raise ValueError("stock_name is blank")
    suspend_sell_note = values.get("暫停現股賣出後現款買進當沖註記")
    suspend_sell_note = suspend_sell_note.strip() if suspend_sell_note is not None else None
    if suspend_sell_note == "":
        suspend_sell_note = None
    return DayTradingRecord(
        trade_date=trade_date,
        market=market,
        stock_id=stock_id,
        stock_name=stock_name,
        suspend_sell_note=suspend_sell_note,
        day_trade_volume=_parse_day_trading_int(values.get("當日沖銷交易成交股數", "")),
        day_trade_buy_amount=_parse_day_trading_int(values.get("當日沖銷交易買進成交金額", "")),
        day_trade_sell_amount=_parse_day_trading_int(values.get("當日沖銷交易賣出成交金額", "")),
    )


def _parse_day_trading_int(value: str) -> int:
    cleaned = value.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", cleaned):
        raise ValueError(f"invalid integer: {value!r}")
    return int(cleaned)


def _looks_like_stock_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{4,8}", value.strip()))


def _day_trading_dates_by_market(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...],
) -> dict[str, list[str]]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (start, end),
    ).fetchall()
    open_dates = [row["trade_date"] if hasattr(row, "keys") else row[0] for row in rows]
    return {market: [trade_date for trade_date in open_dates if trade_date >= DAY_TRADING_START] for market in markets}


def _ensure_day_trading_target_scope_empty(
    conn: sqlite3.Connection,
    dates_by_market: dict[str, list[str]],
) -> None:
    for market, dates in dates_by_market.items():
        if not dates:
            continue
        placeholders = ",".join("?" for _ in dates)
        row = conn.execute(
            f"SELECT COUNT(*) FROM day_trading WHERE market = ? AND trade_date IN ({placeholders})",
            [market, *dates],
        ).fetchone()
        count = int(row["COUNT(*)"] if hasattr(row, "keys") else row[0])
        if count:
            raise ValueError(
                f"day-trading target scope is not empty: rows={count} "
                f"market={market} dates={dates[0]}..{dates[-1]}"
            )


def _insert_day_trading_rows(conn: sqlite3.Connection, rows: list[DayTradingRecord]) -> None:
    conn.executemany(
        """
        INSERT INTO day_trading (
          trade_date, market, stock_id, stock_name, suspend_sell_note,
          day_trade_volume, day_trade_buy_amount, day_trade_sell_amount
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.trade_date,
                row.market,
                row.stock_id,
                row.stock_name,
                row.suspend_sell_note,
                row.day_trade_volume,
                row.day_trade_buy_amount,
                row.day_trade_sell_amount,
            )
            for row in rows
        ],
    )


def _write_day_trading_dry_run_summary(path: Path, **values) -> None:
    problems = values.pop("problems")
    lines = [f"{key}={value}" for key, value in values.items()]
    lines.append(f"problem_count={len(problems)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_day_trading_problems(path: Path, problems: list[DayTradingProblem]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["market", "trade_date", "stock_id", "problem", "detail", "path"])
        for problem in problems:
            writer.writerow(
                [
                    problem.market,
                    problem.trade_date,
                    problem.stock_id or "",
                    problem.problem,
                    problem.detail,
                    problem.path,
                ]
            )


def _validate_day_trading_supported_date(trade_date: str) -> None:
    if validate_iso_date(trade_date) < DAY_TRADING_START:
        raise ValueError(f"day-trading starts at {DAY_TRADING_START}")


def _validate_day_trading_response(raw: bytes, market: str, trade_date: str) -> None:
    if not raw:
        raise ValueError(f"day-trading CSV is empty: {trade_date} {market}")
    sample = raw[:512].decode("utf-8", errors="ignore").lower()
    if "<html" in sample or "<!doctype html" in sample:
        raise ValueError(f"day-trading endpoint returned non-data HTML: {trade_date} {market}")
    text, _encoding = _decode_day_trading_csv(raw)
    if text is None:
        raise ValueError(f"day-trading CSV cannot be decoded: {trade_date} {market}")
    csv_date = _extract_day_trading_csv_date(text)
    if csv_date is None:
        raise ValueError(f"day-trading CSV date not found: {trade_date} {market}")
    if csv_date != trade_date:
        raise ValueError(
            f"day-trading CSV date mismatch: expected {trade_date} {market}, got {csv_date}"
        )


def _decode_day_trading_csv(raw: bytes) -> tuple[str | None, str | None]:
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def _extract_day_trading_csv_date(text: str) -> str | None:
    for line in text.splitlines()[:12]:
        date = _parse_day_trading_date_text(line)
        if date is not None:
            return date
    return None


def _parse_day_trading_date_text(text: str) -> str | None:
    roc_match = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if roc_match:
        year = int(roc_match.group(1)) + 1911
        month = int(roc_match.group(2))
        day = int(roc_match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    roc_slash_match = re.search(r"(?<!\d)(\d{2,3})/(\d{1,2})/(\d{1,2})(?!\d)", text)
    if roc_slash_match:
        year = int(roc_slash_match.group(1)) + 1911
        month = int(roc_slash_match.group(2))
        day = int(roc_slash_match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    western_match = re.search(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
    if western_match:
        year = int(western_match.group(1))
        month = int(western_match.group(2))
        day = int(western_match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    compact_match = re.search(r"(?<!\d)(20\d{6})(?!\d)", text)
    if compact_match:
        compact = compact_match.group(1)
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"

    return None


def _clean_day_trading_row(row: list[str]) -> list[str]:
    cleaned = [cell.strip().replace("\ufeff", "") for cell in row]
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


def _find_day_trading_header_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows):
        if "證券代號" in row and "證券名稱" in row:
            return index
    return None


def _is_day_trading_metadata_row(row: list[str]) -> bool:
    first = row[0] if row else ""
    return (
        first.startswith("備註")
        or "當日沖銷交易統計資訊" in first
        or "當日沖銷交易標的及成交量值" in first
    )
