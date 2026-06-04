from __future__ import annotations

from fastapi import APIRouter

import config


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "code": "OK",
        "status": "healthy",
        "app": "VeriStockDB",
        "api": "local-truth",
        "version": config.APP_VERSION,
    }
