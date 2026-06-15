from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

import config
from ingest import legal_investor
from ingest.downloader import CooldownController, official_legal_url


SCHEMA = """
CREATE TABLE trading_days(
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
);
"""


def sample_legal_csv(market: str, trade_date: str) -> bytes:
    return '\n'.join(
        [
            f'{trade_date.replace('-', '')} {market} 三大法人日交易資訊',
            '證券代號,證券名稱,外資買進股數,投信買進股數,自營商買進股數',
            '2330,台積電,1000,200,300',
        ]
    ).encode('utf-8-sig')


class LegalInvestorTests(unittest.TestCase):
    def test_official_legal_urls_match_documented_routes(self) -> None:
        self.assertEqual(
            official_legal_url('TWSE', '2026-06-12'),
            'https://www.twse.com.tw/rwd/zh/fund/T86?date=20260612&selectType=ALLBUT0999&response=csv',
        )
        self.assertEqual(
            official_legal_url('TPEX', '2026-06-12'),
            'https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=2026%2F06%2F12&id=&response=csv',
        )

    def test_download_legal_range_rejects_dates_before_redownload_boundary(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        with self.assertRaisesRegex(ValueError, '2019-08-21'):
            legal_investor.download_legal_range(
                conn,
                start='2019-08-20',
                end='2019-08-20',
            )

    def test_download_legal_range_uses_open_trading_days_only(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        for trade_date, is_open in (
            ('2019-08-21', 1),
            ('2019-08-22', 0),
            ('2019-08-23', 1),
        ):
            conn.execute(
                'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
                (trade_date, is_open, 'seed', ''),
            )
        original_csv_dir = config.CSV_DIR
        original_calendar = legal_investor.ensure_trading_days_current
        calls: list[tuple[str, str]] = []

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return sample_legal_csv(market, trade_date)

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            legal_investor.ensure_trading_days_current = lambda *args, **kwargs: 0
            try:
                results = legal_investor.download_legal_range(
                    conn,
                    start='2019-08-21',
                    end='2019-08-23',
                    markets=('TWSE',),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir
                legal_investor.ensure_trading_days_current = original_calendar

        self.assertEqual(calls, [('TWSE', '2019-08-21'), ('TWSE', '2019-08-23')])
        self.assertEqual([result.status for result in results], ['OK', 'OK'])
        self.assertTrue(results[0].path.endswith('20190821LegalSII.csv'))

    def test_download_legal_range_rejects_invalid_csv_without_overwriting_existing_file(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-12', 1, 'seed', ''),
        )
        original_csv_dir = config.CSV_DIR
        original_calendar = legal_investor.ensure_trading_days_current

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            legal_investor.ensure_trading_days_current = lambda *args, **kwargs: 0
            existing_path = legal_investor.legal_csv_path('TWSE', '2026-06-12')
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_bytes(sample_legal_csv('TWSE', '2026-06-12'))
            original_bytes = existing_path.read_bytes()
            try:
                results = legal_investor.download_legal_range(
                    conn,
                    start='2026-06-12',
                    end='2026-06-12',
                    markets=('TWSE',),
                    fetcher=lambda market, trade_date: b'\r\n',
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir
                legal_investor.ensure_trading_days_current = original_calendar

            self.assertEqual(results[0].status, 'MISSING')
            self.assertIn('content date not found', results[0].error or '')
            self.assertEqual(existing_path.read_bytes(), original_bytes)

    def test_download_legal_range_rejects_wrong_content_date_without_overwriting_existing_file(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-12', 1, 'seed', ''),
        )
        original_csv_dir = config.CSV_DIR
        original_calendar = legal_investor.ensure_trading_days_current

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            legal_investor.ensure_trading_days_current = lambda *args, **kwargs: 0
            existing_path = legal_investor.legal_csv_path('TWSE', '2026-06-12')
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_bytes(sample_legal_csv('TWSE', '2026-06-12'))
            original_bytes = existing_path.read_bytes()
            try:
                results = legal_investor.download_legal_range(
                    conn,
                    start='2026-06-12',
                    end='2026-06-12',
                    markets=('TWSE',),
                    fetcher=lambda market, trade_date: sample_legal_csv(market, '2026-06-11'),
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir
                legal_investor.ensure_trading_days_current = original_calendar

            self.assertEqual(results[0].status, 'MISSING')
            self.assertIn('date mismatch', results[0].error or '')
            self.assertEqual(existing_path.read_bytes(), original_bytes)

    def test_validate_legal_csv_bytes_accepts_roc_content_date(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,投信買進股數,自營商買進股數',
                '2330,台積電,1000,200,300',
            ]
        ).encode('cp950')

        legal_investor.validate_legal_csv_bytes(content, 'TWSE', '2026-06-12')

    def test_validate_legal_csv_bytes_rejects_short_data_rows(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外陸資買進股數(不含外資自營商),外陸資賣出股數(不含外資自營商),外陸資買賣超股數(不含外資自營商),外資自營商買進股數,外資自營商賣出股數,外資自營商買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數',
                '2330,台積電,1,2,3,4,5,6',
            ]
        ).encode('cp950')

        with self.assertRaisesRegex(ValueError, 'too few columns'):
            legal_investor.validate_legal_csv_bytes(content, 'TWSE', '2026-06-12')

    def test_inspect_legal_file_reports_header_fields_and_samples(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,投信買進股數,自營商買進股數',
                '2330,台積電,"1,000",200,300',
                '2317,鴻海,400,500,600',
                '說明: unit test',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            summary = legal_investor.inspect_legal_file(path, 'TWSE', sample_size=1)

        self.assertEqual(summary.encoding, 'utf-8-sig')
        self.assertEqual(summary.header_index, 1)
        self.assertEqual(summary.row_count, 2)
        self.assertEqual(summary.fields[:2], ['證券代號', '證券名稱'])
        self.assertEqual(summary.sample_rows, [['2330', '台積電', '1,000', '200', '300']])

    def test_inspect_legal_file_accepts_formula_style_security_codes_and_skips_notes(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,投信買進股數,自營商買進股數',
                '="00637L",元大滬深300正2,1000,200,300',
                '自營商表示證券自營商專戶。',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            summary = legal_investor.inspect_legal_file(path, 'TWSE', sample_size=1)

        self.assertEqual(summary.row_count, 1)
        self.assertEqual(summary.sample_rows[0][0], '="00637L"')


if __name__ == '__main__':
    unittest.main()
