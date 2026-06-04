from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import subprocess

import config


DEFAULT_LOG_FILES = (
    "update-close.log",
    "rollback-close.log",
    "backup.log",
)
DEFAULT_TIMERS = (
    "veristockdb-update-close.timer",
    "veristockdb-rollback-close.timer",
    "veristockdb-backup.timer",
)


@dataclass(frozen=True)
class OpsCheckItem:
    status: str
    name: str
    message: str


@dataclass(frozen=True)
class OpsCheckResult:
    items: list[OpsCheckItem]

    @property
    def status(self) -> str:
        statuses = {item.status for item in self.items}
        if "ERROR" in statuses:
            return "ERROR"
        if "WARN" in statuses:
            return "WARN"
        return "OK"

    @property
    def has_errors(self) -> bool:
        return self.status == "ERROR"


def run_ops_check(
    *,
    db_path: Path | str = config.DB_PATH,
    backup_path: Path | str = config.DEFAULT_BACKUP_PATH,
    archive_dir: Path | str = config.ARCHIVE_DIR,
    log_dir: Path | str = config.LOG_DIR,
    check_systemd: bool = True,
) -> OpsCheckResult:
    items: list[OpsCheckItem] = []
    items.append(_check_sqlite_file("db", Path(db_path)))
    items.append(_check_sqlite_file("backup", Path(backup_path), include_size=True))
    items.append(_check_archive_dir(Path(archive_dir)))
    items.extend(_check_logs(Path(log_dir)))
    if check_systemd:
        items.extend(_check_systemd_timers(DEFAULT_TIMERS))
    return OpsCheckResult(items)


def _check_sqlite_file(name: str, path: Path, *, include_size: bool = False) -> OpsCheckItem:
    if not path.exists():
        return OpsCheckItem("ERROR", name, f"missing SQLite file: {path}")
    if not path.is_file():
        return OpsCheckItem("ERROR", name, f"not a file: {path}")

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = conn.execute(
                "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            has_daily_close = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'daily_close'
                """
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return OpsCheckItem("ERROR", name, f"SQLite read failed: {path} ({exc})")

    detail = f"readable tables={tables}"
    if has_daily_close:
        detail += " daily_close=present"
    else:
        detail += " daily_close=missing"
    if include_size:
        detail += f" size={_format_bytes(path.stat().st_size)}"
    detail += f" path={path}"
    return OpsCheckItem("OK", name, detail)


def _check_archive_dir(path: Path) -> OpsCheckItem:
    if not path.exists():
        return OpsCheckItem("ERROR", "archive", f"missing archive dir: {path}")
    if not path.is_dir():
        return OpsCheckItem("ERROR", "archive", f"not a directory: {path}")
    entries = list(path.iterdir())
    if not entries:
        return OpsCheckItem("WARN", "archive", f"archive dir is empty: {path}")
    return OpsCheckItem("OK", "archive", f"entries={len(entries)} path={path}")


def _check_logs(path: Path) -> list[OpsCheckItem]:
    if not path.exists():
        return [OpsCheckItem("WARN", "logs", f"missing log dir: {path}")]
    if not path.is_dir():
        return [OpsCheckItem("ERROR", "logs", f"not a directory: {path}")]

    items: list[OpsCheckItem] = []
    for name in DEFAULT_LOG_FILES:
        file = path / name
        if not file.exists():
            items.append(OpsCheckItem("WARN", f"log:{name}", f"missing log file: {file}"))
            continue
        size = file.stat().st_size
        if size == 0:
            items.append(OpsCheckItem("WARN", f"log:{name}", f"empty log file: {file}"))
            continue
        items.append(
            OpsCheckItem("OK", f"log:{name}", f"size={_format_bytes(size)} path={file}")
        )
    return items


def _check_systemd_timers(timer_names: tuple[str, ...]) -> list[OpsCheckItem]:
    items: list[OpsCheckItem] = []
    for timer_name in timer_names:
        try:
            proc = subprocess.run(
                ["systemctl", "is-enabled", timer_name],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return [OpsCheckItem("WARN", "systemd", "systemctl is not available")]

        output = (proc.stdout or proc.stderr).strip()
        if proc.returncode == 0 and output.startswith("enabled"):
            items.append(OpsCheckItem("OK", f"timer:{timer_name}", output))
        else:
            message = output or f"systemctl returned {proc.returncode}"
            items.append(OpsCheckItem("ERROR", f"timer:{timer_name}", message))
    return items


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{size}B"
