"""Pipeline orchestration: ingest, extract, summarize, and run-bookkeeping.

Functions here are pure orchestrators — they update the ``runs`` table around
each invocation and re-raise on failure. The CLI dispatcher at the bottom is
the only place that swallows tracebacks (and only to set a non-zero exit
code); cron and Make targets call ``python -m finance_news.pipeline <cmd>``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from finance_news import logconfig
from finance_news.store import db

ProgressFn = Callable[[str, int, int], None]
SP_TZ = ZoneInfo("America/Sao_Paulo")

log = logging.getLogger("pipeline")


@dataclass
class RunSummary:
    kind: str
    run_id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str = "running"
    n_fetched: int = 0
    n_extracted: int = 0
    error: Optional[str] = None
    children: list["RunSummary"] = field(default_factory=list)


def _setup_logging() -> None:
    logconfig.silence_third_party()
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def _start(kind: str) -> tuple[int, datetime]:
    started = datetime.now(timezone.utc)
    with db.connect() as conn:
        run_id = db.record_run_start(conn, kind)
    return run_id, started


def _finish(
    run_id: int,
    *,
    status: str,
    n_fetched: Optional[int] = None,
    n_extracted: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    with db.connect() as conn:
        db.record_run_end(
            conn,
            run_id=run_id,
            status=status,
            n_fetched=n_fetched,
            n_extracted=n_extracted,
            error=error,
        )


def run_ingest(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    if setup_logging:
        _setup_logging()
    run_id, started = _start("ingest")
    try:
        from finance_news import ingest
        n = ingest.run(target_date=target_date, progress=progress)
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    _finish(run_id, status="ok", n_fetched=n)
    return RunSummary(
        kind="ingest", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok", n_fetched=n,
    )


def run_extract(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    if setup_logging:
        _setup_logging()
    run_id, started = _start("extract")
    try:
        from finance_news import extract
        n = extract.run(target_date=target_date, progress=progress)
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    _finish(run_id, status="ok", n_extracted=n)
    return RunSummary(
        kind="extract", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok", n_extracted=n,
    )


def run_summarize(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    if setup_logging:
        _setup_logging()
    day = target_date or datetime.now(SP_TZ).date()
    run_id, started = _start("summarize")
    try:
        from finance_news import summaries
        summaries.run_summaries(day, progress=progress)
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    _finish(run_id, status="ok")
    return RunSummary(
        kind="summarize", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok",
    )


def run_full(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    """Ingest, then extract, then summarize.

    Records a single ``full`` run in the ``runs`` table; the per-stage runs
    recorded by ``run_ingest`` / ``run_extract`` / ``run_summarize`` provide
    finer detail.
    """
    if setup_logging:
        _setup_logging()
    day = target_date or datetime.now(SP_TZ).date()
    run_id, started = _start("full")
    children: list[RunSummary] = []
    try:
        children.append(run_ingest(target_date=day, progress=progress, setup_logging=False))
        children.append(run_extract(target_date=day, progress=progress, setup_logging=False))
        children.append(run_summarize(target_date=day, progress=progress, setup_logging=False))
        import os
        if os.environ.get("X_SOCIAL_INGEST", "").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            children.append(
                run_social_ingest(target_date=day, progress=progress, setup_logging=False),
            )
            children.append(
                run_social_extract(target_date=day, progress=progress, setup_logging=False),
            )
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    n_fetched = sum(c.n_fetched for c in children)
    n_extracted = sum(c.n_extracted for c in children)
    _finish(run_id, status="ok", n_fetched=n_fetched, n_extracted=n_extracted)
    return RunSummary(
        kind="full", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok",
        n_fetched=n_fetched, n_extracted=n_extracted, children=children,
    )


def run_social_ingest(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    if setup_logging:
        _setup_logging()
    run_id, started = _start("social_ingest")
    try:
        from finance_news import social_ingest
        n = social_ingest.run_social_ingest(
            target_date=target_date, progress=progress,
        )
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    _finish(run_id, status="ok", n_fetched=n)
    return RunSummary(
        kind="social_ingest", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok", n_fetched=n,
    )


def run_social_extract(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    if setup_logging:
        _setup_logging()
    run_id, started = _start("social_extract")
    try:
        from finance_news import social_extract
        n = social_extract.run_social_extract(
            target_date=target_date, progress=progress,
        )
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    _finish(run_id, status="ok", n_extracted=n)
    return RunSummary(
        kind="social_extract", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok", n_extracted=n,
    )


def run_cvm_ingest(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
    setup_logging: bool = True,
) -> RunSummary:
    if setup_logging:
        _setup_logging()
    run_id, started = _start("cvm")
    try:
        from finance_news import ingest
        n = ingest.run_cvm_ingest(target_date=target_date, progress=progress)
    except Exception as e:
        _finish(run_id, status="error", error=repr(e))
        raise
    _finish(run_id, status="ok", n_fetched=n)
    return RunSummary(
        kind="cvm", run_id=run_id, started_at=started,
        finished_at=datetime.now(timezone.utc), status="ok", n_fetched=n,
    )


def pipeline_status() -> dict[str, Any]:
    """Snapshot of recent activity: row counts + last 5 runs per kind."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT count(*) FROM articles) AS articles_total,
                (SELECT count(*) FROM articles WHERE sentiment IS NULL) AS articles_pending,
                (SELECT count(*) FROM companies) AS companies_total,
                (SELECT count(*) FROM publishers) AS publishers_total,
                (SELECT count(*) FROM judgments) AS judgments_total
            """
        )
        counts = cur.fetchone()

        cur.execute(
            """
            SELECT id, kind, status, started_at, finished_at,
                   n_fetched, n_extracted, error
            FROM runs
            ORDER BY started_at DESC
            LIMIT 10
            """
        )
        recent = cur.fetchall()
    return {"counts": counts, "recent_runs": recent}


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m finance_news.pipeline")
    p.add_argument(
        "subcommand",
        choices=(
            "ingest", "extract", "summarize", "run", "cvm",
            "social", "social-extract", "status",
        ),
    )
    p.add_argument("--date", help="ISO date (YYYY-MM-DD); default = today in BRT.")
    args = p.parse_args(argv)
    target_date = date.fromisoformat(args.date) if args.date else None

    if args.subcommand == "ingest":
        run_ingest(target_date=target_date)
    elif args.subcommand == "extract":
        run_extract(target_date=target_date)
    elif args.subcommand == "summarize":
        run_summarize(target_date=target_date)
    elif args.subcommand == "run":
        run_full(target_date=target_date)
    elif args.subcommand == "cvm":
        run_cvm_ingest(target_date=target_date)
    elif args.subcommand == "social":
        run_social_ingest(target_date=target_date)
    elif args.subcommand == "social-extract":
        run_social_extract(target_date=target_date)
    elif args.subcommand == "status":
        import json
        print(json.dumps(pipeline_status(), default=str, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
