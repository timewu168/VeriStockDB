from __future__ import annotations

from datetime import date
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

import config
from services.dataset_health_check import run_dataset_health_check

try:
    from api.routes.ops import ops_dataset_health_check
except ModuleNotFoundError:
    ops_dataset_health_check = None


class DatasetHealthCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "veristock.db"
        self._create_db()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dataset_health_check_reports_rows_duplicates_gaps_and_errors(self) -> None:
        result = run_dataset_health_check(db_path=self.db_path, today=date(2026, 7, 2))

        self.assertEqual(result.status, "ERROR")
        close = next(item for item in result.datasets if item["dataset"] == config.DATASET_DAILY_CLOSE)
        self.assertEqual(close["row_count"], 2)
        self.assertEqual(close["duplicate_keys"], 1)
        self.assertEqual(close["latest"]["TWSE"], "2026-07-01")
        self.assertEqual(close["gap"]["missing_count"], 1)
        self.assertEqual(close["gap"]["samples"], [{"market": "TWSE", "period": "2026-07-02"}])
        self.assertEqual(close["recent_error_count"], 1)
        self.assertEqual(close["recent_errors"][0]["code"], "BAD_SOURCE_FILE")

    def test_ops_route_returns_dataset_health_check(self) -> None:
        if ops_dataset_health_check is None:
            self.skipTest("FastAPI is not installed")
        with patch("api.routes.ops.config.DB_PATH", self.db_path):
            response = ops_dataset_health_check()

        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["status"], "ERROR")
        datasets = {item["dataset"]: item for item in response["data"]["datasets"]}
        self.assertIn(config.DATASET_DAILY_CLOSE, datasets)
        self.assertEqual(datasets[config.DATASET_DAILY_CLOSE]["duplicate_keys"], 1)

    def _create_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE trading_days(trade_date TEXT PRIMARY KEY, is_open INTEGER NOT NULL);
                CREATE TABLE daily_close(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE legal_investors(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE attention_notices(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE disposal_notices(
                  trade_date TEXT,
                  market TEXT,
                  stock_id TEXT,
                  disposal_start_date TEXT,
                  disposal_end_date TEXT
                );
                CREATE TABLE margin_trading(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE day_trading(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE monthly_revenue(revenue_month TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE import_batches(
                  batch_id TEXT PRIMARY KEY,
                  dataset TEXT NOT NULL,
                  market TEXT,
                  period TEXT NOT NULL,
                  status TEXT NOT NULL,
                  row_count INTEGER,
                  error_summary TEXT,
                  checked_at TEXT NOT NULL
                );
                CREATE TABLE import_errors(
                  error_id TEXT PRIMARY KEY,
                  batch_id TEXT NOT NULL,
                  severity TEXT NOT NULL,
                  code TEXT NOT NULL,
                  message TEXT NOT NULL,
                  sample_stock_id TEXT,
                  sample_value TEXT,
                  created_at TEXT NOT NULL
                );
                """
            )
            conn.executemany(
                "INSERT INTO trading_days VALUES (?, 1)",
                [("2026-07-01",), ("2026-07-02",)],
            )
            for table in (
                "legal_investors",
                "attention_notices",
                "margin_trading",
                "day_trading",
            ):
                self._insert_daily_rows(conn, table)
            conn.executemany(
                "INSERT INTO daily_close VALUES (?, ?, ?)",
                [
                    ("2026-07-01", "TWSE", "2330"),
                    ("2026-07-01", "TWSE", "2330"),
                ],
            )
            conn.executemany(
                "INSERT INTO disposal_notices VALUES (?, ?, ?, ?, ?)",
                [
                    ("2026-07-01", "TWSE", "2330", "2026-07-01", "2026-07-10"),
                    ("2026-07-02", "TWSE", "2330", "2026-07-02", "2026-07-11"),
                ],
            )
            conn.executemany(
                "INSERT INTO monthly_revenue VALUES (?, ?, ?)",
                [("2026-05", "TWSE", "2330"), ("2026-05", "TPEX", "8069")],
            )
            for dataset in (
                config.DATASET_DAILY_CLOSE,
                config.DATASET_LEGAL_INVESTOR,
                config.DATASET_ATTENTION_NOTICE,
                config.DATASET_DISPOSAL_NOTICE,
                config.DATASET_MARGIN,
                config.DATASET_DAY_TRADING,
            ):
                markets = ("TWSE", "TPEX") if dataset != config.DATASET_DAILY_CLOSE else ("TWSE",)
                for market in markets:
                    periods = ["2026-07-01", "2026-07-02"]
                    if dataset == config.DATASET_DAILY_CLOSE:
                        periods = ["2026-07-01"]
                    for period in periods:
                        self._insert_batch(conn, dataset, market, period)
            for market in config.MARKETS:
                self._insert_batch(conn, config.DATASET_REVENUE, market, "2026-05")
            conn.execute(
                "INSERT INTO import_errors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "err-close",
                    f"{config.DATASET_DAILY_CLOSE}:TWSE:2026-07-01",
                    "BLOCK",
                    "BAD_SOURCE_FILE",
                    "sample bad source",
                    "2330",
                    "bad",
                    "2026-07-02T12:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _insert_daily_rows(self, conn: sqlite3.Connection, table: str) -> None:
        conn.executemany(
            f"INSERT INTO {table}(trade_date, market, stock_id) VALUES (?, ?, ?)",
            [("2026-07-01", "TWSE", "2330"), ("2026-07-02", "TWSE", "2330")],
        )

    def _insert_batch(
        self,
        conn: sqlite3.Connection,
        dataset: str,
        market: str,
        period: str,
        *,
        status: str = "OK",
    ) -> None:
        conn.execute(
            "INSERT INTO import_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{dataset}:{market}:{period}",
                dataset,
                market,
                period,
                status,
                1,
                None,
                "2026-07-02T12:00:00Z",
            ),
        )


if __name__ == "__main__":
    unittest.main()
