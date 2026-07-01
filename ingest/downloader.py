from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
import ssl
import time
from typing import Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

import config


FetchCloseCsv = Callable[[str, str], bytes]
FetchCloseMonthJson = Callable[[str, str, str], dict]
FetchAttentionCsv = Callable[[str, str, str], bytes]
FetchDisposalCsv = Callable[[str, str, str], bytes]
FetchLegalCsv = Callable[[str, str], bytes]
FetchMarginFile = Callable[[str, str], bytes]
FetchDayTradingFile = Callable[[str, str], bytes]
FetchRevenueCsv = Callable[[str, str], bytes]
FetchTradingDaysJson = Callable[[str], dict]
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


def official_stock_month_url(market: str, month: str, stock_id: str) -> str:
    yyyymmdd = f"{month.replace('-', '')}01"
    if market == "TWSE":
        return config.URL_TWSE_STOCK_MONTH.format(date_yyyymmdd=yyyymmdd, stock_id=stock_id)
    if market == "TPEX":
        date_url = quote(f"{month.replace('-', '/')}/01", safe="")
        return config.URL_TPEX_STOCK_MONTH.format(date_url=date_url, stock_id=stock_id)
    raise ValueError(f"unknown market: {market}")


def official_trading_days_url(month_start: str) -> str:
    yyyymmdd = month_start.replace("-", "")
    return config.URL_TWSE_TRADING_DAYS.format(date_yyyymmdd=yyyymmdd)


def official_tpex_trading_days_url(month_start: str) -> str:
    date_url = quote(month_start.replace("-", "/"), safe="")
    return config.URL_TPEX_TRADING_DAYS.format(date_url=date_url)


def official_attention_url(market: str, start: str, end: str) -> str:
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")
    if market == "TWSE":
        return config.URL_TWSE_ATTENTION_NOTICE.format(
            start_date_yyyymmdd=start_yyyymmdd,
            end_date_yyyymmdd=end_yyyymmdd,
        )
    if market == "TPEX":
        return config.URL_TPEX_ATTENTION_NOTICE.format(
            start_date_url=quote(start.replace("-", "/"), safe=""),
            end_date_url=quote(end.replace("-", "/"), safe=""),
        )
    raise ValueError(f"unknown market: {market}")


def official_disposal_url(market: str, start: str, end: str) -> str:
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")
    if market == "TWSE":
        return config.URL_TWSE_DISPOSAL_NOTICE.format(
            start_date_yyyymmdd=start_yyyymmdd,
            end_date_yyyymmdd=end_yyyymmdd,
        )
    if market == "TPEX":
        return config.URL_TPEX_DISPOSAL_NOTICE.format(
            start_date_url=quote(start.replace("-", "/"), safe=""),
            end_date_url=quote(end.replace("-", "/"), safe=""),
        )
    raise ValueError(f"unknown market: {market}")


def official_legal_url(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return config.URL_TWSE_LEGAL_INVESTOR.format(date_yyyymmdd=yyyymmdd)
    if market == "TPEX":
        date_url = quote(trade_date.replace("-", "/"), safe="")
        return config.URL_TPEX_LEGAL_INVESTOR.format(date_url=date_url)
    raise ValueError(f"unknown market: {market}")



def official_margin_url(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    date_url = quote(trade_date.replace("-", "/"), safe="")
    if market == "TWSE":
        return config.URL_TWSE_MARGIN.format(date_yyyymmdd=yyyymmdd)
    if market == "TPEX":
        return config.URL_TPEX_MARGIN_BALANCE.format(date_url=date_url)
    raise ValueError(f"unknown market: {market}")


def official_day_trading_url(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    date_url = quote(trade_date.replace("-", "/"), safe="")
    if market == "TWSE":
        return config.URL_TWSE_DAY_TRADING.format(date_yyyymmdd=yyyymmdd)
    if market == "TPEX":
        return config.URL_TPEX_DAY_TRADING.format(date_url=date_url)
    raise ValueError(f"unknown market: {market}")


def official_revenue_url(market: str, roc_month: str) -> str:
    if market == "TWSE":
        return config.URL_TWSE_REVENUE.format(roc_month=roc_month)
    if market == "TPEX":
        return config.URL_TPEX_REVENUE.format(roc_month=roc_month)
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


def download_close_month_json(market: str, month: str, stock_id: str) -> dict:
    url = official_stock_month_url(market, month, stock_id)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "application/json,*/*",
        },
    )
    with urlopen(request, timeout=30, context=official_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def download_attention_csv(market: str, start: str, end: str) -> bytes:
    url = official_attention_url(market, start, end)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
        },
    )
    with urlopen(request, timeout=30, context=official_ssl_context()) as response:
        return response.read()


def download_disposal_csv(market: str, start: str, end: str) -> bytes:
    url = official_disposal_url(market, start, end)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
        },
    )
    with urlopen(request, timeout=30, context=official_ssl_context()) as response:
        return response.read()



def download_margin_file(market: str, trade_date: str) -> bytes:
    url = official_margin_url(market, trade_date)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
        },
    )
    with urlopen(request, timeout=60, context=official_ssl_context()) as response:
        return response.read()


def download_day_trading_file(market: str, trade_date: str) -> bytes:
    url = official_day_trading_url(market, trade_date)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
        },
    )
    with urlopen(request, timeout=60, context=official_ssl_context()) as response:
        return response.read()


def download_revenue_csv(market: str, roc_month: str) -> bytes:
    url = official_revenue_url(market, roc_month)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
            "Referer": config.URL_MOPS_REVENUE_REFERER,
        },
    )
    with urlopen(request, timeout=60, context=official_ssl_context()) as response:
        return response.read()


def download_legal_csv(market: str, trade_date: str) -> bytes:
    url = official_legal_url(market, trade_date)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "text/csv,*/*",
        },
    )
    with urlopen(request, timeout=60, context=official_ssl_context()) as response:
        return response.read()


def download_trading_days_json(month_start: str) -> dict:
    url = official_trading_days_url(month_start)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "application/json,*/*",
        },
    )
    with urlopen(request, timeout=30, context=official_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def download_tpex_trading_days_json(month_start: str) -> dict:
    url = official_tpex_trading_days_url(month_start)
    request = Request(
        url,
        headers={
            "User-Agent": f"VeriStockDB/{config.APP_VERSION} (+https://github.com/timewu168/VeriStockDB)",
            "Accept": "application/json,*/*",
        },
    )
    with urlopen(request, timeout=30, context=official_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8-sig"))


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


def official_attention_csv_path(market: str, start: str, end: str) -> Path:
    year = start[:4]
    return config.CSV_DIR / "attention_notice" / year / official_attention_csv_name(market, start, end)


def official_attention_csv_name(market: str, start: str, end: str) -> str:
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")
    if market == "TWSE":
        return f"{start_yyyymmdd}_{end_yyyymmdd}NoticeSII.csv"
    if market == "TPEX":
        return f"{start_yyyymmdd}_{end_yyyymmdd}NoticeOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_attention_csv(raw: bytes, market: str, start: str, end: str) -> Path:
    path = official_attention_csv_path(market, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def official_disposal_csv_path(market: str, start: str, end: str) -> Path:
    year = start[:4]
    return config.CSV_DIR / "disposal_notice" / year / official_disposal_csv_name(market, start, end)


def official_disposal_csv_name(market: str, start: str, end: str) -> str:
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")
    if market == "TWSE":
        return f"{start_yyyymmdd}_{end_yyyymmdd}DisposalSII.csv"
    if market == "TPEX":
        return f"{start_yyyymmdd}_{end_yyyymmdd}DisposalOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_disposal_csv(raw: bytes, market: str, start: str, end: str) -> Path:
    path = official_disposal_csv_path(market, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def official_legal_csv_path(market: str, trade_date: str) -> Path:
    year = trade_date[:4]
    return config.CSV_DIR / "legal_investor" / year / official_legal_csv_name(market, trade_date)


def official_legal_csv_name(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return f"{yyyymmdd}LegalSII.csv"
    if market == "TPEX":
        return f"{yyyymmdd}LegalOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_legal_csv(raw: bytes, market: str, trade_date: str) -> Path:
    path = official_legal_csv_path(market, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path



def official_margin_file_path(market: str, trade_date: str) -> Path:
    year = trade_date[:4]
    return config.CSV_DIR / "margin" / year / official_margin_file_name(market, trade_date)


def official_margin_file_name(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return f"{yyyymmdd}MarginSII.csv"
    if market == "TPEX":
        return f"{yyyymmdd}MarginOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_margin_file(raw: bytes, market: str, trade_date: str) -> Path:
    path = official_margin_file_path(market, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def official_day_trading_file_path(market: str, trade_date: str) -> Path:
    year = trade_date[:4]
    return config.CSV_DIR / "day_trading" / year / official_day_trading_file_name(market, trade_date)


def official_day_trading_file_name(market: str, trade_date: str) -> str:
    yyyymmdd = trade_date.replace("-", "")
    if market == "TWSE":
        return f"{yyyymmdd}DayTradingSII.csv"
    if market == "TPEX":
        return f"{yyyymmdd}DayTradingOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_day_trading_file(raw: bytes, market: str, trade_date: str) -> Path:
    path = official_day_trading_file_path(market, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def official_revenue_csv_path(market: str, month: str) -> Path:
    year = month[:4]
    return config.CSV_DIR / "revenue" / year / official_revenue_csv_name(market, month)


def official_revenue_csv_name(market: str, month: str) -> str:
    yyyymm = month.replace("-", "")
    if market == "TWSE":
        return f"{yyyymm}RevenueSII.csv"
    if market == "TPEX":
        return f"{yyyymm}RevenueOTC.csv"
    raise ValueError(f"unknown market: {market}")


def save_official_revenue_csv(raw: bytes, market: str, month: str) -> Path:
    path = official_revenue_csv_path(market, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path
