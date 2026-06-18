from __future__ import annotations

from argparse import Namespace
import unittest
from unittest.mock import patch

import main
from ingest.margin import MarginUpdateResult
from services.telegram_notifier import NotificationResult


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

        results = [
            MarginUpdateResult(
                market="TWSE",
                trade_date="2026-06-18",
                status="BLOCKED",
                row_count=0,
                source_file=None,
                error="BAD_SOURCE_FILE HEADER_NOT_FOUND",
            )
        ]

        with patch.object(main.margin, "update_margin_day", return_value=results), patch.object(
            main.telegram_notifier, "notify_task", side_effect=fake_notify_task
        ):
            code = main._cmd_update_margin(
                None,
                Namespace(date="2026-06-18", market=None, no_cooldown=True),
            )

        self.assertEqual(code, 2)
        self.assertEqual(captured["task_name"], "update-margin")
        self.assertEqual(captured["status"], "BLOCKED")
        self.assertEqual(captured["stats"]["BLOCKED"], 1)
        self.assertIn("BAD_SOURCE_FILE", captured["errors"][0])


if __name__ == "__main__":
    unittest.main()
