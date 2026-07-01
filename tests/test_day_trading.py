from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

import config
from ingest import day_trading
from ingest.downloader import (
    CooldownController,
    official_day_trading_file_name,
    official_day_trading_url,
)


SCHEMA = """
CREATE TABLE trading_days(
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
);
"""


class DayTradingDownloadTests(unittest.TestCase):
    def test_official_day_trading_urls_match_documented_routes(self) -> None:
        self.assertEqual(
            official_day_trading_url("TWSE", "2026-06-29"),
            "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date=20260629&selectType=All&response=csv",
        )
        self.assertEqual(
            official_day_trading_url("TPEX", "2026-06-29"),
            "https://www.tpex.org.tw/www/zh-tw/intraday/stat?type=Daily&date=2026%2F06%2F29&id=&response=csv",
        )

    def test_official_day_trading_file_names_are_csv(self) -> None:
        self.assertEqual(
            official_day_trading_file_name("TWSE", "2026-06-29"),
            "20260629DayTradingSII.csv",
        )
        self.assertEqual(
            official_day_trading_file_name("TPEX", "2026-06-29"),
            "20260629DayTradingOTC.csv",
        )

    def test_download_day_trading_range_uses_open_trading_days_only(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        for trade_date, is_open in (
            ("2026-06-26", 1),
            ("2026-06-27", 0),
            ("2026-06-29", 1),
        ):
            conn.execute(
                "INSERT INTO trading_days VALUES (?, ?, ?, ?)",
                (trade_date, is_open, "seed", ""),
            )
        calls: list[tuple[str, str]] = []
        original_csv_dir = config.CSV_DIR

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return _day_trading_csv_bytes(trade_date)

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                results = day_trading.download_day_trading_range(
                    conn,
                    start="2026-06-26",
                    end="2026-06-29",
                    markets=("TWSE",),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [("TWSE", "2026-06-26"), ("TWSE", "2026-06-29")])
        self.assertEqual([result.status for result in results], ["OK", "OK"])
        self.assertTrue(results[0].path and results[0].path.endswith("20260626DayTradingSII.csv"))

    def test_download_day_trading_dates_uses_independent_market_cooldowns(self) -> None:
        original_csv_dir = config.CSV_DIR
        calls: list[tuple[str, str]] = []
        cooldowns = {
            "TWSE": CooldownController(enabled=False),
            "TPEX": CooldownController(enabled=False),
        }

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return _day_trading_csv_bytes(trade_date)

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                results = day_trading.download_day_trading_dates(
                    ["2026-06-26", "2026-06-29"],
                    start="2026-06-26",
                    end="2026-06-29",
                    markets=("TWSE", "TPEX"),
                    fetcher=fake_fetcher,
                    cooldowns=cooldowns,
                    parallel_markets=True,
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(cooldowns["TWSE"].request_count, 2)
        self.assertEqual(cooldowns["TPEX"].request_count, 2)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(results), 4)

    def test_download_day_trading_rejects_csv_date_mismatch(self) -> None:
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                results = day_trading.download_day_trading_dates(
                    ["2026-06-29"],
                    start="2026-06-29",
                    end="2026-06-29",
                    markets=("TWSE",),
                    fetcher=lambda market, trade_date: _day_trading_csv_bytes("2026-06-30"),
                    cooldowns={"TWSE": CooldownController(enabled=False)},
                    parallel_markets=False,
                    max_attempts=1,
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(results[0].status, "MISSING")
        self.assertIn("date mismatch", results[0].error or "")
        self.assertIn("expected 2026-06-29 TWSE, got 2026-06-30", results[0].error or "")

    def test_download_day_trading_redownloads_existing_date_mismatch(self) -> None:
        original_csv_dir = config.CSV_DIR
        calls: list[tuple[str, str]] = []

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return _day_trading_csv_bytes(trade_date)

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                bad_path = day_trading.day_trading_file_path("TWSE", "2026-06-29")
                bad_path.parent.mkdir(parents=True, exist_ok=True)
                bad_path.write_bytes(_day_trading_csv_bytes("2026-06-30"))

                results = day_trading.download_day_trading_dates(
                    ["2026-06-29"],
                    start="2026-06-29",
                    end="2026-06-29",
                    markets=("TWSE",),
                    fetcher=fake_fetcher,
                    cooldowns={"TWSE": CooldownController(enabled=False)},
                    parallel_markets=False,
                )
                fixed = bad_path.read_bytes()
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [("TWSE", "2026-06-29")])
        self.assertEqual(results[0].status, "OK")
        day_trading._validate_day_trading_response(fixed, "TWSE", "2026-06-29")

    def test_download_day_trading_range_rejects_before_official_start(self) -> None:
        results = day_trading.download_day_trading_dates(
            ["2014-01-03"],
            start="2014-01-03",
            end="2014-01-03",
            markets=("TWSE",),
            fetcher=lambda market, trade_date: b"unused",
            cooldowns={"TWSE": CooldownController(enabled=False)},
            parallel_markets=False,
        )
        self.assertEqual(results[0].status, "MISSING")
        self.assertIn("2014-01-06", results[0].error or "")

    def test_inspect_day_trading_file_reports_twse_header_and_rows(self) -> None:
        content = "\n".join(
            [
                '"103年01月06日 當日沖銷交易統計資訊"',
                '"當日沖銷交易總成交股數","占比"',
                '"103年01月06日 當日沖銷交易標的及成交量值"',
                '"證券代號","證券名稱","暫停現股賣出後現款買進當沖註記","當日沖銷交易成交股數","當日沖銷交易買進成交金額","當日沖銷交易賣出成交金額",',
                '"1101","台泥","","127,000","5,608,450","5,570,250",',
                '"1102","亞泥","*","5,000","100,000","99,000",',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "twse.csv"
            path.write_bytes(content.encode("cp950"))
            inspection = day_trading.inspect_day_trading_file(
                path,
                "TWSE",
                "2014-01-06",
                sample_size=1,
            )

        self.assertEqual(inspection.status, "OK")
        self.assertEqual(inspection.encoding, "cp950")
        self.assertEqual(inspection.header_index, 3)
        self.assertEqual(len(inspection.columns), 6)
        self.assertEqual(inspection.row_count, 2)
        self.assertEqual(inspection.sample_rows[0][0], "1101")


def _day_trading_csv_bytes(trade_date: str) -> bytes:
    year, month, day = trade_date.split("-")
    roc_year = int(year) - 1911
    content = "\n".join(
        [
            f'"{roc_year:03d}年{month}月{day}日 當日沖銷交易統計資訊"',
            '"當日沖銷交易總成交股數","占比"',
            f'"{roc_year:03d}年{month}月{day}日 當日沖銷交易標的及成交量值"',
            '"證券代號","證券名稱","暫停現股賣出後現款買進當沖註記","當日沖銷交易成交股數","當日沖銷交易買進成交金額","當日沖銷交易賣出成交金額",',
            '"1101","台泥","","127,000","5,608,450","5,570,250",',
        ]
    )
    return content.encode("cp950")
