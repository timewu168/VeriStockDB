from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

try:
    from fastapi import HTTPException
    from api.routes.disposal_notices import (
        active_disposal_notices,
        normalize_interval_minutes,
    )
except ModuleNotFoundError as exc:
    HTTPException = None
    active_disposal_notices = None
    normalize_interval_minutes = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from db import connection as db_connection


@unittest.skipIf(HTTPException is None, f"FastAPI dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class ActiveDisposalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        db_connection.init_db(self.db_path, seed_trading_days=False)
        self.conn = db_connection.connect(self.db_path)
        self._seed()

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_active_contract_deduplicates_sorts_and_rejects_unverified_rows(self) -> None:
        body = active_disposal_notices(
            interval="all",
            limit=100,
            offset=0,
            sort="announcement_date_desc",
            _=None,
            conn=self.conn,
            as_of_date="2026-07-15",
        )

        self.assertEqual(body["data"]["as_of_date"], "2026-07-15")
        self.assertEqual(body["data"]["total"], 2)
        self.assertEqual(
            [item["stock_id"] for item in body["data"]["items"]],
            ["2330", "4542"],
        )
        self.assertEqual(body["data"]["items"][0]["interval_minutes"], 20)
        self.assertEqual(body["data"]["items"][1]["industry_name"], "電機機械")
        self.assertEqual(
            set(body["data"]["items"][0]),
            {
                "stock_id",
                "stock_name",
                "market",
                "industry_name",
                "interval_minutes",
                "announcement_date",
                "disposal_start_date",
                "disposal_end_date",
            },
        )
        self.assertEqual(body["meta"]["quality"]["status"], "WARN")
        self.assertEqual(body["meta"]["quality"]["rejected"], 1)
        self.assertEqual(body["meta"]["quality"]["excluded"], 1)
        self.assertEqual(
            {message["code"] for message in body["messages"]},
            {"NON_STOCK_SECURITY_EXCLUDED", "UNRESOLVED_INTERVAL"},
        )

    def test_interval_filter_and_pagination(self) -> None:
        filtered = active_disposal_notices(
            interval="20",
            limit=1,
            offset=1,
            sort="announcement_date_desc",
            _=None,
            conn=self.conn,
            as_of_date="2026-07-15",
        )

        self.assertEqual(filtered["data"]["total"], 2)
        self.assertEqual(filtered["data"]["items"][0]["stock_id"], "4542")
        self.assertFalse(filtered["meta"]["pagination"]["has_more"])

    def test_no_effective_security_master_returns_503(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            active_disposal_notices(
                interval="all",
                limit=100,
                offset=0,
                sort="announcement_date_desc",
                _=None,
                conn=self.conn,
                as_of_date="2025-01-01",
            )

        self.assertEqual(cm.exception.status_code, 503)
        self.assertEqual(cm.exception.detail["code"], "DATA_UNAVAILABLE")

    def test_interval_normalization_accepts_official_variants(self) -> None:
        self.assertEqual(normalize_interval_minutes("約每五分鐘撮合一次"), 5)
        self.assertEqual(normalize_interval_minutes("約每20分鐘撮合一次"), 20)
        self.assertIsNone(normalize_interval_minutes("採人工管制撮合"))
        self.assertIsNone(normalize_interval_minutes("每5分鐘，另每20分鐘"))

    def _seed(self) -> None:
        security_rows = [
            ("TWSE", "2330", "台積電", "24", "半導體業"),
            ("TPEX", "4542", "科嶠", "05", "電機機械"),
            ("TWSE", "9999", "測試股", "20", "其他業"),
        ]
        self.conn.executemany(
            """
            INSERT INTO security_master(
              market, stock_id, stock_name, industry_code, industry_name,
              effective_from, effective_to, source_updated_date, source_url
            ) VALUES (?, ?, ?, ?, ?, '2026-01-01', NULL, '2026-07-15', 'test')
            """,
            security_rows,
        )
        notices = [
            ("2026-07-10", "TWSE", "2330", "台積電", "2026-07-11", "2026-07-20", "每5分鐘撮合一次"),
            ("2026-07-14", "TWSE", "2330", "台積電", "2026-07-15", "2026-07-28", "約每二十分鐘撮合一次"),
            ("2026-07-13", "TPEX", "4542", "科嶠", "2026-07-14", "2026-07-27", "約每20分鐘撮合一次"),
            ("2026-07-12", "TWSE", "059570", "測試權證", "2026-07-13", "2026-07-24", "約每五分鐘撮合一次"),
            ("2026-07-11", "TWSE", "9999", "測試股", "2026-07-12", "2026-07-25", "人工管制撮合"),
        ]
        self.conn.executemany(
            """
            INSERT INTO disposal_notices(
              trade_date, market, stock_id, stock_name, disposal_start_date,
              disposal_end_date, reason_text, disposal_text
            ) VALUES (?, ?, ?, ?, ?, ?, 'reason', ?)
            """,
            notices,
        )


if __name__ == "__main__":
    unittest.main()
