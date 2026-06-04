from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


API_VERSION = "v1"


def utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request_id() -> str:
    return f"req_{uuid4().hex}"


def success_response(data, *, meta: dict | None = None, messages: list | None = None) -> dict:
    response_meta = {
        "api_version": API_VERSION,
        "request_id": request_id(),
        "generated_at": utc_now_text(),
    }
    if meta:
        response_meta.update(meta)
    return {
        "ok": True,
        "code": "OK",
        "data": data,
        "meta": response_meta,
        "messages": messages or [],
    }


def error_response(
    *,
    code: str,
    message: str,
    params: dict | None = None,
    data=None,
    messages: list | None = None,
) -> dict:
    return {
        "ok": False,
        "code": code,
        "data": data,
        "meta": {
            "api_version": API_VERSION,
            "request_id": request_id(),
            "generated_at": utc_now_text(),
        },
        "error": {
            "message": message,
            "params": params or {},
        },
        "messages": messages or [],
    }
