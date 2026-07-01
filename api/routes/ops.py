from __future__ import annotations

from fastapi import APIRouter, Depends

import config
from api.deps import require_permission
from api.schemas import success_response
from services.dataset_health_check import run_dataset_health_check
from services.ops_check import run_ops_check
from services.schedule_health import run_schedule_health


router = APIRouter(tags=["ops"])


@router.get("/ops/summary")
def ops_summary(
    skip_systemd: bool = False,
    _: None = Depends(require_permission("ops")),
) -> dict:
    result = run_ops_check(
        db_path=config.DB_PATH,
        backup_path=config.DEFAULT_BACKUP_PATH,
        archive_dir=config.ARCHIVE_DIR,
        log_dir=config.LOG_DIR,
        check_systemd=not skip_systemd,
    )
    return success_response(
        {
            "status": result.status,
            "items": [
                {
                    "status": item.status,
                    "name": item.name,
                    "message": item.message,
                }
                for item in result.items
            ],
        },
        meta={
            "filters": {
                "skip_systemd": skip_systemd,
            }
        },
    )

@router.get("/ops/schedule-health")
def ops_schedule_health(
    skip_systemd: bool = False,
    _: None = Depends(require_permission("ops")),
) -> dict:
    result = run_schedule_health(
        db_path=config.DB_PATH,
        log_dir=config.LOG_DIR,
        check_systemd=not skip_systemd,
    )
    return success_response(
        {
            "status": result.status,
            "schedules": result.schedules,
        },
        meta={
            "filters": {
                "skip_systemd": skip_systemd,
            }
        },
    )


@router.get("/ops/dataset-health-check")
def ops_dataset_health_check(
    _: None = Depends(require_permission("ops")),
) -> dict:
    result = run_dataset_health_check(db_path=config.DB_PATH)
    return success_response(
        {
            "status": result.status,
            "datasets": result.datasets,
        },
    )
