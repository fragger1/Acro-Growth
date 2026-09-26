import argparse
import logging
from logging.handlers import RotatingFileHandler

from gmaps.config import ROOT, load_config


def _setup_logging() -> logging.Logger:
    (ROOT / "logs").mkdir(exist_ok=True)
    logger = logging.getLogger("gmaps")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(message)s")
        file_handler = RotatingFileHandler(ROOT / "logs" / "gmaps.log", maxBytes=5_000_000, backupCount=5,
                                           encoding="utf-8")
        file_handler.setFormatter(fmt)
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        logger.addHandler(file_handler)
        logger.addHandler(console)
    return logger


def _int_or_none(value):
    return None if value in (None, "", "null") else int(value)


def cmd_run(args, db, cfg, log):
    from gmaps.runner import run
    from gmaps.scraper import GosomScraper

    if not cfg.gosom_path.exists():
        raise SystemExit(f"gosom not found at {cfg.gosom_path}; run scripts/setup.ps1")
    if args.all:
        limit = None
    elif args.limit is not None:
        limit = args.limit
    else:
        limit = _int_or_none(db.get_setting("nightly_limit"))
    concurrency = int(db.get_setting("concurrency", 3))
    depth = int(db.get_setting("depth", 12))
    log.info(f"run start: limit={limit or 'unlimited'} concurrency={concurrency} depth={depth} "
             f"proxies={len(cfg.proxies)}")
    stats = run(db, GosomScraper(cfg, concurrency), trigger="scheduled" if args.scheduled else "manual",
                limit=limit, default_depth=depth, log=log.info)
    log.info(f"run finished: {stats}")


def cmd_queue_add(args, db, cfg, log):
    from gmaps.queue import add_searches

    added, skipped = add_searches(db, args.keyword, args.locations, args.client, args.limit, args.force)
    log.info(f"queued {added} searches")
    for query in skipped:
        log.info(f"  skipped (already queued or done in last 30 days): {query}")


def cmd_export(args, db, cfg, log):
    from gmaps.export import export_leads

    path, count = export_leads(db, args.client, since=args.since, keyword=args.search,
                               include_no_email=args.include_no_email, new_only=args.new_only,
                               out_dir=ROOT / "exports")
    log.info(f"exported {count} leads to {path}" if path else "no leads matched; nothing exported")


def cmd_status(args, db, cfg, log):
    summary = db.status_summary()
    print("queue:", summary["queue"])
    print("last run:", summary["last_run"])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gmaps")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="scrape pending searches")
    group = p_run.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, help="stop after this many new places")
    group.add_argument("--all", action="store_true", help="no limit; empty the queue")
    p_run.add_argument("--scheduled", action="store_true", help="mark as scheduled run (uses nightly_limit)")
    p_run.set_defaults(func=cmd_run)

    p_queue = sub.add_parser("queue", help="manage search queue")
    qsub = p_queue.add_subparsers(dest="queue_command", required=True)
    p_add = qsub.add_parser("add", help="add keyword x locations")
    p_add.add_argument("keyword")
    p_add.add_argument("--locations", required=True, help='"Austin, TX; Dallas, TX"')
    p_add.add_argument("--client", required=True)
    p_add.add_argument("--limit", type=int, help="max places per search")
    p_add.add_argument("--force", action="store_true", help="re-queue even if done in last 30 days")
    p_add.set_defaults(func=cmd_queue_add)

    p_export = sub.add_parser("export", help="export leads CSV")
    p_export.add_argument("--client", required=True)
    p_export.add_argument("--since", help="YYYY-MM-DD, by first seen for this client")
    p_export.add_argument("--search", help="keyword filter (ILIKE pattern, e.g. dentist%%)")
    p_export.add_argument("--include-no-email", action="store_true")
    p_export.add_argument("--new-only", action="store_true", help="skip leads already exported to this client")
    p_export.set_defaults(func=cmd_export)

    p_status = sub.add_parser("status", help="queue counts and last run")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    log = _setup_logging()
    cfg = load_config()
    from gmaps.db import Db

    args.func(args, Db.connect(cfg), cfg, log)


if __name__ == "__main__":
    main()
