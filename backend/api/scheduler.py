"""APScheduler wiring for the daily pipeline run at 23:50 America/Sao_Paulo."""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .services import pipeline_runner

log = logging.getLogger("scheduler")

SP_TZ = ZoneInfo("America/Sao_Paulo")
JOB_ID = "daily_pipeline"

scheduler = BackgroundScheduler(timezone=SP_TZ)


def _run_daily() -> None:
    try:
        run_id = pipeline_runner.start(trigger="cron")
        log.info("cron kicked pipeline run %s", run_id)
    except pipeline_runner.RunInProgressError as e:
        log.warning("cron skipped — run %s already in progress", e.run_id)


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _run_daily,
        CronTrigger(hour=23, minute=50, timezone=SP_TZ),
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info("scheduler started; next run: %s", next_run_iso())


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def next_run_iso() -> str | None:
    job = scheduler.get_job(JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.isoformat()
