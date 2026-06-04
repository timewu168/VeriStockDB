from __future__ import annotations

from fastapi import APIRouter, Depends

import config
from api.deps import require_permission
from api.schemas import API_VERSION, success_response


router = APIRouter(tags=["info"])


@router.get("/info")
def info(_: None = Depends(require_permission("read"))) -> dict:
    return success_response(
        {
            "app_name": "VeriStockDB",
            "app_version": config.APP_VERSION,
            "schema_version": config.SCHEMA_VERSION,
            "api_version": API_VERSION,
            "mode": "local_truth",
        }
    )
