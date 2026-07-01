from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import csv
from datetime import date, datetime
from pathlib import Path
import re
import sqlite3
import threading

import config
from ingest.downloader import (
    CooldownController,
    FetchRevenueCsv,
    LogFunc,
    download_revenue_csv,
    official_revenue_csv_path,
    save_official_revenue_csv,
)


REVENUE_START_MONTH = "2013-01"
REVENUE_PUBLIC_DAY = 10
REVENUE_REQUIRED_COLUMNS = (
    "出表日期",
    "資料年月",
    "公司代號",
    "公司名稱",
    "產業別",
    "營業收入-當月營收",
)
REVENUE_COLUMN_MAP = {
    "出表日期": "report_date",
    "資料年月": "roc_period",
    "公司代號": "stock_id",
    "公司名稱": "stock_name",
    "產業別": "industry",
    "營業收入-當月營收": "current_month_revenue",
    "營業收入-上月營收": "previous_month_revenue",
    "營業收入-去年當月營收": "previous_year_month_revenue",
    "營業收入-上月比較增減(%)": "month_over_month_pct",
    "營業收入-去年同月增減(%)": "year_over_year_pct",
    "累計營業收入-當月累計營收": "cumulative_revenue",
    "累計營業收入-去年累計營收": "previous_year_cumulative_revenue",
    "累計營業收入-前期比較增減(%)": "cumulative_growth_pct",
    "備註": "note",
}


@dataclass(frozen=True)
class RevenueRecord:
    revenue_month: str
    market: str
    stock_id: str
    stock_name: str
    industry: str
    report_date: str
    roc_period: str
    current_month_revenue: int
    previous_month_revenue: int
    previous_year_month_revenue: int
    month_over_month_pct: float | None
    year_over_year_pct: float | None
    cumulative_revenue: int
    previous_year_cumulative_revenue: int
    cumulative_growth_pct: float | None
    note: str


@dataclass(frozen=True)
class RevenueProblem:
    market: str
    revenue_month: str
    stock_id: str | None
    problem: str
    detail: str
    path: str


@dataclass(frozen=True)
class RevenueDryRunReport:
    start: str
    end: str
    expected_files: int
    parsed_files: int
    missing_files: int
    bad_files: int
    total_rows: int
    duplicate_keys: int
    problems: list[RevenueProblem]
    summary_path: str | None = None


@dataclass(frozen=True)
class RevenueImportResult:
    market: str
    start: str
    end: str
    months: int
    row_count: int


@dataclass(frozen=True)
class RevenueUpdateResult:
    market: str
    revenue_month: str
    status: str
    row_count: int
    source_file: str | None
    error: str | None = None


@dataclass(frozen=True)
class RevenueDownloadResult:
    market: str
    month: str
    status: str
    path: str | None
    bytes_written: int
    error: str | None = None


def latest_published_revenue_month(today: date | None = None) -> str:
    today = today or date.today()
    year = today.year
    month = today.month - 1 if today.day >= REVENUE_PUBLIC_DAY else today.month - 2
    while month <= 0:
        year -= 1
        month += 12
    return f"{year:04d}-{month:02d}"


def revenue_month_to_roc_month(month: str) -> str:
    year, month_number = _validate_month(month)
    return f"{year - 1911}_{month_number}"


def revenue_months_between(start: str, end: str) -> list[str]:
    start_year, start_month = _validate_month(start)
    end_year, end_month = _validate_month(end)
    if (start_year, start_month) > (end_year, end_month):
        raise ValueError(f"revenue start month is after end month: {start} > {end}")
    months: list[str] = []
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def download_revenue_months(
    months: list[str],
    *,
    markets: tuple[str, ...],
    fetcher: FetchRevenueCsv = download_revenue_csv,
    cooldowns: dict[str, CooldownController] | None = None,
    overwrite: bool = False,
    parallel_markets: bool = True,
    log: LogFunc | None = None,
    max_attempts: int = 3,
) -> list[RevenueDownloadResult]:
    if log:
        mode = "parallel" if parallel_markets and len(markets) > 1 else "serial"
        log(f"INFO revenue download months={len(months)} markets={','.join(markets)} mode={mode}")
    log_lock = threading.Lock()

    def locked_log(message: str) -> None:
        if log:
            with log_lock:
                log(message)

    if parallel_markets and len(markets) > 1:
        results: list[RevenueDownloadResult] = []
        with ThreadPoolExecutor(max_workers=len(markets)) as executor:
            futures = [
                executor.submit(
                    _download_revenue_market,
                    market,
                    months,
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
        return sorted(results, key=lambda result: (result.month, result.market))

    results: list[RevenueDownloadResult] = []
    for market in markets:
        results.extend(
            _download_revenue_market(
                market,
                months,
                fetcher,
                (cooldowns or {}).get(market) or CooldownController(),
                overwrite,
                locked_log,
                max_attempts,
            )
        )
    return results


def revenue_file_path(market: str, month: str) -> Path:
    _validate_month(month)
    return official_revenue_csv_path(market, month)


def parse_revenue_file(path: Path | str, market: str, month: str) -> tuple[list[RevenueRecord], list[RevenueProblem]]:
    path = Path(path)
    problems: list[RevenueProblem] = []
    try:
        raw = path.read_bytes()
        _validate_revenue_response(raw, market, month)
    except Exception as exc:
        return [], [RevenueProblem(market, month, None, "BAD_SOURCE_FILE", str(exc), str(path))]

    text, _encoding = _decode_revenue_csv(raw)
    if text is None:
        return [], [RevenueProblem(market, month, None, "DECODE_ERROR", "", str(path))]

    rows = [_clean_revenue_row(row) for row in csv.reader(text.splitlines())]
    rows = [row for row in rows if any(row)]
    if not rows:
        return [], [RevenueProblem(market, month, None, "NO_ROWS", "", str(path))]

    header = rows[0]
    indexes = {column: header.index(column) for column in REVENUE_COLUMN_MAP}
    records: list[RevenueRecord] = []
    expected_roc_period = _month_to_roc_period(month)

    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) == len(header) - 1 and header[-1] == "備註":
            row = [*row, ""]
        if len(row) < len(header):
            problems.append(
                RevenueProblem(market, month, None, "SHORT_ROW", f"line={line_no} columns={len(row)} expected={len(header)}", str(path))
            )
            continue
        stock_id = row[indexes["公司代號"]].strip()
        stock_name = row[indexes["公司名稱"]].strip()
        industry = row[indexes["產業別"]].strip()
        report_date_raw = row[indexes["出表日期"]].strip()
        roc_period = row[indexes["資料年月"]].strip()
        if not stock_id or not stock_name:
            problems.append(
                RevenueProblem(market, month, stock_id or None, "BLANK_STOCK", f"line={line_no}", str(path))
            )
            continue
        if roc_period != expected_roc_period:
            problems.append(
                RevenueProblem(
                    market,
                    month,
                    stock_id,
                    "MONTH_MISMATCH",
                    f"line={line_no} expected={expected_roc_period} got={roc_period}",
                    str(path),
                )
            )
            continue
        try:
            record = RevenueRecord(
                revenue_month=month,
                market=market,
                stock_id=stock_id,
                stock_name=stock_name,
                industry=industry,
                report_date=_roc_date_to_iso(report_date_raw),
                roc_period=roc_period,
                current_month_revenue=_parse_revenue_int(row[indexes["營業收入-當月營收"]]),
                previous_month_revenue=_parse_revenue_int(row[indexes["營業收入-上月營收"]]),
                previous_year_month_revenue=_parse_revenue_int(row[indexes["營業收入-去年當月營收"]]),
                month_over_month_pct=_parse_revenue_float(row[indexes["營業收入-上月比較增減(%)"]]),
                year_over_year_pct=_parse_revenue_float(row[indexes["營業收入-去年同月增減(%)"]]),
                cumulative_revenue=_parse_revenue_int(row[indexes["累計營業收入-當月累計營收"]]),
                previous_year_cumulative_revenue=_parse_revenue_int(row[indexes["累計營業收入-去年累計營收"]]),
                cumulative_growth_pct=_parse_revenue_float(row[indexes["累計營業收入-前期比較增減(%)"]]),
                note=row[indexes["備註"]].strip(),
            )
        except Exception as exc:
            problems.append(
                RevenueProblem(market, month, stock_id, "PARSE_ERROR", f"line={line_no} {exc}", str(path))
            )
            continue
        records.append(record)
    return records, problems


def dry_run_revenue_import(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> RevenueDryRunReport:
    months = revenue_months_between(start, end)
    selected_markets = markets or config.MARKETS
    report_root = Path(report_dir) if report_dir else config.ROOT_DIR / "reports"
    report_root.mkdir(parents=True, exist_ok=True)

    expected_files = 0
    parsed_files = 0
    missing_files = 0
    bad_files = 0
    total_rows = 0
    duplicate_keys = 0
    problems: list[RevenueProblem] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for month in months:
        for market in selected_markets:
            expected_files += 1
            path = revenue_file_path(market, month)
            if not path.exists():
                missing_files += 1
                problems.append(RevenueProblem(market, month, None, "MISSING_FILE", "", str(path)))
                continue
            records, parse_problems = parse_revenue_file(path, market, month)
            if parse_problems:
                bad_files += 1
                problems.extend(parse_problems)
            else:
                parsed_files += 1
            total_rows += len(records)
            for record in records:
                key = (record.revenue_month, record.market, record.stock_id)
                if key in seen_keys:
                    duplicate_keys += 1
                    problems.append(
                        RevenueProblem(record.market, record.revenue_month, record.stock_id, "DUPLICATE_KEY", "", str(path))
                    )
                seen_keys.add(key)
            if log and parsed_files and parsed_files % 100 == 0:
                log(f"INFO dry-run parsed revenue files={parsed_files} rows={total_rows}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = report_root / f"revenue_import_dry_run_{timestamp}.txt"
    problems_path = report_root / f"revenue_import_problems_{timestamp}.csv"
    _write_revenue_dry_run_summary(
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
    _write_revenue_problems(problems_path, problems)
    return RevenueDryRunReport(
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


def import_revenue_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    report_dir: Path | str | None = None,
    log: LogFunc | None = None,
) -> list[RevenueImportResult]:
    months = revenue_months_between(start, end)
    selected_markets = markets or config.MARKETS
    report = dry_run_revenue_import(
        conn,
        start=start,
        end=end,
        markets=selected_markets,
        report_dir=report_dir,
        log=log,
    )
    if report.problems or report.duplicate_keys or report.missing_files or report.bad_files:
        raise ValueError(f"revenue import blocked by dry-run problems: {report.summary_path}")

    _ensure_revenue_target_scope_empty(conn, months, selected_markets)
    results: list[RevenueImportResult] = []
    for market in selected_markets:
        row_count = 0
        for month in months:
            records, problems = parse_revenue_file(revenue_file_path(market, month), market, month)
            if problems:
                first = problems[0]
                raise ValueError(
                    f"revenue import parse problem after dry-run OK: "
                    f"{first.revenue_month} {first.market} {first.problem} {first.detail}"
                )
            _insert_revenue_rows(conn, records)
            row_count += len(records)
            if log and row_count and row_count % 100000 < len(records):
                log(f"INFO imported revenue rows market={market} rows={row_count}")
        results.append(
            RevenueImportResult(
                market=market,
                start=start,
                end=end,
                months=len(months),
                row_count=row_count,
            )
        )
    return results


def update_revenue_month(
    conn: sqlite3.Connection,
    *,
    month: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchRevenueCsv = download_revenue_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    max_attempts: int = 3,
) -> list[RevenueUpdateResult]:
    _validate_revenue_supported_month(month)
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    latest = latest_published_revenue_month()
    if month > latest:
        return [
            RevenueUpdateResult(
                market=market,
                revenue_month=month,
                status="CLOSED",
                row_count=0,
                source_file=None,
                error=f"revenue month is not published yet; latest={latest}",
            )
            for market in selected_markets
        ]

    results: list[RevenueUpdateResult] = []
    for market in selected_markets:
        try:
            existing = revenue_row_count(conn, market=market, month=month)
            if existing:
                results.append(
                    RevenueUpdateResult(
                        market=market,
                        revenue_month=month,
                        status="EXISTS",
                        row_count=existing,
                        source_file=None,
                        error="revenue rows already exist; not overwriting",
                    )
                )
                continue
            roc_month = revenue_month_to_roc_month(month)
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    cooldown.before_request(log)
                    raw = fetcher(market, roc_month)
                    _validate_revenue_response(raw, market, month)
                    path = save_official_revenue_csv(raw, market, month)
                    records, problems = parse_revenue_file(path, market, month)
                    if problems:
                        first = problems[0]
                        raise ValueError(f"{first.problem} {first.detail}".strip())
                    _insert_revenue_rows(conn, records)
                    results.append(
                        RevenueUpdateResult(
                            market=market,
                            revenue_month=month,
                            status="OK",
                            row_count=len(records),
                            source_file=str(path),
                        )
                    )
                    if log:
                        log(f"INFO {month} {market} revenue update attempt {attempt} OK")
                    break
                except Exception as exc:
                    last_error = exc
                    if log:
                        message = f"ERROR {month} {market} revenue update attempt {attempt} failed: {exc}"
                        log(f"{message}; retrying" if attempt < max_attempts else message)
            else:
                results.append(
                    RevenueUpdateResult(
                        market=market,
                        revenue_month=month,
                        status="BLOCKED",
                        row_count=0,
                        source_file=None,
                        error=str(last_error) if last_error else "revenue update failed",
                    )
                )
        except Exception as exc:
            results.append(
                RevenueUpdateResult(
                    market=market,
                    revenue_month=month,
                    status="BLOCKED",
                    row_count=0,
                    source_file=None,
                    error=str(exc),
                )
            )
    return results


def _download_revenue_market(
    market: str,
    months: list[str],
    fetcher: FetchRevenueCsv,
    cooldown: CooldownController,
    overwrite: bool,
    log: LogFunc | None,
    max_attempts: int,
) -> list[RevenueDownloadResult]:
    results: list[RevenueDownloadResult] = []
    for month in months:
        try:
            _validate_revenue_supported_month(month)
            path = revenue_file_path(market, month)
            if path.exists() and path.stat().st_size > 0 and not overwrite:
                existing = path.read_bytes()
                try:
                    _validate_revenue_response(existing, market, month)
                    size = path.stat().st_size
                    results.append(RevenueDownloadResult(market, month, "SKIP", str(path), size))
                    if log:
                        log(f"INFO {month} {market} revenue file exists {path} bytes={size}")
                    continue
                except Exception as exc:
                    if log:
                        log(f"WARN {month} {market} existing revenue file invalid; redownloading: {exc}")
        except Exception as exc:
            results.append(RevenueDownloadResult(market, month, "MISSING", None, 0, str(exc)))
            if log:
                log(f"ERROR {month} {market} revenue download unsupported: {exc}")
            continue

        last_error: Exception | None = None
        roc_month = revenue_month_to_roc_month(month)
        for attempt in range(1, max_attempts + 1):
            try:
                cooldown.before_request(log)
                raw = fetcher(market, roc_month)
                _validate_revenue_response(raw, market, month)
                path = save_official_revenue_csv(raw, market, month)
                results.append(RevenueDownloadResult(market, month, "OK", str(path), len(raw)))
                if log:
                    log(f"INFO {month} {market} revenue file saved {path} bytes={len(raw)} attempt={attempt}")
                break
            except Exception as exc:
                last_error = exc
                if log:
                    message = f"ERROR {month} {market} revenue attempt {attempt} failed: {exc}"
                    log(f"{message}; retrying" if attempt < max_attempts else message)
        else:
            results.append(
                RevenueDownloadResult(
                    market,
                    month,
                    "MISSING",
                    None,
                    0,
                    str(last_error) if last_error else "revenue download failed",
                )
            )
    return results


def _validate_revenue_supported_month(month: str) -> None:
    if month < REVENUE_START_MONTH:
        raise ValueError(f"revenue starts at {REVENUE_START_MONTH}")


def _validate_revenue_response(raw: bytes, market: str, month: str) -> None:
    if not raw:
        raise ValueError(f"revenue CSV is empty: {month} {market}")
    sample = raw[:512].decode("utf-8", errors="ignore").lower()
    if "<html" in sample or "<!doctype html" in sample:
        raise ValueError(f"revenue endpoint returned non-data HTML: {month} {market}")
    text, _encoding = _decode_revenue_csv(raw)
    if text is None:
        raise ValueError(f"revenue CSV cannot be decoded: {month} {market}")
    rows = [_clean_revenue_row(row) for row in csv.reader(text.splitlines())]
    rows = [row for row in rows if any(row)]
    if len(rows) < 2:
        raise ValueError(f"revenue CSV has no data rows: {month} {market}")
    header = rows[0]
    missing_columns = [column for column in REVENUE_REQUIRED_COLUMNS if column not in header]
    if missing_columns:
        raise ValueError(f"revenue CSV missing columns {missing_columns}: {month} {market}")
    period_index = header.index("資料年月")
    expected_roc_period = _month_to_roc_period(month)
    for row in rows[1:]:
        if len(row) <= period_index:
            continue
        period = row[period_index].strip()
        if period and period != expected_roc_period:
            raise ValueError(
                f"revenue CSV month mismatch: expected {expected_roc_period} {market}, got {period}"
            )


def _month_to_roc_period(month: str) -> str:
    year, month_number = _validate_month(month)
    return f"{year - 1911}/{month_number}"


def _validate_month(month: str) -> tuple[int, int]:
    match = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])", month)
    if not match:
        raise ValueError(f"invalid revenue month: {month}; expected YYYY-MM")
    return int(match.group(1)), int(match.group(2))


def _decode_revenue_csv(raw: bytes) -> tuple[str | None, str | None]:
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def _clean_revenue_row(row: list[str]) -> list[str]:
    cleaned = [cell.strip().replace("\ufeff", "") for cell in row]
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


def _parse_revenue_int(value: str) -> int:
    normalized = value.strip().replace(",", "")
    if normalized == "":
        raise ValueError("blank integer")
    return int(normalized)


def _parse_revenue_float(value: str) -> float | None:
    normalized = value.strip().replace(",", "")
    if normalized in {"", "-", "--"}:
        return None
    return float(normalized)


def _roc_date_to_iso(value: str) -> str:
    match = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", value.strip())
    if not match:
        raise ValueError(f"invalid ROC date: {value}")
    year = int(match.group(1)) + 1911
    month = int(match.group(2))
    day = int(match.group(3))
    return date(year, month, day).isoformat()


def _ensure_revenue_target_scope_empty(
    conn: sqlite3.Connection,
    months: list[str],
    markets: tuple[str, ...],
) -> None:
    if not months:
        return
    month_placeholders = ",".join("?" for _ in months)
    for market in markets:
        row = conn.execute(
            f"SELECT COUNT(*) FROM monthly_revenue WHERE market = ? AND revenue_month IN ({month_placeholders})",
            [market, *months],
        ).fetchone()
        count = int(row["COUNT(*)"] if hasattr(row, "keys") else row[0])
        if count:
            raise ValueError(
                f"revenue target scope is not empty: rows={count} "
                f"market={market} months={months[0]}..{months[-1]}"
            )


def revenue_row_count(
    conn: sqlite3.Connection,
    *,
    market: str | None = None,
    month: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[str] = []
    if market is not None:
        clauses.append("market = ?")
        params.append(market)
    if month is not None:
        _validate_month(month)
        clauses.append("revenue_month = ?")
        params.append(month)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) FROM monthly_revenue{where}", params).fetchone()
    return int(row["COUNT(*)"] if hasattr(row, "keys") else row[0])


def _insert_revenue_rows(conn: sqlite3.Connection, rows: list[RevenueRecord]) -> None:
    conn.executemany(
        """
        INSERT INTO monthly_revenue (
          revenue_month, market, stock_id, stock_name, industry, report_date, roc_period,
          current_month_revenue, previous_month_revenue, previous_year_month_revenue,
          month_over_month_pct, year_over_year_pct,
          cumulative_revenue, previous_year_cumulative_revenue, cumulative_growth_pct, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.revenue_month,
                row.market,
                row.stock_id,
                row.stock_name,
                row.industry,
                row.report_date,
                row.roc_period,
                row.current_month_revenue,
                row.previous_month_revenue,
                row.previous_year_month_revenue,
                row.month_over_month_pct,
                row.year_over_year_pct,
                row.cumulative_revenue,
                row.previous_year_cumulative_revenue,
                row.cumulative_growth_pct,
                row.note,
            )
            for row in rows
        ],
    )


def _write_revenue_dry_run_summary(path: Path, **values) -> None:
    problems = values.pop("problems")
    lines = [f"{key}={value}" for key, value in values.items()]
    lines.append(f"problem_count={len(problems)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_revenue_problems(path: Path, problems: list[RevenueProblem]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["market", "revenue_month", "stock_id", "problem", "detail", "path"])
        for problem in problems:
            writer.writerow(
                [
                    problem.market,
                    problem.revenue_month,
                    problem.stock_id or "",
                    problem.problem,
                    problem.detail,
                    problem.path,
                ]
            )
