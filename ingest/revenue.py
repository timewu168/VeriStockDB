from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import csv
from datetime import date
from pathlib import Path
import re
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
