from __future__ import annotations

from datetime import date
from pathlib import Path
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


def _revenue_csv_bytes(month: str, *, data_rows: bool = True) -> bytes:
    year, month_number = month.split("-")
    roc_period = f"{int(year) - 1911}/{int(month_number)}"
    rows = [
        "出表日期,資料年月,公司代號,公司名稱,產業別,營業收入-當月營收,營業收入-上月營收,營業收入-去年當月營收,營業收入-上月比較增減(%),營業收入-去年同月增減(%),累計營業收入-當月累計營收,累計營業收入-去年累計營收,累計營業收入-前期比較增減(%),備註",
    ]
    if data_rows:
        rows.append(f"115/07/01,{roc_period},1101,台泥,水泥工業,12612013,12213195,12619495,3.26,-0.05,60000000,59000000,1.69,")
    return "\n".join(rows).encode("utf-8-sig")


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
