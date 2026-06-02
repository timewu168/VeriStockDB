from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

import config
from db import connection as db_connection
from ingest import close_importer
from ingest.downloader import CooldownController
from ingest.trading_calendar import validate_iso_date
from services import batch_status
from services.backup import backup_database
from services.monthly_archive import archive_month
from services.monthly_audit import audit_month
from services.monthly_finalize import finalize_close_months


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="VeriStockDB")
    parser.add_argument("--db", default=str(config.DB_PATH), help="SQLite DB path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="initialize the SQLite database")

    import_close = subparsers.add_parser("import-close", help="import daily Close data")
    import_close.add_argument("--file", help="local CSV file to import")
    import_close.add_argument("--market", choices=config.MARKETS)
    import_close.add_argument("--date", help="target date YYYY-MM-DD")
    import_close.add_argument("--from", dest="start", help="range start YYYY-MM-DD")
    import_close.add_argument("--to", dest="end", help="range end YYYY-MM-DD")
    import_close.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    update_close = subparsers.add_parser("update-close", help="update Close data from latest DB date to today")
    update_close.add_argument("--to", dest="end", help="target end date YYYY-MM-DD, default today")
    update_close.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    import_close_local = subparsers.add_parser(
        "import-close-local", help="import local Close CSV files in a date range"
    )
    import_close_local.add_argument(
        "--dir",
        default=str(config.CSV_DIR / "Close"),
        help="local Close CSV directory, default data/csv/Close",
    )
    import_close_local.add_argument("--from", dest="start", required=True, help="range start YYYY-MM-DD")
    import_close_local.add_argument("--to", dest="end", required=True, help="range end YYYY-MM-DD")
    import_close_local.add_argument("--market", choices=config.MARKETS)

    rollback_close = subparsers.add_parser(
        "rollback-close", help="run three-trading-day Close rollback check"
    )
    rollback_close.add_argument(
        "--date",
        help="target date YYYY-MM-DD, default latest imported Close date",
    )
    rollback_close.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    status = subparsers.add_parser("status", help="show batch status")
    status.add_argument("--dataset", default=None)
    status.add_argument("--problems", action="store_true", help="list blocked/recheck/missing batches")
    status.add_argument("--details", action="store_true", help="show problem error samples")

    query = subparsers.add_parser("query-close", help="query imported Close data")
    query.add_argument("--stock-id")
    query.add_argument("--date")
    query.add_argument("--from", dest="start")
    query.add_argument("--to", dest="end")

    approve = subparsers.add_parser("approve-batch", help="record manual batch approval")
    approve.add_argument("--dataset", default=config.DATASET_DAILY_CLOSE)
    approve.add_argument("--market", choices=config.MARKETS)
    approve.add_argument("--period", required=True)
    approve.add_argument("--reason", required=True)
    approve.add_argument("--note")

    audit = subparsers.add_parser("audit-month", help="run monthly zero-tolerance audit")
    audit.add_argument("--dataset", default=config.DATASET_DAILY_CLOSE)
    audit.add_argument("--month", required=True, help="YYYY-MM")
    audit.add_argument("--market", choices=config.MARKETS)
    audit.add_argument("--from", dest="start", help="audit start date YYYY-MM-DD")
    audit.add_argument("--to", dest="end", help="audit end date YYYY-MM-DD")
    audit.add_argument(
        "--skip-rollback",
        action="store_true",
        help="skip last-day rollback requirement for historical/local audits",
    )

    archive = subparsers.add_parser("archive-month", help="ZIP and verify monthly CSV files")
    archive.add_argument("--dataset", default=config.DATASET_DAILY_CLOSE)
    archive.add_argument("--month", required=True, help="YYYY-MM")
    archive.add_argument("--market", choices=config.MARKETS)
    archive.add_argument("--from", dest="start", help="archive start date YYYY-MM-DD")
    archive.add_argument("--to", dest="end", help="archive end date YYYY-MM-DD")
    archive.add_argument("--dir", help="loose CSV directory, default data/csv/daily_close/YYYY")
    archive.add_argument(
        "--skip-rollback",
        action="store_true",
        help="match a historical/local audit that skipped rollback",
    )

    finalize = subparsers.add_parser(
        "finalize-close-months", help="audit and archive a range of Close months"
    )
    finalize.add_argument("--dataset", default=config.DATASET_DAILY_CLOSE)
    finalize.add_argument("--from", dest="start_month", required=True, help="start month YYYY-MM")
    finalize.add_argument("--to", dest="end_month", required=True, help="end month YYYY-MM")
    finalize.add_argument("--market", choices=config.MARKETS)
    finalize.add_argument(
        "--start-date",
        help="first month start date YYYY-MM-DD, for historical partial-month starts",
    )
    finalize.add_argument(
        "--end-date",
        help="last month end date YYYY-MM-DD, for partial final months",
    )
    finalize.add_argument("--dir", help="loose CSV directory, default data/csv/daily_close/YYYY")
    finalize.add_argument(
        "--skip-rollback",
        action="store_true",
        help="skip last-day rollback requirement for historical/local finalization",
    )

    subparsers.add_parser("backup", help="create latest DB backup")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not argv:
        parser.print_help()
        _print_quickstart()
        return 0

    args = parser.parse_args(argv)
    db_path = Path(args.db)

    try:
        if args.command == "init-db":
            path = db_connection.init_db(db_path)
            print(f"initialized {path}")
            return 0
        if args.command == "backup":
            target = backup_database(db_path=db_path)
            print(f"backup written: {target}")
            return 0

        db_connection.init_db(db_path)
        conn = db_connection.connect(db_path)
        try:
            if args.command == "import-close":
                result = _cmd_import_close(conn, args)
            elif args.command == "update-close":
                result = _cmd_update_close(conn, args)
            elif args.command == "import-close-local":
                result = _cmd_import_close_local(conn, args)
            elif args.command == "rollback-close":
                result = _cmd_rollback_close(conn, args)
            elif args.command == "status":
                result = _cmd_status(conn, args)
            elif args.command == "query-close":
                result = _cmd_query_close(conn, args)
            elif args.command == "approve-batch":
                result = _cmd_approve_batch(conn, args)
            elif args.command == "audit-month":
                result = _cmd_audit_month(conn, args)
            elif args.command == "archive-month":
                result = _cmd_archive_month(conn, args)
            elif args.command == "finalize-close-months":
                result = _cmd_finalize_close_months(conn, args)
            else:
                result = 1
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 1


def _cmd_import_close(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    if args.file:
        if not args.date or not args.market:
            raise ValueError("--file import requires --date and --market")
        trade_date = validate_iso_date(args.date)
        batch_id = close_importer.import_close_file(
            conn, path=args.file, market=args.market, trade_date=trade_date
        )
        _print_batch(conn, args.market, trade_date, batch_id)
        return _status_exit_code(conn, args.market, trade_date)

    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("range import requires both --from and --to")
        stats = close_importer.import_close_range(
            conn,
            start=validate_iso_date(args.start),
            end=validate_iso_date(args.end),
            cooldown=cooldown,
            log=print,
        )
        print(_format_stats(stats))
        return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2

    if not args.date:
        raise ValueError("import-close requires --date, --from/--to, or --file")
    stats = close_importer.import_close_day(
        conn,
        trade_date=validate_iso_date(args.date),
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


def _cmd_update_close(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    stats = close_importer.import_close_update(
        conn,
        through_date=validate_iso_date(args.end) if args.end else None,
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


def _cmd_import_close_local(conn, args: argparse.Namespace) -> int:
    stats = close_importer.import_close_local_range(
        conn,
        directory=Path(args.dir),
        start=validate_iso_date(args.start),
        end=validate_iso_date(args.end),
        markets=(args.market,) if args.market else None,
        log=print,
    )
    print(_format_stats(stats))
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


def _cmd_rollback_close(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    target_date = validate_iso_date(args.date) if args.date else close_importer.latest_close_date(conn)
    if target_date is None:
        raise ValueError("rollback-close requires --date when no daily_close rows exist")
    if not args.date:
        print(f"INFO rollback-close target latest daily_close date: {target_date}")
    stats = close_importer.import_close_with_rollback(
        conn,
        target_date=target_date,
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


def _cmd_status(conn, args: argparse.Namespace) -> int:
    if args.problems:
        return _cmd_status_problems(conn, args)

    rows = batch_status.status_summary(conn, args.dataset)
    if not rows:
        print("No batches found.")
        return 0
    current_dataset = None
    for row in rows:
        if row["dataset"] != current_dataset:
            current_dataset = row["dataset"]
            print(current_dataset)
        print(f"  {row['status']:<8} {row['count']} batches")
    problem = batch_status.latest_problem(conn, args.dataset)
    if problem:
        print()
        print("Latest problem:")
        market = f" {problem['market']}" if problem["market"] else ""
        print(
            f"  {problem['period']}{market} {problem['status']} "
            f"{problem['error_summary'] or ''}".rstrip()
        )
    return 0


def _cmd_status_problems(conn, args: argparse.Namespace) -> int:
    rows = batch_status.problem_batches(conn, args.dataset)
    if not rows:
        print("No problem batches found.")
        return 0
    print("Problem batches:")
    for row in rows:
        market = row["market"] or "-"
        reason = row["error_summary"] or "(no error summary)"
        print(f"  {row['period']} {market} {row['status']} {reason}")
        if args.details:
            for error in batch_status.batch_errors(conn, row["batch_id"]):
                sample = _format_error_sample(error)
                print(f"    - {error['code']}: {error['message']}{sample}")
    return 0


def _cmd_query_close(conn, args: argparse.Namespace) -> int:
    rows = close_importer.query_close(
        conn,
        stock_id=args.stock_id,
        trade_date=validate_iso_date(args.date) if args.date else None,
        start=validate_iso_date(args.start) if args.start else None,
        end=validate_iso_date(args.end) if args.end else None,
    )
    print(
        "trade_date market stock_id stock_name open high low close volume amount transactions"
    )
    for row in rows:
        print(
            f"{row['trade_date']} {row['market']} {row['stock_id']} {row['stock_name']} "
            f"{_money(row['open'])} {_money(row['high'])} {_money(row['low'])} {_money(row['close'])} "
            f"{row['volume']} {row['amount']} {row['transactions']}"
        )
    return 0


def _cmd_approve_batch(conn, args: argparse.Namespace) -> int:
    batch_status.approve_batch(
        conn,
        dataset=args.dataset,
        market=args.market,
        period=args.period,
        reason=args.reason,
        note=args.note,
    )
    print(f"approved {args.dataset} {args.market or '-'} {args.period}")
    return 0


def _cmd_audit_month(conn, args: argparse.Namespace) -> int:
    result = audit_month(
        conn,
        dataset=args.dataset,
        month=args.month,
        markets=(args.market,) if args.market else None,
        start=args.start,
        end=args.end,
        require_rollback=not args.skip_rollback,
    )
    print(f"{result.dataset} {result.month} {result.status}")
    for error in result.errors:
        print(f"  {error}")
    return 0 if result.status == "OK" else 2


def _cmd_archive_month(conn, args: argparse.Namespace) -> int:
    zip_path = archive_month(
        conn,
        dataset=args.dataset,
        month=args.month,
        markets=(args.market,) if args.market else None,
        start=args.start,
        end=args.end,
        source_dir=Path(args.dir) if args.dir else None,
        require_rollback=not args.skip_rollback,
    )
    print(f"archived: {zip_path}")
    return 0


def _cmd_finalize_close_months(conn, args: argparse.Namespace) -> int:
    result = finalize_close_months(
        conn,
        dataset=args.dataset,
        start_month=args.start_month,
        end_month=args.end_month,
        markets=(args.market,) if args.market else None,
        start_date=args.start_date,
        end_date=args.end_date,
        source_dir=Path(args.dir) if args.dir else None,
        require_rollback=not args.skip_rollback,
        log=print,
    )
    print(f"finalize-close-months {result.status}")
    for month in result.months:
        suffix = f" {month.zip_path}" if month.zip_path else ""
        print(f"  {month.month} {month.status}{suffix}")
        for error in month.errors:
            print(f"    {error}")
    return 0 if result.status == "OK" else 2


def _print_batch(conn, market: str, trade_date: str, batch_id: str) -> None:
    batch = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
    if not batch:
        print(batch_id)
        return
    print(
        f"{batch['period']} {batch['market']} {batch['status']} "
        f"rows={batch['row_count'] or 0} retries={batch['retry_count']}"
    )
    if batch["error_summary"]:
        print(f"  {batch['error_summary']}")


def _status_exit_code(conn, market: str, trade_date: str) -> int:
    batch = batch_status.get_batch(conn, config.DATASET_DAILY_CLOSE, market, trade_date)
    if batch and batch["status"] in {"OK", "FIXED"}:
        return 0
    return 2


def _money(cents: int) -> str:
    return f"{Decimal(cents) / Decimal('100'):.2f}"


def _format_stats(stats: dict[str, int]) -> str:
    return (
        f"OK: {stats['OK']} FIXED: {stats['FIXED']} BLOCKED: {stats['BLOCKED']} "
        f"RECHECK: {stats['RECHECK']} MISSING: {stats['MISSING']} SKIPPED: {stats['SKIPPED']}"
    )


def _format_error_sample(error) -> str:
    parts = []
    if error["sample_stock_id"]:
        parts.append(f"sample_stock_id={error['sample_stock_id']}")
    if error["sample_value"]:
        parts.append(f"sample_value={error['sample_value']}")
    return " (" + ", ".join(parts) + ")" if parts else ""


def _print_quickstart() -> None:
    print()
    print("Quickstart:")
    print("  python main.py init-db")
    print("  python main.py status")
    print("  python main.py update-close")
    print("  python main.py import-close --date YYYY-MM-DD")
    print("  python main.py rollback-close")
    print("  python main.py import-close-local --from YYYY-MM-DD --to YYYY-MM-DD --dir data/csv/Close")
    print("  python main.py finalize-close-months --from YYYY-MM --to YYYY-MM --dir data/csv/Close")
    print("  python main.py query-close --stock-id 2330 --from YYYY-MM-DD --to YYYY-MM-DD")


if __name__ == "__main__":
    raise SystemExit(main())
