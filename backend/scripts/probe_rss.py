"""Validate that each top-150 company has a working Google News RSS feed.

Replaces the old publication-list probe. Reads `data/companies.csv` and for
each company builds the same Google News query `ingest.process_company`
uses, then reports PASS/FAIL + coverage summary.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.pipeline.discovery import google_news_feed  # noqa: E402
from backend.pipeline.ingest import _company_query  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_COMPANIES = ROOT / "data" / "companies.csv"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--companies", type=Path, default=DEFAULT_COMPANIES)
    p.add_argument("--limit", type=int, default=0,
                   help="Probe only the first N companies (0 = all).")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    if not args.companies.exists():
        print(f"Missing {args.companies} — run scripts/fetch_top_companies.py",
              file=sys.stderr)
        return 2

    with args.companies.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    passed = 0
    zero = []
    counts: list[int] = []
    for i, company in enumerate(rows, 1):
        ticker = company.get("ticker", "?")
        short = company.get("short_name", "")
        try:
            cands = google_news_feed(_company_query(company))
        except Exception as e:
            print(f"{i:>3}. FAIL   {ticker:<8}  {short:<30}  ERROR: {e}")
            zero.append(ticker)
            continue

        n = len(cands)
        counts.append(n)
        if n > 0:
            passed += 1
            status = f"OK ({n})"
        else:
            status = "FAIL"
            zero.append(ticker)
        print(f"{i:>3}. {status:<10} {ticker:<8}  {short}")
        if args.verbose and cands:
            for c in cands[:3]:
                print(f"        · {c.title[:90] if c.title else ''}")

    total = len(rows)
    avg = (sum(counts) / len(counts)) if counts else 0
    print()
    print(f"Passed: {passed}/{total}  ·  avg entries: {avg:.1f}")
    if zero:
        print(f"Zero coverage ({len(zero)}): {', '.join(zero[:20])}"
              + ("…" if len(zero) > 20 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
