from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

import config
from api.deps import require_permission
from api.schemas import success_response


router = APIRouter(tags=["jobs"])


UPDATE_COMMANDS: dict[str, tuple[str, ...]] = {
    config.DATASET_DAILY_CLOSE: ("update-close",),
    config.DATASET_ATTENTION_NOTICE: ("update-attention",),
    config.DATASET_DISPOSAL_NOTICE: ("update-disposal",),
    config.DATASET_LEGAL_INVESTOR: ("update-legal",),
    config.DATASET_MARGIN: ("update-margin",),
    config.DATASET_DAY_TRADING: ("update-day-trading",),
    config.DATASET_REVENUE: ("update-revenue",),
}

TERMINAL_STATUSES = {"DONE", "FAILED"}
MAX_LOG_CHARS = 4000
_jobs: dict[str, "JobRecord"] = {}
_job_lock = threading.Lock()
_schema_lock = threading.Lock()
_schema_ready = False


class UpdateDatasetRequest(BaseModel):
    dataset: str


@dataclass
class JobRecord:
    job_id: str
    dataset: str
    command: list[str]
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    error_message: str | None = None
    messages: list[dict] = field(default_factory=list)


@router.post("/jobs/update-dataset")
def update_dataset_job(
    payload: UpdateDatasetRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_permission("ops")),
) -> dict:
    _ensure_jobs_schema()
    dataset = payload.dataset.strip()
    command = UPDATE_COMMANDS.get(dataset)
    if command is None:
        raise _api_error(
            "INVALID_DATASET",
            status.HTTP_400_BAD_REQUEST,
            f"manual update is not supported for dataset: {payload.dataset}",
            {
                "dataset": payload.dataset,
                "allowed": sorted(UPDATE_COMMANDS),
            },
        )

    with _job_lock:
        _sync_memory_from_db_locked()
        running = _running_job_locked()
        if running is not None:
            raise _api_error(
                "JOB_ALREADY_RUNNING",
                status.HTTP_409_CONFLICT,
                "another update job is already running",
                {
                    "job_id": running.job_id,
                    "dataset": running.dataset,
                    "status": running.status,
                },
            )
        job = JobRecord(
            job_id=f"job_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}",
            dataset=dataset,
            command=["python3", "main.py", *command],
            status="QUEUED",
            created_at=_now(),
            messages=[
                {
                    "code": "MANUAL_UPDATE_REQUESTED",
                    "level": "INFO",
                    "message": "manual dataset update queued",
                }
            ],
        )
        _jobs[job.job_id] = job
        _upsert_job(job)

    background_tasks.add_task(_run_job, job.job_id)
    return success_response(_job_to_dict(job))


@router.get("/jobs")
def jobs(
    limit: int = 50,
    _: None = Depends(require_permission("ops")),
) -> dict:
    _ensure_jobs_schema()
    if limit < 1 or limit > 200:
        raise _api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            "limit must be 1..200",
            {"limit": limit},
        )
    with _job_lock:
        rows = _load_jobs(limit)
        _jobs.update({job.job_id: job for job in rows if job.status not in TERMINAL_STATUSES})
        running = _running_job_locked()
    return success_response(
        [_job_to_dict(job) for job in rows],
        meta={"running_job_id": running.job_id if running else None},
    )


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: str,
    _: None = Depends(require_permission("ops")),
) -> dict:
    _ensure_jobs_schema()
    with _job_lock:
        job = _jobs.get(job_id) or _load_job(job_id)
    if job is None:
        raise _api_error(
            "NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "job not found",
            {"job_id": job_id},
        )
    return success_response(_job_to_dict(job))


def _run_job(job_id: str) -> None:
    _ensure_jobs_schema()
    with _job_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = "RUNNING"
        job.started_at = _now()
        job.messages.append(
            {
                "code": "MANUAL_UPDATE_STARTED",
                "level": "INFO",
                "message": "manual dataset update started",
            }
        )
        _upsert_job(job)

    try:
        completed = subprocess.run(
            job.command,
            cwd=Path(config.ROOT_DIR),
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=None,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime path
        with _job_lock:
            current = _jobs.get(job_id)
            if current is None:
                return
            current.status = "FAILED"
            current.finished_at = _now()
            current.error_message = str(exc)
            current.messages.append(
                {
                    "code": "MANUAL_UPDATE_FAILED",
                    "level": "ERROR",
                    "message": "manual dataset update failed before completion",
                }
            )
            _upsert_job(current)
        return

    with _job_lock:
        current = _jobs.get(job_id)
        if current is None:
            return
        current.returncode = completed.returncode
        current.stdout_tail = _tail(completed.stdout)
        current.stderr_tail = _tail(completed.stderr)
        current.finished_at = _now()
        if completed.returncode == 0:
            current.status = "DONE"
            current.messages.append(
                {
                    "code": "MANUAL_UPDATE_DONE",
                    "level": "INFO",
                    "message": "manual dataset update completed",
                }
            )
        else:
            current.status = "FAILED"
            current.error_message = f"command exited with return code {completed.returncode}"
            current.messages.append(
                {
                    "code": "MANUAL_UPDATE_FAILED",
                    "level": "ERROR",
                    "message": "manual dataset update command failed",
                }
            )
        _upsert_job(current)


def initialize_job_store() -> None:
    _ensure_jobs_schema()
    now = _now()
    message = {
        "code": "MANUAL_UPDATE_ABANDONED",
        "level": "ERROR",
        "message": "API restarted before manual update completed",
    }
    with _job_lock:
        with _connect_jobs_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ops_jobs
                WHERE status NOT IN ('DONE', 'FAILED')
                """
            ).fetchall()
            for row in rows:
                messages = _messages_from_json(row["messages_json"])
                messages.append(message)
                conn.execute(
                    """
                    UPDATE ops_jobs
                    SET status = 'FAILED',
                        finished_at = ?,
                        error_message = ?,
                        messages_json = ?
                    WHERE job_id = ?
                    """,
                    (
                        now,
                        "API restarted before manual update completed",
                        json.dumps(messages, ensure_ascii=False),
                        row["job_id"],
                    ),
                )
        _jobs.clear()


def _running_job_locked() -> JobRecord | None:
    for job in _load_active_jobs():
        _jobs[job.job_id] = job
    for job in _jobs.values():
        if job.status not in TERMINAL_STATUSES:
            return job
    return None


def _job_to_dict(job: JobRecord) -> dict:
    data = asdict(job)
    data["terminal"] = job.status in TERMINAL_STATUSES
    return data


def _sync_memory_from_db_locked() -> None:
    _jobs.clear()
    for job in _load_active_jobs():
        _jobs[job.job_id] = job


def _ensure_jobs_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with _connect_jobs_db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ops_jobs (
                  job_id TEXT PRIMARY KEY,
                  dataset TEXT NOT NULL,
                  command_json TEXT NOT NULL,
                  status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
                  created_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  returncode INTEGER,
                  stdout_tail TEXT NOT NULL DEFAULT '',
                  stderr_tail TEXT NOT NULL DEFAULT '',
                  error_message TEXT,
                  messages_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_ops_jobs_created_at
                ON ops_jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_ops_jobs_status
                ON ops_jobs(status);
                """
            )
        _schema_ready = True


def _connect_jobs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _upsert_job(job: JobRecord) -> None:
    with _connect_jobs_db() as conn:
        conn.execute(
            """
            INSERT INTO ops_jobs (
              job_id, dataset, command_json, status, created_at, started_at,
              finished_at, returncode, stdout_tail, stderr_tail, error_message,
              messages_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              dataset = excluded.dataset,
              command_json = excluded.command_json,
              status = excluded.status,
              created_at = excluded.created_at,
              started_at = excluded.started_at,
              finished_at = excluded.finished_at,
              returncode = excluded.returncode,
              stdout_tail = excluded.stdout_tail,
              stderr_tail = excluded.stderr_tail,
              error_message = excluded.error_message,
              messages_json = excluded.messages_json
            """,
            (
                job.job_id,
                job.dataset,
                json.dumps(job.command, ensure_ascii=False),
                job.status,
                job.created_at,
                job.started_at,
                job.finished_at,
                job.returncode,
                job.stdout_tail,
                job.stderr_tail,
                job.error_message,
                json.dumps(job.messages, ensure_ascii=False),
            ),
        )


def _load_jobs(limit: int) -> list[JobRecord]:
    with _connect_jobs_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ops_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_job_from_row(row) for row in rows]


def _load_active_jobs() -> list[JobRecord]:
    with _connect_jobs_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ops_jobs
            WHERE status NOT IN ('DONE', 'FAILED')
            ORDER BY created_at ASC
            """
        ).fetchall()
    return [_job_from_row(row) for row in rows]


def _load_job(job_id: str) -> JobRecord | None:
    with _connect_jobs_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM ops_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
    return _job_from_row(row) if row else None


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=str(row["job_id"]),
        dataset=str(row["dataset"]),
        command=_command_from_json(row["command_json"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        returncode=row["returncode"],
        stdout_tail=str(row["stdout_tail"] or ""),
        stderr_tail=str(row["stderr_tail"] or ""),
        error_message=row["error_message"],
        messages=_messages_from_json(row["messages_json"]),
    )


def _command_from_json(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return []
    return parsed


def _messages_from_json(value: str | None) -> list[dict]:
    if not value:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _tail(value: str | None) -> str:
    if not value:
        return ""
    return value[-MAX_LOG_CHARS:]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _api_error(
    code: str, http_status: int, message: str, params: dict | None = None
) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "error": {
                "message": message,
                "params": params or {},
            },
        },
    )
