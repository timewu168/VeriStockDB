from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import calendar
import sqlite3

import config
from ingest import revenue


@dataclass(frozen=True)
class DatasetCheckDefinition:
    dataset: str
    title: str
    table: str
    period_column: str
    period_type: str
    key_columns: tuple[str, ...]
    coverage_mode: str
    markets: tuple[str, ...] = config.MARKETS


@dataclass(frozen=True)
class DatasetHealthCheckResult:
    datasets: list[dict]

    @property
    def status(self) -> str:
        statuses = {item["status"] for item in self.datasets}
        if "ERROR" in statuses:
            return "ERROR"
        if "WARN" in statuses:
            return "WARN"
        return "OK"


DATASET_CHECKS = (
    DatasetCheckDefinition(
        dataset=config.DATASET_DAILY_CLOSE,
        title="Close",
        table="daily_close",
        period_column="trade_date",
        period_type="date",
        key_columns=("trade_date", "market", "stock_id"),
        coverage_mode="dense_date",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_ATTENTION_NOTICE,
        title="注意公告",
        table="attention_notices",
        period_column="trade_date",
        period_type="date",
        key_columns=("trade_date", "market", "stock_id"),
        coverage_mode="sparse_notice",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_DISPOSAL_NOTICE,
        title="處置公告",
        table="disposal_notices",
        period_column="trade_date",
        period_type="date",
        key_columns=(
            "trade_date",
            "market",
            "stock_id",
            "disposal_start_date",
            "disposal_end_date",
        ),
        coverage_mode="sparse_notice",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_LEGAL_INVESTOR,
        title="法人",
        table="legal_investors",
        period_column="trade_date",
        period_type="date",
        key_columns=("trade_date", "market", "stock_id"),
        coverage_mode="dense_date",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_MARGIN,
        title="資券",
        table="margin_trading",
        period_column="trade_date",
        period_type="date",
        key_columns=("trade_date", "market", "stock_id"),
        coverage_mode="dense_date",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_DAY_TRADING,
        title="當沖",
        table="day_trading",
        period_column="trade_date",
        period_type="date",
        key_columns=("trade_date", "market", "stock_id"),
        coverage_mode="dense_date",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_REVENUE,
        title="月營收",
        table="monthly_revenue",
        period_column="revenue_month",
        period_type="month",
        key_columns=("revenue_month", "market", "stock_id"),
        coverage_mode="dense_month",
    ),
    DatasetCheckDefinition(
        dataset=config.DATASET_SECURITY_MASTER,
        title="股票基本資料",
        table="security_master",
        period_column="source_updated_date",
        period_type="date",
        key_columns=("market", "stock_id", "effective_from"),
        coverage_mode="full_snapshot",
    ),
)


def run_dataset_health_check(
    *,
    db_path: Path | str = config.DB_PATH,
    today: date | None = None,
    recent_limit: int = 5,
    gap_sample_limit: int = 8,
) -> DatasetHealthCheckResult:
    today = today or date.today()
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        latest_open_date = _latest_open_trading_day(conn, today)
        datasets = [
            _dataset_report(
                conn,
                definition,
                today=today,
                latest_open_date=latest_open_date,
                recent_limit=recent_limit,
                gap_sample_limit=gap_sample_limit,
            )
            for definition in DATASET_CHECKS
        ]
    finally:
        conn.close()
    return DatasetHealthCheckResult(datasets)


def _dataset_report(
    conn: sqlite3.Connection,
    definition: DatasetCheckDefinition,
    *,
    today: date,
    latest_open_date: str | None,
    recent_limit: int,
    gap_sample_limit: int,
) -> dict:
    row_count = _row_count(conn, definition.table)
    rows_by_market = _rows_by_market(conn, definition)
    latest = _latest_by_market(conn, definition)
    duplicate_keys = _duplicate_key_count(conn, definition)
    gap = _gap_report(
        conn,
        definition,
        today=today,
        latest_open_date=latest_open_date,
        sample_limit=gap_sample_limit,
    )
    recent_errors = _recent_errors(conn, definition.dataset, recent_limit)
    recent_non_ok_batches = _recent_non_ok_batches(conn, definition.dataset, recent_limit)
    recent_error_count = len(recent_errors)
    status = "OK"
    messages: list[str] = []
    if duplicate_keys:
        status = "ERROR"
        messages.append(f"duplicate_keys={duplicate_keys}")
    if gap["missing_count"]:
        if status != "ERROR":
            status = "WARN"
        messages.append(f"gap_count={gap['missing_count']}")
    if recent_error_count:
        if status != "ERROR":
            status = "WARN"
        messages.append(f"recent_errors={recent_error_count}")
    if recent_non_ok_batches:
        if status != "ERROR":
            status = "WARN"
        messages.append(f"recent_non_ok_batches={len(recent_non_ok_batches)}")
    return {
        "dataset": definition.dataset,
        "title": definition.title,
        "status": status,
        "message": "; ".join(messages) if messages else "dataset checks passed",
        "table": definition.table,
        "period_type": definition.period_type,
        "row_count": row_count,
        "rows_by_market": rows_by_market,
        "latest": latest,
        "duplicate_keys": duplicate_keys,
        "gap": gap,
        "recent_error_count": recent_error_count,
        "recent_errors": recent_errors,
        "recent_non_ok_batches": recent_non_ok_batches,
    }


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _rows_by_market(conn: sqlite3.Connection, definition: DatasetCheckDefinition) -> dict[str, int]:
    rows = conn.execute(
        f"""
        SELECT market, COUNT(*) AS count
        FROM {definition.table}
        GROUP BY market
        ORDER BY market
        """
    ).fetchall()
    return {str(row["market"]): int(row["count"]) for row in rows}


def _latest_by_market(conn: sqlite3.Connection, definition: DatasetCheckDefinition) -> dict[str, str | None]:
    rows = conn.execute(
        f"""
        SELECT market, MAX({definition.period_column}) AS latest_period
        FROM {definition.table}
        GROUP BY market
        ORDER BY market
        """
    ).fetchall()
    latest = {market: None for market in definition.markets}
    latest.update({str(row["market"]): row["latest_period"] for row in rows})
    return latest


def _duplicate_key_count(conn: sqlite3.Connection, definition: DatasetCheckDefinition) -> int:
    columns = ", ".join(definition.key_columns)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM (
          SELECT {columns}, COUNT(*) AS row_count
          FROM {definition.table}
          GROUP BY {columns}
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()
    return int(row["count"])


def _gap_report(
    conn: sqlite3.Connection,
    definition: DatasetCheckDefinition,
    *,
    today: date,
    latest_open_date: str | None,
    sample_limit: int,
) -> dict:
    if definition.coverage_mode == "full_snapshot":
        return {
            "scope": "full_snapshot",
            "missing_count": 0,
            "samples": [],
            "by_market": {},
            "message": "full official snapshot dataset; daily row gaps are not applicable",
        }
    if definition.coverage_mode == "sparse_notice":
        return {
            "scope": "sparse_notice",
            "missing_count": 0,
            "samples": [],
            "by_market": {},
            "message": "sparse announcement dataset; gap is not defined by daily canonical rows",
        }
    if definition.coverage_mode == "dense_month":
        return _month_gap_report(conn, definition, today=today, sample_limit=sample_limit)
    return _date_gap_report(
        conn,
        definition,
        latest_open_date=latest_open_date,
        sample_limit=sample_limit,
    )


def _date_gap_report(
    conn: sqlite3.Connection,
    definition: DatasetCheckDefinition,
    *,
    latest_open_date: str | None,
    sample_limit: int,
) -> dict:
    if latest_open_date is None:
        return {
            "scope": "trading_days",
            "missing_count": 0,
            "samples": [],
            "by_market": {},
            "message": "latest open trading day is unknown",
        }

    by_market: dict[str, dict] = {}
    total = 0
    for market in definition.markets:
        start = _first_canonical_period(conn, definition, market)
        if start is None:
            by_market[market] = {"start": None, "end": latest_open_date, "missing_count": 0, "samples": []}
            continue
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM trading_days td
            WHERE td.is_open = 1
              AND td.trade_date BETWEEN ? AND ?
              AND NOT EXISTS (
                SELECT 1
                FROM {table} c
                WHERE c.market = ?
                  AND c.{period_column} = td.trade_date
              )
            """.format(table=definition.table, period_column=definition.period_column),
            (start, latest_open_date, market),
        ).fetchone()["count"]
        samples = conn.execute(
            """
            SELECT td.trade_date
            FROM trading_days td
            WHERE td.is_open = 1
              AND td.trade_date BETWEEN ? AND ?
              AND NOT EXISTS (
                SELECT 1
                FROM {table} c
                WHERE c.market = ?
                  AND c.{period_column} = td.trade_date
              )
            ORDER BY td.trade_date
            LIMIT ?
            """.format(table=definition.table, period_column=definition.period_column),
            (start, latest_open_date, market, sample_limit),
        ).fetchall()
        missing_count = int(count)
        market_samples = [row["trade_date"] for row in samples]
        by_market[market] = {
            "start": start,
            "end": latest_open_date,
            "missing_count": missing_count,
            "samples": market_samples,
        }
        total += missing_count
    return {
        "scope": "trading_days",
        "missing_count": total,
        "samples": _flatten_gap_samples(by_market),
        "by_market": by_market,
        "message": "missing canonical rows over open trading days",
    }


def _month_gap_report(
    conn: sqlite3.Connection,
    definition: DatasetCheckDefinition,
    *,
    today: date,
    sample_limit: int,
) -> dict:
    target = revenue.latest_published_revenue_month(today=today)
    by_market: dict[str, dict] = {}
    total = 0
    for market in definition.markets:
        start = _first_canonical_period(conn, definition, market)
        if start is None or target is None:
            by_market[market] = {"start": start, "end": target, "missing_count": 0, "samples": []}
            continue
        months = list(_iter_months(start, target))
        accepted = {
            row[definition.period_column]
            for row in conn.execute(
                f"""
                SELECT DISTINCT {definition.period_column}
                FROM {definition.table}
                WHERE market = ?
                  AND {definition.period_column} BETWEEN ? AND ?
                """,
                (market, start, target),
            ).fetchall()
        }
        missing = [month for month in months if month not in accepted]
        by_market[market] = {
            "start": start,
            "end": target,
            "missing_count": len(missing),
            "samples": missing[:sample_limit],
        }
        total += len(missing)
    return {
        "scope": "months",
        "missing_count": total,
        "samples": _flatten_gap_samples(by_market),
        "by_market": by_market,
        "message": "missing canonical rows over expected months",
    }


def _first_batch_period(conn: sqlite3.Connection, dataset: str, market: str) -> str | None:
    row = conn.execute(
        """
        SELECT MIN(period) AS first_period
        FROM import_batches
        WHERE dataset = ?
          AND market = ?
          AND status IN ('OK', 'FIXED')
        """,
        (dataset, market),
    ).fetchone()
    return row["first_period"] if row and row["first_period"] else None


def _first_canonical_period(
    conn: sqlite3.Connection,
    definition: DatasetCheckDefinition,
    market: str,
) -> str | None:
    row = conn.execute(
        f"""
        SELECT MIN({definition.period_column}) AS first_period
        FROM {definition.table}
        WHERE market = ?
        """,
        (market,),
    ).fetchone()
    return row["first_period"] if row and row["first_period"] else None


def _latest_open_trading_day(conn: sqlite3.Connection, today: date) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(trade_date) AS trade_date
        FROM trading_days
        WHERE is_open = 1
          AND trade_date <= ?
        """,
        (today.isoformat(),),
    ).fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


def _recent_errors(conn: sqlite3.Connection, dataset: str, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.error_id, e.batch_id, b.market, b.period, e.severity, e.code,
               e.message, e.created_at
        FROM import_errors e
        JOIN import_batches b ON b.batch_id = e.batch_id
        WHERE b.dataset = ?
        ORDER BY e.created_at DESC
        LIMIT ?
        """,
        (dataset, limit),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _recent_non_ok_batches(conn: sqlite3.Connection, dataset: str, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT batch_id, market, period, status, row_count, error_summary, checked_at
        FROM import_batches
        WHERE dataset = ?
          AND status NOT IN ('OK', 'FIXED')
        ORDER BY checked_at DESC, period DESC
        LIMIT ?
        """,
        (dataset, limit),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _flatten_gap_samples(by_market: dict[str, dict]) -> list[dict]:
    samples: list[dict] = []
    for market, report in by_market.items():
        for period in report["samples"]:
            samples.append({"market": market, "period": period})
    return samples


def _iter_months(start: str, end: str):
    start_year, start_month = (int(part) for part in start.split("-", 1))
    end_year, end_month = (int(part) for part in end.split("-", 1))
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        _, days_in_month = calendar.monthrange(year, month)
        next_month = date(year, month, days_in_month).replace(day=1)
        if next_month.month == 12:
            year = next_month.year + 1
            month = 1
        else:
            year = next_month.year
            month = next_month.month + 1


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}
