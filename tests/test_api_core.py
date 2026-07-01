from __future__ import annotations

import sqlite3
import unittest

try:
    from fastapi import HTTPException
    from api.routes.daily_close import daily_close
    from api.routes.attention_notices import attention_notices
    from api.routes.disposal_notices import disposal_notices
    from api.routes.trading_days import trading_days
    from api.routes.batches import batches
    from api.routes.datasets import dataset_status
    from api.routes.errors import errors
    from api.routes.events import events
except ModuleNotFoundError as exc:
    HTTPException = None
    daily_close = None
    attention_notices = None
    disposal_notices = None
    trading_days = None
    batches = None
    dataset_status = None
    errors = None
    events = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


@unittest.skipIf(HTTPException is None, f"FastAPI route dependencies are unavailable: {FASTAPI_IMPORT_ERROR}")
class CoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._create_schema()
        self._seed()

    def tearDown(self) -> None:
        self.conn.close()

    def test_daily_close_field_selection_and_quality(self) -> None:
        body = daily_close(
            start="2026-06-15",
            end="2026-06-15",
            stock_id="2330",
            market="TWSE",
            fields="trade_date,stock_id,close_cents,volume",
            require_quality="ok",
            conn=self.conn,
        )

        self.assertEqual(
            body["data"],
            [{"trade_date": "2026-06-15", "stock_id": "2330", "close_cents": 12345, "volume": 1000}],
        )
        self.assertEqual(body["meta"]["price_scale"], 100)

    def test_attention_notice_quality_uses_overlapping_range_batch(self) -> None:
        body = attention_notices(
            start="2026-06-15",
            end="2026-06-15",
            stock_id="2330",
            market="TWSE",
            require_quality="ok",
            conn=self.conn,
        )

        self.assertEqual(body["data"][0]["notice_text"], "attention reason")
        self.assertEqual(body["meta"]["quality"]["status"], "OK")

    def test_disposal_notice_active_date_filter(self) -> None:
        body = disposal_notices(
            start="2026-06-15",
            end="2026-06-15",
            active_date="2026-06-20",
            stock_id="2330",
            market="TWSE",
            fields="trade_date,stock_id,disposal_start_date,disposal_end_date",
            require_quality="ok",
            conn=self.conn,
        )

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["disposal_start_date"], "2026-06-16")

    def test_trading_days_pagination(self) -> None:
        body = trading_days(
            start="2026-06-15",
            end="2026-06-17",
            limit=2,
            conn=self.conn,
        )

        self.assertEqual(len(body["data"]), 2)
        self.assertTrue(body["meta"]["pagination"]["has_more"])
        self.assertEqual(body["meta"]["pagination"]["limit"], 2)

    def test_batches_reject_invalid_date_filter(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            batches(start="20260615", end=None, batch_status=None, conn=self.conn)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"], "INVALID_DATE")

    def test_dataset_status_prefers_canonical_latest_period(self) -> None:
        self.conn.execute(
            "INSERT INTO import_batches(batch_id, dataset, market, period, status, row_count, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "daily_close:reconcile:2026-06:5483",
                "daily_close",
                None,
                "2026-06:5483",
                "OK",
                1,
                "2026-06-30T00:00:00Z",
            ),
        )

        body = dataset_status("daily_close", start=None, end=None, conn=self.conn)

        self.assertEqual(body["data"]["latest_period"], "2026-06-15")

    def test_errors_reject_invalid_date_filter(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            errors(dataset="daily_close", start="20260615", end=None, conn=self.conn)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"], "INVALID_DATE")

    def test_errors_and_events_filters(self) -> None:
        error_body = errors(
            dataset="daily_close",
            severity="WARN",
            start="2026-06-15",
            end="2026-06-15",
            conn=self.conn,
        )
        event_body = events(dataset="daily_close", start=None, end=None, stock_id="2330", event_type="DOUBLE_CHECK", conn=self.conn)

        self.assertEqual(error_body["data"][0]["code"], "SAMPLE_WARN")
        self.assertEqual(error_body["meta"]["filters"]["from"], "2026-06-15")
        self.assertEqual(event_body["data"][0]["stored_close_cents"], 12345)

    def test_pwa_query_route_smoke_for_table_contract(self) -> None:
        close_body = daily_close(
            start="2026-06-15",
            end="2026-06-15",
            market="TWSE",
            require_quality="any",
            limit=10000,
            offset=0,
            conn=self.conn,
        )
        attention_body = attention_notices(
            start="2026-06-15",
            end="2026-06-15",
            market="TWSE",
            require_quality="any",
            limit=10000,
            offset=0,
            conn=self.conn,
        )
        disposal_body = disposal_notices(
            start="2026-06-15",
            end="2026-06-15",
            market="TWSE",
            require_quality="any",
            limit=10000,
            offset=0,
            conn=self.conn,
        )

        for body in (close_body, attention_body, disposal_body):
            self.assertTrue(body["ok"])
            self.assertIsInstance(body["data"], list)
            self.assertIn("fields", body["meta"])
            self.assertIn("pagination", body["meta"])
            self.assertEqual(body["meta"]["pagination"]["limit"], 10000)
            self.assertEqual(body["meta"]["pagination"]["offset"], 0)

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE daily_close(
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
              PRIMARY KEY(trade_date, stock_id, market)
            );
            CREATE TABLE attention_notices(
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT NOT NULL,
              notice_text TEXT NOT NULL,
              PRIMARY KEY(trade_date, market, stock_id)
            );
            CREATE TABLE disposal_notices(
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT NOT NULL,
              disposal_start_date TEXT NOT NULL,
              disposal_end_date TEXT NOT NULL,
              reason_text TEXT NOT NULL,
              disposal_text TEXT NOT NULL,
              PRIMARY KEY(trade_date, market, stock_id, disposal_start_date, disposal_end_date)
            );
            CREATE TABLE trading_days(
              trade_date TEXT PRIMARY KEY,
              is_open INTEGER NOT NULL,
              source TEXT NOT NULL,
              note TEXT
            );
            CREATE TABLE import_batches(
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
            CREATE TABLE data_events(
              event_id TEXT PRIMARY KEY,
              batch_id TEXT NOT NULL,
              dataset TEXT NOT NULL,
              market TEXT,
              period TEXT NOT NULL,
              stock_id TEXT,
              stock_name TEXT,
              event_type TEXT NOT NULL,
              source_open TEXT,
              source_high TEXT,
              source_low TEXT,
              source_close TEXT,
              stored_open INTEGER,
              stored_high INTEGER,
              stored_low INTEGER,
              stored_close INTEGER,
              reference_period TEXT,
              reference_value INTEGER,
              note TEXT,
              created_at TEXT NOT NULL
            );
            """
        )

    def _seed(self) -> None:
        self.conn.execute(
            "INSERT INTO daily_close VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-15", "2330", "台積電", "TWSE", 12000, 12500, 11900, 12345, 1000, 12345000, 10),
        )
        self.conn.execute(
            "INSERT INTO attention_notices VALUES (?, ?, ?, ?, ?)",
            ("2026-06-15", "TWSE", "2330", "台積電", "attention reason"),
        )
        self.conn.execute(
            "INSERT INTO disposal_notices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-15", "TWSE", "2330", "台積電", "2026-06-16", "2026-06-30", "reason", "text"),
        )
        for trade_date, is_open in [("2026-06-15", 1), ("2026-06-16", 1), ("2026-06-17", 1)]:
            self.conn.execute(
                "INSERT INTO trading_days VALUES (?, ?, ?, ?)",
                (trade_date, is_open, "test", None),
            )
        batches_data = [
            ("daily_close:TWSE:2026-06-15", "daily_close", "TWSE", "2026-06-15", "OK", 1),
            ("attention_notice:TWSE:2026-06-01..2026-06-30", "attention_notice", "TWSE", "2026-06-01..2026-06-30", "OK", 1),
            ("disposal_notice:TWSE:2026-06-01..2026-06-30", "disposal_notice", "TWSE", "2026-06-01..2026-06-30", "OK", 1),
        ]
        for batch in batches_data:
            self.conn.execute(
                "INSERT INTO import_batches(batch_id, dataset, market, period, status, row_count, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '2026-06-15T00:00:00Z')",
                batch,
            )
        self.conn.execute(
            "INSERT INTO import_errors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "err1",
                "daily_close:TWSE:2026-06-15",
                "WARN",
                "SAMPLE_WARN",
                "sample warning",
                "2330",
                "x",
                "2026-06-15T00:00:00Z",
            ),
        )
        self.conn.execute(
            "INSERT INTO data_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt1",
                "daily_close:TWSE:2026-06-15",
                "daily_close",
                "TWSE",
                "2026-06-15",
                "2330",
                "台積電",
                "DOUBLE_CHECK",
                "120.00",
                "125.00",
                "119.00",
                "123.45",
                12000,
                12500,
                11900,
                12345,
                None,
                None,
                "ok",
                "2026-06-15T00:00:00Z",
            ),
        )


if __name__ == "__main__":
    unittest.main()
