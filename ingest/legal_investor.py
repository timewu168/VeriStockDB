from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import sqlite3

import config
from ingest.downloader import (
    CooldownController,
    FetchLegalCsv,
    LogFunc,
    download_legal_csv,
    official_legal_csv_path,
    save_official_legal_csv,
)
from ingest.trading_calendar import (
    ensure_trading_days_current,
    trading_days_between,
    validate_iso_date,
)


DATASET_LEGAL_INVESTOR = config.DATASET_LEGAL_INVESTOR
LEGAL_DOWNLOAD_START = '2019-08-21'
SUPPORTED_ENCODINGS = ('utf-8-sig', 'cp950', 'big5')


@dataclass(frozen=True)
class LegalDownloadResult:
    market: str
    trade_date: str
    status: str
    path: str | None
    bytes_written: int
    error: str | None = None


@dataclass(frozen=True)
class LegalInspectSummary:
    market: str
    source_file: str
    encoding: str
    header_index: int
    fields: list[str]
    row_count: int
    sample_rows: list[list[str]]


def download_legal_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchLegalCsv = download_legal_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> list[LegalDownloadResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f'legal investor start date is after end date: {start} > {end}')
    if start < LEGAL_DOWNLOAD_START:
        raise ValueError(
            f'download-legal only supports official re-download from {LEGAL_DOWNLOAD_START}; '
            f'use existing local CSV for earlier dates'
        )
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    ensure_trading_days_current(conn, through_date=end, cooldown=cooldown, log=log)
    open_dates = trading_days_between(conn, start, end)
    results: list[LegalDownloadResult] = []
    if log:
        log(
            f'INFO legal investor download {start} -> {end} '
            f'open_days={len(open_dates)} markets={",".join(selected_markets)}'
        )
    for trade_date in open_dates:
        for market in selected_markets:
            try:
                cooldown.before_request(log)
                raw = fetcher(market, trade_date)
                validate_legal_csv_bytes(raw, market, trade_date)
                path = save_official_legal_csv(raw, market, trade_date)
                results.append(
                    LegalDownloadResult(
                        market=market,
                        trade_date=trade_date,
                        status='OK',
                        path=str(path),
                        bytes_written=len(raw),
                    )
                )
                if log:
                    log(f'INFO {trade_date} {market} legal CSV saved {path} bytes={len(raw)}')
            except Exception as exc:
                results.append(
                    LegalDownloadResult(
                        market=market,
                        trade_date=trade_date,
                        status='MISSING',
                        path=None,
                        bytes_written=0,
                        error=str(exc),
                    )
                )
                if log:
                    log(f'ERROR {trade_date} {market} legal CSV download failed: {exc}')
    return results


def inspect_legal_file(path: Path | str, market: str, *, sample_size: int = 3) -> LegalInspectSummary:
    if market not in config.MARKETS:
        raise ValueError(f'unknown market: {market}')
    source = Path(path)
    text, encoding = _read_text(source)
    rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(rows)
    fields = [_clean_cell(cell) for cell in rows[header_index]]
    data_rows = [row for row in rows[header_index + 1 :] if _is_data_row(row)]
    sample_rows = [_trim_row(row, len(fields)) for row in data_rows[:sample_size]]
    return LegalInspectSummary(
        market=market,
        source_file=str(source),
        encoding=encoding,
        header_index=header_index,
        fields=fields,
        row_count=len(data_rows),
        sample_rows=sample_rows,
    )


def legal_csv_path(market: str, trade_date: str) -> Path:
    return official_legal_csv_path(market, validate_iso_date(trade_date))


def validate_legal_csv_bytes(raw: bytes, market: str, trade_date: str) -> None:
    if market not in config.MARKETS:
        raise ValueError(f'unknown market: {market}')
    text, _encoding = _decode_legal_text(raw, f'{market} {trade_date}')
    rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(rows)
    data_rows = [row for row in rows[header_index + 1 :] if _is_data_row(row)]
    if not data_rows:
        raise ValueError(f'legal investor CSV has no data rows: {trade_date} {market}')


def _read_text(path: Path) -> tuple[str, str]:
    return _decode_legal_text(path.read_bytes(), str(path))


def _decode_legal_text(raw: bytes, source: str) -> tuple[str, str]:
    last_error: Exception | None = None
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f'cannot decode legal investor CSV: {source}') from last_error


def _find_header_index(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        cleaned = [_clean_cell(cell) for cell in row]
        joined = ' '.join(cleaned)
        has_code = '證券代號' in cleaned or '代號' in cleaned or any('證券代號' in cell for cell in cleaned)
        has_name = '證券名稱' in cleaned or '名稱' in cleaned or any('證券名稱' in cell for cell in cleaned)
        has_legal_columns = any('外資' in cell for cell in cleaned) and any(
            '投信' in cell or '自營商' in cell for cell in cleaned
        )
        if has_code and (has_name or has_legal_columns):
            return index
        if '證券代號' in joined and ('外資' in joined or '三大法人' in joined):
            return index
    raise ValueError('legal investor CSV header not found')


def _is_data_row(row: list[str]) -> bool:
    if not row:
        return False
    first = _clean_cell(row[0])
    return bool(first and not first.startswith('=') and not first.startswith('說明') and first != '證券代號')


def _trim_row(row: list[str], size: int) -> list[str]:
    values = [_clean_cell(cell) for cell in row[:size]]
    if len(values) < size:
        values.extend([''] * (size - len(values)))
    return values


def _clean_cell(value: str) -> str:
    return str(value).strip().strip('\ufeff').strip()
