from __future__ import annotations

from datetime import date
import re

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_api_date(value: str) -> str:
    if not DATE_RE.fullmatch(value):
        raise ValueError(value)
    return date.fromisoformat(value).isoformat()
