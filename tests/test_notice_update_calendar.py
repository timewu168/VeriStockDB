from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

import config
import ingest.attention_notice as attention
import ingest.disposal_notice as disposal
from ingest.downloader import CooldownController
from ingest.disposal_notice import DisposalNoticeImportResult


SCHEMA = """
CREATE TABLE trading_days(
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
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
CREATE UNIQUE INDEX uq_import_batches_scope
  ON import_batches(dataset, market, period);
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


class NoticeUpdateCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        for trade_date, is_open in (
            ('2026-06-05', 1),
            ('2026-06-06', 0),
            ('2026-06-07', 0),
            ('2026-06-08', 1),
        ):
            self.conn.execute(
                'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
                (trade_date, is_open, 'seed', ''),
            )
        self.conn.execute(
            "INSERT INTO attention_notices VALUES "
            "('2026-06-05','TWSE','2330','台積電','x')"
        )
        self.conn.execute(
            "INSERT INTO disposal_notices VALUES "
            "('2026-06-05','TWSE','2330','台積電',"
            "'2026-06-05','2026-06-10','x','y')"
        )
        self.conn.execute(
            "INSERT INTO import_batches("
            "batch_id,dataset,market,period,status,row_count,checked_at,manual_approved"
            ") VALUES ('a','attention_notice','TWSE','2026-06-05','OK',1,'now',0)"
        )
        self.conn.execute(
            "INSERT INTO import_batches("
            "batch_id,dataset,market,period,status,row_count,checked_at,manual_approved"
            ") VALUES ('d','disposal_notice','TWSE','2026-06-05','OK',1,'now',0)"
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_attention_update_skips_closed_target_without_official_download(self) -> None:
        original = attention.ensure_trading_days_current
        attention.ensure_trading_days_current = lambda *args, **kwargs: 0
        try:
            stats = attention.import_attention_notice_update(
                self.conn,
                through_date='2026-06-07',
                markets=('TWSE',),
                fetcher=_raising_fetcher,
            )
        finally:
            attention.ensure_trading_days_current = original

        self.assertEqual(
            stats,
            {'OK': 0, 'FIXED': 0, 'BLOCKED': 0, 'RECHECK': 0, 'MISSING': 0, 'SKIPPED': 1},
        )


    def test_attention_official_retries_until_success_and_records_retry_count(self) -> None:
        calls = 0

        def flaky_fetcher(market: str, start: str, end: str) -> bytes:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError(f'temporary attention failure {calls}')
            return _attention_csv('2026-06-08')

        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                result = attention.import_attention_notice_official(
                    self.conn,
                    market='TWSE',
                    start='2026-06-08',
                    end='2026-06-08',
                    fetcher=flaky_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        batch = self.conn.execute(
            "SELECT status, retry_count FROM import_batches "
            "WHERE dataset = 'attention_notice' AND market = 'TWSE' AND period = '2026-06-08'"
        ).fetchone()
        self.assertEqual(calls, 3)
        self.assertEqual(result.status, 'FIXED')
        self.assertEqual(batch['status'], 'FIXED')
        self.assertEqual(batch['retry_count'], 2)

    def test_disposal_official_retries_until_success_and_records_retry_count(self) -> None:
        calls = 0

        def flaky_fetcher(market: str, start: str, end: str) -> bytes:
            nonlocal calls
            calls += 1
            if calls < 3:
                return b''
            return _disposal_csv('2026-06-08')

        original_csv_dir = config.CSV_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            config.CSV_DIR = Path(temp_dir)
            try:
                result = disposal.import_disposal_notice_official(
                    self.conn,
                    market='TWSE',
                    start='2026-06-08',
                    end='2026-06-08',
                    fetcher=flaky_fetcher,
                    cooldown=CooldownController(enabled=False),
                )
            finally:
                config.CSV_DIR = original_csv_dir

        batch = self.conn.execute(
            "SELECT status, retry_count FROM import_batches "
            "WHERE dataset = 'disposal_notice' AND market = 'TWSE' AND period = '2026-06-08'"
        ).fetchone()
        self.assertEqual(calls, 3)
        self.assertEqual(result.status, 'FIXED')
        self.assertEqual(batch['status'], 'FIXED')
        self.assertEqual(batch['retry_count'], 2)

    def test_disposal_update_uses_announcement_horizon_even_when_target_is_closed(self) -> None:
        calls: list[tuple[str, str, str]] = []

        def fake_import(conn, *, market, start, end, fetcher, cooldown, log):
            calls.append((market, start, end))
            return DisposalNoticeImportResult(
                'new', market, f'{start}..{end}', 'OK', 1, 0, 0, 0, 0, 0, 0, 0, 0, 'fake'
            )

        original_calendar = disposal.ensure_trading_days_current
        original_import = disposal.import_disposal_notice_official
        disposal.ensure_trading_days_current = lambda *args, **kwargs: 0
        disposal.import_disposal_notice_official = fake_import
        try:
            stats = disposal.import_disposal_notice_update(
                self.conn,
                through_date='2026-06-07',
                markets=('TWSE',),
            )
        finally:
            disposal.ensure_trading_days_current = original_calendar
            disposal.import_disposal_notice_official = original_import

        self.assertEqual(stats['OK'], 1)
        self.assertEqual(calls, [('TWSE', '2026-06-05', '2026-06-22')])

    def test_closed_day_ok_batch_does_not_advance_disposal_latest(self) -> None:
        self.conn.execute(
            "INSERT INTO import_batches("
            "batch_id,dataset,market,period,status,row_count,checked_at,manual_approved"
            ") VALUES ('bad','disposal_notice','TWSE','2026-06-07','OK',51,'now',0)"
        )
        calls: list[tuple[str, str, str]] = []

        def fake_import(conn, *, market, start, end, fetcher, cooldown, log):
            calls.append((market, start, end))
            return DisposalNoticeImportResult(
                'new', market, end, 'OK', 1, 0, 0, 0, 0, 0, 0, 0, 0, 'fake'
            )

        original_calendar = disposal.ensure_trading_days_current
        original_import = disposal.import_disposal_notice_official
        disposal.ensure_trading_days_current = lambda *args, **kwargs: 0
        disposal.import_disposal_notice_official = fake_import
        try:
            stats = disposal.import_disposal_notice_update(
                self.conn,
                through_date='2026-06-08',
                markets=('TWSE',),
            )
        finally:
            disposal.ensure_trading_days_current = original_calendar
            disposal.import_disposal_notice_official = original_import

        self.assertEqual(stats['OK'], 1)
        self.assertEqual(calls, [('TWSE', '2026-06-05', '2026-06-23')])

    def test_disposal_update_queries_requested_target_plus_15_days(self) -> None:
        self.conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-16', 1, 'seed', ''),
        )
        self.conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-17', 1, 'seed', ''),
        )
        self.conn.execute(
            'INSERT INTO trading_days VALUES (?, ?, ?, ?)',
            ('2026-06-18', 1, 'seed', ''),
        )
        self.conn.execute(
            "INSERT INTO disposal_notices VALUES "
            "('2026-06-16','TWSE','3167','大量',"
            "'2026-06-17','2026-07-01','x','y')"
        )
        calls: list[tuple[str, str, str]] = []

        def fake_import(conn, *, market, start, end, fetcher, cooldown, log):
            calls.append((market, start, end))
            return DisposalNoticeImportResult(
                'new', market, f'{start}..{end}', 'OK', 1, 0, 0, 0, 0, 0, 0, 0, 0, 'fake'
            )

        original_calendar = disposal.ensure_trading_days_current
        original_import = disposal.import_disposal_notice_official
        disposal.ensure_trading_days_current = lambda *args, **kwargs: 0
        disposal.import_disposal_notice_official = fake_import
        try:
            stats = disposal.import_disposal_notice_update(
                self.conn,
                through_date='2026-06-18',
                markets=('TWSE',),
            )
        finally:
            disposal.ensure_trading_days_current = original_calendar
            disposal.import_disposal_notice_official = original_import

        self.assertEqual(stats['OK'], 1)
        self.assertEqual(calls, [('TWSE', '2026-06-16', '2026-07-03')])


def _attention_csv(trade_date: str) -> bytes:
    roc_year = int(trade_date[:4]) - 1911
    mmdd = trade_date[5:].replace('-', '/')
    roc_date = f'{roc_year}/{mmdd}'
    return (
        f'期間:{roc_date}~{roc_date}\n'
        '編號,日期,證券代號,證券名稱,注意交易資訊\n'
        f'1,{roc_date},2330,台積電,測試注意\n'
    ).encode('utf-8-sig')


def _disposal_csv(trade_date: str) -> bytes:
    roc_year = int(trade_date[:4]) - 1911
    mmdd = trade_date[5:].replace('-', '/')
    roc_date = f'{roc_year}/{mmdd}'
    return (
        f'期間:{roc_date}~{roc_date}\n'
        '編號,公布日期,證券代號,證券名稱,處置起迄時間,處置條件,處置內容\n'
        f'1,{roc_date},2330,台積電,{roc_date}~{roc_date},測試條件,測試處置\n'
    ).encode('utf-8-sig')


def _raising_fetcher(*args):
    raise AssertionError('official notice fetcher should not be called')


if __name__ == '__main__':
    unittest.main()
