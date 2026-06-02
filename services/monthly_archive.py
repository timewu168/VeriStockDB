from __future__ import annotations

from pathlib import Path
import sqlite3
from zipfile import ZipFile, ZIP_DEFLATED

import config
from services import batch_status


def archive_month(
    conn: sqlite3.Connection,
    *,
    dataset: str = config.DATASET_DAILY_CLOSE,
    month: str,
) -> Path:
    if dataset != config.DATASET_DAILY_CLOSE:
        raise ValueError("v1 monthly archive only supports daily_close")
    audit_key = f"audit:{dataset}:{month}"
    if batch_status.get_setting(conn, audit_key) != "OK":
        raise ValueError(f"monthly audit is not OK for {dataset} {month}")

    year, month_number = month.split("-")
    csv_dir = config.CSV_DIR / "daily_close" / year
    files = sorted(
        list(csv_dir.glob(f"{year}{month_number}??CloseSII.csv"))
        + list(csv_dir.glob(f"{year}{month_number}??CloseOTC.csv"))
    )
    if not files:
        raise FileNotFoundError(f"no loose CSV files found for {dataset} {month}")

    zip_path = config.CSV_DIR / "monthly_zip" / f"{dataset}_{year}_{month_number}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    expected_names = [file.name for file in files]
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, arcname=file.name)

    _verify_zip(zip_path, expected_names)
    conn.execute(
        """
        UPDATE import_batches
        SET archived_zip = ?
        WHERE dataset = ? AND period LIKE ? AND status IN ('OK', 'FIXED')
        """,
        (str(zip_path), dataset, month + "-%"),
    )
    delete_loose = batch_status.get_setting(
        conn, "delete_loose_csv_after_verified_zip", "1"
    )
    if delete_loose == "1":
        for file in files:
            file.unlink()
    return zip_path


def _verify_zip(zip_path: Path, expected_names: list[str]) -> None:
    with ZipFile(zip_path, "r") as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"ZIP CRC check failed for {bad_file}")
        actual_names = sorted(archive.namelist())
    if actual_names != sorted(expected_names):
        raise ValueError("ZIP file list does not match loose CSV files")
