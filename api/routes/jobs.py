from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import os
from pathlib import Path
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

    background_tasks.add_task(_run_job, job.job_id)
    return success_response(_job_to_dict(job))


@router.get("/jobs")
def jobs(
    limit: int = 50,
    _: None = Depends(require_permission("ops")),
) -> dict:
    if limit < 1 or limit > 200:
        raise _api_error(
            "INVALID_PAGINATION",
            status.HTTP_400_BAD_REQUEST,
            "limit must be 1..200",
            {"limit": limit},
        )
    with _job_lock:
        rows = sorted(_jobs.values(), key=lambda job: job.created_at, reverse=True)[:limit]
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
    with _job_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise _api_error(
            "NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "job not found",
            {"job_id": job_id},
        )
    return success_response(_job_to_dict(job))


def _run_job(job_id: str) -> None:
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


def _running_job_locked() -> JobRecord | None:
    for job in _jobs.values():
        if job.status not in TERMINAL_STATUSES:
            return job
    return None


def _job_to_dict(job: JobRecord) -> dict:
    data = asdict(job)
    data["terminal"] = job.status in TERMINAL_STATUSES
    return data


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
