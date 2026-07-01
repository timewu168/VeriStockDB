from __future__ import annotations

from collections.abc import Callable
import sqlite3

from fastapi import Header, HTTPException, status

import config


PERMISSION_RANK = {
    "read": 1,
    "ops": 2,
    "admin": 3,
}


def require_permission(permission: str) -> Callable[[str | None], None]:
    if permission not in PERMISSION_RANK:
        raise ValueError(f"unknown API permission: {permission}")

    def dependency(authorization: str | None = Header(default=None)) -> None:
        if not config.API_REQUIRE_AUTH:
            return

        token = _bearer_token(authorization)
        if not token:
            raise _auth_error(
                "AUTH_REQUIRED",
                status.HTTP_401_UNAUTHORIZED,
                "bearer token is required",
            )
        if not _token_has_permission(token, permission):
            raise _auth_error(
                "PERMISSION_DENIED",
                status.HTTP_403_FORBIDDEN,
                "token permission is insufficient",
            )

    return dependency


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _token_has_permission(token: str, permission: str) -> bool:
    required_rank = PERMISSION_RANK[permission]
    for candidate_permission, candidate_token in _configured_tokens().items():
        if candidate_token and token == candidate_token:
            return PERMISSION_RANK[candidate_permission] >= required_rank
    return False


def _configured_tokens() -> dict[str, str]:
    return {
        "read": config.API_READ_TOKEN,
        "ops": config.API_OPS_TOKEN,
        "admin": config.API_ADMIN_TOKEN,
    }


def _auth_error(code: str, http_status: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "error": {
                "message": message,
                "params": {},
            },
        },
    )


def read_only_connection():
    path = config.DB_PATH
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error as exc:
        raise _api_error(
            "DB_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"SQLite DB is not readable: {path}",
            {"path": str(path), "reason": str(exc)},
        ) from exc

    try:
        yield conn
    finally:
        conn.close()


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
