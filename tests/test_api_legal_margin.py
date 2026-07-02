from __future__ import annotations

import sqlite3
import unittest

try:
    from fastapi import HTTPException
    from api.dataset_registry import list_datasets
    from api.routes.datasets import dataset_status, datasets_status_summary
    from api.routes.day_trading import day_trading
    from api.routes.legal_investors import legal_investors
    from api.routes.margin_trading import margin_trading
    from api.routes.monthly_revenue import monthly_revenue
except ModuleNotFoundError as exc:
    HTTPException = None
    list_datasets = None
    dataset_status = None
    datasets_status_summary = None
    day_trading = None
    legal_investors = None
    margin_trading = None
    monthly_revenue = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


@unittest.skipIf(HTTPException is None, f"FastAPI route dependencies are unavailable: {FASTAPI_IMPORT_ERROR}")
class LegalMarginApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = self._conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_legal_investors_query_fields_and_quality(self) -> None:
        body = legal_investors(
            start="2026-06-15",
            end="2026-06-15",
            stock_id="2330",
            market="TWSE",
            fields="trade_date,market,stock_id,foreign_net,dealer_hedge_net",
            require_quality="ok",
            conn=self.conn,
        )
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["data"],
            [
                {
                    "trade_date": "2026-06-15",
                    "market": "TWSE",
                    "stock_id": "2330",
                    "foreign_net": 100,
                    "dealer_hedge_net": -3,
                }
            ],
        )
        self.assertEqual(body["meta"]["quality"]["status"], "OK")

    def test_margin_trading_query_pagination(self) -> None:
        body = margin_trading(
            start="2026-06-15",
            end="2026-06-15",
            fields="trade_date,stock_id,margin_balance,short_balance,note",
            limit=1,
            conn=self.conn,
        )
        self.assertEqual(len(body["data"]), 1)
        self.assertTrue(body["meta"]["pagination"]["has_more"])
        self.assertEqual(body["data"][0]["stock_id"], "5483")

    def test_day_trading_query_fields_and_pagination(self) -> None:
        body = day_trading(
            start="2026-06-30",
            end="2026-06-30",
            stock_ids="2330,5483",
            fields="trade_date,market,stock_id,day_trade_volume,day_trade_buy_amount",
            limit=1,
            conn=self.conn,
        )
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["data"]), 1)
        self.assertTrue(body["meta"]["pagination"]["has_more"])
        self.assertEqual(
            body["data"][0],
            {
                "trade_date": "2026-06-30",
                "market": "TPEX",
                "stock_id": "5483",
                "day_trade_volume": 2000,
                "day_trade_buy_amount": 100000,
            },
        )

    def test_monthly_revenue_query_fields_and_quality(self) -> None:
        body = monthly_revenue(
            start="2026-05",
            end="2026-05",
            stock_id="2330",
            market="TWSE",
            fields="revenue_month,market,stock_id,current_month_revenue,cumulative_growth_pct",
            require_quality="ok",
            conn=self.conn,
        )
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["data"],
            [
                {
                    "revenue_month": "2026-05",
                    "market": "TWSE",
                    "stock_id": "2330",
                    "current_month_revenue": 1000,
                    "cumulative_growth_pct": 7.5,
                }
            ],
        )
        self.assertEqual(body["meta"]["unit"], "thousand_twd")
        self.assertEqual(body["meta"]["quality"]["status"], "OK")

    def test_quality_rejected_for_problem_batch(self) -> None:
        self.conn.execute(
            "UPDATE import_batches SET status = 'RECHECK', error_summary = 'sample issue' "
            "WHERE dataset = 'margin' AND market = 'TWSE' AND period = '2026-06-15'"
        )
        with self.assertRaises(HTTPException) as cm:
            margin_trading(
                start="2026-06-15",
                end="2026-06-15",
                market="TWSE",
                require_quality="ok",
                conn=self.conn,
            )

        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], "QUALITY_REJECTED")

    def test_datasets_include_legal_and_margin(self) -> None:
        datasets = {row.dataset for row in list_datasets()}
        self.assertIn("legal_investor", datasets)
        self.assertIn("margin", datasets)
        self.assertIn("day_trading", datasets)
        self.assertIn("revenue", datasets)

    def test_revenue_dataset_status_falls_back_to_canonical_table(self) -> None:
        body = dataset_status(
            "revenue",
            start="2026-05",
            end="2026-05",
            conn=self.conn,
        )

        self.assertEqual(body["data"]["latest_period"], "2026-05")
        self.assertEqual(body["data"]["period_type"], "month")

    def test_revenue_dataset_status_rejects_compact_month(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            dataset_status("revenue", start="202605", end="2026-05", conn=self.conn)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"], "INVALID_DATE")

    def test_datasets_status_summary_returns_all_supported_datasets(self) -> None:
        body = datasets_status_summary(conn=self.conn)

        rows = {row["dataset"]: row for row in body["data"]}
        self.assertIn("legal_investor", rows)
        self.assertIn("margin", rows)
        self.assertIn("day_trading", rows)
        self.assertIn("revenue", rows)
        self.assertEqual(rows["revenue"]["latest_period"], "2026-05")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self._create_schema(conn)
        self._seed(conn)
        return conn

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
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
              PRIMARY KEY(trade_date, stock_id, market)
            );
            CREATE TABLE attention_notices (
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT NOT NULL,
              notice_text TEXT NOT NULL,
              PRIMARY KEY(trade_date, market, stock_id)
            );
            CREATE TABLE disposal_notices (
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
            CREATE TABLE legal_investors (
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT NOT NULL,
              foreign_buy INTEGER NOT NULL,
              foreign_sell INTEGER NOT NULL,
              foreign_net INTEGER NOT NULL,
              investment_trust_buy INTEGER NOT NULL,
              investment_trust_sell INTEGER NOT NULL,
              investment_trust_net INTEGER NOT NULL,
              dealer_buy INTEGER NOT NULL,
              dealer_sell INTEGER NOT NULL,
              dealer_net INTEGER NOT NULL,
              dealer_hedge_buy INTEGER NOT NULL,
              dealer_hedge_sell INTEGER NOT NULL,
              dealer_hedge_net INTEGER NOT NULL,
              PRIMARY KEY (trade_date, market, stock_id)
            );
            CREATE TABLE margin_trading (
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT NOT NULL,
              margin_buy INTEGER NOT NULL,
              margin_sell INTEGER NOT NULL,
              margin_cash_repay INTEGER NOT NULL,
              previous_margin_balance INTEGER NOT NULL,
              margin_balance INTEGER NOT NULL,
              margin_limit INTEGER NOT NULL,
              short_buy INTEGER NOT NULL,
              short_sell INTEGER NOT NULL,
              short_stock_repay INTEGER NOT NULL,
              previous_short_balance INTEGER NOT NULL,
              short_balance INTEGER NOT NULL,
              short_limit INTEGER NOT NULL,
              offsetting INTEGER NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              PRIMARY KEY (trade_date, market, stock_id)
            );
            CREATE TABLE day_trading (
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              stock_name TEXT NOT NULL,
              suspend_sell_note TEXT,
              day_trade_volume INTEGER NOT NULL,
              day_trade_buy_amount INTEGER NOT NULL,
              day_trade_sell_amount INTEGER NOT NULL,
              PRIMARY KEY (trade_date, market, stock_id)
            );
            CREATE TABLE monthly_revenue (
              revenue_month TEXT NOT NULL,
              market TEXT NOT NULL,
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
            CREATE TABLE trading_days (
              trade_date TEXT PRIMARY KEY,
              is_open INTEGER NOT NULL,
              source TEXT NOT NULL,
              note TEXT
            );
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
            );
            CREATE TABLE import_errors (
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

    def _seed(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO legal_investors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-15",
                "TWSE",
                "2330",
                "台積電",
                1000,
                900,
                100,
                20,
                10,
                10,
                5,
                2,
                3,
                1,
                4,
                -3,
            ),
        )
        conn.execute(
            "INSERT INTO margin_trading VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-15",
                "TWSE",
                "2330",
                "台積電",
                1,
                2,
                0,
                100,
                99,
                1000,
                3,
                4,
                0,
                50,
                51,
                1000,
                7,
                "",
            ),
        )
        conn.execute(
            "INSERT INTO margin_trading VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-15",
                "TPEX",
                "5483",
                "中美晶",
                10,
                20,
                0,
                200,
                190,
                2000,
                30,
                40,
                0,
                60,
                70,
                2000,
                0,
                "X",
            ),
        )
        conn.execute(
            "INSERT INTO day_trading VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-30",
                "TWSE",
                "2330",
                "台積電",
                None,
                1000,
                500000,
                501000,
            ),
        )
        conn.execute(
            "INSERT INTO day_trading VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-30",
                "TPEX",
                "5483",
                "中美晶",
                "Y",
                2000,
                100000,
                101000,
            ),
        )
        conn.execute(
            "INSERT INTO monthly_revenue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-05",
                "TWSE",
                "2330",
                "台積電",
                "半導體業",
                "2026-07-01",
                "115/5",
                1000,
                900,
                800,
                11.1,
                25.0,
                5000,
                4651,
                7.5,
                "",
            ),
        )
        for trade_date in ("2026-06-15", "2026-06-30"):
            conn.execute(
                "INSERT INTO trading_days VALUES (?, 1, 'test', NULL)",
                (trade_date,),
            )
        batches = [
            ("legal_investor:TWSE:2026-06-15", "legal_investor", "TWSE", "2026-06-15", "OK", 1),
            ("margin:TWSE:2026-06-15", "margin", "TWSE", "2026-06-15", "OK", 1),
            ("margin:TPEX:2026-06-15", "margin", "TPEX", "2026-06-15", "OK", 1),
            ("day_trading:TWSE:2026-06-30", "day_trading", "TWSE", "2026-06-30", "OK", 1),
            ("day_trading:TPEX:2026-06-30", "day_trading", "TPEX", "2026-06-30", "OK", 1),
            ("revenue:TWSE:2026-05", "revenue", "TWSE", "2026-05", "OK", 1),
        ]
        for batch in batches:
            conn.execute(
                "INSERT INTO import_batches(batch_id, dataset, market, period, status, row_count, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '2026-06-15T00:00:00+00:00')",
                batch,
            )

    def test_status_summary_warns_when_one_market_lags_latest_open_date(self) -> None:
        conn = self._conn()
        try:
            conn.execute("INSERT INTO trading_days VALUES (?, 1, 'test', NULL)", ("2026-07-02",))
            conn.execute(
                "INSERT INTO legal_investors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-30",
                    "TWSE",
                    "2330",
                    "台積電",
                    1,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ),
            )
            conn.execute(
                "INSERT INTO legal_investors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-07-02",
                    "TPEX",
                    "5483",
                    "中美晶",
                    1,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ),
            )

            body = datasets_status_summary(conn=conn)

            rows = {row["dataset"]: row for row in body["data"]}
            legal = rows["legal_investor"]
            self.assertEqual(legal["latest_period"], "2026-07-02")
            self.assertEqual(legal["quality"]["status"], "WARN")
            self.assertEqual(legal["quality"]["health_status"], "WARN")
            self.assertEqual(legal["quality"]["gap_count"], 1)
            self.assertEqual(legal["quality"]["latest_by_market"]["TWSE"], "2026-06-30")
            self.assertEqual(legal["quality"]["latest_by_market"]["TPEX"], "2026-07-02")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
