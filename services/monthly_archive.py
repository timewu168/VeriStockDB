from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import sqlite3
from zipfile import ZipFile, ZIP_DEFLATED

import config
from services import batch_status
from services.monthly_audit import audit_date_range, audit_setting_key, normalize_markets


def archive_month(
    conn: sqlite3.Connection,
    *,
    dataset: str = config.DATASET_DAILY_CLOSE,
    month: str,
    markets: Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    source_dir: Path | str | None = None,
    require_rollback: bool = True,
) -> Path:
    if dataset != config.DATASET_DAILY_CLOSE:
        raise ValueError("v1 monthly archive only supports daily_close")
    start_date, end_date, full_month = audit_date_range(month, start, end)
    selected_markets = normalize_markets(markets)
    full_markets = selected_markets == config.MARKETS
    audit_key = audit_setting_key(
        dataset,
        month,
        start_date,
        end_date,
        selected_markets,
        full_month=full_month,
        full_markets=full_markets,
        require_rollback=require_rollback,
    )
    if batch_status.get_setting(conn, audit_key) != "OK":
        raise ValueError(f"monthly audit is not OK for {dataset} {month} scope {audit_key}")

    year, month_number = month.split("-")
    csv_dir = Path(source_dir) if source_dir else config.CSV_DIR / "daily_close" / year
    files = _expected_csv_files(conn, csv_dir, start_date, end_date, selected_markets)
    if not files:
        raise FileNotFoundError(
            f"no loose CSV files found for {dataset} between {start_date} and {end_date}"
        )
    missing = [file for file in files if not file.exists()]
    if missing:
        sample = ", ".join(str(file) for file in missing[:3])
        more = f", ... plus {len(missing) - 3} more" if len(missing) > 3 else ""
        raise FileNotFoundError(f"expected loose CSV files are missing: {sample}{more}")

    zip_path = _zip_path(
        dataset,
        month,
        start_date,
        end_date,
        selected_markets,
        full_month=full_month,
        full_markets=full_markets,
        require_rollback=require_rollback,
    )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    expected_names = [file.name for file in files]
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, arcname=file.name)

    _verify_zip(zip_path, expected_names)
    conn.execute(
        f"""
        UPDATE import_batches
        SET archived_zip = ?
        WHERE dataset = ?
          AND period BETWEEN ? AND ?
          AND market IN ({",".join("?" for _ in selected_markets)})
          AND status IN ('OK', 'FIXED')
        """,
        (str(zip_path), dataset, start_date, end_date, *selected_markets),
    )
    delete_loose = batch_status.get_setting(
        conn, "delete_loose_csv_after_verified_zip", "1"
    )
    if delete_loose == "1":
        for file in files:
            file.unlink()
    return zip_path


def _expected_csv_files(
    conn: sqlite3.Connection,
    csv_dir: Path,
    start: str,
    end: str,
    markets: tuple[str, ...],
) -> list[Path]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM trading_days
        WHERE is_open = 1 AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (start, end),
    ).fetchall()
    files: list[Path] = []
    for row in rows:
        for market in markets:
            files.append(csv_dir / _close_csv_name(market, row["trade_date"]))
    return files


def _close_csv_name(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return f"{yyyymmdd}CloseSII.csv"
    if market == "TPEX":
        return f"{yyyymmdd}CloseOTC.csv"
    raise ValueError(f"unknown market: {market}")


def _zip_path(
    dataset: str,
    month: str,
    start: str,
    end: str,
    markets: tuple[str, ...],
    *,
    full_month: bool,
    full_markets: bool,
    require_rollback: bool,
) -> Path:
    year, month_number = month.split("-")
    if full_month and full_markets and require_rollback:
        name = f"{dataset}_{year}_{month_number}.zip"
    else:
        start_token = start.replace("-", "")
        end_token = end.replace("-", "")
        market_token = "-".join(markets)
        rollback_token = "with_rollback" if require_rollback else "skip_rollback"
        name = f"{dataset}_{year}_{month_number}_{start_token}_{end_token}_{market_token}_{rollback_token}.zip"
    return config.ARCHIVE_DIR / name


def _verify_zip(zip_path: Path, expected_names: list[str]) -> None:
    with ZipFile(zip_path, "r") as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"ZIP CRC check failed for {bad_file}")
        actual_names = sorted(archive.namelist())
    if actual_names != sorted(expected_names):
        raise ValueError("ZIP file list does not match loose CSV files")
