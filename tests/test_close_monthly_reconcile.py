from __future__ import annotations

import sqlite3
import unittest

from services.close_monthly_reconcile import (
    parse_official_close_month_json,
    reconcile_close_month,
)


class CloseMonthlyReconcileTests(unittest.TestCase):
    def test_parse_twse_json_uses_shares_and_cents(self) -> None:
        payload = {
            "stat": "OK",
            "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
            "data": [["115/06/01", "60,942,792", "1", "2,355.00", "2,415.00", "2,350.00", "2,355.00"]],
        }

        rows = parse_official_close_month_json(payload, market="TWSE")

        self.assertEqual(rows[0].trade_date, "2026-06-01")
        self.assertEqual(rows[0].close, 235500)
        self.assertEqual(rows[0].volume, 60942792)

    def test_parse_tpex_json_converts_lots_to_shares(self) -> None:
        payload = {
            "stat": "ok",
            "tables": [
                {
                    "fields": ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤"],
                    "data": [["115/06/01", "25,949", "4,452,419", "174.50", "179.50", "167.00", "168.50"]],
                }
            ],
        }

        rows = parse_official_close_month_json(payload, market="TPEX")

        self.assertEqual(rows[0].trade_date, "2026-06-01")
        self.assertEqual(rows[0].close, 16850)
        self.assertEqual(rows[0].volume, 25949000)

    def test_reconcile_ok_records_month_and_target_batches(self) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO daily_close VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-01", "0050", "元大台灣50", "TWSE", 1000, 1000, 1000, 1000, 1000, 0, 0),
        )

        result = reconcile_close_month(
            conn,
            month="2026-06",
            markets=("TWSE",),
            stock_ids=("0050",),
            start="2026-06-01",
            end="2026-06-01",
            fetcher=lambda market, month, stock_id: {
                "stat": "OK",
                "fields": ["日期", "成交股數", "收盤價"],
                "data": [["115/06/01", "1,000", "10.00"]],
            },
        )

        self.assertEqual(result.status, "OK")
        statuses = conn.execute(
            "SELECT market, period, status FROM import_batches ORDER BY market, period"
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in statuses],
            [
                ("ALL", "2026-06", "OK"),
                ("TWSE", "2026-06:0050", "OK"),
            ],
        )

    def test_tpex_volume_allows_monthly_lot_rounding(self) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO daily_close VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-01", "5483", "中美晶", "TPEX", 1000, 1000, 1000, 16850, 25948950, 0, 0),
        )

        result = reconcile_close_month(
            conn,
            month="2026-06",
            markets=("TPEX",),
            stock_ids=("5483",),
            start="2026-06-01",
            end="2026-06-01",
            fetcher=lambda market, month, stock_id: {
                "stat": "ok",
                "tables": [
                    {
                        "fields": ["日 期", "成交張數", "收盤"],
                        "data": [["115/06/01", "25,949", "168.50"]],
                    }
                ],
            },
        )

        self.assertEqual(result.status, "OK")

    def test_reconcile_mismatch_records_recheck_errors(self) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO daily_close VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-01", "0050", "元大台灣50", "TWSE", 1000, 1000, 1000, 1000, 1000, 0, 0),
        )

        result = reconcile_close_month(
            conn,
            month="2026-06",
            markets=("TWSE",),
            stock_ids=("0050",),
            start="2026-06-01",
            end="2026-06-01",
            fetcher=lambda market, month, stock_id: {
                "stat": "OK",
                "fields": ["日期", "成交股數", "收盤價"],
                "data": [["115/06/01", "2,000", "11.00"]],
            },
        )

        self.assertEqual(result.status, "RECHECK")
        batch = conn.execute(
            "SELECT status, error_summary FROM import_batches WHERE period = '2026-06'"
        ).fetchone()
        self.assertEqual(batch["status"], "RECHECK")
        self.assertIn("close mismatch", batch["error_summary"])

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE daily_close (
              trade_date TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT,
              market TEXT NOT NULL,
              open INTEGER,
              high INTEGER,
              low INTEGER,
              close INTEGER,
              volume INTEGER,
              amount INTEGER,
              transactions INTEGER,
              PRIMARY KEY (trade_date, stock_id, market)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE import_batches (
              batch_id TEXT PRIMARY KEY,
              dataset TEXT NOT NULL,
              market TEXT,
              period TEXT NOT NULL,
              status TEXT NOT NULL,
              row_count INTEGER,
              error_summary TEXT,
              source_file TEXT,
              source_sha256 TEXT,
              retry_count INTEGER NOT NULL DEFAULT 0,
              archived_zip TEXT,
              checked_at TEXT NOT NULL,
              manual_approved INTEGER NOT NULL DEFAULT 0,
              manual_approved_at TEXT,
              manual_approved_reason TEXT,
              note TEXT
            )
            """
        )
        conn.execute("CREATE UNIQUE INDEX uq_import_batches_scope ON import_batches(dataset, market, period)")
        conn.execute(
            """
            CREATE TABLE import_errors (
              error_id TEXT PRIMARY KEY,
              batch_id TEXT NOT NULL,
              severity TEXT NOT NULL,
              code TEXT NOT NULL,
              message TEXT NOT NULL,
              sample_stock_id TEXT,
              sample_value TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        return conn


if __name__ == "__main__":
    unittest.main()
