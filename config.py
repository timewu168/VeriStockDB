from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.3.8.3"
SCHEMA_VERSION = "0.3-margin-trading"


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _int_from_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    return int(value)


def _bool_from_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = _path_from_env("VERISTOCK_DATA_DIR", ROOT_DIR / "data")
CSV_DIR = _path_from_env("VERISTOCK_CSV_DIR", DATA_DIR / "csv")
DB_DIR = _path_from_env("VERISTOCK_DB_DIR", DATA_DIR / "db")
BACKUP_DIR = _path_from_env("VERISTOCK_BACKUP_DIR", DATA_DIR / "backup")
ARCHIVE_DIR = _path_from_env("VERISTOCK_ARCHIVE_DIR", CSV_DIR / "monthly_zip")
LOG_DIR = _path_from_env("VERISTOCK_LOG_DIR", ROOT_DIR / "logs")

DB_PATH = _path_from_env("VERISTOCK_DB_PATH", DB_DIR / "veristock.db")
TRADING_DAY_SEED_DB = _path_from_env(
    "VERISTOCK_TRADING_DAY_SEED_DB", DB_DIR / "trading_days.db"
)

DEFAULT_BACKUP_PATH = _path_from_env(
    "VERISTOCK_BACKUP_PATH", BACKUP_DIR / "veristock_latest_backup.db"
)
DEFAULT_COOLDOWN_MIN_SECONDS = 10
DEFAULT_COOLDOWN_MAX_SECONDS = 15

DATASET_DAILY_CLOSE = "daily_close"
DATASET_ATTENTION_NOTICE = "attention_notice"
DATASET_DISPOSAL_NOTICE = "disposal_notice"
DATASET_LEGAL_INVESTOR = "legal_investor"
DATASET_MARGIN = "margin"
MARKETS = ("TWSE", "TPEX")

API_HOST = os.environ.get("VERISTOCK_API_HOST", "127.0.0.1")
API_PORT = _int_from_env("VERISTOCK_API_PORT", 8000)
API_REQUIRE_AUTH = _bool_from_env("VERISTOCK_API_REQUIRE_AUTH", False)
API_READ_TOKEN = os.environ.get("VERISTOCK_API_READ_TOKEN", "")
API_OPS_TOKEN = os.environ.get("VERISTOCK_API_OPS_TOKEN", "")
API_ADMIN_TOKEN = os.environ.get("VERISTOCK_API_ADMIN_TOKEN", "")

TELEGRAM_ENABLED = _bool_from_env("VERISTOCK_TELEGRAM_ENABLED", False)
TELEGRAM_BOT_TOKEN = os.environ.get("VERISTOCK_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("VERISTOCK_TELEGRAM_CHAT_ID", "")
TELEGRAM_TIMEOUT_SECONDS = _int_from_env("VERISTOCK_TELEGRAM_TIMEOUT_SECONDS", 10)
TELEGRAM_NOTIFY_SUCCESS = _bool_from_env("VERISTOCK_TELEGRAM_NOTIFY_SUCCESS", True)
TELEGRAM_NOTIFY_WARNING = _bool_from_env("VERISTOCK_TELEGRAM_NOTIFY_WARNING", True)
TELEGRAM_NOTIFY_FAILURE = _bool_from_env("VERISTOCK_TELEGRAM_NOTIFY_FAILURE", True)

URL_TWSE_CLOSE = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?response=csv&date={date_yyyymmdd}&type=ALLBUT0999NOTIND"
)
URL_TPEX_CLOSE = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
    "?date={date_url}&id=&response=csv"
)
URL_TWSE_STOCK_MONTH = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    "?response=json&date={date_yyyymmdd}&stockNo={stock_id}"
)
URL_TPEX_STOCK_MONTH = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    "?date={date_url}&code={stock_id}&response=json"
)
URL_TWSE_TRADING_DAYS = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
    "?date={date_yyyymmdd}&response=json"
)
URL_TPEX_TRADING_DAYS = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingIndex"
    "?date={date_url}&id=&response=json"
)
URL_TWSE_ATTENTION_NOTICE = (
    "https://www.twse.com.tw/rwd/zh/announcement/notice"
    "?response=csv&startDate={start_date_yyyymmdd}&endDate={end_date_yyyymmdd}"
    "&stockNo=&sortKind=STKNO&querytype=1&selectType="
)
URL_TPEX_ATTENTION_NOTICE = (
    "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"
    "?startDate={start_date_url}&endDate={end_date_url}"
    "&code=&cate=&type=all&order=date&id=&response=csv"
)
URL_TWSE_LEGAL_INVESTOR = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?date={date_yyyymmdd}&selectType=ALLBUT0999&response=csv"
)
URL_TPEX_LEGAL_INVESTOR = (
    "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
    "?type=Daily&sect=EW&date={date_url}&id=&response=csv"
)

URL_TWSE_MARGIN = (
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    "?response=csv&date={date_yyyymmdd}&selectType=ALL"
)
URL_TPEX_MARGIN_SBL_HIS = (
    "https://www.tpex.org.tw/www/zh-tw/margin/sblHis"
    "?date={date_url}&id=&response=csv&order=0&sort=asc"
)
URL_TPEX_MARGIN_SBL_HIS2 = (
    "https://www.tpex.org.tw/www/zh-tw/margin/sblHis2"
    "?date={date_url}&id=&response=csv&order=0&sort=asc"
)
URL_TPEX_MARGIN_BALANCE = (
    "https://www.tpex.org.tw/www/zh-tw/margin/balance"
    "?date={date_url}&id=&response=csv"
)
URL_TWSE_DISPOSAL_NOTICE = (
    "https://www.twse.com.tw/rwd/zh/announcement/punish"
    "?response=csv&startDate={start_date_yyyymmdd}&endDate={end_date_yyyymmdd}"
    "&stockNo=&sortKind=DATE&querytype=&selectType=&proceType=&remarkType="
)
URL_TPEX_DISPOSAL_NOTICE = (
    "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"
    "?startDate={start_date_url}&endDate={end_date_url}"
    "&code=&cate=&type=all&reason=-1&measure=-1&order=date&id=&response=csv"
)
