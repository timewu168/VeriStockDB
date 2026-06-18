from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

import config
from db import connection as db_connection
from ingest import attention_notice
from ingest import close_importer
from ingest import disposal_notice
from ingest import legal_investor
from ingest import margin
from ingest.downloader import CooldownController
from ingest import trading_calendar
from ingest.trading_calendar import validate_iso_date
from services import batch_status
from services import telegram_notifier
from services.backup import backup_database
from services.monthly_archive import archive_month
from services.monthly_audit import audit_month
from services.monthly_finalize import finalize_close_months
from services.ops_check import run_ops_check


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

    backfill_calendar = subparsers.add_parser(
        "backfill-trading-days", help="backfill trading_days from TWSE FMTQIK monthly calendar"
    )
    backfill_calendar.add_argument("--from", dest="start", required=True, help="range start YYYY-MM-DD")
    backfill_calendar.add_argument("--to", dest="end", required=True, help="range end YYYY-MM-DD")
    backfill_calendar.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

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

    inspect_attention = subparsers.add_parser(
        "inspect-attention", help="inspect local attention announcement CSV files without importing"
    )
    inspect_attention.add_argument("--twse-file", help="local TWSE notice CSV file")
    inspect_attention.add_argument("--tpex-file", help="local TPEX attention CSV file")

    inspect_disposal = subparsers.add_parser(
        "inspect-disposal", help="inspect local disposal announcement CSV files without importing"
    )
    inspect_disposal.add_argument("--twse-file", help="local TWSE disposal CSV file")
    inspect_disposal.add_argument("--tpex-file", help="local TPEX disposal CSV file")

    download_legal = subparsers.add_parser(
        "download-legal", help="download official legal investor CSV files without importing"
    )
    download_legal.add_argument("--date", help="target date YYYY-MM-DD")
    download_legal.add_argument("--from", dest="start", help="range start YYYY-MM-DD")
    download_legal.add_argument("--to", dest="end", help="range end YYYY-MM-DD")
    download_legal.add_argument("--market", choices=config.MARKETS)
    download_legal.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    download_margin = subparsers.add_parser(
        "download-margin", help="download official margin trading CSV files without importing"
    )
    download_margin.add_argument("--date", help="target date YYYY-MM-DD")
    download_margin.add_argument("--from", dest="start", help="range start YYYY-MM-DD")
    download_margin.add_argument("--to", dest="end", help="range end YYYY-MM-DD")
    download_margin.add_argument("--market", choices=config.MARKETS)
    download_margin.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")
    download_margin.add_argument("--overwrite", action="store_true", help="redownload and overwrite existing margin CSV files")

    inspect_margin = subparsers.add_parser(
        "inspect-margin", help="inspect downloaded margin trading CSV files without importing"
    )
    inspect_margin.add_argument("--from", dest="start", required=True, help="range start YYYY-MM-DD")
    inspect_margin.add_argument("--to", dest="end", required=True, help="range end YYYY-MM-DD")
    inspect_margin.add_argument("--market", choices=config.MARKETS)
    inspect_margin.add_argument("--report-dir", default=str(config.ROOT_DIR / "reports"))

    import_margin = subparsers.add_parser(
        "import-margin", help="dry-run margin trading CSV normalization before importing"
    )
    import_margin_mode = import_margin.add_mutually_exclusive_group(required=True)
    import_margin_mode.add_argument("--dry-run", action="store_true", help="parse and validate only")
    import_margin_mode.add_argument("--execute", action="store_true", help="write parsed rows to SQLite after dry-run validation")
    import_margin.add_argument("--from", dest="start", required=True, help="range start YYYY-MM-DD")
    import_margin.add_argument("--to", dest="end", required=True, help="range end YYYY-MM-DD")
    import_margin.add_argument("--market", choices=config.MARKETS)
    import_margin.add_argument("--twse-from", default=margin.TWSE_MARGIN_START, help="TWSE formal start date")
    import_margin.add_argument("--tpex-from", default=margin.TPEX_FORMAL_MARGIN_START, help="TPEX formal start date")
    import_margin.add_argument("--report-dir", default=str(config.ROOT_DIR / "reports"))

    update_margin = subparsers.add_parser(
        "update-margin", help="update one margin trading day without overwriting existing rows"
    )
    update_margin.add_argument("--date", help="target date YYYY-MM-DD, default today")
    update_margin.add_argument("--market", choices=config.MARKETS)
    update_margin.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    inspect_legal = subparsers.add_parser(
        "inspect-legal", help="inspect local legal investor CSV files without importing"
    )
    inspect_legal.add_argument("--file", help="single local legal investor CSV file")
    inspect_legal.add_argument("--market", choices=config.MARKETS)
    inspect_legal.add_argument("--date", help="inspect standard saved CSV for YYYY-MM-DD")
    inspect_legal.add_argument("--sample-size", type=int, default=3, help="sample rows to print, default 3")

    import_legal = subparsers.add_parser(
        "import-legal", help="import or dry-run legal investor CSV normalization"
    )
    import_legal.add_argument("--dry-run", action="store_true", help="parse and validate only")
    import_legal.add_argument("--file", help="single local legal investor CSV file")
    import_legal.add_argument("--market", choices=config.MARKETS)
    import_legal.add_argument("--date", help="target date YYYY-MM-DD")
    import_legal.add_argument("--from", dest="start", help="range start YYYY-MM-DD")
    import_legal.add_argument("--to", dest="end", help="range end YYYY-MM-DD")

    report_legal = subparsers.add_parser(
        "report-legal", help="report full legal investor CSV dry-run status without importing"
    )
    report_legal.add_argument("--from", dest="start", help="range start YYYY-MM-DD, default first local CSV per market")
    report_legal.add_argument("--to", dest="end", help="range end YYYY-MM-DD, default last local CSV per market")
    report_legal.add_argument("--market", choices=config.MARKETS)
    report_legal.add_argument("--all", action="store_true", help="print OK rows too; default prints problems only")

    update_legal = subparsers.add_parser(
        "update-legal", help="manually update one legal investor trading day without overwriting existing rows"
    )
    update_legal.add_argument("--date", help="target date YYYY-MM-DD, default today")
    update_legal.add_argument("--market", choices=config.MARKETS)
    update_legal.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    import_attention = subparsers.add_parser("import-attention", help="import attention announcement CSV files")

    import_attention.add_argument("--file", help="single local attention CSV file")
    import_attention.add_argument("--market", choices=config.MARKETS)
    import_attention.add_argument("--twse-file", help="local TWSE notice CSV file")
    import_attention.add_argument("--tpex-file", help="local TPEX attention CSV file")

    import_disposal = subparsers.add_parser("import-disposal", help="import disposal announcement CSV files")
    import_disposal.add_argument("--file", help="single local disposal CSV file")
    import_disposal.add_argument("--market", choices=config.MARKETS)
    import_disposal.add_argument("--twse-file", help="local TWSE disposal CSV file")
    import_disposal.add_argument("--tpex-file", help="local TPEX disposal CSV file")

    update_attention = subparsers.add_parser(
        "update-attention", help="update attention announcements from latest coverage to today"
    )
    update_attention.add_argument("--to", dest="end", help="target end date YYYY-MM-DD, default today")
    update_attention.add_argument("--market", choices=config.MARKETS)
    update_attention.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    update_disposal = subparsers.add_parser(
        "update-disposal", help="update disposal announcements from latest coverage to today"
    )
    update_disposal.add_argument("--to", dest="end", help="target end date YYYY-MM-DD, default today")
    update_disposal.add_argument("--market", choices=config.MARKETS)
    update_disposal.add_argument("--no-cooldown", action="store_true", help="disable official cooldown")

    status = subparsers.add_parser("status", help="show batch status")
    status.add_argument("--dataset", default=None)
    status.add_argument("--problems", action="store_true", help="list blocked/recheck/missing batches")
    status.add_argument("--details", action="store_true", help="show problem error samples")

    ops = subparsers.add_parser("ops-check", help="check deployment DB, backup, archive, logs, and timers")
    ops.add_argument("--backup-path", default=str(config.DEFAULT_BACKUP_PATH))
    ops.add_argument("--archive-dir", default=str(config.ARCHIVE_DIR))
    ops.add_argument("--log-dir", default=str(config.LOG_DIR))
    ops.add_argument("--skip-systemd", action="store_true", help="skip systemd timer checks")

    notify = subparsers.add_parser("notify-telegram", help="send a Telegram notification")
    notify_target = notify.add_mutually_exclusive_group(required=True)
    notify_target.add_argument("--test", action="store_true", help="send a VeriStockDB test notification")
    notify_target.add_argument("--message", help="send a custom plain-text message")
    notify.add_argument("--status", default="OK", help="notification status, default OK")

    query = subparsers.add_parser("query-close", help="query imported Close data")
    query.add_argument("--stock-id")
    query.add_argument("--date")
    query.add_argument("--from", dest="start")
    query.add_argument("--to", dest="end")

    query_attention = subparsers.add_parser("query-attention", help="query imported attention announcements")
    query_attention.add_argument("--market", choices=config.MARKETS)
    query_attention.add_argument("--stock-id")
    query_attention.add_argument("--date")
    query_attention.add_argument("--from", dest="start")
    query_attention.add_argument("--to", dest="end")

    query_disposal = subparsers.add_parser("query-disposal", help="query imported disposal announcements")
    query_disposal.add_argument("--market", choices=config.MARKETS)
    query_disposal.add_argument("--stock-id")
    query_disposal.add_argument("--date")
    query_disposal.add_argument("--from", dest="start")
    query_disposal.add_argument("--to", dest="end")
    query_disposal.add_argument("--active-date", help="filter rows active on YYYY-MM-DD")

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
            _emit_telegram_notification(
                "backup",
                "OK",
                lines=[
                    f"path: {target}",
                    f"size: {_format_file_size(target)}",
                ],
            )
            return 0
        if args.command == "ops-check":
            return _cmd_ops_check(db_path, args)
        if args.command == "notify-telegram":
            return _cmd_notify_telegram(args)
        if args.command == "inspect-attention":
            return _cmd_inspect_attention(args)
        if args.command == "inspect-disposal":
            return _cmd_inspect_disposal(args)
        if args.command == "inspect-legal":
            return _cmd_inspect_legal(args, db_path)
        if args.command == "report-legal":
            conn = db_connection.connect(db_path)
            try:
                return _cmd_report_legal(conn, args)
            finally:
                conn.close()
        if args.command == "download-margin":
            db_connection.init_db(db_path)
            conn = db_connection.connect(db_path)
            try:
                start, end, markets, open_dates = _prepare_margin_download(conn, args)
            finally:
                conn.close()
            return _cmd_download_margin_from_dates(args, start, end, markets, open_dates)
        if args.command == "inspect-margin":
            db_connection.init_db(db_path)
            conn = db_connection.connect(db_path)
            try:
                return _cmd_inspect_margin(conn, args)
            finally:
                conn.close()
        if args.command == "import-margin":
            db_connection.init_db(db_path)
            conn = db_connection.connect(db_path)
            try:
                result = _cmd_import_margin(conn, args)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        db_connection.init_db(db_path)
        conn = db_connection.connect(db_path)
        try:
            if args.command == "import-close":
                result = _cmd_import_close(conn, args)
            elif args.command == "update-close":
                result = _cmd_update_close(conn, args)
            elif args.command == "backfill-trading-days":
                result = _cmd_backfill_trading_days(conn, args)
            elif args.command == "import-close-local":
                result = _cmd_import_close_local(conn, args)
            elif args.command == "rollback-close":
                result = _cmd_rollback_close(conn, args)
            elif args.command == "import-attention":
                result = _cmd_import_attention(conn, args)
            elif args.command == "import-disposal":
                result = _cmd_import_disposal(conn, args)
            elif args.command == "update-attention":
                result = _cmd_update_attention(conn, args)
            elif args.command == "update-disposal":
                result = _cmd_update_disposal(conn, args)
            elif args.command == "download-legal":
                result = _cmd_download_legal(conn, args)
            elif args.command == "import-legal":
                result = _cmd_import_legal(conn, args)
            elif args.command == "update-legal":
                result = _cmd_update_legal(conn, args)
            elif args.command == "update-margin":
                result = _cmd_update_margin(conn, args)
            elif args.command == "status":
                result = _cmd_status(conn, args)
            elif args.command == "query-close":
                result = _cmd_query_close(conn, args)
            elif args.command == "query-attention":
                result = _cmd_query_attention(conn, args)
            elif args.command == "query-disposal":
                result = _cmd_query_disposal(conn, args)
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
        command = getattr(locals().get("args", None), "command", "unknown")
        _emit_telegram_notification(command, "ERROR", lines=[f"error: {exc}"])
        return 1
    return 1



def _cmd_backfill_trading_days(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    changed = trading_calendar.backfill_trading_days_from_twse(
        conn,
        start=validate_iso_date(args.start),
        end=validate_iso_date(args.end),
        cooldown=cooldown,
        log=print,
    )
    print(f"trading_days backfill rows={changed}")
    return 0

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
        trade_date=validate_iso_date(args.date or date.today().isoformat()),
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


def _cmd_update_close(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    through_date = validate_iso_date(args.end) if args.end else None
    latest_before = close_importer.latest_close_date(conn)
    stats = close_importer.import_close_update(
        conn,
        through_date=through_date,
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    latest_after = close_importer.latest_close_date(conn)
    _emit_stats_notification(
        "update-close",
        stats,
        lines=_update_lines(through_date=through_date, latest_before=latest_before, latest_after=latest_after),
    )
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
    _emit_stats_notification(
        "rollback-close",
        stats,
        lines=[f"target: {target_date}"],
    )
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


def _cmd_ops_check(db_path: Path, args: argparse.Namespace) -> int:
    result = run_ops_check(
        db_path=db_path,
        backup_path=Path(args.backup_path),
        archive_dir=Path(args.archive_dir),
        log_dir=Path(args.log_dir),
        check_systemd=not args.skip_systemd,
    )
    print(f"ops-check {result.status}")
    for item in result.items:
        print(f"  {item.status:<5} {item.name:<36} {item.message}")
    if result.status != "OK":
        _emit_telegram_notification(
            "ops-check",
            result.status,
            lines=[
                f"{item.status} {item.name} {item.message}"
                for item in result.items
                if item.status != "OK"
            ],
        )
    return 2 if result.has_errors else 0


def _cmd_notify_telegram(args: argparse.Namespace) -> int:
    message = (
        telegram_notifier.build_task_message(
            "notify-telegram",
            args.status,
            lines=["message: test notification"],
        )
        if args.test
        else str(args.message)
    )
    result = telegram_notifier.notify_message(message, status=args.status)
    if result.sent:
        print("telegram notification sent")
        return 0
    if result.skipped:
        print(f"telegram notification skipped: {result.reason}")
        return 2
    print(f"telegram notification failed: {result.error}")
    return 2


def _cmd_inspect_attention(args: argparse.Namespace) -> int:
    targets: list[tuple[str, str]] = []
    if args.twse_file:
        targets.append(("TWSE", args.twse_file))
    if args.tpex_file:
        targets.append(("TPEX", args.tpex_file))
    if not targets:
        raise ValueError("inspect-attention requires --twse-file, --tpex-file, or both")

    total_rows = 0
    total_duplicates = 0
    print("attention_notice inspect")
    for market, path in targets:
        result = attention_notice.parse_attention_notice_file(path, market)
        summary = attention_notice.summarize_attention_notice(result)
        total_rows += summary.row_count
        total_duplicates += summary.duplicate_keys
        print(f"{market}")
        print(f"  file             {summary.source_file}")
        print(f"  encoding         {summary.encoding}")
        print(f"  rows             {summary.row_count}")
        print(f"  date_range       {summary.first_date} -> {summary.last_date}")
        print(f"  unique_stock_ids {summary.unique_stock_ids}")
        print(f"  duplicate_keys   {summary.duplicate_keys}")
        print(f"  no_notice_rows   {summary.no_notice_rows}")
        print(f"  metadata_rows    {summary.metadata_rows}")
        print(f"  skipped_rows     {summary.skipped_rows}")
    print(f"TOTAL rows={total_rows} duplicate_keys={total_duplicates}")
    return 0 if total_duplicates == 0 else 2


def _cmd_inspect_disposal(args: argparse.Namespace) -> int:
    targets: list[tuple[str, str]] = []
    if args.twse_file:
        targets.append(("TWSE", args.twse_file))
    if args.tpex_file:
        targets.append(("TPEX", args.tpex_file))
    if not targets:
        raise ValueError("inspect-disposal requires --twse-file, --tpex-file, or both")

    total_rows = 0
    total_duplicates = 0
    total_skipped = 0
    print("disposal_notice inspect")
    for market, path in targets:
        result = disposal_notice.parse_disposal_notice_file(path, market)
        summary = disposal_notice.summarize_disposal_notice(result)
        total_rows += summary.row_count
        total_duplicates += summary.duplicate_keys
        total_skipped += summary.skipped_rows
        print(f"{market}")
        print(f"  file                     {summary.source_file}")
        print(f"  encoding                 {summary.encoding}")
        print(f"  rows                     {summary.row_count}")
        print(f"  trade_date_range         {summary.first_date} -> {summary.last_date}")
        print(
            f"  disposal_date_range      {summary.first_disposal_date} -> "
            f"{summary.last_disposal_date}"
        )
        print(f"  unique_stock_ids         {summary.unique_stock_ids}")
        print(f"  duplicate_keys           {summary.duplicate_keys}")
        print(f"  duplicate_date_stock     {summary.duplicate_date_stock_keys}")
        print(f"  metadata_rows            {summary.metadata_rows}")
        print(f"  no_disposal_rows         {summary.no_disposal_rows}")
        print(f"  blank_stock_name_rows    {summary.blank_stock_name_rows}")
        print(f"  blank_reason_text_rows   {summary.blank_reason_text_rows}")
        print(f"  blank_disposal_text_rows {summary.blank_disposal_text_rows}")
        print(f"  skipped_rows             {summary.skipped_rows}")
        print(f"  invalid_period_rows      {summary.invalid_period_rows}")
    print(
        f"TOTAL rows={total_rows} duplicate_keys={total_duplicates} "
        f"skipped_rows={total_skipped}"
    )
    return 0 if total_duplicates == 0 and total_skipped == 0 else 2


def _cmd_download_legal(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    if args.date:
        if args.start or args.end:
            raise ValueError("download-legal accepts --date or --from/--to, not both")
        start = end = validate_iso_date(args.date)
    else:
        if not args.start or not args.end:
            raise ValueError("download-legal requires --date or both --from and --to")
        start = validate_iso_date(args.start)
        end = validate_iso_date(args.end)
    markets = (args.market,) if args.market else None
    results = legal_investor.download_legal_range(
        conn,
        start=start,
        end=end,
        markets=markets,
        cooldown=cooldown,
        log=print,
    )
    ok = sum(1 for result in results if result.status == "OK")
    failed = [result for result in results if result.status != "OK"]
    print(f"legal_investor download OK={ok} MISSING={len(failed)}")
    for result in failed[:10]:
        print(f"  {result.trade_date} {result.market} {result.status} {result.error}")
    return 0 if not failed else 2



def _cmd_inspect_margin(conn, args: argparse.Namespace) -> int:
    markets = (args.market,) if args.market else None
    report = margin.audit_margin_csvs(
        conn,
        start=validate_iso_date(args.start),
        end=validate_iso_date(args.end),
        markets=markets,
        report_dir=Path(args.report_dir),
        log=print,
    )
    print(f"margin inspect expected={report.expected_files} actual={report.actual_files} OK={report.ok_files} SUSPICIOUS={report.suspicious_files} BAD={report.bad_files} MISSING={report.missing_files} EMPTY={report.empty_files} EXTRA={report.extra_files}")
    print(f"summary: {report.summary_path}")
    print(f"formats: {report.formats_path}")
    print(f"bad_files: {report.bad_files_path}")
    return 0 if report.bad_files == 0 and report.missing_files == 0 and report.empty_files == 0 and report.extra_files == 0 else 2


def _cmd_import_margin(conn, args: argparse.Namespace) -> int:
    markets = (args.market,) if args.market else None
    start = validate_iso_date(args.start)
    end = validate_iso_date(args.end)
    twse_start = validate_iso_date(args.twse_from)
    tpex_start = validate_iso_date(args.tpex_from)
    if args.dry_run:
        report = margin.dry_run_margin_import(
            conn,
            start=start,
            end=end,
            markets=markets,
            twse_start=twse_start,
            tpex_start=tpex_start,
            report_dir=Path(args.report_dir),
            log=print,
        )
        print(
            f"margin dry-run expected={report.expected_files} parsed_files={report.parsed_files} rows={report.rows} "
            f"duplicates={report.duplicate_keys} problems={report.problems} missing={report.missing_files} "
            f"bad={report.bad_files} null_required={report.null_required} invalid_numeric={report.invalid_numeric} "
            f"date_gaps={report.date_coverage_gaps}"
        )
        print(f"summary: {report.summary_path}")
        print(f"daily_counts: {report.daily_counts_path}")
        print(f"problems: {report.problems_path}")
        return 0 if report.problems == 0 and report.duplicate_keys == 0 and report.missing_files == 0 and report.bad_files == 0 and report.null_required == 0 and report.invalid_numeric == 0 and report.date_coverage_gaps == 0 else 2

    results = margin.import_margin_range(
        conn,
        start=start,
        end=end,
        markets=markets,
        twse_start=twse_start,
        tpex_start=tpex_start,
        report_dir=Path(args.report_dir),
        log=print,
    )
    total_rows = sum(result.row_count for result in results)
    total_days = sum(result.open_days for result in results)
    print(f"margin import OK markets={len(results)} open_days={total_days} rows={total_rows}")
    for result in results:
        print(f"  {result.market} range={result.start} -> {result.end} open_days={result.open_days} rows={result.row_count}")
    return 0


def _prepare_margin_download(conn, args: argparse.Namespace) -> tuple[str, str, tuple[str, ...], list[str]]:
    if args.date:
        if args.start or args.end:
            raise ValueError("download-margin accepts --date or --from/--to, not both")
        start = end = validate_iso_date(args.date)
    else:
        if not args.start or not args.end:
            raise ValueError("download-margin requires --date or both --from and --to")
        start = validate_iso_date(args.start)
        end = validate_iso_date(args.end)
    markets = (args.market,) if args.market else config.MARKETS
    open_dates = trading_calendar.trading_days_between(conn, start, end)
    return start, end, markets, open_dates


def _cmd_download_margin_from_dates(
    args: argparse.Namespace,
    start: str,
    end: str,
    markets: tuple[str, ...],
    open_dates: list[str],
) -> int:
    cooldowns = {
        market: CooldownController(enabled=not args.no_cooldown)
        for market in markets
    }
    results = margin.download_margin_dates(
        open_dates,
        start=start,
        end=end,
        markets=markets,
        cooldowns=cooldowns,
        overwrite=args.overwrite,
        parallel_markets=args.market is None,
        log=print,
    )
    ok = sum(1 for result in results if result.status == "OK")
    skipped = sum(1 for result in results if result.status == "SKIP")
    failed = [result for result in results if result.status not in {"OK", "SKIP"}]
    print(f"margin download OK={ok} SKIP={skipped} MISSING={len(failed)}")
    for result in failed[:10]:
        print(f"  {result.trade_date} {result.market} {result.status} {result.error}")
    return 0 if not failed else 2

def _cmd_inspect_legal(args: argparse.Namespace, db_path: Path) -> int:
    if args.sample_size < 0:
        raise ValueError("--sample-size must be >= 0")
    if args.file or args.date:
        if bool(args.file) == bool(args.date):
            raise ValueError("inspect-legal requires exactly one of --file or --date")
        if not args.market:
            raise ValueError("inspect-legal requires --market")
    else:
        raise ValueError("inspect-legal requires --file or --date")

    path = Path(args.file) if args.file else legal_investor.legal_csv_path(args.market, args.date)
    close_row_count = None
    if args.date:
        trade_date = validate_iso_date(args.date)
        conn = db_connection.connect(db_path)
        try:
            close_row_count = legal_investor.daily_close_row_count(conn, args.market, trade_date)
        finally:
            conn.close()
    summary = legal_investor.inspect_legal_file(
        path,
        args.market,
        sample_size=args.sample_size,
        daily_close_row_count=close_row_count,
    )
    print("legal_investor inspect")
    print(f"{summary.market}")
    print(f"  file         {summary.source_file}")
    print(f"  encoding     {summary.encoding}")
    print(f"  header_index {summary.header_index}")
    print(f"  fields       {len(summary.fields)}")
    for index, field in enumerate(summary.fields):
        print(f"    {index}: {field}")
    print(f"  rows         {summary.row_count}")
    if close_row_count is not None:
        print(f"  close_rows   {close_row_count}")
    if summary.sample_rows:
        print("  samples")
        for row in summary.sample_rows:
            print("    " + " | ".join(row))
    return 0


def _cmd_import_legal(conn, args: argparse.Namespace) -> int:
    if args.file:
        if not args.dry_run:
            raise ValueError('import-legal --file supports --dry-run only')
        if args.start or args.end:
            raise ValueError('import-legal --file cannot be combined with --from/--to')
        if not args.date or not args.market:
            raise ValueError('import-legal --file requires --date and --market')
        result = legal_investor.dry_run_legal_file(
            Path(args.file), args.market, validate_iso_date(args.date)
        )
        _print_legal_dry_run_results([result])
        return 0 if result.status == 'OK' else 2

    if args.date:
        if args.start or args.end:
            raise ValueError('import-legal accepts --date or --from/--to, not both')
        start = end = validate_iso_date(args.date)
    else:
        if not args.start or not args.end:
            raise ValueError('import-legal requires --file, --date, or both --from and --to')
        start = validate_iso_date(args.start)
        end = validate_iso_date(args.end)
    markets = (args.market,) if args.market else None
    if args.dry_run:
        results = legal_investor.dry_run_legal_range(conn, start=start, end=end, markets=markets)
        _print_legal_dry_run_results(results)
        return 0 if all(result.status == 'OK' for result in results) else 2

    results = legal_investor.import_legal_range(conn, start=start, end=end, markets=markets)
    total_days = sum(result.open_days for result in results)
    total_rows = sum(result.row_count for result in results)
    print(f'legal_investor import OK markets={len(results)} open_days={total_days} rows={total_rows}')
    for result in results:
        print(
            f'  {result.market} range={result.start} -> {result.end} '
            f'open_days={result.open_days} rows={result.row_count}'
        )
    return 0


def _print_legal_dry_run_results(results: list[legal_investor.LegalDryRunResult]) -> None:
    ok = sum(1 for result in results if result.status == 'OK')
    blocked = sum(1 for result in results if result.status == 'BLOCKED')
    missing = sum(1 for result in results if result.status == 'MISSING')
    print(f'legal_investor dry-run OK={ok} BLOCKED={blocked} MISSING={missing}')
    for result in results:
        source = result.source_file or '-'
        line = f'  {result.trade_date} {result.market} {result.status} rows={result.row_count} file={source}'
        if result.error:
            line += f' error={result.error}'
        print(line)



def _cmd_update_legal(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    results = legal_investor.update_legal_day(
        conn,
        trade_date=validate_iso_date(args.date or date.today().isoformat()),
        markets=(args.market,) if args.market else None,
        cooldown=cooldown,
        log=print,
    )
    ok = sum(1 for result in results if result.status == 'OK')
    exists = sum(1 for result in results if result.status == 'EXISTS')
    closed = sum(1 for result in results if result.status == 'CLOSED')
    blocked = sum(1 for result in results if result.status == 'BLOCKED')
    print(
        f'legal_investor update OK={ok} EXISTS={exists} CLOSED={closed} BLOCKED={blocked}'
    )
    for result in results:
        source = result.source_file or '-'
        line = (
            f'  {result.trade_date} {result.market} {result.status} '
            f'rows={result.row_count} file={source}'
        )
        if result.error:
            line += f' error={result.error}'
        print(line)
    return 0 if blocked == 0 else 2

def _cmd_update_margin(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    results = margin.update_margin_day(
        conn,
        trade_date=validate_iso_date(args.date or date.today().isoformat()),
        markets=(args.market,) if args.market else None,
        cooldown=cooldown,
        log=print,
    )
    ok = sum(1 for result in results if result.status == 'OK')
    exists = sum(1 for result in results if result.status == 'EXISTS')
    closed = sum(1 for result in results if result.status == 'CLOSED')
    blocked = sum(1 for result in results if result.status == 'BLOCKED')
    print(f'margin update OK={ok} EXISTS={exists} CLOSED={closed} BLOCKED={blocked}')
    for result in results:
        source = result.source_file or '-'
        line = (
            f'  {result.trade_date} {result.market} {result.status} '
            f'rows={result.row_count} file={source}'
        )
        if result.error:
            line += f' error={result.error}'
        print(line)
    return 0 if blocked == 0 else 2


def _cmd_report_legal(conn, args: argparse.Namespace) -> int:
    markets = (args.market,) if args.market else None
    report = legal_investor.legal_csv_report(
        conn,
        start=validate_iso_date(args.start) if args.start else None,
        end=validate_iso_date(args.end) if args.end else None,
        markets=markets,
    )
    _print_legal_report(report, include_ok=args.all)
    return 0 if not report.problems else 2


def _print_legal_report(report: legal_investor.LegalReport, *, include_ok: bool = False) -> None:
    total_open_days = sum(summary.open_days for summary in report.summaries)
    total_ok = sum(summary.ok for summary in report.summaries)
    total_blocked = sum(summary.blocked for summary in report.summaries)
    total_missing = sum(summary.missing for summary in report.summaries)
    total_rows = sum(summary.rows for summary in report.summaries)
    print(
        'legal_investor report '
        f'open_days={total_open_days} OK={total_ok} BLOCKED={total_blocked} '
        f'MISSING={total_missing} rows={total_rows}'
    )
    for summary in report.summaries:
        date_range = f'{summary.start} -> {summary.end}' if summary.start and summary.end else '-'
        print(
            f'  {summary.market} range={date_range} open_days={summary.open_days} '
            f'OK={summary.ok} BLOCKED={summary.blocked} MISSING={summary.missing} rows={summary.rows}'
        )
    if report.problems:
        print('Problems:')
        for result in report.problems:
            source = result.source_file or '-'
            print(
                f'  {result.trade_date} {result.market} {result.status} '
                f'rows={result.row_count} file={source} error={result.error}'
            )
    elif not include_ok:
        print('Problems: none')
    if include_ok:
        print('All results:')
        for result in report.results:
            source = result.source_file or '-'
            line = (
                f'  {result.trade_date} {result.market} {result.status} '
                f'rows={result.row_count} file={source}'
            )
            if result.error:
                line += f' error={result.error}'
            print(line)


def _cmd_import_attention(conn, args: argparse.Namespace) -> int:
    targets = _attention_targets(args)
    exit_code = 0
    for market, path in targets:
        result = attention_notice.import_attention_notice_file(conn, path=path, market=market)
        _print_attention_import_result(result)
        if result.status not in {"OK", "FIXED"}:
            exit_code = 2
    return exit_code


def _cmd_import_disposal(conn, args: argparse.Namespace) -> int:
    targets = _disposal_targets(args)
    exit_code = 0
    for market, path in targets:
        result = disposal_notice.import_disposal_notice_file(conn, path=path, market=market)
        _print_disposal_import_result(result)
        if result.status not in {"OK", "FIXED"}:
            exit_code = 2
    return exit_code


def _cmd_update_attention(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    through_date = validate_iso_date(args.end) if args.end else None
    markets = (args.market,) if args.market else None
    latest_before = _latest_by_market(attention_notice.latest_attention_notice_date, conn, markets)
    stats = attention_notice.import_attention_notice_update(
        conn,
        through_date=through_date,
        markets=markets,
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    latest_after = _latest_by_market(attention_notice.latest_attention_notice_date, conn, markets)
    _emit_stats_notification(
        "update-attention",
        stats,
        lines=_update_lines(
            through_date=through_date,
            latest_before=_format_market_latest(latest_before),
            latest_after=_format_market_latest(latest_after),
            markets=markets,
        ),
    )
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


def _cmd_update_disposal(conn, args: argparse.Namespace) -> int:
    cooldown = CooldownController(enabled=not args.no_cooldown)
    through_date = validate_iso_date(args.end) if args.end else None
    markets = (args.market,) if args.market else None
    latest_before = _latest_by_market(disposal_notice.latest_disposal_notice_date, conn, markets)
    stats = disposal_notice.import_disposal_notice_update(
        conn,
        through_date=through_date,
        markets=markets,
        cooldown=cooldown,
        log=print,
    )
    print(_format_stats(stats))
    latest_after = _latest_by_market(disposal_notice.latest_disposal_notice_date, conn, markets)
    _emit_stats_notification(
        "update-disposal",
        stats,
        lines=_update_lines(
            through_date=through_date,
            latest_before=_format_market_latest(latest_before),
            latest_after=_format_market_latest(latest_after),
            markets=markets,
        ),
    )
    return 0 if not any(stats[key] for key in ("BLOCKED", "RECHECK", "MISSING")) else 2


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


def _cmd_query_attention(conn, args: argparse.Namespace) -> int:
    rows = attention_notice.query_attention_notices(
        conn,
        market=args.market,
        stock_id=args.stock_id,
        trade_date=validate_iso_date(args.date) if args.date else None,
        start=validate_iso_date(args.start) if args.start else None,
        end=validate_iso_date(args.end) if args.end else None,
    )
    print("trade_date\tmarket\tstock_id\tstock_name\tnotice_text")
    for row in rows:
        notice_text = " ".join(str(row["notice_text"]).split())
        print(
            f"{row['trade_date']}\t{row['market']}\t{row['stock_id']}\t"
            f"{row['stock_name']}\t{notice_text}"
        )
    return 0


def _cmd_query_disposal(conn, args: argparse.Namespace) -> int:
    rows = disposal_notice.query_disposal_notices(
        conn,
        market=args.market,
        stock_id=args.stock_id,
        trade_date=validate_iso_date(args.date) if args.date else None,
        start=validate_iso_date(args.start) if args.start else None,
        end=validate_iso_date(args.end) if args.end else None,
        active_date=validate_iso_date(args.active_date) if args.active_date else None,
    )
    print(
        "trade_date\tmarket\tstock_id\tstock_name\tdisposal_start_date\t"
        "disposal_end_date\treason_text\tdisposal_text"
    )
    for row in rows:
        reason_text = " ".join(str(row["reason_text"]).split())
        disposal_text = " ".join(str(row["disposal_text"]).split())
        print(
            f"{row['trade_date']}\t{row['market']}\t{row['stock_id']}\t"
            f"{row['stock_name']}\t{row['disposal_start_date']}\t"
            f"{row['disposal_end_date']}\t{reason_text}\t{disposal_text}"
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


def _attention_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    if args.file or args.market:
        if not args.file or not args.market:
            raise ValueError("--file import requires --file and --market")
        targets.append((args.market, args.file))
    if args.twse_file:
        targets.append(("TWSE", args.twse_file))
    if args.tpex_file:
        targets.append(("TPEX", args.tpex_file))
    if not targets:
        raise ValueError("attention import requires --file/--market, --twse-file, or --tpex-file")
    markets = [market for market, _path in targets]
    if len(markets) != len(set(markets)):
        raise ValueError("attention import received duplicate files for the same market")
    return targets


def _disposal_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    if args.file or args.market:
        if not args.file or not args.market:
            raise ValueError("--file import requires --file and --market")
        targets.append((args.market, args.file))
    if args.twse_file:
        targets.append(("TWSE", args.twse_file))
    if args.tpex_file:
        targets.append(("TPEX", args.tpex_file))
    if not targets:
        raise ValueError("disposal import requires --file/--market, --twse-file, or --tpex-file")
    markets = [market for market, _path in targets]
    if len(markets) != len(set(markets)):
        raise ValueError("disposal import received duplicate files for the same market")
    return targets


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


def _print_attention_import_result(result: attention_notice.AttentionNoticeImportResult) -> None:
    print(
        f"{result.period} {result.market} {result.status} rows={result.row_count} "
        f"no_notice_rows={result.no_notice_rows} metadata_rows={result.metadata_rows}"
    )
    if result.duplicate_keys or result.skipped_rows:
        print(f"  duplicate_keys={result.duplicate_keys} skipped_rows={result.skipped_rows}")


def _print_disposal_import_result(result: disposal_notice.DisposalNoticeImportResult) -> None:
    print(
        f"{result.period} {result.market} {result.status} rows={result.row_count} "
        f"no_disposal_rows={result.no_disposal_rows} metadata_rows={result.metadata_rows}"
    )
    details = []
    if result.blank_stock_name_rows:
        details.append(f"blank_stock_name_rows={result.blank_stock_name_rows}")
    if result.blank_reason_text_rows:
        details.append(f"blank_reason_text_rows={result.blank_reason_text_rows}")
    if result.blank_disposal_text_rows:
        details.append(f"blank_disposal_text_rows={result.blank_disposal_text_rows}")
    if result.duplicate_keys:
        details.append(f"duplicate_keys={result.duplicate_keys}")
    if result.skipped_rows:
        details.append(f"skipped_rows={result.skipped_rows}")
    if result.invalid_period_rows:
        details.append(f"invalid_period_rows={result.invalid_period_rows}")
    if details:
        print("  " + " ".join(details))


def _money(cents: int) -> str:
    return f"{Decimal(cents) / Decimal('100'):.2f}"


def _format_stats(stats: dict[str, int]) -> str:
    return (
        f"OK: {stats['OK']} FIXED: {stats['FIXED']} BLOCKED: {stats['BLOCKED']} "
        f"RECHECK: {stats['RECHECK']} MISSING: {stats['MISSING']} SKIPPED: {stats['SKIPPED']}"
    )


def _emit_stats_notification(
    task_name: str,
    stats: dict[str, int],
    *,
    lines: list[str] | None = None,
) -> None:
    _emit_telegram_notification(
        task_name,
        telegram_notifier.status_from_stats(stats),
        stats=stats,
        lines=lines,
    )


def _emit_telegram_notification(
    task_name: str,
    status: str,
    *,
    stats: dict[str, int] | None = None,
    lines: list[str] | None = None,
    errors: list[str] | None = None,
) -> None:
    result = telegram_notifier.notify_task(
        task_name,
        status,
        stats=stats,
        lines=lines,
        errors=errors,
    )
    if result.sent:
        print("INFO telegram notification sent")
    elif result.error:
        print(f"WARN telegram notification failed: {result.error}")
    elif result.skipped and result.reason not in {"disabled"} and not str(result.reason).startswith("status "):
        print(f"WARN telegram notification skipped: {result.reason}")


def _update_lines(
    *,
    through_date: str | None,
    latest_before: str | None,
    latest_after: str | None,
    markets: tuple[str, ...] | None = None,
) -> list[str]:
    lines = [f"target: {through_date or 'today'}"]
    if markets:
        lines.append(f"markets: {','.join(markets)}")
    lines.append(f"latest_before: {latest_before or '-'}")
    lines.append(f"latest_after: {latest_after or '-'}")
    return lines


def _latest_by_market(func, conn, markets: tuple[str, ...] | None) -> dict[str, str | None]:
    target_markets = markets or config.MARKETS
    return {market: func(conn, market) for market in target_markets}


def _format_market_latest(values: dict[str, str | None]) -> str:
    return " ".join(f"{market}={value or '-'}" for market, value in values.items())


def _format_file_size(path: Path) -> str:
    size = path.stat().st_size
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{size}B"


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
    print("  python main.py ops-check")
    print("  python main.py notify-telegram --test")
    print("  python main.py import-close --date YYYY-MM-DD")
    print("  python main.py rollback-close")
    print("  python main.py import-attention --twse-file notice.csv --tpex-file attention.csv")
    print("  python main.py update-attention")
    print("  python main.py query-attention --stock-id 2330 --from YYYY-MM-DD --to YYYY-MM-DD")
    print("  python main.py import-disposal --twse-file punish.csv --tpex-file disposal.csv")
    print("  python main.py update-disposal")
    print("  python main.py download-legal --from 2019-08-21 --to YYYY-MM-DD")
    print("  python main.py inspect-legal --date YYYY-MM-DD --market TWSE")
    print("  python main.py query-disposal --stock-id 2330 --from YYYY-MM-DD --to YYYY-MM-DD")
    print("  python main.py import-close-local --from YYYY-MM-DD --to YYYY-MM-DD --dir data/csv/Close")
    print("  python main.py finalize-close-months --from YYYY-MM --to YYYY-MM --dir data/csv/Close")
    print("  python main.py query-close --stock-id 2330 --from YYYY-MM-DD --to YYYY-MM-DD")


if __name__ == "__main__":
    raise SystemExit(main())
