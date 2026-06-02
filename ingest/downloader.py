from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import ssl
import time
from typing import Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

import config


FetchCloseCsv = Callable[[str, str], bytes]
LogFunc = Callable[[str], None]
SleepFunc = Callable[[float], None]


@dataclass
class CooldownController:
    min_seconds: int = config.DEFAULT_COOLDOWN_MIN_SECONDS
    max_seconds: int = config.DEFAULT_COOLDOWN_MAX_SECONDS
    enabled: bool = True
    sleep: SleepFunc = time.sleep
    request_count: int = 0

    def before_request(self, log: LogFunc | None = None) -> None:
        if self.request_count > 0 and self.enabled:
            seconds = random.uniform(self.min_seconds, self.max_seconds)
            if log:
                log(f"INFO cooldown {seconds:.1f}s before official request")
            self.sleep(seconds)
        self.request_count += 1


def official_close_url(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return config.URL_TWSE_CLOSE.format(date_yyyymmdd=yyyymmdd)
    if market == "TPEX":
        date_url = quote(trade_date.replace("-", "/"), safe="")
        return config.URL_TPEX_CLOSE.format(date_url=date_url)
    raise ValueError(f"unknown market: {market}")


def download_close_csv(market: str, trade_date: str) -> bytes:
    url = official_close_url(market, trade_date)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
        },
    )
    with urlopen(request, timeout=30, context=official_ssl_context()) as response:
        return response.read()


def official_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag:
        context.verify_flags &= ~strict_flag
    return context


def official_csv_path(market: str, trade_date: str) -> Path:
    year = trade_date[:4]
    return config.CSV_DIR / "daily_close" / year / official_csv_name(market, trade_date)


def official_csv_name(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return f"{yyyymmdd}CloseSII.csv"
    if market == "TPEX":
        return f"{yyyymmdd}CloseOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_csv(raw: bytes, market: str, trade_date: str) -> Path:
    path = official_csv_path(market, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path
