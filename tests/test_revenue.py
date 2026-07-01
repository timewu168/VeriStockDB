from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

import config
from ingest import revenue
from ingest.downloader import CooldownController, official_revenue_url


class RevenueDownloadTests(unittest.TestCase):
    def test_official_revenue_urls_match_documented_routes(self) -> None:
        self.assertEqual(
            official_revenue_url("TWSE", "115_5"),
            "https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9&functionName=show_file2&filePath=%2Ft21%2Fsii%2F&fileName=t21sc03_115_5.csv",
        )
        self.assertEqual(
            official_revenue_url("TPEX", "115_5"),
            "https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9&functionName=show_file2&filePath=%2Ft21%2Fotc%2F&fileName=t21sc03_115_5.csv",
        )

    def test_revenue_month_to_roc_month(self) -> None:
        self.assertEqual(revenue.revenue_month_to_roc_month("2026-05"), "115_5")
        self.assertEqual(revenue.revenue_month_to_roc_month("2013-01"), "102_1")

    def test_latest_published_revenue_month_uses_tenth_day_gate(self) -> None:
        self.assertEqual(
            revenue.latest_published_revenue_month(date(2026, 7, 1)),
            "2026-05",
        )
        self.assertEqual(
            revenue.latest_published_revenue_month(date(2026, 7, 10)),
            "2026-06",
        )
        self.assertEqual(
            revenue.latest_published_revenue_month(date(2026, 1, 9)),
            "2025-11",
        )

    def test_revenue_months_between(self) -> None:
        self.assertEqual(
            revenue.revenue_months_between("2025-11", "2026-02"),
            ["2025-11", "2025-12", "2026-01", "2026-02"],
        )

    def test_download_revenue_months_saves_valid_csv(self) -> None:
        original_csv_dir = config.CSV_DIR
        calls: list[tuple[str, str]] = []

        def fake_fetcher(market: str, roc_month: str) -> bytes:
            calls.append((market, roc_month))
            return _revenue_csv_bytes("2026-05")

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                results = revenue.download_revenue_months(
                    ["2026-05"],
                    markets=("TWSE",),
                    fetcher=fake_fetcher,
                    cooldowns={"TWSE": CooldownController(enabled=False)},
                    parallel_markets=False,
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [("TWSE", "115_5")])
        self.assertEqual(results[0].status, "OK")
        self.assertTrue(results[0].path and results[0].path.endswith("202605RevenueSII.csv"))

    def test_download_revenue_rejects_html(self) -> None:
        results = _download_revenue_with_temp_csv(
            fetcher=lambda market, roc_month: b"<html></html>",
        )

        self.assertEqual(results[0].status, "MISSING")
        self.assertIn("HTML", results[0].error or "")

    def test_download_revenue_rejects_header_only(self) -> None:
        results = _download_revenue_with_temp_csv(
            fetcher=lambda market, roc_month: _revenue_csv_bytes("2026-05", data_rows=False),
        )

        self.assertEqual(results[0].status, "MISSING")
        self.assertIn("no data rows", results[0].error or "")

    def test_download_revenue_rejects_month_mismatch(self) -> None:
        results = _download_revenue_with_temp_csv(
            fetcher=lambda market, roc_month: _revenue_csv_bytes("2026-04"),
        )

        self.assertEqual(results[0].status, "MISSING")
        self.assertIn("month mismatch", results[0].error or "")

    def test_parse_revenue_file_normalizes_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "202605RevenueSII.csv"
            path.write_bytes(_revenue_csv_bytes("2026-05"))

            records, problems = revenue.parse_revenue_file(path, "TWSE", "2026-05")

        self.assertEqual(problems, [])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.revenue_month, "2026-05")
        self.assertEqual(record.market, "TWSE")
        self.assertEqual(record.stock_id, "1101")
        self.assertEqual(record.report_date, "2026-07-01")
        self.assertEqual(record.roc_period, "115/5")
        self.assertEqual(record.current_month_revenue, 12612013)
        self.assertEqual(record.month_over_month_pct, 3.26)

    def test_dry_run_revenue_import_blocks_duplicate_keys(self) -> None:
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                path = revenue.revenue_file_path("TWSE", "2026-05")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_revenue_csv_bytes("2026-05", duplicate=True))
                conn = sqlite3.connect(":memory:")
                report = revenue.dry_run_revenue_import(
                    conn,
                    start="2026-05",
                    end="2026-05",
                    markets=("TWSE",),
                    report_dir=Path(temp_dir) / "reports",
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(report.expected_files, 1)
        self.assertEqual(report.duplicate_keys, 1)
        self.assertEqual(report.total_rows, 2)
        self.assertTrue(any(problem.problem == "DUPLICATE_KEY" for problem in report.problems))

    def test_import_revenue_range_inserts_and_blocks_overwrite(self) -> None:
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir) / "csv"
            try:
                path = revenue.revenue_file_path("TWSE", "2026-05")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_revenue_csv_bytes("2026-05"))
                conn = sqlite3.connect(":memory:")
                conn.executescript(
                    """
                    CREATE TABLE monthly_revenue (
                      revenue_month TEXT NOT NULL,
                      market TEXT NOT NULL CHECK (market IN ('TWSE', 'TPEX')),
                      stock_id TEXT NOT NULL,
                      stock_name TEXT NOT NULL,
                      industry TEXT NOT NULL,
                      report_date TEXT NOT NULL,
                      roc_period TEXT NOT NULL,
                      current_month_revenue INTEGER NOT NULL,
                      previous_month_revenue INTEGER NOT NULL,
                      previous_year_month_revenue INTEGER NOT NULL,
                      month_over_month_pct REAL,
                      year_over_year_pct REAL,
                      cumulative_revenue INTEGER NOT NULL,
                      previous_year_cumulative_revenue INTEGER NOT NULL,
                      cumulative_growth_pct REAL,
                      note TEXT NOT NULL DEFAULT '',
                      PRIMARY KEY (revenue_month, market, stock_id)
                    );
                    """
                )
                results = revenue.import_revenue_range(
                    conn,
                    start="2026-05",
                    end="2026-05",
                    markets=("TWSE",),
                    report_dir=Path(temp_dir) / "reports",
                )
                count = conn.execute("SELECT COUNT(*) FROM monthly_revenue").fetchone()[0]
                row = conn.execute(
                    "SELECT stock_name, report_date, current_month_revenue FROM monthly_revenue"
                ).fetchone()

                with self.assertRaisesRegex(ValueError, "target scope is not empty"):
                    revenue.import_revenue_range(
                        conn,
                        start="2026-05",
                        end="2026-05",
                        markets=("TWSE",),
                        report_dir=Path(temp_dir) / "reports",
                    )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(results[0].row_count, 1)
        self.assertEqual(count, 1)
        self.assertEqual(row, ("台泥", "2026-07-01", 12612013))

    def test_update_revenue_month_inserts_and_skips_existing(self) -> None:
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir) / "csv"
            try:
                conn = sqlite3.connect(":memory:")
                conn.executescript(_monthly_revenue_schema_sql())

                calls: list[tuple[str, str]] = []

                def fake_fetcher(market: str, roc_month: str) -> bytes:
                    calls.append((market, roc_month))
                    return _revenue_csv_bytes("2026-05")

                first = revenue.update_revenue_month(
                    conn,
                    month="2026-05",
                    markets=("TWSE",),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
                second = revenue.update_revenue_month(
                    conn,
                    month="2026-05",
                    markets=("TWSE",),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [("TWSE", "115_5")])
        self.assertEqual(first[0].status, "OK")
        self.assertEqual(first[0].row_count, 1)
        self.assertEqual(second[0].status, "EXISTS")
        self.assertEqual(second[0].row_count, 1)


def _revenue_csv_bytes(month: str, *, data_rows: bool = True, duplicate: bool = False) -> bytes:
    year, month_number = month.split("-")
    roc_period = f"{int(year) - 1911}/{int(month_number)}"
    rows = [
        "出表日期,資料年月,公司代號,公司名稱,產業別,營業收入-當月營收,營業收入-上月營收,營業收入-去年當月營收,營業收入-上月比較增減(%),營業收入-去年同月增減(%),累計營業收入-當月累計營收,累計營業收入-去年累計營收,累計營業收入-前期比較增減(%),備註",
    ]
    if data_rows:
        rows.append(f"115/07/01,{roc_period},1101,台泥,水泥工業,12612013,12213195,12619495,3.26,-0.05,60000000,59000000,1.69,")
        if duplicate:
            rows.append(f"115/07/01,{roc_period},1101,台泥,水泥工業,12612013,12213195,12619495,3.26,-0.05,60000000,59000000,1.69,")
    return "\n".join(rows).encode("utf-8-sig")


def _monthly_revenue_schema_sql() -> str:
    return """
    CREATE TABLE monthly_revenue (
      revenue_month TEXT NOT NULL,
      market TEXT NOT NULL CHECK (market IN ('TWSE', 'TPEX')),
      stock_id TEXT NOT NULL,
      stock_name TEXT NOT NULL,
      industry TEXT NOT NULL,
      report_date TEXT NOT NULL,
      roc_period TEXT NOT NULL,
      current_month_revenue INTEGER NOT NULL,
      previous_month_revenue INTEGER NOT NULL,
      previous_year_month_revenue INTEGER NOT NULL,
      month_over_month_pct REAL,
      year_over_year_pct REAL,
      cumulative_revenue INTEGER NOT NULL,
      previous_year_cumulative_revenue INTEGER NOT NULL,
      cumulative_growth_pct REAL,
      note TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (revenue_month, market, stock_id)
    );
    """


def _download_revenue_with_temp_csv(fetcher):
    original_csv_dir = config.CSV_DIR
    with tempfile.TemporaryDirectory() as temp_dir:
        config.CSV_DIR = Path(temp_dir)
        try:
            return revenue.download_revenue_months(
                ["2026-05"],
                markets=("TWSE",),
                fetcher=fetcher,
                cooldowns={"TWSE": CooldownController(enabled=False)},
                parallel_markets=False,
                max_attempts=1,
            )
        finally:
            config.CSV_DIR = original_csv_dir
