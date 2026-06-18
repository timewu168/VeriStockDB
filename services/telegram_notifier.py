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
TASK_LABELS = {
    "update-close": "Close 日常更新",
    "rollback-close": "Close 三日回滾",
    "update-attention": "注意股公告更新",
    "update-disposal": "處置股公告更新",
    "update-legal": "法人資料更新",
    "update-margin": "資券資料更新",
    "backup": "DB 備份",
    "ops-check": "部署健康檢查",
    "notify-telegram": "Telegram 通知測試",
}
LINE_LABELS = {
    "target": "目標",
    "markets": "市場",
    "latest_before": "更新前",
    "latest_after": "更新後",
    "path": "路徑",
    "size": "大小",
    "message": "訊息",
    "error": "錯誤",
}
VALUE_LABELS = {
    "today": "今天",
}


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
    task_label = TASK_LABELS.get(task_name, task_name)
    parts = [
        f"VeriStockDB {task_label} {status.upper()}",
        f"時間：{timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    if lines:
        parts.extend(_format_detail_line(line) for line in lines if line)
    if stats is not None:
        parts.append(f"統計：{format_stats(stats)}")
    if errors:
        parts.append("錯誤：")
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
        f"成功={stats.get('OK', 0)} 修正={stats.get('FIXED', 0)} "
        f"阻擋={stats.get('BLOCKED', 0)} 複查={stats.get('RECHECK', 0)} "
        f"缺漏={stats.get('MISSING', 0)} 略過={stats.get('SKIPPED', 0)}"
    )


def _format_detail_line(line: str) -> str:
    key, separator, value = line.partition(":")
    if not separator:
        return line
    label = LINE_LABELS.get(key.strip(), key.strip())
    display_value = VALUE_LABELS.get(value.strip(), value.strip())
    return f"{label}：{display_value}"


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
    return message[: MAX_MESSAGE_LENGTH - 20].rstrip() + "\n... 已截斷 ..."


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
