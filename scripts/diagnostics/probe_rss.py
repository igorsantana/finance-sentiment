#!/usr/bin/env python3
"""Validate that every discovery adapter is reachable and listing today.

For each entry in ``finance_news.net.discovery.default_adapters()``, run
``list_today(today_sp)`` and report PASS / WARN / FAIL with the per-adapter
HTTP count, elapsed time, and number of articles listed. Exits non-zero
if any adapter errored — wire it into a cron health check or run it
ad-hoc when triaging "ingest produced fewer articles than usual" days.

Usage:
    python scripts/diagnostics/probe_rss.py
    python scripts/diagnostics/probe_rss.py --date 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news.net import discovery  # noqa: E402

SP_TZ = ZoneInfo("America/Sao_Paulo")


def _resolve_day(arg: Optional[str]) -> date:
    if arg:
        return date.fromisoformat(arg)
    return datetime.now(SP_TZ).date()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="ISO date (default: today in SP)")
    args = p.parse_args(argv)
    day = _resolve_day(args.date)

    adapters = discovery.default_adapters()
    print(f"Probing {len(adapters)} adapters for {day} (SP)…\n")
    results = discovery.run_adapters(adapters, day)

    pass_n = warn_n = fail_n = 0
    for r in sorted(results, key=lambda x: x.publisher.lower()):
        if r.error:
            status = "FAIL"
            fail_n += 1
        elif not r.articles:
            status = "WARN"
            warn_n += 1
        else:
            status = "PASS"
            pass_n += 1
        suffix = f"  ERROR: {r.error}" if r.error else ""
        print(
            f"{status:4s} {r.publisher:30s} "
            f"{len(r.articles):3d} articles, "
            f"{r.http_calls:2d} http, "
            f"{r.elapsed_s:5.2f}s{suffix}"
        )

    total = len(results)
    listed_raw = sum(len(r.articles) for r in results)
    deduped, _ = discovery.discover_articles(day, adapters=adapters)
    print(
        f"\nCoverage: {pass_n}/{total} pass · {warn_n} warn (0 articles) · "
        f"{fail_n} fail"
    )
    print(f"Listed URLs: {listed_raw} raw · {len(deduped)} unique after dedup")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
