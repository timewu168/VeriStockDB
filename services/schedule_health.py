from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Callable, Sequence

import config
from ingest import revenue


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ScheduleDefinition:
    dataset: str
    title: str
    timer: str
    service: str
    log_file: str
    table: str
    period_column: str
    period_type: str


@dataclass(frozen=True)
class ScheduleHealthResult:
    schedules: list[dict]

    @property
    def status(self) -> str:
        statuses = {schedule["status"] for schedule in self.schedules}
        if "ERROR" in statuses:
            return "ERROR"
        if "WARN" in statuses:
            return "WARN"
        return "OK"


SCHEDULES = (
    ScheduleDefinition(
        dataset=config.DATASET_DAILY_CLOSE,
        title="Close",
        timer="veristockdb-update-close.timer",
        service="veristockdb-update-close.service",
        log_file="update-close.log",
        table="daily_close",
        period_column="trade_date",
        period_type="date",
    ),
    ScheduleDefinition(
        dataset=config.DATASET_LEGAL_INVESTOR,
        title="法人",
        timer="veristockdb-update-legal.timer",
        service="veristockdb-update-legal.service",
        log_file="update-legal.log",
        table="legal_investors",
        period_column="trade_date",
        period_type="date",
    ),
    ScheduleDefinition(
        dataset=config.DATASET_ATTENTION_NOTICE,
        title="注意公告",
        timer="veristockdb-update-attention.timer",
        service="veristockdb-update-attention.service",
        log_file="update-attention.log",
        table="attention_notices",
        period_column="trade_date",
        period_type="date",
    ),
    ScheduleDefinition(
        dataset=config.DATASET_DISPOSAL_NOTICE,
        title="處置公告",
        timer="veristockdb-update-disposal.timer",
        service="veristockdb-update-disposal.service",
        log_file="update-disposal.log",
        table="disposal_notices",
        period_column="trade_date",
        period_type="date",
    ),
    ScheduleDefinition(
        dataset=config.DATASET_MARGIN,
        title="資券",
        timer="veristockdb-update-margin.timer",
        service="veristockdb-update-margin.service",
        log_file="update-margin.log",
        table="margin_trading",
        period_column="trade_date",
        period_type="date",
    ),
    ScheduleDefinition(
        dataset=config.DATASET_DAY_TRADING,
        title="當沖",
        timer="veristockdb-update-day-trading.timer",
        service="veristockdb-update-day-trading.service",
        log_file="update-day-trading.log",
        table="day_trading",
        period_column="trade_date",
        period_type="date",
    ),
    ScheduleDefinition(
        dataset=config.DATASET_REVENUE,
        title="月營收",
        timer="veristockdb-update-revenue.timer",
        service="veristockdb-update-revenue.service",
        log_file="update-revenue.log",
        table="monthly_revenue",
        period_column="revenue_month",
        period_type="month",
    ),
)

LOG_ERROR_PATTERNS = ("Traceback", "ERROR", "Exception", "Internal Server Error")
LOG_PROBLEM_COUNT_PATTERN = re.compile(r"\b(BLOCKED|RECHECK|MISSING|FAILED)\s*[=:]\s*([1-9]\d*)\b")
DENSE_MARKET_DATASETS = {
    config.DATASET_DAILY_CLOSE,
    config.DATASET_LEGAL_INVESTOR,
    config.DATASET_MARGIN,
    config.DATASET_DAY_TRADING,
}


def run_schedule_health(
    *,
    db_path: Path | str = config.DB_PATH,
    log_dir: Path | str = config.LOG_DIR,
    check_systemd: bool = True,
    today: date | None = None,
    runner: Runner | None = None,
) -> ScheduleHealthResult:
    today = today or date.today()
    runner = runner or _run_command
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        expected_open_date = _latest_open_trading_day(conn, today)
        schedules = [
            _schedule_report(
                conn,
                definition,
                log_dir=Path(log_dir),
                check_systemd=check_systemd,
                expected_open_date=expected_open_date,
                today=today,
                runner=runner,
            )
            for definition in SCHEDULES
        ]
    finally:
        conn.close()
    return ScheduleHealthResult(schedules)


def _schedule_report(
    conn: sqlite3.Connection,
    definition: ScheduleDefinition,
    *,
    log_dir: Path,
    check_systemd: bool,
    expected_open_date: str | None,
    today: date,
    runner: Runner,
) -> dict:
    timer = _timer_report(definition, check_systemd=check_systemd, runner=runner)
    data = _data_report(conn, definition, expected_open_date=expected_open_date, today=today)
    log = _log_report(
        log_dir / definition.log_file,
        allow_missing_ok=definition.period_type == "month" and data["status"] == "OK",
    )
    if data["status"] == "OK" and log["status"] == "WARN":
        log = {
            **log,
            "status": "OK",
            "message": "warning markers found but canonical data is current",
        }
    status = _overall_status(timer["status"], log["status"], data["status"])
    return {
        "dataset": definition.dataset,
        "title": definition.title,
        "status": status,
        "timer": timer,
        "log": log,
        "data": data,
    }


def _timer_report(
    definition: ScheduleDefinition,
    *,
    check_systemd: bool,
    runner: Runner,
) -> dict:
    if not check_systemd:
        return {
            "status": "SKIPPED",
            "timer": definition.timer,
            "service": definition.service,
            "enabled": None,
            "active": None,
            "last_trigger": None,
            "next_trigger": None,
            "message": "systemd check skipped",
        }
    try:
        enabled = runner(["systemctl", "is-enabled", definition.timer])
        active = runner(["systemctl", "is-active", definition.timer])
        show = runner(
            [
                "systemctl",
                "show",
                definition.timer,
                "-p",
                "LastTriggerUSec",
                "-p",
                "NextElapseUSecRealtime",
            ]
        )
    except FileNotFoundError:
        return {
            "status": "WARN",
            "timer": definition.timer,
            "service": definition.service,
            "enabled": None,
            "active": None,
            "last_trigger": None,
            "next_trigger": None,
            "message": "systemctl is not available",
        }

    enabled_text = _completed_text(enabled)
    active_text = _completed_text(active)
    show_values = _parse_systemctl_show(_completed_text(show))
    problems: list[str] = []
    if enabled.returncode != 0 or not enabled_text.startswith("enabled"):
        problems.append(f"not enabled: {enabled_text or enabled.returncode}")
    if active.returncode != 0 or active_text != "active":
        problems.append(f"not active: {active_text or active.returncode}")
    return {
        "status": "ERROR" if problems else "OK",
        "timer": definition.timer,
        "service": definition.service,
        "enabled": enabled_text or None,
        "active": active_text or None,
        "last_trigger": _empty_to_none(show_values.get("LastTriggerUSec")),
        "next_trigger": _empty_to_none(show_values.get("NextElapseUSecRealtime")),
        "message": "; ".join(problems) if problems else "timer enabled and active",
    }


def _log_report(path: Path, *, tail_bytes: int = 64_000, allow_missing_ok: bool = False) -> dict:
    if not path.exists():
        return {
            "status": "OK" if allow_missing_ok else "WARN",
            "path": str(path),
            "size": 0,
            "message": "log file not created yet; data is current" if allow_missing_ok else "log file missing",
            "matches": [],
        }
    size = path.stat().st_size
    if size == 0:
        return {
            "status": "WARN",
            "path": str(path),
            "size": 0,
            "message": "log file empty",
            "matches": [],
        }
    text = _latest_log_segment(_read_tail(path, tail_bytes))
    matches = _log_matches(text)
    status = "OK"
    message = "no error markers in recent log tail"
    if any(match["level"] == "ERROR" for match in matches):
        status = "ERROR"
        message = "error marker found in recent log tail"
    elif matches:
        status = "WARN"
        message = "warning marker found in recent log tail"
    return {
        "status": status,
        "path": str(path),
        "size": size,
        "message": message,
        "matches": matches[:8],
    }


def _data_report(
    conn: sqlite3.Connection,
    definition: ScheduleDefinition,
    *,
    expected_open_date: str | None,
    today: date,
) -> dict:
    canonical_latest = _canonical_latest(conn, definition.table, definition.period_column)
    latest_by_market = _canonical_latest_by_market(conn, definition.table, definition.period_column)
    batch_latest = _batch_latest(conn, definition.dataset)
    expected = _expected_period(definition, expected_open_date=expected_open_date, today=today)
    observed = _max_period(canonical_latest, batch_latest["period_end"], definition.period_type)
    status = "OK"
    message = "data is current"
    if expected is None:
        status = "WARN"
        message = "expected period is unknown"
    elif observed is None:
        status = "WARN"
        message = "no canonical or batch period found"
    elif observed < expected:
        status = "WARN"
        message = f"latest observed period {observed} is before expected {expected}"
    elif definition.dataset in DENSE_MARKET_DATASETS:
        lagging = [
            market
            for market, latest in latest_by_market.items()
            if latest is None or latest < expected
        ]
        if lagging:
            status = "WARN"
            message = "market data before expected: " + ", ".join(
                f"{market}={latest_by_market.get(market) or '-'}" for market in lagging
            )
    elif batch_latest["status"] in {"BLOCKED", "RECHECK", "MISSING"}:
        status = "WARN"
        message = f"latest batch status is {batch_latest['status']}"
    return {
        "status": status,
        "expected_period": expected,
        "canonical_latest": canonical_latest,
        "latest_by_market": latest_by_market,
        "batch_latest": batch_latest,
        "observed_period": observed,
        "message": message,
    }


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


def _canonical_latest(conn: sqlite3.Connection, table: str, period_column: str) -> str | None:
    row = conn.execute(
        f"SELECT MAX({period_column}) AS latest_period FROM {table}",
    ).fetchone()
    return row["latest_period"] if row and row["latest_period"] else None


def _canonical_latest_by_market(conn: sqlite3.Connection, table: str, period_column: str) -> dict[str, str | None]:
    rows = conn.execute(
        f"""
        SELECT market, MAX({period_column}) AS latest_period
        FROM {table}
        GROUP BY market
        """
    ).fetchall()
    latest = {market: None for market in config.MARKETS}
    latest.update({str(row["market"]): row["latest_period"] for row in rows})
    return latest


def _batch_latest(conn: sqlite3.Connection, dataset: str) -> dict:
    row = conn.execute(
        """
        SELECT batch_id, period, status, checked_at, error_summary
        FROM import_batches
        WHERE dataset = ?
        ORDER BY checked_at DESC, period DESC
        LIMIT 1
        """,
        (dataset,),
    ).fetchone()
    if not row:
        return {
            "batch_id": None,
            "period": None,
            "period_end": None,
            "status": None,
            "checked_at": None,
            "error_summary": None,
        }
    period = row["period"]
    return {
        "batch_id": row["batch_id"],
        "period": period,
        "period_end": _period_end(period),
        "status": row["status"],
        "checked_at": row["checked_at"],
        "error_summary": row["error_summary"],
    }


def _expected_period(
    definition: ScheduleDefinition,
    *,
    expected_open_date: str | None,
    today: date,
) -> str | None:
    if definition.period_type == "month":
        return revenue.latest_published_revenue_month(today=today)
    return expected_open_date


def _period_end(period: str | None) -> str | None:
    if not period:
        return None
    candidate = period.split("..")[-1]
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", candidate):
        return candidate
    if re.fullmatch(r"20\d{2}-\d{2}", candidate):
        return candidate
    return None


def _max_period(first: str | None, second: str | None, period_type: str) -> str | None:
    values = [
        value
        for value in (first, second)
        if value and _period_matches_type(value, period_type)
    ]
    return max(values) if values else None


def _period_matches_type(value: str, period_type: str) -> bool:
    if period_type == "month":
        return bool(re.fullmatch(r"20\d{2}-\d{2}", value))
    return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value))


def _read_tail(path: Path, tail_bytes: int) -> str:
    with path.open("rb") as file:
        if path.stat().st_size > tail_bytes:
            file.seek(-tail_bytes, 2)
        data = file.read()
    return data.decode("utf-8", errors="replace")


def _log_matches(text: str) -> list[dict]:
    matches: list[dict] = []
    for line in text.splitlines():
        level = None
        if any(pattern in line for pattern in LOG_ERROR_PATTERNS) and "retrying" not in line:
            level = "ERROR"
        elif LOG_PROBLEM_COUNT_PATTERN.search(line):
            level = "WARN"
        if level:
            matches.append({"level": level, "line": line[-500:]})
    return matches[-8:]


def _latest_log_segment(text: str) -> str:
    lines = text.splitlines()
    notification_indexes = [
        index for index, line in enumerate(lines) if "INFO telegram notification sent" in line
    ]
    if len(notification_indexes) >= 2:
        return "\n".join(lines[notification_indexes[-2] + 1 :])
    return text


def _overall_status(*statuses: str) -> str:
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    return "OK"


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=5)


def _completed_text(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stdout or completed.stderr or "").strip()


def _parse_systemctl_show(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in value.splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        result[key] = raw
    return result


def _empty_to_none(value: str | None) -> str | None:
    if value is None or value in {"", "n/a"}:
        return None
    return value
