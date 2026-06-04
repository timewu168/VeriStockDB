from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.2.7"
SCHEMA_VERSION = "0.2-human-first"


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


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
MARKETS = ("TWSE", "TPEX")

URL_TWSE_CLOSE = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?response=csv&date={date_yyyymmdd}&type=ALLBUT0999NOTIND"
)
URL_TPEX_CLOSE = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
    "?date={date_url}&id=&response=csv"
)
URL_TWSE_TRADING_DAYS = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
    "?date={date_yyyymmdd}&response=json"
)
