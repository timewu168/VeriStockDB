from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

try:
    from api.disposition_utils import disposition_notice_id
    from api.routes.stocks import disposition_detail, stock_dispositions, stock_warnings
    from fastapi import HTTPException
except ModuleNotFoundError as exc:
    HTTPException = None
    disposition_detail = None
    disposition_notice_id = None
    stock_dispositions = None
    stock_warnings = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from db import connection as db_connection


@unittest.skipIf(HTTPException is None, f"FastAPI dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class StockDetailApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        db_connection.init_db(self.db_path, seed_trading_days=False)
        self.conn = db_connection.connect(self.db_path)
        self._seed()

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_detail_selects_requested_event_and_returns_latest_30_trading_rows(self) -> None:
        event_id = disposition_notice_id(
            "TPEX", "2492", "2026-06-23", "2026-06-24", "2026-07-07"
        )
        body = disposition_detail(
            market="TPEX",
            stock_id="2492",
            disposition_id=event_id,
            _=None,
            conn=self.conn,
            as_of_date="2026-07-15",
        )

        self.assertEqual(body["data"]["stock"]["stock_name"], "華新科")
        self.assertEqual(body["data"]["disposition"]["id"], event_id)
        self.assertEqual(body["data"]["disposition"]["interval_minutes"], 20)
        self.assertEqual(body["data"]["disposition"]["status"], "ended")
        self.assertEqual(len(body["data"]["ohlcv"]), 30)
        self.assertEqual(
            [row["date"] for row in body["data"]["ohlcv"]],
            sorted(row["date"] for row in body["data"]["ohlcv"]),
        )
        self.assertNotIn("2026-07-16", [row["date"] for row in body["data"]["ohlcv"]])
        self.assertEqual(body["meta"]["price_scale"], 100)
        self.assertEqual(body["meta"]["institutional_unit"], "lots")

    def test_pre_start_reference_uses_three_open_rows_before_start(self) -> None:
        body = disposition_detail(
            market="TPEX",
            stock_id="2492",
            disposition_id=None,
            _=None,
            conn=self.conn,
            as_of_date="2026-06-25",
        )

        reference = body["data"]["pre_start_reference"]
        self.assertTrue(reference["complete"])
        self.assertEqual(
            [item["date"] for item in reference["trading_days"]],
            ["2026-06-19", "2026-06-22", "2026-06-23"],
        )
        self.assertEqual(reference["three_day_high_cents"], 24550)

    def test_detail_does_not_fill_missing_series_with_zero(self) -> None:
        body = disposition_detail(
            market="TPEX",
            stock_id="2492",
            disposition_id=None,
            _=None,
            conn=self.conn,
            as_of_date="2026-07-15",
        )

        self.assertEqual(len(body["data"]["institutional"]), 1)
        self.assertEqual(len(body["data"]["margin"]), 1)
        self.assertEqual(body["data"]["institutional"][0]["foreign_net_lots"], -1200)

    def test_unknown_disposition_id_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            disposition_detail(
                market="TPEX",
                stock_id="2492",
                disposition_id="disp_missing",
                _=None,
                conn=self.conn,
                as_of_date="2026-07-15",
            )
        self.assertEqual(cm.exception.status_code, 404)

    def test_warning_history_is_descending_paginated_and_preserves_official_text(self) -> None:
        body = stock_warnings(
            market="TPEX", stock_id="2492", limit=1, offset=0, _=None, conn=self.conn
        )

        self.assertEqual(body["data"]["total"], 2)
        self.assertEqual(body["data"]["items"][0]["announcement_date"], "2026-07-14")
        self.assertEqual(body["data"]["items"][0]["clauses"], ["第一款", "第四款"])
        self.assertIn("<script>", body["data"]["items"][0]["official_text"])
        self.assertTrue(body["meta"]["pagination"]["has_more"])

    def test_disposition_history_is_descending_and_normalized(self) -> None:
        body = stock_dispositions(
            market="TPEX",
            stock_id="2492",
            limit=20,
            offset=0,
            _=None,
            conn=self.conn,
            as_of_date="2026-07-15",
        )

        self.assertEqual(body["data"]["total"], 2)
        self.assertEqual(body["data"]["items"][0]["announcement_date"], "2026-06-23")
        self.assertEqual(body["data"]["items"][0]["business_days"], 10)
        self.assertEqual(body["data"]["items"][0]["notice_status"], "published")
        self.assertEqual(body["data"]["items"][1]["notice_status"], "cancelled")

    def _seed(self) -> None:
        self.conn.execute(
            """
            INSERT INTO security_master(
              market, stock_id, stock_name, industry_code, industry_name,
              effective_from, effective_to, source_updated_date, source_url
            ) VALUES ('TPEX', '2492', '華新科', '28', '電子零組件業',
                      '2020-01-01', NULL, '2026-07-15', 'test')
            """
        )
        open_days = [
            "2026-06-19", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25",
            "2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02",
            "2026-07-03", "2026-07-06", "2026-07-07",
        ]
        self.conn.executemany(
            "INSERT INTO trading_days(trade_date, is_open, source, note) VALUES (?, 1, 'test', '')",
            [(day,) for day in open_days],
        )
        all_dates = [f"2026-05-{day:02d}" for day in range(1, 32)] + open_days + ["2026-07-14", "2026-07-16"]
        daily_rows = []
        for index, day in enumerate(all_dates):
            high = 20000 + index * 10
            if day == "2026-06-19":
                high = 22050
            elif day == "2026-06-22":
                high = 23800
            elif day == "2026-06-23":
                high = 24550
            daily_rows.append((day, high - 100, high, high - 200, high - 50, 1000 + index))
        self.conn.executemany(
            """
            INSERT INTO daily_close(
              trade_date, stock_id, stock_name, market, open, high, low, close,
              volume, amount, transactions
            ) VALUES (?, '2492', '華新科', 'TPEX', ?, ?, ?, ?, ?, 0, 0)
            """,
            daily_rows,
        )
        notices = [
            (
                "2025-01-02", "2025-01-03", "2025-01-10", "舊處置",
                "取消處置公告，約每5分鐘撮合一次",
            ),
            (
                "2026-06-23", "2026-06-24", "2026-07-07", "連續三次",
                "處置公告，如遇休市則順延執行，約每20分鐘撮合一次",
            ),
        ]
        self.conn.executemany(
            """
            INSERT INTO disposal_notices(
              trade_date, market, stock_id, stock_name, disposal_start_date,
              disposal_end_date, reason_text, disposal_text
            ) VALUES (?, 'TPEX', '2492', '華新科', ?, ?, ?, ?)
            """,
            notices,
        )
        self.conn.executemany(
            """
            INSERT INTO attention_notices(trade_date, market, stock_id, stock_name, notice_text)
            VALUES (?, 'TPEX', '2492', '華新科', ?)
            """,
            [
                ("2026-07-13", "舊原因(第三款)"),
                ("2026-07-14", "完整官方內容(第一款)<script>alert(1)</script>(第四款)"),
            ],
        )
        self.conn.execute(
            """
            INSERT INTO legal_investors(
              trade_date, market, stock_id, stock_name, foreign_buy, foreign_sell,
              foreign_net, investment_trust_buy, investment_trust_sell,
              investment_trust_net, dealer_buy, dealer_sell, dealer_net,
              dealer_hedge_buy, dealer_hedge_sell, dealer_hedge_net
            ) VALUES ('2026-07-14', 'TPEX', '2492', '華新科', 0, 1200, -1200,
                      300, 0, 300, 0, 0, 0, 0, 0, 0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO margin_trading(
              trade_date, market, stock_id, stock_name, margin_buy, margin_sell,
              margin_cash_repay, previous_margin_balance, margin_balance, margin_limit,
              short_buy, short_sell, short_stock_repay, previous_short_balance,
              short_balance, short_limit, offsetting, note
            ) VALUES ('2026-07-14', 'TPEX', '2492', '華新科', 0, 0, 0, 1000,
                      1100, 5000, 0, 0, 0, 100, 90, 1000, 0, '')
            """
        )


if __name__ == "__main__":
    unittest.main()
