from __future__ import annotations

from datetime import date
import sqlite3
import subprocess
import tempfile
from pathlib import Path
import unittest

import config
from services.schedule_health import run_schedule_health


class ScheduleHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "veristock.db"
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()
        self._create_db()
        self._write_logs("update completed OK\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_schedule_health_ok_when_timer_log_and_data_are_current(self) -> None:
        result = run_schedule_health(
            db_path=self.db_path,
            log_dir=self.log_dir,
            today=date(2026, 7, 1),
            runner=self._ok_runner,
        )

        self.assertEqual(result.status, "OK")
        close = next(item for item in result.schedules if item["dataset"] == config.DATASET_DAILY_CLOSE)
        self.assertEqual(close["timer"]["status"], "OK")
        self.assertEqual(close["log"]["status"], "OK")
        self.assertEqual(close["data"]["status"], "OK")
        self.assertEqual(close["data"]["expected_period"], "2026-07-01")
        self.assertEqual(close["data"]["observed_period"], "2026-07-01")

    def test_schedule_health_warns_on_log_error_and_lagging_data(self) -> None:
        self._write_logs("Traceback official endpoint failed\n")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM daily_close")
            conn.execute("INSERT INTO daily_close(trade_date, market, stock_id) VALUES ('2026-06-30', 'TWSE', '2330')")
            conn.execute(
                "UPDATE import_batches SET period = '2026-06-30' WHERE dataset = ?",
                (config.DATASET_DAILY_CLOSE,),
            )

        result = run_schedule_health(
            db_path=self.db_path,
            log_dir=self.log_dir,
            today=date(2026, 7, 1),
            runner=self._ok_runner,
        )

        close = next(item for item in result.schedules if item["dataset"] == config.DATASET_DAILY_CLOSE)
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(close["log"]["status"], "ERROR")
        self.assertEqual(close["data"]["status"], "WARN")
        self.assertIn("before expected", close["data"]["message"])

    def test_schedule_health_reports_disabled_timer(self) -> None:
        result = run_schedule_health(
            db_path=self.db_path,
            log_dir=self.log_dir,
            today=date(2026, 7, 1),
            runner=self._disabled_runner,
        )

        close = next(item for item in result.schedules if item["dataset"] == config.DATASET_DAILY_CLOSE)
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(close["timer"]["status"], "ERROR")
        self.assertIn("not enabled", close["timer"]["message"])

    def _create_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE trading_days(trade_date TEXT PRIMARY KEY, is_open INTEGER NOT NULL);
                CREATE TABLE daily_close(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE legal_investors(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE attention_notices(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE disposal_notices(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE margin_trading(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE day_trading(trade_date TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE monthly_revenue(revenue_month TEXT, market TEXT, stock_id TEXT);
                CREATE TABLE import_batches(
                  batch_id TEXT PRIMARY KEY,
                  dataset TEXT NOT NULL,
                  market TEXT,
                  period TEXT NOT NULL,
                  status TEXT NOT NULL,
                  row_count INTEGER,
                  error_summary TEXT,
                  checked_at TEXT NOT NULL
                );
                """
            )
            conn.execute("INSERT INTO trading_days VALUES ('2026-07-01', 1)")
            for table in (
                "daily_close",
                "legal_investors",
                "attention_notices",
                "disposal_notices",
                "margin_trading",
                "day_trading",
            ):
                conn.execute(f"INSERT INTO {table}(trade_date, market, stock_id) VALUES ('2026-07-01', 'TWSE', '2330')")
            conn.execute("INSERT INTO monthly_revenue VALUES ('2026-05', 'TWSE', '2330')")
            for dataset, period in (
                (config.DATASET_DAILY_CLOSE, "2026-07-01"),
                (config.DATASET_LEGAL_INVESTOR, "2026-07-01"),
                (config.DATASET_ATTENTION_NOTICE, "2026-07-01"),
                (config.DATASET_DISPOSAL_NOTICE, "2026-07-01"),
                (config.DATASET_MARGIN, "2026-07-01"),
                (config.DATASET_DAY_TRADING, "2026-07-01"),
                (config.DATASET_REVENUE, "2026-05"),
            ):
                conn.execute(
                    "INSERT INTO import_batches(batch_id, dataset, market, period, status, row_count, checked_at) "
                    "VALUES (?, ?, 'TWSE', ?, 'OK', 1, '2026-07-01T12:00:00Z')",
                    (f"{dataset}:TWSE:{period}", dataset, period),
                )
            conn.commit()
        finally:
            conn.close()

    def _write_logs(self, text: str) -> None:
        for name in (
            "update-close.log",
            "update-legal.log",
            "update-attention.log",
            "update-disposal.log",
            "update-margin.log",
            "update-day-trading.log",
            "update-revenue.log",
        ):
            (self.log_dir / name).write_text(text, encoding="utf-8")

    def _ok_runner(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="LastTriggerUSec=Wed 2026-07-01 21:10:00 CST\nNextElapseUSecRealtime=Thu 2026-07-02 21:10:00 CST\n",
                stderr="",
            )
        if command[:2] == ["systemctl", "is-enabled"]:
            return subprocess.CompletedProcess(command, 0, stdout="enabled\n", stderr="")
        if command[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unsupported")

    def _disabled_runner(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["systemctl", "is-enabled"]:
            return subprocess.CompletedProcess(command, 1, stdout="disabled\n", stderr="")
        if command[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(command, 3, stdout="inactive\n", stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unsupported")


if __name__ == "__main__":
    unittest.main()
