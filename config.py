from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.2.0"
SCHEMA_VERSION = "0.2-human-first"
DATA_DIR = ROOT_DIR / "data"
CSV_DIR = DATA_DIR / "csv"
DB_DIR = DATA_DIR / "db"
BACKUP_DIR = DATA_DIR / "backup"

DB_PATH = DB_DIR / "veristock.db"
TRADING_DAY_SEED_DB = DB_DIR / "trading_days.db"

DEFAULT_BACKUP_PATH = BACKUP_DIR / "veristock_latest_backup.db"
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
