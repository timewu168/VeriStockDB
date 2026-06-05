from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import config
from api.routes import (
    attention_notices,
    batches,
    daily_close,
    datasets,
    disposal_notices,
    errors,
    events,
    health,
    info,
    ops,
    trading_days,
)
from api.schemas import error_response


def create_app() -> FastAPI:
    app = FastAPI(
        title="VeriStockDB Local Truth API",
        description="Local-only API for the VeriStockDB truth database.",
        version=config.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.include_router(health.router)
    app.include_router(info.router, prefix="/api/v1")
    app.include_router(datasets.router, prefix="/api/v1")
    app.include_router(daily_close.router, prefix="/api/v1")
    app.include_router(attention_notices.router, prefix="/api/v1")
    app.include_router(disposal_notices.router, prefix="/api/v1")
    app.include_router(trading_days.router, prefix="/api/v1")
    app.include_router(batches.router, prefix="/api/v1")
    app.include_router(errors.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(ops.router, prefix="/api/v1")
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    error = detail.get("error", {}) if isinstance(detail.get("error"), dict) else {}
    code = str(detail.get("code") or "INTERNAL_ERROR")
    message = str(error.get("message") or detail.get("message") or exc.detail)
    params = error.get("params") if isinstance(error.get("params"), dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(code=code, message=message, params=params),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=error_response(
            code="INVALID_FIELD",
            message="request validation failed",
            params={"errors": exc.errors()},
        ),
    )


app = create_app()
