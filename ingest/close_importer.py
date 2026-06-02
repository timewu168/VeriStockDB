from __future__ import annotations

from collections.abc import Iterable
import hashlib
from pathlib import Path
import sqlite3

import config
from ingest.downloader import (
    CooldownController,
    FetchCloseCsv,
    LogFunc,
    download_close_csv,
    save_official_csv,
)
from ingest.trading_calendar import is_open, rollback_trading_days, trading_days_between
from services import batch_status, data_events
from validate.close_rules import validate_close_csv
from validate.result import CloseRow, PreviousClose, ValidationError, ValidationOutcome


MANUAL_OVERRIDE_CODES = {
    "MARKET_ROW_COUNT_RECHECK",
    "DOUBLE_CHECK_MISMATCH",
    "DOUBLE_CHECK_MISSING_ROW",
    "DOUBLE_CHECK_EXTRA_ROW",
}

SUCCESS_STATUSES = {"OK", "FIXED"}


def import_close_file(
    conn: sqlite3.Connection,
    *,
    path: Path | str,
    market: str,
    trade_date: str,
    double_check_rows: Iterable[CloseRow] | None = None,
) -> str:
    source_path = Path(path)
    raw = source_path.read_bytes()
    return import_close_bytes(
        conn,
        raw=raw,
        market=market,
        trade_date=trade_date,
        source_file=str(source_path),
        retry_count=0,
        double_check_rows=double_check_rows,
        note="local_csv",
    )


def import_close_bytes(
    conn: sqlite3.Connection,
    *,
    raw: bytes,
    market: str,
    trade_date: str,
    source_file: str | None,
    retry_count: int,
    double_check_rows: Iterable[CloseRow] | None = None,
    note: str | None = None,
) -> str:
    source_sha256 = hashlib.sha256(raw).hexdigest()
    existing = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
    outcome = validate_close_csv(
        raw,
        market=market,
        trade_date=trade_date,
        previous_close_lookup=lambda stock_id, date, mkt: previous_close_reference(
            conn, stock_id, date, mkt
        ),
        previous_market_row_count=previous_market_row_count(conn, market, trade_date),
    )

    if double_check_rows is not None and outcome.rows:
        _apply_double_check(outcome, double_check_rows)

    manual_approved = batch_status.is_manual_approved(
        conn, config.DATASET_DAILY_CLOSE, market, trade_date
    )
    can_write = outcome.ok
    manual_override = manual_approved and _manual_override_allowed(outcome)
    if manual_override:
        can_write = True

    if can_write:
        status = "OK"
        if existing and existing["status"] in {"BLOCKED", "RECHECK", "MISSING"}:
            status = "FIXED"
        _replace_daily_close_rows(conn, market, trade_date, outcome.rows)
        batch_id = batch_status.record_batch(
            conn,
            dataset=config.DATASET_DAILY_CLOSE,
            market=market,
            period=trade_date,
            status=status,
            row_count=len(outcome.rows),
            errors=[] if manual_override else outcome.errors,
            source_file=source_file,
            source_sha256=source_sha256,
            retry_count=retry_count,
            note=_merge_note(
                note,
                _excluded_note(outcome),
                "manual_approved" if manual_override else None,
            ),
            clear_manual_approval=not manual_override,
        )
        data_events.replace_batch_events(
            conn,
            batch_id=batch_id,
            dataset=config.DATASET_DAILY_CLOSE,
            market=market,
            period=trade_date,
            events=outcome.events,
        )
        return batch_id

    batch_id = batch_status.record_batch(
        conn,
        dataset=config.DATASET_DAILY_CLOSE,
        market=market,
        period=trade_date,
        status=outcome.status,
        row_count=len(outcome.rows) if outcome.rows else None,
        errors=outcome.errors,
        source_file=source_file,
        source_sha256=source_sha256,
        retry_count=retry_count,
        note=_merge_note(note, _excluded_note(outcome)),
    )
    data_events.replace_batch_events(
        conn,
        batch_id=batch_id,
        dataset=config.DATASET_DAILY_CLOSE,
        market=market,
        period=trade_date,
        events=[],
    )
    return batch_id


def import_close_official(
    conn: sqlite3.Connection,
    *,
    market: str,
    trade_date: str,
    fetcher: FetchCloseCsv = download_close_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    max_attempts: int = 3,
    require_calendar: bool = True,
) -> str | None:
    open_status = is_open(conn, trade_date)
    if require_calendar and open_status is None:
        raise ValueError(f"unknown trading day: {trade_date}")
    if open_status is False:
        if log:
            log(f"INFO {trade_date} is not a trading day; skipped")
        return None

    cooldown = cooldown or CooldownController()
    last_batch_id: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            cooldown.before_request(log)
            raw = fetcher(market, trade_date)
            source_path = save_official_csv(raw, market, trade_date)
            last_batch_id = import_close_bytes(
                conn,
                raw=raw,
                market=market,
                trade_date=trade_date,
                source_file=str(source_path),
                retry_count=attempt - 1,
                note=f"official_attempt={attempt}",
            )
        except Exception as exc:
            last_batch_id = _record_official_failure(
                conn, market, trade_date, exc, retry_count=attempt - 1
            )

        conn.commit()
        batch = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
        if batch and batch["status"] in SUCCESS_STATUSES:
            if log:
                log(f"INFO {trade_date} {market} import {batch['status']}")
            return last_batch_id
        if log and batch:
            message = _format_attempt_result(trade_date, market, attempt, batch)
            if attempt < max_attempts:
                log(f"{message}; retrying")
            else:
                log(message)

    return last_batch_id


def import_close_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    fetcher: FetchCloseCsv = download_close_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    require_calendar: bool = True,
) -> dict[str, int]:
    dates = trading_days_between(conn, start, end)
    if require_calendar and not dates:
        raise ValueError(f"no open trading days found between {start} and {end}")

    cooldown = cooldown or CooldownController()
    stats = {"OK": 0, "FIXED": 0, "BLOCKED": 0, "RECHECK": 0, "MISSING": 0, "SKIPPED": 0}
    total = len(dates) * len(config.MARKETS)
    current = 0
    if log:
        log(f"Range: {start} -> {end}")
    for trade_date in dates:
        for market in config.MARKETS:
            current += 1
            if log:
                log(f"Progress: {current} / {total}")
                log(f"Current: {trade_date} {market}")
            batch_id = import_close_official(
                conn,
                market=market,
                trade_date=trade_date,
                fetcher=fetcher,
                cooldown=cooldown,
                log=log,
                require_calendar=require_calendar,
            )
            if batch_id is None:
                stats["SKIPPED"] += 1
                continue
            batch = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
            if batch:
                stats[batch["status"]] += 1
            if log:
                _log_stats(stats, log)
    return stats


def import_close_day(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    fetcher: FetchCloseCsv = download_close_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    require_calendar: bool = True,
) -> dict[str, int]:
    cooldown = cooldown or CooldownController()
    stats = {"OK": 0, "FIXED": 0, "BLOCKED": 0, "RECHECK": 0, "MISSING": 0, "SKIPPED": 0}
    for market in config.MARKETS:
        if log:
            log(f"Current: {trade_date} {market}")
        batch_id = import_close_official(
            conn,
            market=market,
            trade_date=trade_date,
            fetcher=fetcher,
            cooldown=cooldown,
            log=log,
            require_calendar=require_calendar,
        )
        if batch_id is None:
            stats["SKIPPED"] += 1
            continue
        batch = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
        if batch:
            stats[batch["status"]] += 1
    return stats


def import_close_with_rollback(
    conn: sqlite3.Connection,
    *,
    target_date: str,
    fetcher: FetchCloseCsv = download_close_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    require_calendar: bool = True,
) -> dict[str, int]:
    dates = rollback_trading_days(conn, target_date, 3)
    if require_calendar and not dates:
        raise ValueError(f"no trading calendar rows available for rollback ending {target_date}")

    cooldown = cooldown or CooldownController()
    stats = {"OK": 0, "FIXED": 0, "BLOCKED": 0, "RECHECK": 0, "MISSING": 0, "SKIPPED": 0}
    all_success = True
    for trade_date in dates:
        for market in config.MARKETS:
            if log:
                log(f"Current: {trade_date} {market}")
            batch_id = import_close_official(
                conn,
                market=market,
                trade_date=trade_date,
                fetcher=fetcher,
                cooldown=cooldown,
                log=log,
                require_calendar=require_calendar,
            )
            if batch_id is None:
                stats["SKIPPED"] += 1
                continue
            batch = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
            if batch:
                stats[batch["status"]] += 1
                if batch["status"] not in SUCCESS_STATUSES:
                    all_success = False
    if all_success and dates:
        batch_status.set_setting(conn, f"rollback:{config.DATASET_DAILY_CLOSE}:{target_date}", "OK")
    return stats


def previous_close(
    conn: sqlite3.Connection, stock_id: str, trade_date: str, market: str
) -> int | None:
    previous = previous_close_reference(conn, stock_id, trade_date, market)
    return previous.close if previous else None


def previous_close_reference(
    conn: sqlite3.Connection, stock_id: str, trade_date: str, market: str
) -> PreviousClose | None:
    row = conn.execute(
        """
        SELECT trade_date, close
        FROM daily_close
        WHERE stock_id = ? AND market = ? AND trade_date < ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (stock_id, market, trade_date),
    ).fetchone()
    return PreviousClose(int(row["close"]), row["trade_date"]) if row else None


def previous_market_row_count(
    conn: sqlite3.Connection, market: str, trade_date: str
) -> int | None:
    row = conn.execute(
        """
        SELECT trade_date
        FROM daily_close
        WHERE market = ? AND trade_date < ?
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (market, trade_date),
    ).fetchone()
    if row is None:
        return None
    count_row = conn.execute(
        "SELECT COUNT(*) AS count FROM daily_close WHERE market = ? AND trade_date = ?",
        (market, row["trade_date"]),
    ).fetchone()
    return int(count_row["count"]) if count_row else None


def query_close(
    conn: sqlite3.Connection,
    *,
    stock_id: str | None = None,
    trade_date: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list[str] = []
    if stock_id:
        clauses.append("stock_id = ?")
        params.append(stock_id)
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
        SELECT trade_date, stock_id, stock_name, market,
               open, high, low, close, volume, amount, transactions
        FROM daily_close
        {where}
        ORDER BY trade_date, market, stock_id
        """,
        params,
    ).fetchall()


def _record_official_failure(
    conn: sqlite3.Connection,
    market: str,
    trade_date: str,
    exc: Exception,
    retry_count: int,
) -> str:
    batch_id = batch_status.record_batch(
        conn,
        dataset=config.DATASET_DAILY_CLOSE,
        market=market,
        period=trade_date,
        status="MISSING",
        row_count=None,
        errors=[
            ValidationError(
                "BLOCK",
                "DOWNLOAD_FAILED",
                str(exc),
            )
        ],
        retry_count=retry_count,
        note="official_download",
    )
    data_events.replace_batch_events(
        conn,
        batch_id=batch_id,
        dataset=config.DATASET_DAILY_CLOSE,
        market=market,
        period=trade_date,
        events=[],
    )
    return batch_id


def _replace_daily_close_rows(
    conn: sqlite3.Connection, market: str, trade_date: str, rows: list[CloseRow]
) -> None:
    conn.execute(
        "DELETE FROM daily_close WHERE trade_date = ? AND market = ?",
        (trade_date, market),
    )
    conn.executemany(
        """
        INSERT INTO daily_close(
          trade_date, stock_id, stock_name, market, open, high, low, close,
          volume, amount, transactions
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.trade_date,
                row.stock_id,
                row.stock_name,
                row.market,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.amount,
                row.transactions,
            )
            for row in rows
        ],
    )


def _apply_double_check(
    outcome: ValidationOutcome, expected_rows: Iterable[CloseRow]
) -> None:
    expected = {(row.market, row.stock_id): row for row in expected_rows}
    actual = {(row.market, row.stock_id): row for row in outcome.rows}
    for key, expected_row in expected.items():
        actual_row = actual.get(key)
        if actual_row is None:
            outcome.errors.append(
                ValidationError(
                    "BLOCK",
                    "DOUBLE_CHECK_MISSING_ROW",
                    "double-check source has row missing from import source",
                    expected_row.stock_id,
                )
            )
        elif actual_row.close != expected_row.close:
            outcome.errors.append(
                ValidationError(
                    "BLOCK",
                    "DOUBLE_CHECK_MISMATCH",
                    "double-check close price differs",
                    actual_row.stock_id,
                    str(actual_row.close),
                )
            )
    for key, actual_row in actual.items():
        if key not in expected:
            outcome.errors.append(
                ValidationError(
                    "BLOCK",
                    "DOUBLE_CHECK_EXTRA_ROW",
                    "import source has row missing from double-check source",
                    actual_row.stock_id,
                )
            )
    if outcome.errors and outcome.status != "BLOCKED":
        outcome.status = "RECHECK"


def _manual_override_allowed(outcome: ValidationOutcome) -> bool:
    if not outcome.rows or not outcome.errors:
        return False
    return all(error.code in MANUAL_OVERRIDE_CODES for error in outcome.errors)


def _merge_note(*parts: str | None) -> str | None:
    values = [part for part in parts if part]
    return "; ".join(values) if values else None


def _excluded_note(outcome: ValidationOutcome) -> str | None:
    if outcome.excluded_count == 0:
        return None
    return f"excluded_rows={outcome.excluded_count}"


def _log_stats(stats: dict[str, int], log: LogFunc) -> None:
    log(
        "OK: {OK} FIXED: {FIXED} BLOCKED: {BLOCKED} RECHECK: {RECHECK} "
        "MISSING: {MISSING}".format(**stats)
    )


def _format_attempt_result(
    trade_date: str, market: str, attempt: int, batch: sqlite3.Row
) -> str:
    reason = f": {batch['error_summary']}" if batch["error_summary"] else ""
    return f"INFO {trade_date} {market} attempt {attempt} ended {batch['status']}{reason}"
