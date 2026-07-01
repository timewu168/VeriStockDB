from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

try:
    from fastapi import BackgroundTasks, HTTPException
    from api import deps
    from api.routes import jobs as jobs_route
except ModuleNotFoundError as exc:
    BackgroundTasks = None
    HTTPException = None
    deps = None
    jobs_route = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


@unittest.skipIf(HTTPException is None, f"FastAPI route dependencies are unavailable: {FASTAPI_IMPORT_ERROR}")
class JobsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        jobs_route._jobs.clear()
        jobs_route._schema_ready = False
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.temp_dir.name}/jobs.db"
        self.db_patch = patch.object(jobs_route.config, "DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self) -> None:
        jobs_route._jobs.clear()
        jobs_route._schema_ready = False
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_rejects_unsupported_dataset(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            jobs_route.update_dataset_job(
                jobs_route.UpdateDatasetRequest(dataset="drop_table"),
                BackgroundTasks(),
            )

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"], "INVALID_DATASET")

    def test_queues_allowlisted_update_without_shell_command(self) -> None:
        body = jobs_route.update_dataset_job(
            jobs_route.UpdateDatasetRequest(dataset="legal_investor"),
            BackgroundTasks(),
        )

        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["dataset"], "legal_investor")
        self.assertEqual(body["data"]["command"], ["python3", "main.py", "update-legal"])
        self.assertEqual(body["data"]["status"], "QUEUED")
        saved = jobs_route._load_job(body["data"]["job_id"])
        self.assertIsNotNone(saved)
        self.assertEqual(saved.dataset, "legal_investor")
        self.assertEqual(saved.status, "QUEUED")

    def test_single_writer_guard_blocks_second_job(self) -> None:
        jobs_route.update_dataset_job(
            jobs_route.UpdateDatasetRequest(dataset="daily_close"),
            BackgroundTasks(),
        )

        with self.assertRaises(HTTPException) as cm:
            jobs_route.update_dataset_job(
                jobs_route.UpdateDatasetRequest(dataset="revenue"),
                BackgroundTasks(),
            )

        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], "JOB_ALREADY_RUNNING")

    def test_jobs_limit_validation(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            jobs_route.jobs(limit=0)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"], "INVALID_PAGINATION")

    def test_jobs_list_and_detail_smoke(self) -> None:
        created = jobs_route.update_dataset_job(
            jobs_route.UpdateDatasetRequest(dataset="margin"),
            BackgroundTasks(),
        )["data"]

        list_body = jobs_route.jobs(limit=10)
        detail_body = jobs_route.job_detail(created["job_id"])

        self.assertTrue(list_body["ok"])
        self.assertEqual(list_body["data"][0]["job_id"], created["job_id"])
        self.assertEqual(list_body["data"][0]["dataset"], "margin")
        self.assertIn("running_job_id", list_body["meta"])
        self.assertTrue(detail_body["ok"])
        self.assertEqual(detail_body["data"]["command"], ["python3", "main.py", "update-margin"])
        self.assertFalse(detail_body["data"]["terminal"])

    def test_initialize_job_store_marks_abandoned_jobs_failed(self) -> None:
        body = jobs_route.update_dataset_job(
            jobs_route.UpdateDatasetRequest(dataset="daily_close"),
            BackgroundTasks(),
        )
        job_id = body["data"]["job_id"]
        job = jobs_route._load_job(job_id)
        self.assertIsNotNone(job)
        job.status = "RUNNING"
        jobs_route._upsert_job(job)

        jobs_route._jobs.clear()
        jobs_route.initialize_job_store()
        saved = jobs_route._load_job(job_id)

        self.assertIsNotNone(saved)
        self.assertEqual(saved.status, "FAILED")
        self.assertEqual(saved.error_message, "API restarted before manual update completed")

    def test_read_only_connection_allows_fastapi_threadpool_use(self) -> None:
        class FakeConnection:
            row_factory = None

            def __init__(self) -> None:
                self.closed = False
                self.executed = []

            def execute(self, sql: str) -> None:
                self.executed.append(sql)

            def close(self) -> None:
                self.closed = True

        fake_conn = FakeConnection()
        with patch.object(deps.sqlite3, "connect", return_value=fake_conn) as connect:
            generator = deps.read_only_connection()
            yielded = next(generator)
            with self.assertRaises(StopIteration):
                next(generator)

        self.assertIs(yielded, fake_conn)
        self.assertTrue(fake_conn.closed)
        self.assertIn("PRAGMA foreign_keys=ON", fake_conn.executed)
        self.assertTrue(connect.call_args.kwargs["uri"])
        self.assertFalse(connect.call_args.kwargs["check_same_thread"])
