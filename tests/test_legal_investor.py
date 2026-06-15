from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

import config
from ingest import legal_investor
from ingest.downloader import CooldownController, official_legal_url



LEGAL_SCHEMA = """
CREATE TABLE legal_investors(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL CHECK (market IN ('TWSE', 'TPEX')),
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
"""

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


    def test_validate_legal_csv_bytes_rejects_duplicate_security_codes(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數',
                '2330,台積電,1000,0,1000',
                '2330,台積電,2000,0,2000',
            ]
        ).encode('cp950')

        with self.assertRaisesRegex(ValueError, 'duplicate security code'):
            legal_investor.validate_legal_csv_bytes(content, 'TWSE', '2026-06-12')

    def test_validate_legal_csv_bytes_rejects_too_many_data_columns(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數',
                '2330,台積電,1000,0,1000,unexpected',
            ]
        ).encode('cp950')

        with self.assertRaisesRegex(ValueError, 'too many columns'):
            legal_investor.validate_legal_csv_bytes(content, 'TWSE', '2026-06-12')

    def test_validate_legal_csv_bytes_rejects_foreign_dealer_nonzero(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外陸資買進股數(不含外資自營商),外陸資賣出股數(不含外資自營商),外陸資買賣超股數(不含外資自營商),外資自營商買進股數,外資自營商賣出股數,外資自營商買賣超股數',
                '2330,台積電,1000,0,1000,1,0,1',
            ]
        ).encode('cp950')

        with self.assertRaisesRegex(ValueError, 'foreign dealer nonzero'):
            legal_investor.validate_legal_csv_bytes(content, 'TWSE', '2026-06-12')

    def test_validate_legal_csv_bytes_rejects_tpex_external_investor_mismatch(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '代號,名稱,外資及陸資(不含外資自營商)-買進股數,外資及陸資(不含外資自營商)-賣出股數,外資及陸資(不含外資自營商)-買賣超股數,外資自營商-買進股數,外資自營商-賣出股數,外資自營商-買賣超股數,外資及陸資-買進股數,外資及陸資-賣出股數,外資及陸資-買賣超股數',
                '00679B,元大美債20年,1000,500,500,0,0,0,1001,500,501',
            ]
        ).encode('cp950')

        with self.assertRaisesRegex(ValueError, 'TPEX external investor mismatch'):
            legal_investor.validate_legal_csv_bytes(content, 'TPEX', '2026-06-12')

    def test_validate_legal_csv_bytes_rejects_blank_numeric_cells(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,自營商買進股數(避險),自營商賣出股數(避險),自營商買賣超股數(避險)',
                '2330,台積電,,0,0',
            ]
        ).encode('cp950')

        with self.assertRaisesRegex(ValueError, 'invalid numeric cell'):
            legal_investor.validate_legal_csv_bytes(content, 'TWSE', '2026-06-12')

    def test_download_legal_range_rejects_csv_when_matching_close_rows_are_missing(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(
            SCHEMA
            + """
CREATE TABLE daily_close(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_id TEXT NOT NULL
);
"""
        )
        conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-12', 1, 'seed', ''),
        )
        original_csv_dir = config.CSV_DIR
        original_calendar = legal_investor.ensure_trading_days_current

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            legal_investor.ensure_trading_days_current = lambda *args, **kwargs: 0
            try:
                results = legal_investor.download_legal_range(
                    conn,
                    start='2026-06-12',
                    end='2026-06-12',
                    markets=('TWSE',),
                    fetcher=lambda market, trade_date: sample_legal_csv(market, trade_date),
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir
                legal_investor.ensure_trading_days_current = original_calendar

        self.assertEqual(results[0].status, 'MISSING')
        self.assertIn('matching daily_close rows', results[0].error or '')


    def test_parse_legal_file_normalizes_modern_twse_columns(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外陸資買進股數(不含外資自營商),外陸資賣出股數(不含外資自營商),外陸資買賣超股數(不含外資自營商),外資自營商買進股數,外資自營商賣出股數,外資自營商買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數,自營商買賣超股數,自營商買進股數(自行買賣),自營商賣出股數(自行買賣),自營商買賣超股數(自行買賣),自營商買進股數(避險),自營商賣出股數(避險),自營商買賣超股數(避險),三大法人買賣超股數,',
                '2330,台積電,100,20,80,0,0,0,10,1,9,38,3,4,-1,30,2,28,117,',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            result = legal_investor.parse_legal_file(path, 'TWSE', '2026-06-12')

        row = result.rows[0]
        self.assertEqual(row.foreign_buy, 100)
        self.assertEqual(row.foreign_net, 80)
        self.assertEqual(row.investment_trust_net, 9)
        self.assertEqual((row.dealer_buy, row.dealer_sell, row.dealer_net), (3, 4, -1))
        self.assertEqual((row.dealer_hedge_buy, row.dealer_hedge_sell, row.dealer_hedge_net), (30, 2, 28))

    def test_parse_legal_file_normalizes_old_twse_without_hedge_as_zero(self) -> None:
        content = '\n'.join(
            [
                '102年01月03日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數,自營商買賣超股數,自營商買進股數,自營商賣出股數,三大法人買賣超股數,',
                '2890,永豐金,100,20,80,10,1,9,7,12,5,96,',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            result = legal_investor.parse_legal_file(path, 'TWSE', '2013-01-03')

        row = result.rows[0]
        self.assertEqual((row.dealer_buy, row.dealer_sell, row.dealer_net), (12, 5, 7))
        self.assertEqual((row.dealer_hedge_buy, row.dealer_hedge_sell, row.dealer_hedge_net), (0, 0, 0))

    def test_parse_legal_file_uses_tpex_total_foreign_columns(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '代號,名稱,外資及陸資(不含外資自營商)-買進股數,外資及陸資(不含外資自營商)-賣出股數,外資及陸資(不含外資自營商)-買賣超股數,外資自營商-買進股數,外資自營商-賣出股數,外資自營商-買賣超股數,外資及陸資-買進股數,外資及陸資-賣出股數,外資及陸資-買賣超股數,投信-買進股數,投信-賣出股數,投信-買賣超股數,自營商(自行買賣)-買進股數,自營商(自行買賣)-賣出股數,自營商(自行買賣)-買賣超股數,自營商(避險)-買進股數,自營商(避險)-賣出股數,自營商(避險)-買賣超股數,自營商-買進股數,自營商-賣出股數,自營商-買賣超股數,三大法人買賣超股數合計',
                '00679B,元大美債20年,100,20,80,0,0,0,100,20,80,10,1,9,3,4,-1,30,2,28,33,6,27,117',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            result = legal_investor.parse_legal_file(path, 'TPEX', '2026-06-12')

        row = result.rows[0]
        self.assertEqual((row.foreign_buy, row.foreign_sell, row.foreign_net), (100, 20, 80))
        self.assertEqual((row.dealer_buy, row.dealer_sell, row.dealer_net), (3, 4, -1))
        self.assertEqual((row.dealer_hedge_buy, row.dealer_hedge_sell, row.dealer_hedge_net), (30, 2, 28))

    def test_dry_run_legal_file_blocks_bad_csv_without_writing(self) -> None:
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數',
                '2330,台積電,100,20,80,extra',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            result = legal_investor.dry_run_legal_file(path, 'TWSE', '2026-06-12')

        self.assertEqual(result.status, 'BLOCKED')
        self.assertIn('too many columns', result.error or '')


    def test_parse_legal_file_accepts_old_tpex_buy_sell_net_names(self) -> None:
        content = '\n'.join(
            [
                '96年04月23日 三大法人日交易資訊',
                '代號,名稱,外資及陸資買股數,外資及陸資賣股數,外資及陸資淨買股數,投信買進股數,投信賣股數,投信淨買股數,自營商買股數,自營商賣股數,自營淨買股數,三大法人買賣超股數',
                '1565,精華,72000,169586,-97586,0,0,0,10,3,7,-97579',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'legal.csv'
            path.write_text(content, encoding='utf-8-sig')
            result = legal_investor.parse_legal_file(path, 'TPEX', '2007-04-23')

        row = result.rows[0]
        self.assertEqual((row.foreign_buy, row.foreign_sell, row.foreign_net), (72000, 169586, -97586))
        self.assertEqual((row.investment_trust_buy, row.investment_trust_sell, row.investment_trust_net), (0, 0, 0))
        self.assertEqual((row.dealer_buy, row.dealer_sell, row.dealer_net), (10, 3, 7))
        self.assertEqual((row.dealer_hedge_buy, row.dealer_hedge_sell, row.dealer_hedge_net), (0, 0, 0))

    def test_legal_csv_report_summarizes_ok_blocked_and_missing(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        for trade_date in ('2026-06-10', '2026-06-11', '2026-06-12'):
            conn.execute(
                'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
                (trade_date, 1, 'seed', ''),
            )
        original_csv_dir = config.CSV_DIR
        good = '\n'.join(
            [
                '115年06月10日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數,自營商買賣超股數,自營商買進股數,自營商賣出股數,三大法人買賣超股數,',
                '2330,台積電,100,20,80,10,1,9,7,12,5,96,',
            ]
        )
        bad = '\n'.join(
            [
                '115年06月11日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數',
                '2330,台積電,100,20,80,extra',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                target = config.CSV_DIR / 'legal_investor' / '2026'
                target.mkdir(parents=True)
                (target / '20260610LegalSII.csv').write_text(good, encoding='utf-8-sig')
                (target / '20260611LegalSII.csv').write_text(bad, encoding='utf-8-sig')
                report = legal_investor.legal_csv_report(
                    conn,
                    start='2026-06-10',
                    end='2026-06-12',
                    markets=('TWSE',),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(len(report.results), 3)
        self.assertEqual((report.summaries[0].ok, report.summaries[0].blocked, report.summaries[0].missing), (1, 1, 1))
        self.assertEqual([problem.status for problem in report.problems], ['BLOCKED', 'MISSING'])

    def test_import_legal_range_inserts_rows_and_blocks_reimport_scope(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA + LEGAL_SCHEMA)
        conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-12', 1, 'seed', ''),
        )
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數,自營商買賣超股數,自營商買進股數,自營商賣出股數,三大法人買賣超股數,',
                '2330,台積電,100,20,80,10,1,9,7,12,5,96,',
            ]
        )
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                target = config.CSV_DIR / 'legal_investor' / '2026'
                target.mkdir(parents=True)
                (target / '20260612LegalSII.csv').write_text(content, encoding='utf-8-sig')
                results = legal_investor.import_legal_range(
                    conn,
                    start='2026-06-12',
                    end='2026-06-12',
                    markets=('TWSE',),
                )
                self.assertEqual(results[0].row_count, 1)
                row = conn.execute('SELECT * FROM legal_investors').fetchone()
                self.assertEqual(row['stock_id'], '2330')
                self.assertEqual(row['foreign_net'], 80)
                with self.assertRaisesRegex(ValueError, 'target scope is not empty'):
                    legal_investor.import_legal_range(
                        conn,
                        start='2026-06-12',
                        end='2026-06-12',
                        markets=('TWSE',),
                    )
            finally:
                config.CSV_DIR = original_csv_dir

    def test_import_legal_range_does_not_insert_when_dry_run_blocks(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA + LEGAL_SCHEMA)
        conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-12', 1, 'seed', ''),
        )
        bad = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數',
                '2330,台積電,100,20,80,extra',
            ]
        )
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                target = config.CSV_DIR / 'legal_investor' / '2026'
                target.mkdir(parents=True)
                (target / '20260612LegalSII.csv').write_text(bad, encoding='utf-8-sig')
                with self.assertRaisesRegex(ValueError, 'blocked by dry-run problem'):
                    legal_investor.import_legal_range(
                        conn,
                        start='2026-06-12',
                        end='2026-06-12',
                        markets=('TWSE',),
                    )
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM legal_investors').fetchone()[0], 0)
            finally:
                config.CSV_DIR = original_csv_dir


    def test_update_legal_day_skips_existing_rows_without_fetching(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(
            SCHEMA
            + LEGAL_SCHEMA
            + """
CREATE TABLE daily_close(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_id TEXT NOT NULL
);
"""
        )
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2026-06-12', 1, 'seed', ''))
        conn.execute(
            """
            INSERT INTO legal_investors VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            ('2026-06-12', 'TWSE', '2330', '台積電', 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        )
        original_calendar = legal_investor.ensure_trading_days_current
        legal_investor.ensure_trading_days_current = lambda *args, **kwargs: self.fail('calendar should not refresh for known date')
        try:
            results = legal_investor.update_legal_day(
                conn,
                trade_date='2026-06-12',
                markets=('TWSE',),
                fetcher=lambda market, trade_date: self.fail('fetcher should not be called'),
                cooldown=CooldownController(enabled=False),
            )
        finally:
            legal_investor.ensure_trading_days_current = original_calendar

        self.assertEqual(results[0].status, 'EXISTS')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM legal_investors').fetchone()[0], 1)

    def test_update_legal_day_skips_closed_day_without_fetching(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA + LEGAL_SCHEMA)
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2026-06-13', 0, 'seed', ''))
        original_calendar = legal_investor.ensure_trading_days_current
        legal_investor.ensure_trading_days_current = lambda *args, **kwargs: self.fail('calendar should not refresh for known date')
        try:
            results = legal_investor.update_legal_day(
                conn,
                trade_date='2026-06-13',
                markets=('TWSE',),
                fetcher=lambda market, trade_date: self.fail('fetcher should not be called'),
                cooldown=CooldownController(enabled=False),
            )
        finally:
            legal_investor.ensure_trading_days_current = original_calendar

        self.assertEqual(results[0].status, 'CLOSED')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM legal_investors').fetchone()[0], 0)

    def test_update_legal_day_blocks_when_close_rows_are_missing_without_fetching(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(
            SCHEMA
            + LEGAL_SCHEMA
            + """
CREATE TABLE daily_close(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_id TEXT NOT NULL
);
"""
        )
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2026-06-12', 1, 'seed', ''))
        original_calendar = legal_investor.ensure_trading_days_current
        legal_investor.ensure_trading_days_current = lambda *args, **kwargs: self.fail('calendar should not refresh for known date')
        try:
            results = legal_investor.update_legal_day(
                conn,
                trade_date='2026-06-12',
                markets=('TWSE',),
                fetcher=lambda market, trade_date: self.fail('fetcher should not be called'),
                cooldown=CooldownController(enabled=False),
            )
        finally:
            legal_investor.ensure_trading_days_current = original_calendar

        self.assertEqual(results[0].status, 'BLOCKED')
        self.assertIn('daily_close', results[0].error or '')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM legal_investors').fetchone()[0], 0)

    def test_update_legal_day_downloads_and_imports_new_open_day(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(
            SCHEMA
            + LEGAL_SCHEMA
            + """
CREATE TABLE daily_close(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_id TEXT NOT NULL
);
"""
        )
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2026-06-12', 1, 'seed', ''))
        conn.execute('INSERT INTO daily_close VALUES (?, ?, ?)', ('2026-06-12', 'TWSE', '2330'))
        content = '\n'.join(
            [
                '115年06月12日 三大法人日交易資訊',
                '證券代號,證券名稱,外資買進股數,外資賣出股數,外資買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數,自營商買賣超股數,自營商買進股數,自營商賣出股數,三大法人買賣超股數,',
                '2330,台積電,100,20,80,10,1,9,7,12,5,96,',
            ]
        ).encode('utf-8-sig')
        original_csv_dir = config.CSV_DIR
        original_calendar = legal_investor.ensure_trading_days_current
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            legal_investor.ensure_trading_days_current = lambda *args, **kwargs: self.fail('calendar should not refresh for known date')
            try:
                results = legal_investor.update_legal_day(
                    conn,
                    trade_date='2026-06-12',
                    markets=('TWSE',),
                    fetcher=lambda market, trade_date: content,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir
                legal_investor.ensure_trading_days_current = original_calendar

        self.assertEqual(results[0].status, 'OK')
        self.assertEqual(results[0].row_count, 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM legal_investors').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
