from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import sqlite3

import config
from ingest.downloader import (
    CooldownController,
    FetchSecurityMasterJson,
    LogFunc,
    download_security_master_json,
    official_security_master_url,
    save_official_security_master_json,
)
from services import batch_status
from validate.close_rules import _clean_stock_id
from validate.result import ValidationError


DATASET = config.DATASET_SECURITY_MASTER

# Official TWSE/TPEX securities industry codes. Market overrides preserve the
# official wording where the same code has a market-specific label.
COMMON_INDUSTRY_NAMES = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "18": "貿易百貨",
    "20": "其他業",
    "21": "化學工業",
    "22": "生技醫療業",
    "23": "油電燃氣業",
    "24": "半導體業",
    "25": "電腦及週邊設備業",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    "32": "文化創意業",
    "33": "農業科技業",
    "34": "電子商務",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
}
MARKET_INDUSTRY_NAMES = {
    "TWSE": {"17": "金融保險業", "91": "存託憑證"},
    "TPEX": {"17": "金融業", "80": "管理股票"},
}


@dataclass(frozen=True)
class SecurityMasterRow:
    market: str
    stock_id: str
    stock_name: str
    industry_code: str
    industry_name: str


@dataclass(frozen=True)
class SecurityMasterSnapshot:
    market: str
    source_date: str
    rows: list[SecurityMasterRow]


@dataclass(frozen=True)
class SecurityMasterImportResult:
    market: str
    source_date: str
    status: str
    row_count: int
    inserted: int
    changed: int
    closed: int


def industry_name(market: str, code: str) -> str | None:
    return MARKET_INDUSTRY_NAMES.get(market, {}).get(code) or COMMON_INDUSTRY_NAMES.get(code)


def parse_security_master_json(raw: bytes, market: str) -> SecurityMasterSnapshot:
    if market not in config.MARKETS:
        raise ValueError(f"unknown market: {market}")
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("security master response must be a non-empty JSON array")

    rows: list[SecurityMasterRow] = []
    source_dates: set[str] = set()
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("security master row must be a JSON object")
        if market == "TWSE":
            stock_id = _clean_stock_id(str(item.get("公司代號", "")))
            stock_name = str(item.get("公司簡稱", "")).strip()
            industry_code = str(item.get("產業別", "")).strip().zfill(2)
            source_date = _roc_compact_to_iso(str(item.get("出表日期", "")).strip())
        else:
            stock_id = _clean_stock_id(str(item.get("SecuritiesCompanyCode", "")))
            stock_name = str(item.get("CompanyAbbreviation", "")).strip()
            industry_code = str(item.get("SecuritiesIndustryCode", "")).strip().zfill(2)
            source_date = _roc_compact_to_iso(str(item.get("Date", "")).strip())
        resolved_industry = industry_name(market, industry_code)
        if not stock_id or not stock_name or not resolved_industry:
            raise ValueError(
                f"invalid security master row: stock_id={stock_id!r}, "
                f"stock_name={stock_name!r}, industry_code={industry_code!r}"
            )
        if stock_id in seen:
            raise ValueError(f"duplicate security master stock_id: {market}:{stock_id}")
        seen.add(stock_id)
        source_dates.add(source_date)
        rows.append(
            SecurityMasterRow(
                market=market,
                stock_id=stock_id,
                stock_name=stock_name,
                industry_code=industry_code,
                industry_name=resolved_industry,
            )
        )
    if len(source_dates) != 1:
        raise ValueError(f"security master has inconsistent source dates: {sorted(source_dates)}")
    return SecurityMasterSnapshot(market=market, source_date=source_dates.pop(), rows=rows)


def import_security_master_official(
    conn: sqlite3.Connection,
    *,
    market: str,
    fetcher: FetchSecurityMasterJson = download_security_master_json,
    minimum_rows: int = 100,
) -> SecurityMasterImportResult:
    raw: bytes | None = None
    source_date = date.today().isoformat()
    try:
        raw = fetcher(market)
        snapshot = parse_security_master_json(raw, market)
        source_date = snapshot.source_date
        if len(snapshot.rows) < minimum_rows:
            raise ValueError(
                f"security master row count below minimum: {len(snapshot.rows)} < {minimum_rows}"
            )
        path = save_official_security_master_json(raw, market, source_date)
        conn.execute("SAVEPOINT security_master_snapshot")
        try:
            inserted, changed, closed = _apply_snapshot(conn, snapshot)
            conn.execute("RELEASE SAVEPOINT security_master_snapshot")
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT security_master_snapshot")
            conn.execute("RELEASE SAVEPOINT security_master_snapshot")
            raise
        existing = batch_status.get_batch(conn, DATASET, market, source_date)
        status = "FIXED" if existing and existing["status"] in {"BLOCKED", "RECHECK", "MISSING"} else "OK"
        batch_status.record_batch(
            conn,
            dataset=DATASET,
            market=market,
            period=source_date,
            status=status,
            row_count=len(snapshot.rows),
            errors=[],
            source_file=str(path),
            source_sha256=hashlib.sha256(raw).hexdigest(),
            note=f"inserted={inserted}; changed={changed}; closed={closed}",
            clear_manual_approval=True,
        )
        return SecurityMasterImportResult(
            market=market,
            source_date=source_date,
            status=status,
            row_count=len(snapshot.rows),
            inserted=inserted,
            changed=changed,
            closed=closed,
        )
    except Exception as exc:
        status = "MISSING" if raw is None else "BLOCKED"
        batch_status.record_batch(
            conn,
            dataset=DATASET,
            market=market,
            period=source_date,
            status=status,
            row_count=None,
            errors=[ValidationError("BLOCK", "SECURITY_MASTER_IMPORT_FAILED", str(exc))],
            source_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
            note="official_openapi_snapshot",
        )
        return SecurityMasterImportResult(
            market=market,
            source_date=source_date,
            status=status,
            row_count=0,
            inserted=0,
            changed=0,
            closed=0,
        )


def update_security_master(
    conn: sqlite3.Connection,
    *,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchSecurityMasterJson = download_security_master_json,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
    minimum_rows: int = 100,
) -> dict[str, int]:
    stats = {
        "OK": 0,
        "FIXED": 0,
        "BLOCKED": 0,
        "RECHECK": 0,
        "MISSING": 0,
        "SKIPPED": 0,
    }
    cooldown = cooldown or CooldownController()
    for market in markets or config.MARKETS:
        cooldown.before_request(log)
        result = import_security_master_official(
            conn,
            market=market,
            fetcher=fetcher,
            minimum_rows=minimum_rows,
        )
        stats[result.status] += 1
        if log:
            log(
                f"INFO security_master {market} {result.source_date} {result.status} "
                f"rows={result.row_count} inserted={result.inserted} "
                f"changed={result.changed} closed={result.closed}"
            )
    return stats


def _apply_snapshot(conn: sqlite3.Connection, snapshot: SecurityMasterSnapshot) -> tuple[int, int, int]:
    current_rows = conn.execute(
        "SELECT * FROM security_master WHERE market = ? AND effective_to IS NULL",
        (snapshot.market,),
    ).fetchall()
    current = {str(row["stock_id"]): row for row in current_rows}
    latest = max((str(row["effective_from"]) for row in current_rows), default=None)
    if latest and snapshot.source_date < latest:
        raise ValueError(
            f"stale security master snapshot: source_date={snapshot.source_date} latest={latest}"
        )

    incoming = {row.stock_id: row for row in snapshot.rows}
    close_date = (date.fromisoformat(snapshot.source_date) - timedelta(days=1)).isoformat()
    inserted = changed = closed = 0
    source_url = official_security_master_url(snapshot.market)

    for stock_id, existing in current.items():
        replacement = incoming.get(stock_id)
        is_same = replacement and (
            existing["stock_name"] == replacement.stock_name
            and existing["industry_code"] == replacement.industry_code
            and existing["industry_name"] == replacement.industry_name
        )
        if is_same:
            conn.execute(
                "UPDATE security_master SET source_updated_date = ?, source_url = ? "
                "WHERE market = ? AND stock_id = ? AND effective_from = ?",
                (
                    snapshot.source_date,
                    source_url,
                    snapshot.market,
                    stock_id,
                    existing["effective_from"],
                ),
            )
            continue
        if existing["effective_from"] == snapshot.source_date:
            conn.execute(
                "DELETE FROM security_master WHERE market = ? AND stock_id = ? AND effective_from = ?",
                (snapshot.market, stock_id, snapshot.source_date),
            )
        else:
            conn.execute(
                "UPDATE security_master SET effective_to = ? "
                "WHERE market = ? AND stock_id = ? AND effective_to IS NULL",
                (close_date, snapshot.market, stock_id),
            )
        if replacement:
            changed += 1
        else:
            closed += 1

    for row in snapshot.rows:
        existing = current.get(row.stock_id)
        if existing and (
            existing["stock_name"] == row.stock_name
            and existing["industry_code"] == row.industry_code
            and existing["industry_name"] == row.industry_name
        ):
            continue
        conn.execute(
            """
            INSERT INTO security_master(
              market, stock_id, stock_name, industry_code, industry_name,
              effective_from, effective_to, source_updated_date, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                row.market,
                row.stock_id,
                row.stock_name,
                row.industry_code,
                row.industry_name,
                snapshot.source_date,
                snapshot.source_date,
                source_url,
            ),
        )
        inserted += 1
    return inserted, changed, closed


def _roc_compact_to_iso(value: str) -> str:
    if not value.isdigit() or len(value) not in {7, 8}:
        raise ValueError(f"invalid ROC compact date: {value!r}")
    year_digits = len(value) - 4
    return date(int(value[:year_digits]) + 1911, int(value[year_digits:year_digits + 2]), int(value[-2:])).isoformat()
