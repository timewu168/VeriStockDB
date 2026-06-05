from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Callable, Protocol
from urllib import error as url_error
from urllib import parse, request

import config


MAX_MESSAGE_LENGTH = 3900
TELEGRAM_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"


class UrlOpen(Protocol):
    def __call__(self, req: request.Request, timeout: int): ...


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool
    bot_token: str
    chat_id: str
    timeout_seconds: int = 10
    notify_success: bool = True
    notify_warning: bool = True
    notify_failure: bool = True


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    skipped: bool = False
    reason: str | None = None
    error: str | None = None


def settings_from_config() -> TelegramSettings:
    return TelegramSettings(
        enabled=config.TELEGRAM_ENABLED,
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
        timeout_seconds=config.TELEGRAM_TIMEOUT_SECONDS,
        notify_success=config.TELEGRAM_NOTIFY_SUCCESS,
        notify_warning=config.TELEGRAM_NOTIFY_WARNING,
        notify_failure=config.TELEGRAM_NOTIFY_FAILURE,
    )


def notify_task(
    task_name: str,
    status: str,
    *,
    stats: dict[str, int] | None = None,
    lines: list[str] | None = None,
    errors: list[str] | None = None,
    settings: TelegramSettings | None = None,
    opener: UrlOpen | None = None,
    generated_at: datetime | None = None,
) -> NotificationResult:
    message = build_task_message(
        task_name,
        status,
        stats=stats,
        lines=lines,
        errors=errors,
        generated_at=generated_at,
    )
    return notify_message(message, status=status, settings=settings, opener=opener)


def notify_message(
    message: str,
    *,
    status: str = "OK",
    settings: TelegramSettings | None = None,
    opener: UrlOpen | None = None,
) -> NotificationResult:
    current_settings = settings or settings_from_config()
    if not current_settings.enabled:
        return NotificationResult(sent=False, skipped=True, reason="disabled")
    if not _should_notify_status(status, current_settings):
        return NotificationResult(sent=False, skipped=True, reason=f"status {status} is disabled")
    if not current_settings.bot_token or not current_settings.chat_id:
        return NotificationResult(
            sent=False,
            skipped=True,
            reason="missing token or chat id",
        )

    text = _trim_message(message)
    url = TELEGRAM_SEND_MESSAGE_URL.format(token=current_settings.bot_token)
    payload = parse.urlencode(
        {
            "chat_id": current_settings.chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    sender = opener or request.urlopen

    try:
        with sender(req, timeout=current_settings.timeout_seconds) as response:
            status_code = _response_status(response)
            body = response.read().decode("utf-8", errors="replace")
    except url_error.HTTPError as exc:
        return NotificationResult(sent=False, error=f"HTTP {exc.code}: {_safe_http_body(exc)}")
    except url_error.URLError as exc:
        return NotificationResult(sent=False, error=str(exc.reason))
    except TimeoutError:
        return NotificationResult(sent=False, error="timeout")
    except OSError as exc:
        return NotificationResult(sent=False, error=str(exc))

    if status_code < 200 or status_code >= 300:
        return NotificationResult(sent=False, error=f"HTTP {status_code}: {body}")

    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return NotificationResult(sent=False, error="invalid Telegram response JSON")
        if parsed.get("ok") is False:
            description = parsed.get("description") or "Telegram API returned ok=false"
            return NotificationResult(sent=False, error=str(description))
    return NotificationResult(sent=True)


def build_task_message(
    task_name: str,
    status: str,
    *,
    stats: dict[str, int] | None = None,
    lines: list[str] | None = None,
    errors: list[str] | None = None,
    generated_at: datetime | None = None,
) -> str:
    timestamp = generated_at or datetime.now().astimezone()
    parts = [
        f"VeriStockDB {task_name} {status.upper()}",
        f"time: {timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    if lines:
        parts.extend(line for line in lines if line)
    if stats is not None:
        parts.append(f"stats: {format_stats(stats)}")
    if errors:
        parts.append("errors:")
        parts.extend(f"- {error}" for error in errors if error)
    return "\n".join(parts)


def status_from_stats(stats: dict[str, int]) -> str:
    if stats.get("BLOCKED", 0):
        return "BLOCKED"
    if stats.get("RECHECK", 0):
        return "RECHECK"
    if stats.get("MISSING", 0):
        return "MISSING"
    return "OK"


def format_stats(stats: dict[str, int]) -> str:
    return (
        f"OK={stats.get('OK', 0)} FIXED={stats.get('FIXED', 0)} "
        f"BLOCKED={stats.get('BLOCKED', 0)} RECHECK={stats.get('RECHECK', 0)} "
        f"MISSING={stats.get('MISSING', 0)} SKIPPED={stats.get('SKIPPED', 0)}"
    )


def _should_notify_status(status: str, settings: TelegramSettings) -> bool:
    normalized = status.upper()
    if normalized == "OK":
        return settings.notify_success
    if normalized in {"WARN", "WARNING"}:
        return settings.notify_warning
    return settings.notify_failure


def _trim_message(message: str) -> str:
    if len(message) <= MAX_MESSAGE_LENGTH:
        return message
    return message[: MAX_MESSAGE_LENGTH - 20].rstrip() + "\n... truncated ..."


def _response_status(response) -> int:
    status = getattr(response, "status", None)
    if status is not None:
        return int(status)
    getcode = getattr(response, "getcode", None)
    if getcode is not None:
        return int(getcode())
    return 200


def _safe_http_body(exc: url_error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)
