#!/usr/bin/env python3
"""Validate that each tracked company has a working Google News RSS feed.

For each company in the ``companies`` table, build the same query
``finance_news.ingest._company_query`` uses, hit Google News RSS, and
report PASS/FAIL + total coverage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news.nlp.companies import load_companies_from_db  # noqa: E402
from finance_news.net.discovery import google_news_feed  # noqa: E402
from finance_news.ingest import _company_query  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0,
                   help="Stop after probing N companies (0 = all).")
    args = p.parse_args(argv)

    companies = load_companies_from_db()
    if args.limit:
        companies = companies[: args.limit]

    pass_n = 0
    for c in companies:
        query = _company_query(c)
        cands = google_news_feed(query) if query else []
        status = "PASS" if cands else "FAIL"
        if cands:
            pass_n += 1
        print(f"{status:4s} {c['ticker']:7s} {len(cands):3d} hits  q={query!r}")

    total = len(companies)
    print(f"\nCoverage: {pass_n}/{total} ({pass_n / max(total, 1):.0%})")
    return 0 if pass_n == total else 1


if __name__ == "__main__":
    sys.exit(main())
