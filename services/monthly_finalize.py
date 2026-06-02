from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

import config
from services.monthly_archive import archive_month
from services.monthly_audit import audit_month, normalize_markets


@dataclass
class FinalizeMonthResult:
    month: str
    status: str
    zip_path: Path | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class FinalizeMonthsResult:
    status: str
    months: list[FinalizeMonthResult] = field(default_factory=list)


def finalize_close_months(
    conn: sqlite3.Connection,
    *,
    dataset: str = config.DATASET_DAILY_CLOSE,
    start_month: str,
    end_month: str,
    markets: Iterable[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source_dir: Path | str | None = None,
    require_rollback: bool = True,
    log=None,
) -> FinalizeMonthsResult:
    if dataset != config.DATASET_DAILY_CLOSE:
        raise ValueError("v1 monthly finalization only supports daily_close")

    months = months_between(start_month, end_month)
    selected_markets = normalize_markets(markets)
    results: list[FinalizeMonthResult] = []
    if log:
        log(f"Finalize months: {start_month} -> {end_month}")

    for index, month in enumerate(months, start=1):
        month_start = start_date if index == 1 else None
        month_end = end_date if index == len(months) else None
        if log:
            log(f"Progress: {index} / {len(months)}")
            log(f"Current: {month}")

        audit = audit_month(
            conn,
            dataset=dataset,
            month=month,
            markets=selected_markets,
            start=month_start,
            end=month_end,
            require_rollback=require_rollback,
        )
        conn.commit()
        if log:
            log(f"Audit: {audit.status}")
        if audit.status != "OK":
            results.append(FinalizeMonthResult(month=month, status=audit.status, errors=audit.errors))
            return FinalizeMonthsResult(status=audit.status, months=results)

        try:
            zip_path = archive_month(
                conn,
                dataset=dataset,
                month=month,
                markets=selected_markets,
                start=month_start,
                end=month_end,
                source_dir=source_dir,
                require_rollback=require_rollback,
            )
        except Exception as exc:
            conn.rollback()
            error = f"{month} archive failed: {exc}"
            if log:
                log(f"Archive: FAILED {exc}")
            results.append(FinalizeMonthResult(month=month, status="FAILED", errors=[error]))
            return FinalizeMonthsResult(status="FAILED", months=results)

        conn.commit()
        if log:
            log(f"Archive: {zip_path}")
        results.append(FinalizeMonthResult(month=month, status="OK", zip_path=zip_path))

    return FinalizeMonthsResult(status="OK", months=results)


def months_between(start_month: str, end_month: str) -> list[str]:
    start_year, start_number = _parse_month(start_month)
    end_year, end_number = _parse_month(end_month)
    if (start_year, start_number) > (end_year, end_number):
        raise ValueError(f"--from must be earlier than or equal to --to: {start_month} > {end_month}")

    months: list[str] = []
    year = start_year
    month = start_number
    while (year, month) <= (end_year, end_number):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _parse_month(value: str) -> tuple[int, int]:
    parts = value.split("-")
    if len(parts) != 2:
        raise ValueError(f"month must be YYYY-MM: {value}")
    year = int(parts[0])
    month = int(parts[1])
    if month < 1 or month > 12:
        raise ValueError(f"month must be YYYY-MM: {value}")
    return year, month
