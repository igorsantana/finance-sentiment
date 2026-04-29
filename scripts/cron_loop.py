#!/usr/bin/env python3
"""Daily scheduler for the finance_news pipeline.

Sleeps until 23:50 in $TZ and shells out to ``python -m finance_news.pipeline run``.
Kept deliberately tiny so the cron container stays single-purpose; if scheduling
needs ever grow past one slot a day we should reach for a real cron, not extend
this loop.
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "America/Sao_Paulo"))
HOUR = 23
MINUTE = 50


def next_fire_time(now: datetime) -> datetime:
    target = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def main() -> None:
    while True:
        now = datetime.now(TZ)
        target = next_fire_time(now)
        time.sleep((target - now).total_seconds())
        subprocess.run(
            ["python", "-m", "finance_news.pipeline", "run"],
            check=False,
        )


if __name__ == "__main__":
    main()
