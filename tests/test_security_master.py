from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import config
from db import connection as db_connection
from ingest import security_master


def _raw_snapshot(
    source_date: str,
    rows: list[tuple[str, str, str]],
    market: str = "TWSE",
) -> bytes:
    if market == "TWSE":
        payload = [
            {
                "出表日期": source_date,
                "公司代號": stock_id,
                "公司簡稱": stock_name,
                "產業別": industry_code,
            }
            for stock_id, stock_name, industry_code in rows
        ]
    else:
        payload = [
            {
                "Date": source_date,
                "SecuritiesCompanyCode": stock_id,
                "CompanyAbbreviation": stock_name,
                "SecuritiesIndustryCode": industry_code,
            }
            for stock_id, stock_name, industry_code in rows
        ]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class SecurityMasterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        db_connection.init_db(self.db_path, seed_trading_days=False)
        self.conn = db_connection.connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_parse_official_snapshot(self) -> None:
        snapshot = security_master.parse_security_master_json(
            _raw_snapshot("1150715", [("2330", "台積電", "24")]),
            "TWSE",
        )

        self.assertEqual(snapshot.source_date, "2026-07-15")
        self.assertEqual(snapshot.rows[0].industry_name, "半導體業")

    def test_init_db_updates_runtime_version_settings(self) -> None:
        self.conn.execute("UPDATE settings SET value = 'old' WHERE key = 'app_version'")
        self.conn.execute("UPDATE settings SET value = 'old' WHERE key = 'schema_version'")
        self.conn.commit()
        self.conn.close()

        db_connection.init_db(self.db_path, seed_trading_days=False)
        self.conn = db_connection.connect(self.db_path)
        versions = dict(
            self.conn.execute(
                "SELECT key, value FROM settings WHERE key IN ('app_version', 'schema_version')"
            ).fetchall()
        )

        self.assertEqual(versions["app_version"], config.APP_VERSION)
        self.assertEqual(versions["schema_version"], config.SCHEMA_VERSION)

    def test_unknown_industry_code_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "industry_code='99'"):
            security_master.parse_security_master_json(
                _raw_snapshot("1150715", [("2330", "台積電", "99")]),
                "TWSE",
            )

    def test_snapshot_changes_create_effective_history(self) -> None:
        first = security_master.parse_security_master_json(
            _raw_snapshot(
                "1150715",
                [("2330", "台積電", "24"), ("2303", "聯電", "24")],
            ),
            "TWSE",
        )
        second = security_master.parse_security_master_json(
            _raw_snapshot(
                "1150716",
                [("2330", "台積電新", "24"), ("2603", "長榮", "15")],
            ),
            "TWSE",
        )

        self.assertEqual(security_master._apply_snapshot(self.conn, first), (2, 0, 0))
        self.assertEqual(security_master._apply_snapshot(self.conn, second), (2, 1, 1))

        rows = self.conn.execute(
            "SELECT stock_id, stock_name, effective_from, effective_to "
            "FROM security_master ORDER BY stock_id, effective_from"
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                ("2303", "聯電", "2026-07-15", "2026-07-15"),
                ("2330", "台積電", "2026-07-15", "2026-07-15"),
                ("2330", "台積電新", "2026-07-16", None),
                ("2603", "長榮", "2026-07-16", None),
            ],
        )

    def test_official_import_records_verified_batch_and_archive(self) -> None:
        raw = _raw_snapshot("1150715", [("4542", "科嶠", "05")], market="TPEX")
        archive_root = Path(self.tempdir.name) / "csv"
        with patch.object(config, "CSV_DIR", archive_root):
            result = security_master.import_security_master_official(
                self.conn,
                market="TPEX",
                fetcher=lambda market: raw,
                minimum_rows=1,
            )

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.row_count, 1)
        batch = self.conn.execute(
            "SELECT status, source_file, source_sha256 FROM import_batches "
            "WHERE dataset = 'security_master' AND market = 'TPEX'"
        ).fetchone()
        self.assertEqual(batch["status"], "OK")
        self.assertTrue(Path(batch["source_file"]).exists())
        self.assertEqual(len(batch["source_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
