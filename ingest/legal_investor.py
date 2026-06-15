from __future__ import annotations

import csv
from dataclasses import dataclass
import re
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
    is_open,
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


@dataclass(frozen=True)
class LegalInvestorRow:
    trade_date: str
    market: str
    stock_id: str
    stock_name: str
    foreign_buy: int
    foreign_sell: int
    foreign_net: int
    investment_trust_buy: int
    investment_trust_sell: int
    investment_trust_net: int
    dealer_buy: int
    dealer_sell: int
    dealer_net: int
    dealer_hedge_buy: int
    dealer_hedge_sell: int
    dealer_hedge_net: int


@dataclass(frozen=True)
class LegalParseResult:
    market: str
    trade_date: str
    source_file: str
    encoding: str
    fields: list[str]
    rows: list[LegalInvestorRow]


@dataclass(frozen=True)
class LegalDryRunResult:
    market: str
    trade_date: str
    status: str
    source_file: str | None
    row_count: int
    error: str | None = None




@dataclass(frozen=True)
class LegalUpdateResult:
    market: str
    trade_date: str
    status: str
    row_count: int
    source_file: str | None
    error: str | None = None

@dataclass(frozen=True)
class LegalImportResult:
    market: str
    start: str
    end: str
    open_days: int
    row_count: int

@dataclass(frozen=True)
class LegalReportMarketSummary:
    market: str
    start: str | None
    end: str | None
    open_days: int
    ok: int
    blocked: int
    missing: int
    rows: int


@dataclass(frozen=True)
class LegalReport:
    summaries: list[LegalReportMarketSummary]
    results: list[LegalDryRunResult]
    problems: list[LegalDryRunResult]


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
                validate_legal_csv_bytes(
                    raw,
                    market,
                    trade_date,
                    daily_close_row_count=daily_close_row_count(conn, market, trade_date),
                )
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


def inspect_legal_file(
    path: Path | str,
    market: str,
    *,
    sample_size: int = 3,
    daily_close_row_count: int | None = None,
) -> LegalInspectSummary:
    if market not in config.MARKETS:
        raise ValueError(f'unknown market: {market}')
    source = Path(path)
    text, encoding = _read_text(source)
    rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(rows)
    fields = [_clean_cell(cell) for cell in rows[header_index]]
    data_rows = [row for row in rows[header_index + 1 :] if _is_data_row(row)]
    _validate_legal_rows(
        fields,
        data_rows,
        market,
        source.name,
        daily_close_row_count=daily_close_row_count,
    )
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


def parse_legal_file(path: Path | str, market: str, trade_date: str) -> LegalParseResult:
    trade_date = validate_iso_date(trade_date)
    if market not in config.MARKETS:
        raise ValueError(f'unknown market: {market}')
    source = Path(path)
    raw = source.read_bytes()
    validate_legal_csv_bytes(raw, market, trade_date)
    text, encoding = _decode_legal_text(raw, str(source))
    rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(rows)
    fields = [_clean_cell(cell) for cell in rows[header_index]]
    mapping = _build_normalized_mapping(fields, market)
    parsed_rows = [
        _parse_legal_row(row, fields, mapping, market, trade_date)
        for row in rows[header_index + 1 :]
        if _is_data_row(row)
    ]
    return LegalParseResult(
        market=market,
        trade_date=trade_date,
        source_file=str(source),
        encoding=encoding,
        fields=fields,
        rows=parsed_rows,
    )


def dry_run_legal_file(path: Path | str, market: str, trade_date: str) -> LegalDryRunResult:
    trade_date = validate_iso_date(trade_date)
    try:
        result = parse_legal_file(path, market, trade_date)
    except Exception as exc:
        return LegalDryRunResult(
            market=market,
            trade_date=trade_date,
            status='BLOCKED',
            source_file=str(path),
            row_count=0,
            error=str(exc),
        )
    return LegalDryRunResult(
        market=market,
        trade_date=trade_date,
        status='OK',
        source_file=result.source_file,
        row_count=len(result.rows),
    )


def dry_run_legal_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
) -> list[LegalDryRunResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f'legal investor start date is after end date: {start} > {end}')
    selected_markets = markets or config.MARKETS
    results: list[LegalDryRunResult] = []
    for trade_date in trading_days_between(conn, start, end):
        for market in selected_markets:
            source_path = find_legal_csv_path(market, trade_date)
            if source_path is None:
                results.append(
                    LegalDryRunResult(
                        market=market,
                        trade_date=trade_date,
                        status='MISSING',
                        source_file=None,
                        row_count=0,
                        error='legal investor CSV file not found',
                    )
                )
                continue
            results.append(dry_run_legal_file(source_path, market, trade_date))
    return results




def update_legal_day(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    markets: tuple[str, ...] | None = None,
    fetcher: FetchLegalCsv = download_legal_csv,
    cooldown: CooldownController | None = None,
    log: LogFunc | None = None,
) -> list[LegalUpdateResult]:
    trade_date = validate_iso_date(trade_date)
    selected_markets = markets or config.MARKETS
    cooldown = cooldown or CooldownController()
    open_status = is_open(conn, trade_date)
    if open_status is None:
        ensure_trading_days_current(conn, through_date=trade_date, cooldown=cooldown, log=log)
        open_status = is_open(conn, trade_date)
    if open_status is not True:
        return [
            LegalUpdateResult(
                market=market,
                trade_date=trade_date,
                status='CLOSED',
                row_count=0,
                source_file=None,
                error='not an open trading day',
            )
            for market in selected_markets
        ]

    results: list[LegalUpdateResult] = []
    for market in selected_markets:
        existing = legal_investor_row_count(conn, market=market, trade_date=trade_date)
        if existing:
            results.append(
                LegalUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status='EXISTS',
                    row_count=existing,
                    source_file=None,
                    error='legal investor rows already exist; not overwriting',
                )
            )
            continue
        close_rows = daily_close_row_count(conn, market, trade_date)
        if not close_rows:
            results.append(
                LegalUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status='BLOCKED',
                    row_count=0,
                    source_file=None,
                    error='matching daily_close rows not found',
                )
            )
            continue
        try:
            cooldown.before_request(log)
            raw = fetcher(market, trade_date)
            validate_legal_csv_bytes(
                raw,
                market,
                trade_date,
                daily_close_row_count=close_rows,
            )
            path = save_official_legal_csv(raw, market, trade_date)
            imported = import_legal_range(conn, start=trade_date, end=trade_date, markets=(market,))
            results.append(
                LegalUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status='OK',
                    row_count=imported[0].row_count,
                    source_file=str(path),
                )
            )
        except Exception as exc:
            results.append(
                LegalUpdateResult(
                    market=market,
                    trade_date=trade_date,
                    status='BLOCKED',
                    row_count=0,
                    source_file=None,
                    error=str(exc),
                )
            )
    return results


def legal_investor_row_count(
    conn: sqlite3.Connection,
    *,
    market: str | None = None,
    trade_date: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[str] = []
    if market is not None:
        clauses.append('market = ?')
        params.append(market)
    if trade_date is not None:
        clauses.append('trade_date = ?')
        params.append(validate_iso_date(trade_date))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    row = conn.execute(f'SELECT COUNT(*) FROM legal_investors{where}', params).fetchone()
    return int(row['COUNT(*)'] if isinstance(row, sqlite3.Row) else row[0])

def import_legal_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    markets: tuple[str, ...] | None = None,
) -> list[LegalImportResult]:
    start = validate_iso_date(start)
    end = validate_iso_date(end)
    if start > end:
        raise ValueError(f'legal investor start date is after end date: {start} > {end}')
    selected_markets = markets or config.MARKETS
    results = dry_run_legal_range(conn, start=start, end=end, markets=selected_markets)
    problems = [result for result in results if result.status != 'OK']
    if problems:
        first = problems[0]
        raise ValueError(
            'legal investor import blocked by dry-run problem: '
            f'{first.trade_date} {first.market} {first.status} {first.error or ""}'.rstrip()
        )
    open_dates = trading_days_between(conn, start, end)
    _ensure_legal_target_scope_empty(conn, open_dates, selected_markets)

    parsed_by_market: dict[str, list[LegalInvestorRow]] = {market: [] for market in selected_markets}
    for result in results:
        if result.source_file is None:
            raise ValueError(f'legal investor import missing source after dry-run OK: {result.trade_date} {result.market}')
        parsed = parse_legal_file(result.source_file, result.market, result.trade_date)
        parsed_by_market[result.market].extend(parsed.rows)

    import_results: list[LegalImportResult] = []
    for market in selected_markets:
        rows = parsed_by_market[market]
        _insert_legal_rows(conn, rows)
        import_results.append(
            LegalImportResult(
                market=market,
                start=start,
                end=end,
                open_days=sum(1 for result in results if result.market == market),
                row_count=len(rows),
            )
        )
    return import_results


def _ensure_legal_target_scope_empty(
    conn: sqlite3.Connection,
    open_dates: list[str],
    markets: tuple[str, ...],
) -> None:
    if not open_dates:
        return
    date_placeholders = ','.join('?' for _ in open_dates)
    market_placeholders = ','.join('?' for _ in markets)
    params = [*open_dates, *markets]
    row = conn.execute(
        f'SELECT COUNT(*) FROM legal_investors '
        f'WHERE trade_date IN ({date_placeholders}) AND market IN ({market_placeholders})',
        params,
    ).fetchone()
    count = int(row['COUNT(*)'] if isinstance(row, sqlite3.Row) else row[0])
    if count:
        raise ValueError(
            f'legal investor target scope is not empty: rows={count} '
            f'dates={open_dates[0]}..{open_dates[-1]} markets={",".join(markets)}'
        )


def _insert_legal_rows(conn: sqlite3.Connection, rows: list[LegalInvestorRow]) -> None:
    sql = """
        INSERT INTO legal_investors (
          trade_date, market, stock_id, stock_name,
          foreign_buy, foreign_sell, foreign_net,
          investment_trust_buy, investment_trust_sell, investment_trust_net,
          dealer_buy, dealer_sell, dealer_net,
          dealer_hedge_buy, dealer_hedge_sell, dealer_hedge_net
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(
        sql,
        [
            (
                row.trade_date,
                row.market,
                row.stock_id,
                row.stock_name,
                row.foreign_buy,
                row.foreign_sell,
                row.foreign_net,
                row.investment_trust_buy,
                row.investment_trust_sell,
                row.investment_trust_net,
                row.dealer_buy,
                row.dealer_sell,
                row.dealer_net,
                row.dealer_hedge_buy,
                row.dealer_hedge_sell,
                row.dealer_hedge_net,
            )
            for row in rows
        ],
    )

def legal_csv_report(
    conn: sqlite3.Connection,
    *,
    start: str | None = None,
    end: str | None = None,
    markets: tuple[str, ...] | None = None,
) -> LegalReport:
    selected_markets = markets or config.MARKETS
    summaries: list[LegalReportMarketSummary] = []
    all_results: list[LegalDryRunResult] = []
    problems: list[LegalDryRunResult] = []
    for market in selected_markets:
        available_dates = list_legal_csv_dates(market)
        if not available_dates:
            summaries.append(
                LegalReportMarketSummary(
                    market=market,
                    start=None,
                    end=None,
                    open_days=0,
                    ok=0,
                    blocked=0,
                    missing=0,
                    rows=0,
                )
            )
            continue
        market_start = validate_iso_date(start) if start else available_dates[0]
        market_end = validate_iso_date(end) if end else available_dates[-1]
        results = dry_run_legal_range(
            conn,
            start=market_start,
            end=market_end,
            markets=(market,),
        )
        all_results.extend(results)
        ok = sum(1 for result in results if result.status == 'OK')
        blocked = sum(1 for result in results if result.status == 'BLOCKED')
        missing = sum(1 for result in results if result.status == 'MISSING')
        rows = sum(result.row_count for result in results if result.status == 'OK')
        summaries.append(
            LegalReportMarketSummary(
                market=market,
                start=market_start,
                end=market_end,
                open_days=len(results),
                ok=ok,
                blocked=blocked,
                missing=missing,
                rows=rows,
            )
        )
        problems.extend(result for result in results if result.status != 'OK')
    return LegalReport(summaries=summaries, results=all_results, problems=problems)


def list_legal_csv_dates(market: str) -> list[str]:
    if market not in config.MARKETS:
        raise ValueError(f'unknown market: {market}')
    dates: set[str] = set()
    root = config.CSV_DIR / 'legal_investor'
    suffix = 'LegalSII.csv' if market == 'TWSE' else 'LegalOTC.csv'
    legacy_prefix = 'LegalSII' if market == 'TWSE' else 'LegalOTC'
    for path in root.rglob('*.csv'):
        name = path.name
        trade_date = None
        if name.endswith(suffix) and re.fullmatch(r'\d{8}' + re.escape(suffix), name):
            trade_date = _date_from_yyyymmdd(name[:8])
        elif name.startswith(legacy_prefix) and re.fullmatch(re.escape(legacy_prefix) + r'\d{8}\.csv', name):
            trade_date = _date_from_yyyymmdd(name[len(legacy_prefix):len(legacy_prefix) + 8])
        if trade_date:
            dates.add(trade_date)
    return sorted(dates)


def _date_from_yyyymmdd(value: str) -> str | None:
    if not re.fullmatch(r'\d{8}', value):
        return None
    return f'{value[:4]}-{value[4:6]}-{value[6:8]}'


def find_legal_csv_path(market: str, trade_date: str) -> Path | None:
    for path in _legal_csv_path_candidates(market, validate_iso_date(trade_date)):
        if path.exists():
            return path
    return None


def _legal_csv_path_candidates(market: str, trade_date: str) -> list[Path]:
    yyyymmdd = trade_date.replace('-', '')
    standard = legal_csv_path(market, trade_date)
    root = config.CSV_DIR / 'legal_investor'
    if market == 'TWSE':
        legacy_name = f'LegalSII{yyyymmdd}.csv'
        return [
            standard,
            root / '2012-2014' / 'SII' / legacy_name,
            root / '2014-2017' / legacy_name,
            root / '2017-2019' / legacy_name,
        ]
    legacy_name = f'LegalOTC{yyyymmdd}.csv'
    return [
        standard,
        root / '2012-2014' / 'LegalOTC2007-2014' / legacy_name,
        root / '2014-2017' / legacy_name,
        root / '2017-2019' / legacy_name,
    ]


def _build_normalized_mapping(fields: list[str], market: str) -> dict[str, int | None]:
    mapping: dict[str, int | None] = {
        'stock_id': _find_field(fields, ('證券代號', '代號')),
        'stock_name': _find_field(fields, ('證券名稱', '名稱')),
    }
    foreign_marker = '外資及陸資-' if market == 'TPEX' else None
    mapping.update(
        _triple_mapping(
            fields,
            'foreign',
            include_any=('外陸資', '外資及陸資', '外資'),
            exclude_any=() if foreign_marker is None else ('不含外資自營商',),
            preferred_prefix=foreign_marker,
        )
    )
    mapping.update(
        _triple_mapping(fields, 'investment_trust', include_any=('投信',), exclude_any=())
    )
    mapping.update(
        _triple_mapping(
            fields,
            'dealer',
            include_any=('自營商', '自營'),
            exclude_any=('外資自營商', '避險', '三大法人', '合計'),
            preferred_any=('自行買賣',),
        )
    )
    hedge = _triple_mapping(fields, 'dealer_hedge', include_any=('避險',), exclude_any=('外資自營商',))
    mapping.update(hedge)
    required = [
        'stock_id', 'stock_name', 'foreign_buy', 'foreign_sell', 'foreign_net',
        'investment_trust_buy', 'investment_trust_sell', 'investment_trust_net',
        'dealer_buy', 'dealer_sell', 'dealer_net',
    ]
    missing = [name for name in required if mapping.get(name) is None]
    if missing:
        raise ValueError('legal investor CSV missing normalized columns: ' + ', '.join(missing))
    has_partial_hedge = any(mapping.get(name) is not None for name in ('dealer_hedge_buy', 'dealer_hedge_sell', 'dealer_hedge_net'))
    has_full_hedge = all(mapping.get(name) is not None for name in ('dealer_hedge_buy', 'dealer_hedge_sell', 'dealer_hedge_net'))
    if has_partial_hedge and not has_full_hedge:
        raise ValueError('legal investor CSV has partial hedge columns')
    return mapping


def _triple_mapping(
    fields: list[str],
    prefix: str,
    *,
    include_any: tuple[str, ...],
    exclude_any: tuple[str, ...],
    preferred_any: tuple[str, ...] = (),
    preferred_prefix: str | None = None,
) -> dict[str, int | None]:
    return {
        f'{prefix}_buy': _find_numeric_field(fields, 'buy', include_any, exclude_any, preferred_any, preferred_prefix),
        f'{prefix}_sell': _find_numeric_field(fields, 'sell', include_any, exclude_any, preferred_any, preferred_prefix),
        f'{prefix}_net': _find_numeric_field(fields, 'net', include_any, exclude_any, preferred_any, preferred_prefix),
    }


def _find_field(fields: list[str], names: tuple[str, ...]) -> int | None:
    for index, field in enumerate(fields):
        if field in names:
            return index
    return None


def _find_numeric_field(
    fields: list[str],
    kind: str,
    include_any: tuple[str, ...],
    exclude_any: tuple[str, ...],
    preferred_any: tuple[str, ...],
    preferred_prefix: str | None,
) -> int | None:
    candidates = [
        (index, field)
        for index, field in enumerate(fields)
        if field
        and any(token in field for token in include_any)
        and not any(token in field for token in exclude_any)
        and not ('外資' in include_any and _is_foreign_dealer_field(field))
        and _field_matches_kind(field, kind)
    ]
    if preferred_prefix:
        preferred = [(index, field) for index, field in candidates if field.startswith(preferred_prefix)]
        if preferred:
            return preferred[0][0]
    if preferred_any:
        preferred = [(index, field) for index, field in candidates if any(token in field for token in preferred_any)]
        if preferred:
            return preferred[0][0]
    return candidates[0][0] if candidates else None


def _field_matches_kind(field: str, kind: str) -> bool:
    if kind == 'buy':
        return '買進' in field or '買股' in field
    if kind == 'sell':
        return '賣出' in field or '賣股' in field
    return '買賣超' in field or '淨買' in field


def _parse_legal_row(
    row: list[str],
    fields: list[str],
    mapping: dict[str, int | None],
    market: str,
    trade_date: str,
) -> LegalInvestorRow:
    stock_id = _clean_security_code(row[_required_index(mapping, 'stock_id')])
    stock_name = _clean_cell(row[_required_index(mapping, 'stock_name')])
    if not stock_id:
        raise ValueError('legal investor CSV blank stock_id')
    if not stock_name:
        raise ValueError(f'legal investor CSV blank stock_name: {trade_date} {market} code={stock_id}')
    return LegalInvestorRow(
        trade_date=trade_date,
        market=market,
        stock_id=stock_id,
        stock_name=stock_name,
        foreign_buy=_required_int(row, fields, mapping, 'foreign_buy', stock_id),
        foreign_sell=_required_int(row, fields, mapping, 'foreign_sell', stock_id),
        foreign_net=_required_int(row, fields, mapping, 'foreign_net', stock_id),
        investment_trust_buy=_required_int(row, fields, mapping, 'investment_trust_buy', stock_id),
        investment_trust_sell=_required_int(row, fields, mapping, 'investment_trust_sell', stock_id),
        investment_trust_net=_required_int(row, fields, mapping, 'investment_trust_net', stock_id),
        dealer_buy=_required_int(row, fields, mapping, 'dealer_buy', stock_id),
        dealer_sell=_required_int(row, fields, mapping, 'dealer_sell', stock_id),
        dealer_net=_required_int(row, fields, mapping, 'dealer_net', stock_id),
        dealer_hedge_buy=_optional_int(row, fields, mapping, 'dealer_hedge_buy', stock_id),
        dealer_hedge_sell=_optional_int(row, fields, mapping, 'dealer_hedge_sell', stock_id),
        dealer_hedge_net=_optional_int(row, fields, mapping, 'dealer_hedge_net', stock_id),
    )


def _required_index(mapping: dict[str, int | None], name: str) -> int:
    index = mapping.get(name)
    if index is None:
        raise ValueError(f'legal investor CSV missing normalized column: {name}')
    return index


def _required_int(row: list[str], fields: list[str], mapping: dict[str, int | None], name: str, stock_id: str) -> int:
    index = _required_index(mapping, name)
    value = _parse_legal_integer(row[index])
    if value is None:
        raise ValueError(
            f'legal investor CSV invalid normalized integer: code={stock_id} column={fields[index]}'
        )
    return value


def _optional_int(row: list[str], fields: list[str], mapping: dict[str, int | None], name: str, stock_id: str) -> int:
    index = mapping.get(name)
    if index is None:
        return 0
    value = _parse_legal_integer(row[index])
    if value is None:
        raise ValueError(
            f'legal investor CSV invalid hedge integer: code={stock_id} column={fields[index]}'
        )
    return value


def legal_csv_path(market: str, trade_date: str) -> Path:
    return official_legal_csv_path(market, validate_iso_date(trade_date))


def validate_legal_csv_bytes(
    raw: bytes,
    market: str,
    trade_date: str,
    *,
    daily_close_row_count: int | None = None,
) -> None:
    if market not in config.MARKETS:
        raise ValueError(f'unknown market: {market}')
    text, _encoding = _decode_legal_text(raw, f'{market} {trade_date}')
    content_trade_date = _find_content_trade_date(text)
    if content_trade_date != trade_date:
        raise ValueError(
            f'legal investor CSV date mismatch: expected {trade_date} {market}, got {content_trade_date}'
        )
    rows = list(csv.reader(text.splitlines()))
    header_index = _find_header_index(rows)
    fields = [_clean_cell(cell) for cell in rows[header_index]]
    data_rows = [row for row in rows[header_index + 1 :] if _is_data_row(row)]
    if not data_rows:
        raise ValueError(f'legal investor CSV has no data rows: {trade_date} {market}')
    _validate_legal_rows(
        fields,
        data_rows,
        market,
        trade_date,
        daily_close_row_count=daily_close_row_count,
    )


def daily_close_row_count(conn: sqlite3.Connection, market: str, trade_date: str) -> int | None:
    try:
        row = conn.execute(
            'SELECT COUNT(*) AS count FROM daily_close WHERE trade_date = ? AND market = ?',
            (trade_date, market),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row['count'] if isinstance(row, sqlite3.Row) else row[0])


def _validate_legal_rows(
    fields: list[str],
    data_rows: list[list[str]],
    market: str,
    source: str,
    *,
    daily_close_row_count: int | None = None,
) -> None:
    if daily_close_row_count == 0:
        raise ValueError(
            f'legal investor CSV has no matching daily_close rows: {source} {market}'
        )
    _validate_data_row_widths(data_rows, len(fields), market, source)
    _validate_unique_security_codes(data_rows, market, source)
    _validate_numeric_columns(fields, data_rows, market, source)
    _validate_foreign_dealer_zero(fields, data_rows, market, source)
    if market == 'TPEX':
        _validate_tpex_external_investor_columns(fields, data_rows, source)


def _validate_data_row_widths(data_rows: list[list[str]], field_count: int, market: str, source: str) -> None:
    for row in data_rows:
        if len(row) != field_count:
            code = _clean_cell(row[0]) if row else ''
            relation = 'too few' if len(row) < field_count else 'too many'
            raise ValueError(
                f'legal investor CSV row has {relation} columns: {source} {market} '
                f'code={code} columns={len(row)} expected={field_count}'
            )


def _validate_unique_security_codes(data_rows: list[list[str]], market: str, source: str) -> None:
    seen: set[str] = set()
    for row in data_rows:
        code = _clean_security_code(row[0])
        if code in seen:
            raise ValueError(
                f'legal investor CSV duplicate security code: {source} {market} code={code}'
            )
        seen.add(code)


def _validate_numeric_columns(
    fields: list[str], data_rows: list[list[str]], market: str, source: str
) -> None:
    indexes = [index for index, field in enumerate(fields) if _is_legal_numeric_field(field)]
    if not indexes:
        raise ValueError(f'legal investor CSV numeric columns not found: {source} {market}')
    for row in data_rows:
        code = _clean_security_code(row[0])
        for index in indexes:
            value = _parse_legal_integer(row[index])
            if value is None:
                raise ValueError(
                    f'legal investor CSV invalid numeric cell: {source} {market} '
                    f'code={code} column={fields[index]} value={_clean_cell(row[index])!r}'
                )
            if value < 0 and not _is_legal_signed_field(fields[index]):
                raise ValueError(
                    f'legal investor CSV negative unsigned cell: {source} {market} '
                    f'code={code} column={fields[index]} value={_clean_cell(row[index])!r}'
                )


def _validate_foreign_dealer_zero(
    fields: list[str], data_rows: list[list[str]], market: str, source: str
) -> None:
    indexes = [index for index, field in enumerate(fields) if _is_foreign_dealer_field(field)]
    for row in data_rows:
        code = _clean_security_code(row[0])
        for index in indexes:
            cleaned = _clean_cell(row[index])
            if not cleaned:
                continue
            value = _parse_legal_integer(cleaned)
            if value != 0:
                raise ValueError(
                    f'legal investor CSV foreign dealer nonzero: {source} {market} '
                    f'code={code} column={fields[index]} value={cleaned!r}'
                )


def _validate_tpex_external_investor_columns(
    fields: list[str], data_rows: list[list[str]], source: str
) -> None:
    without_dealer = _tpex_external_column_indexes(fields, '(不含外資自營商)')
    total = _tpex_external_column_indexes(fields, '外資及陸資-')
    if set(without_dealer) != {'buy', 'sell', 'net'} or set(total) != {'buy', 'sell', 'net'}:
        return
    for row in data_rows:
        code = _clean_security_code(row[0])
        for key in ('buy', 'sell', 'net'):
            left = _parse_legal_integer(row[without_dealer[key]])
            right = _parse_legal_integer(row[total[key]])
            if left != right:
                raise ValueError(
                    f'legal investor CSV TPEX external investor mismatch: {source} '
                    f'code={code} kind={key} without_dealer={left} total={right}'
                )


def _tpex_external_column_indexes(fields: list[str], marker: str) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, field in enumerate(fields):
        if marker not in field:
            continue
        if '買進' in field:
            indexes['buy'] = index
        elif '賣出' in field:
            indexes['sell'] = index
        elif '買賣超' in field or '淨買' in field:
            indexes['net'] = index
    return indexes


def _is_legal_numeric_field(field: str) -> bool:
    if not field or _is_foreign_dealer_field(field):
        return False
    return any(token in field for token in ('買進', '賣出', '買賣超', '淨買', '股數', '合計'))


def _is_foreign_dealer_field(field: str) -> bool:
    return '外資自營商' in field and '不含外資自營商' not in field


def _is_legal_signed_field(field: str) -> bool:
    return any(token in field for token in ('買賣超', '淨買', '差額', '合計'))


def _parse_legal_integer(value: str) -> int | None:
    cleaned = _clean_cell(value).replace(',', '')
    if not cleaned or cleaned in {'--', '---', '----', 'NaN', 'N/A', 'nan', 'n/a'}:
        return None
    if not re.fullmatch(r'-?\d+', cleaned):
        return None
    return int(cleaned)


def _find_content_trade_date(text: str) -> str:
    for line in text.splitlines()[:8]:
        trade_date = _parse_trade_date_text(line)
        if trade_date:
            return trade_date
    raise ValueError('legal investor CSV content date not found')


def _parse_trade_date_text(text: str) -> str | None:
    roc_match = re.search(r'(?<!\d)(\d{2,3})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?', text)
    if roc_match:
        year = int(roc_match.group(1))
        month = int(roc_match.group(2))
        day = int(roc_match.group(3))
        if year < 1911:
            year += 1911
        if 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
            return f'{year:04d}-{month:02d}-{day:02d}'

    gregorian_match = re.search(r'(?<!\d)(20\d{2})\s*[年/.\-]?\s*(\d{1,2})\s*[月/.\-]?\s*(\d{1,2})\s*日?', text)
    if gregorian_match:
        year = int(gregorian_match.group(1))
        month = int(gregorian_match.group(2))
        day = int(gregorian_match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f'{year:04d}-{month:02d}-{day:02d}'
    return None


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
    first = _clean_security_code(row[0])
    return bool(re.match(r'^\d[0-9A-Z]*$', first))


def _clean_security_code(value: str) -> str:
    return _clean_cell(value).strip('=').strip('\"').strip()


def _trim_row(row: list[str], size: int) -> list[str]:
    values = [_clean_cell(cell) for cell in row[:size]]
    if len(values) < size:
        values.extend([''] * (size - len(values)))
    return values


def _clean_cell(value: str) -> str:
    return str(value).strip().strip('\ufeff').strip()
