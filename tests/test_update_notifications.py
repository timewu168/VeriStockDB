from __future__ import annotations

from argparse import Namespace
import sqlite3
import unittest
from unittest.mock import patch

import main
from ingest.legal_investor import LegalUpdateResult
from ingest.margin import MarginUpdateResult
from services.telegram_notifier import NotificationResult


SCHEMA = """
CREATE TABLE trading_days(
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
);
CREATE TABLE legal_investors(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_id TEXT NOT NULL,
  PRIMARY KEY (trade_date, market, stock_id)
);
CREATE TABLE margin_trading(
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_id TEXT NOT NULL,
  PRIMARY KEY (trade_date, market, stock_id)
);
"""


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for trade_date in ("2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"):
        conn.execute("INSERT INTO trading_days VALUES (?, 1, 'seed', '')", (trade_date,))
    conn.execute("INSERT INTO legal_investors VALUES ('2026-06-15', 'TWSE', '2330')")
    conn.execute("INSERT INTO legal_investors VALUES ('2026-06-15', 'TPEX', '5483')")
    conn.execute("INSERT INTO margin_trading VALUES ('2026-06-15', 'TWSE', '2330')")
    conn.execute("INSERT INTO margin_trading VALUES ('2026-06-15', 'TPEX', '5483')")
    conn.commit()
    return conn


class UpdateNotificationTests(unittest.TestCase):
    def test_update_margin_blocked_result_emits_telegram_failure_notification(self) -> None:
        captured = {}

        def fake_notify_task(task_name, status, *, stats=None, lines=None, errors=None):
            captured["task_name"] = task_name
            captured["status"] = status
            captured["stats"] = stats
            captured["lines"] = lines
            captured["errors"] = errors
            return NotificationResult(sent=True)

        def fake_update(conn, *, trade_date, markets=None, cooldown=None, log=None):
            return [
                MarginUpdateResult(
                    market=markets[0],
                    trade_date=trade_date,
                    status="BLOCKED",
                    row_count=0,
                    source_file=None,
                    error="BAD_SOURCE_FILE HEADER_NOT_FOUND",
                )
            ]

        conn = make_conn()
        with patch.object(main.margin, "update_margin_day", side_effect=fake_update), patch.object(
            main.telegram_notifier, "notify_task", side_effect=fake_notify_task
        ):
            code = main._cmd_update_margin(
                conn,
                Namespace(date="2026-06-18", market="TWSE", no_cooldown=True),
            )

        self.assertEqual(code, 2)
        self.assertEqual(captured["task_name"], "update-margin")
        self.assertEqual(captured["status"], "BLOCKED")
        self.assertEqual(captured["stats"]["BLOCKED"], 3)
        self.assertIn("BAD_SOURCE_FILE", captured["errors"][0])


    def test_update_legal_backfills_open_days_after_latest_db_date(self) -> None:
        conn = make_conn()
        calls = []

        def fake_update(conn, *, trade_date, markets=None, cooldown=None, log=None):
            calls.append((trade_date, markets))
            return [
                LegalUpdateResult(
                    market=markets[0],
                    trade_date=trade_date,
                    status="OK",
                    row_count=1,
                    source_file="sample.csv",
                )
            ]

        with patch.object(main.legal_investor, "update_legal_day", side_effect=fake_update), patch.object(
            main.telegram_notifier, "notify_task", return_value=NotificationResult(sent=False, skipped=True, reason="disabled")
        ):
            code = main._cmd_update_legal(
                conn,
                Namespace(date="2026-06-18", market="TWSE", no_cooldown=True),
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                ("2026-06-16", ("TWSE",)),
                ("2026-06-17", ("TWSE",)),
                ("2026-06-18", ("TWSE",)),
            ],
        )

    def test_update_legal_fills_internal_gap_even_when_max_date_exists(self) -> None:
        conn = make_conn()
        conn.execute("INSERT INTO legal_investors VALUES ('2026-06-18', 'TWSE', '2330')")
        conn.commit()
        calls = []

        def fake_update(conn, *, trade_date, markets=None, cooldown=None, log=None):
            calls.append((trade_date, markets))
            return [
                LegalUpdateResult(
                    market=markets[0],
                    trade_date=trade_date,
                    status="OK",
                    row_count=1,
                    source_file="sample.csv",
                )
            ]

        with patch.object(main.legal_investor, "update_legal_day", side_effect=fake_update), patch.object(
            main.telegram_notifier, "notify_task", return_value=NotificationResult(sent=False, skipped=True, reason="disabled")
        ):
            code = main._cmd_update_legal(
                conn,
                Namespace(date="2026-06-18", market="TWSE", no_cooldown=True),
            )

        self.assertEqual(code, 0)
        self.assertEqual(calls, [("2026-06-16", ("TWSE",)), ("2026-06-17", ("TWSE",))])


    def test_update_margin_backfills_open_days_after_latest_db_date(self) -> None:
        conn = make_conn()
        calls = []

        def fake_update(conn, *, trade_date, markets=None, cooldown=None, log=None):
            calls.append((trade_date, markets))
            return [
                MarginUpdateResult(
                    market=markets[0],
                    trade_date=trade_date,
                    status="OK",
                    row_count=1,
                    source_file="sample.csv",
                )
            ]

        with patch.object(main.margin, "update_margin_day", side_effect=fake_update), patch.object(
            main.telegram_notifier, "notify_task", return_value=NotificationResult(sent=False, skipped=True, reason="disabled")
        ):
            code = main._cmd_update_margin(
                conn,
                Namespace(date="2026-06-18", market="TWSE", no_cooldown=True),
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                ("2026-06-16", ("TWSE",)),
                ("2026-06-17", ("TWSE",)),
                ("2026-06-18", ("TWSE",)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
