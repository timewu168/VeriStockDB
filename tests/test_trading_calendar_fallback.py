from __future__ import annotations

import sqlite3
import unittest

from ingest.trading_calendar import (
    ensure_trading_days_current,
    parse_tpex_trading_index_open_dates,
)


class TradingCalendarFallbackTests(unittest.TestCase):
    def test_parse_tpex_trading_index_nested_tables(self) -> None:
        payload = {
            'stat': 'ok',
            'tables': [
                {
                    'fields': ['日期', '成交張數'],
                    'data': [['115/06/01', '1'], ['115/06/02', '2']],
                }
            ],
        }

        self.assertEqual(
            parse_tpex_trading_index_open_dates(payload),
            {'2026-06-01', '2026-06-02'},
        )

    def test_ensure_trading_days_current_uses_tpex_when_twse_has_no_data(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute(
            'CREATE TABLE trading_days('
            'trade_date TEXT PRIMARY KEY, is_open INTEGER NOT NULL, source TEXT NOT NULL, note TEXT)'
        )
        payload = {
            'stat': 'ok',
            'tables': [
                {
                    'fields': ['日期', '成交張數'],
                    'data': [['115/06/01', '1'], ['115/06/02', '2']],
                }
            ],
        }

        changed = ensure_trading_days_current(
            conn,
            through_date='2026-06-03',
            fetcher=lambda month: {'stat': 'OK', 'fields': ['日期'], 'data': []},
            fallback_fetcher=lambda month: payload,
        )

        self.assertEqual(changed, 3)
        rows = conn.execute(
            'SELECT trade_date, is_open, source, note FROM trading_days ORDER BY trade_date'
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                ('2026-06-01', 1, 'tpex_trading_index', 'open day from TPEx tradingIndex'),
                ('2026-06-02', 1, 'tpex_trading_index', 'open day from TPEx tradingIndex'),
                (
                    '2026-06-03',
                    0,
                    'tpex_trading_index',
                    'closed day inferred from TPEx tradingIndex',
                ),
            ],
        )

    def test_ensure_trading_days_current_raises_when_both_sources_fail(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute(
            'CREATE TABLE trading_days('
            'trade_date TEXT PRIMARY KEY, is_open INTEGER NOT NULL, source TEXT NOT NULL, note TEXT)'
        )

        with self.assertRaisesRegex(ValueError, 'trading calendar unavailable'):
            ensure_trading_days_current(
                conn,
                through_date='2026-06-03',
                fetcher=lambda month: {'stat': 'OK', 'fields': ['日期'], 'data': []},
                fallback_fetcher=lambda month: (_ for _ in ()).throw(RuntimeError('boom')),
            )


if __name__ == '__main__':
    unittest.main()
