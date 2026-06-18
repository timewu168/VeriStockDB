from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

import config
from ingest import margin
from ingest.downloader import CooldownController, official_margin_file_name, official_margin_url


SCHEMA = """
CREATE TABLE trading_days(
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
);
"""


class MarginDownloadTests(unittest.TestCase):
    def test_official_margin_urls_match_documented_routes(self) -> None:
        self.assertEqual(
            official_margin_url('TWSE', '2026-06-12'),
            'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=csv&date=20260612&selectType=ALL',
        )
        self.assertEqual(
            official_margin_url('TPEX', '2007-01-02'),
            'https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2007%2F01%2F02&id=&response=csv',
        )
        self.assertEqual(
            official_margin_url('TPEX', '2012-03-16'),
            'https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2012%2F03%2F16&id=&response=csv',
        )
        self.assertEqual(
            official_margin_url('TPEX', '2012-10-01'),
            'https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2012%2F10%2F01&id=&response=csv',
        )
        self.assertEqual(
            official_margin_url('TPEX', '2012-10-02'),
            'https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2012%2F10%2F02&id=&response=csv',
        )

    def test_official_margin_file_names_are_csv(self) -> None:
        self.assertEqual(official_margin_file_name('TWSE', '2026-06-12'), '20260612MarginSII.csv')
        self.assertEqual(official_margin_file_name('TPEX', '2012-10-01'), '20121001MarginOTC.csv')

    def test_download_margin_range_uses_open_trading_days_only_and_saves_files(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        for trade_date, is_open in (
            ('2026-06-10', 1),
            ('2026-06-11', 0),
            ('2026-06-12', 1),
        ):
            conn.execute(
                'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
                (trade_date, is_open, 'seed', ''),
            )
        calls: list[tuple[str, str]] = []
        original_csv_dir = config.CSV_DIR

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return f'{trade_date},{market},margin'.encode('utf-8')

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                results = margin.download_margin_range(
                    conn,
                    start='2026-06-10',
                    end='2026-06-12',
                    markets=('TWSE',),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [('TWSE', '2026-06-10'), ('TWSE', '2026-06-12')])
        self.assertEqual([result.status for result in results], ['OK', 'OK'])
        self.assertTrue(results[0].path and results[0].path.endswith('20260610MarginSII.csv'))

    def test_download_margin_dates_uses_independent_market_cooldowns(self) -> None:
        original_csv_dir = config.CSV_DIR
        calls: list[tuple[str, str]] = []
        cooldowns = {
            'TWSE': CooldownController(enabled=False),
            'TPEX': CooldownController(enabled=False),
        }

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return f'{trade_date},{market},margin'.encode('utf-8')

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                results = margin.download_margin_dates(
                    ['2026-06-11', '2026-06-12'],
                    start='2026-06-11',
                    end='2026-06-12',
                    markets=('TWSE', 'TPEX'),
                    fetcher=fake_fetcher,
                    cooldowns=cooldowns,
                    parallel_markets=True,
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(cooldowns['TWSE'].request_count, 2)
        self.assertEqual(cooldowns['TPEX'].request_count, 2)
        self.assertEqual(len(results), 4)
        self.assertEqual({result.market for result in results}, {'TWSE', 'TPEX'})
        self.assertEqual(set(calls), {
            ('TWSE', '2026-06-11'),
            ('TWSE', '2026-06-12'),
            ('TPEX', '2026-06-11'),
            ('TPEX', '2026-06-12'),
        })

    def test_download_margin_range_skips_existing_files_by_default(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2026-06-12', 1, 'seed', ''))
        original_csv_dir = config.CSV_DIR
        calls: list[tuple[str, str]] = []

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return b'should-not-fetch'

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                existing = margin.margin_file_path('TWSE', '2026-06-12')
                existing.parent.mkdir(parents=True, exist_ok=True)
                existing.write_bytes(b'existing-margin-csv')
                results = margin.download_margin_range(
                    conn,
                    start='2026-06-12',
                    end='2026-06-12',
                    markets=('TWSE',),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [])
        self.assertEqual(results[0].status, 'SKIP')
        self.assertEqual(results[0].bytes_written, len(b'existing-margin-csv'))

    def test_download_margin_range_overwrites_existing_files_when_requested(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2026-06-12', 1, 'seed', ''))
        original_csv_dir = config.CSV_DIR
        calls: list[tuple[str, str]] = []

        def fake_fetcher(market: str, trade_date: str) -> bytes:
            calls.append((market, trade_date))
            return b'fresh-margin-csv'

        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                existing = margin.margin_file_path('TWSE', '2026-06-12')
                existing.parent.mkdir(parents=True, exist_ok=True)
                existing.write_bytes(b'existing-margin-csv')
                results = margin.download_margin_range(
                    conn,
                    start='2026-06-12',
                    end='2026-06-12',
                    markets=('TWSE',),
                    fetcher=fake_fetcher,
                    cooldown=CooldownController(enabled=False),
                    overwrite=True,
                )
                saved = existing.read_bytes()
            finally:
                config.CSV_DIR = original_csv_dir

        self.assertEqual(calls, [('TWSE', '2026-06-12')])
        self.assertEqual(results[0].status, 'OK')
        self.assertEqual(saved, b'fresh-margin-csv')

    def test_download_margin_range_rejects_before_market_start(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2005-12-30', 1, 'seed', ''))
        results = margin.download_margin_range(
            conn,
            start='2005-12-30',
            end='2005-12-30',
            markets=('TPEX',),
            fetcher=lambda market, trade_date: b'should-not-fetch',
            cooldown=CooldownController(enabled=False),
        )
        self.assertEqual(results[0].status, 'MISSING')
        self.assertIn('2006-01-02', results[0].error or '')


    def test_inspect_margin_file_parses_twse_csv_and_file_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / '20260612MarginSII.csv'
            body = ''.join(
                f'"{2300 + i}","測試{i}","1,234","2","0",""\n'
                for i in range(250)
            )
            path.write_text(
                '"115年06月12日 信用交易統計"\n'
                '"代號","名稱","買進","賣出","現金償還","註記"\n'
                + body,
                encoding='cp950',
            )
            result = margin.inspect_margin_file(path, 'TWSE', '2026-06-12')
        self.assertEqual(result.status, 'OK')
        self.assertEqual(result.encoding, 'cp950')
        self.assertEqual(result.file_date, '2026-06-12')
        self.assertEqual(result.data_row_count, 250)
        self.assertEqual(result.column_count, 6)

    def test_inspect_margin_file_flags_small_file_without_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / '20260612MarginSII.csv'
            path.write_text('查無資料\n', encoding='cp950')
            result = margin.inspect_margin_file(path, 'TWSE', '2026-06-12')
        self.assertEqual(result.status, 'BAD')
        self.assertIn('SUSPICIOUS_SMALL_FILE', result.errors)
        self.assertIn('HEADER_NOT_FOUND', result.errors)

    def test_audit_margin_csvs_uses_trading_days_not_weekday_rule(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        # 2026-06-13 is Saturday, but this audit accepts it if trading_days says open.
        for trade_date, is_open in (
            ('2026-06-12', 1),
            ('2026-06-13', 1),
            ('2026-06-14', 0),
        ):
            conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', (trade_date, is_open, 'seed', ''))
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                for trade_date in ('2026-06-12', '2026-06-13'):
                    path = margin.margin_file_path('TWSE', trade_date)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    roc = int(trade_date[:4]) - 1911
                    body = ''.join(
                        f'"{2300 + i}","測試{i}","1","2","0",""\n'
                        for i in range(250)
                    )
                    path.write_text(
                        f'"{roc:03d}年{trade_date[5:7]}月{trade_date[8:10]}日 信用交易統計"\n'
                        '"代號","名稱","買進","賣出","現金償還","註記"\n'
                        + body,
                        encoding='cp950',
                    )
                extra = margin.margin_file_path('TWSE', '2026-06-14')
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text('extra', encoding='cp950')
                report = margin.audit_margin_csvs(
                    conn,
                    start='2026-06-12',
                    end='2026-06-14',
                    markets=('TWSE',),
                    report_dir=Path(temp_dir) / 'reports',
                )
            finally:
                config.CSV_DIR = original_csv_dir
        self.assertEqual(report.expected_files, 2)
        self.assertEqual(report.missing_files, 0)
        self.assertEqual(report.extra_files, 1)
        self.assertEqual(report.ok_files, 2)


    def test_parse_margin_file_maps_twse_17_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / '20260612MarginSII.csv'
            path.write_text(
                '"115年06月12日 信用交易統計"\n'
                '"代號","名稱","買進","賣出","現金償還","前日餘額","今日餘額","次一營業日限額",'
                '"買進","賣出","現券償還","前日餘額","今日餘額","次一營業日限額","資券互抵","註記",""\n'
                '"2330","台積電","1","2","3","4","5","6","7","8","9","10","11","12","13","A",""\n',
                encoding='cp950',
            )
            records, problems = margin.parse_margin_file(path, 'TWSE', '2026-06-12')
        self.assertEqual(problems, [])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.stock_id, '2330')
        self.assertEqual(record.margin_buy, 1)
        self.assertEqual(record.margin_sell, 2)
        self.assertEqual(record.margin_cash_repay, 3)
        self.assertEqual(record.previous_margin_balance, 4)
        self.assertEqual(record.margin_balance, 5)
        self.assertEqual(record.margin_limit, 6)
        self.assertEqual(record.short_buy, 7)
        self.assertEqual(record.short_sell, 8)
        self.assertEqual(record.short_stock_repay, 9)
        self.assertEqual(record.previous_short_balance, 10)
        self.assertEqual(record.short_balance, 11)
        self.assertEqual(record.short_limit, 12)
        self.assertEqual(record.offsetting, 13)
        self.assertEqual(record.note, 'A')

    def test_parse_margin_file_maps_tpex_20_columns_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / '20080930MarginOTC.csv'
            path.write_text(
                '上櫃股票融資融券餘額\n'
                '資料日期:97/09/30\n'
                '"代號","名稱","前資餘額(張)","資買","資賣","現償","資餘額","資屬證金","資使用率(%)","資限額",'
                '"前券餘額(張)","券賣","券買","券償","券餘額","券屬證金","券使用率(%)","券限額","資券相抵(張)","備註"\n'
                '"006201","測試ETF","10","11","12","13","14","0","0.00","15","20","21","22","23","24","0","0.00","25","26","B"\n',
                encoding='cp950',
            )
            records, problems = margin.parse_margin_file(path, 'TPEX', '2008-09-30')
        self.assertEqual(problems, [])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.stock_id, '006201')
        self.assertEqual(record.margin_buy, 11)
        self.assertEqual(record.margin_sell, 12)
        self.assertEqual(record.margin_cash_repay, 13)
        self.assertEqual(record.previous_margin_balance, 10)
        self.assertEqual(record.margin_balance, 14)
        self.assertEqual(record.margin_limit, 15)
        self.assertEqual(record.short_buy, 22)
        self.assertEqual(record.short_sell, 21)
        self.assertEqual(record.short_stock_repay, 23)
        self.assertEqual(record.previous_short_balance, 20)
        self.assertEqual(record.short_balance, 24)
        self.assertEqual(record.short_limit, 25)
        self.assertEqual(record.offsetting, 26)
        self.assertEqual(record.note, 'B')

    def test_dry_run_margin_import_excludes_tpex_before_formal_start(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        for trade_date in ('2008-09-29', '2008-09-30'):
            conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', (trade_date, 1, 'seed', ''))
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                path = margin.margin_file_path('TPEX', '2008-09-30')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    '上櫃股票融資融券餘額\n'
                    '資料日期:97/09/30\n'
                    '"代號","名稱","前資餘額(張)","資買","資賣","現償","資餘額","資屬證金","資使用率(%)","資限額",'
                    '"前券餘額(張)","券賣","券買","券償","券餘額","券屬證金","券使用率(%)","券限額","資券相抵(張)","備註"\n'
                    '"006201","測試ETF","10","11","12","13","14","0","0.00","15","20","21","22","23","24","0","0.00","25","26",""\n',
                    encoding='cp950',
                )
                report = margin.dry_run_margin_import(
                    conn,
                    start='2008-09-29',
                    end='2008-09-30',
                    markets=('TPEX',),
                    report_dir=Path(temp_dir) / 'reports',
                )
            finally:
                config.CSV_DIR = original_csv_dir
        self.assertEqual(report.expected_files, 1)
        self.assertEqual(report.parsed_files, 1)
        self.assertEqual(report.rows, 1)
        self.assertEqual(report.problems, 0)


    def test_import_margin_range_inserts_rows_and_rejects_non_empty_scope(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.executescript(
            """
            CREATE TABLE margin_trading (
              trade_date TEXT NOT NULL,
              market TEXT NOT NULL CHECK (market IN ('TWSE', 'TPEX')),
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
            """
        )
        conn.execute('INSERT INTO trading_days VALUES (?, ?, ?, ?)', ('2008-09-30', 1, 'seed', ''))
        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                path = margin.margin_file_path('TPEX', '2008-09-30')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    '上櫃股票融資融券餘額\n'
                    '資料日期:97/09/30\n'
                    '"代號","名稱","前資餘額(張)","資買","資賣","現償","資餘額","資屬證金","資使用率(%)","資限額",'
                    '"前券餘額(張)","券賣","券買","券償","券餘額","券屬證金","券使用率(%)","券限額","資券相抵(張)","備註"\n'
                    '"006201","測試ETF","10","11","12","13","14","0","0.00","15","20","21","22","23","24","0","0.00","25","26","B"\n',
                    encoding='cp950',
                )
                results = margin.import_margin_range(
                    conn,
                    start='2008-09-30',
                    end='2008-09-30',
                    markets=('TPEX',),
                    report_dir=Path(temp_dir) / 'reports',
                )
                with self.assertRaisesRegex(ValueError, 'target scope is not empty'):
                    margin.import_margin_range(
                        conn,
                        start='2008-09-30',
                        end='2008-09-30',
                        markets=('TPEX',),
                        report_dir=Path(temp_dir) / 'reports2',
                    )
            finally:
                config.CSV_DIR = original_csv_dir
        self.assertEqual(results[0].row_count, 1)
        row = conn.execute('SELECT * FROM margin_trading').fetchone()
        self.assertEqual(row['stock_id'], '006201')
        self.assertEqual(row['margin_buy'], 11)
        self.assertEqual(row['short_sell'], 21)
        self.assertEqual(row['short_buy'], 22)
        self.assertEqual(row['previous_short_balance'], 20)
        self.assertEqual(row['short_balance'], 24)
        self.assertEqual(row['note'], 'B')


if __name__ == '__main__':
    unittest.main()
