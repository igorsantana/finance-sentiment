#!/usr/bin/env python3
"""Diagnostic: flag likely false-positives in ``articles.matched_tickers``.

For every extracted article whose matched_tickers includes one whose
short_name's normalized alias is in ``_AMBIGUOUS_ALIASES`` (e.g. "vale",
"tim", "rumo"), check whether the article body actually contains the
ticker / ticker_root (case-sensitive) or a spaCy ORG span. Articles with
neither are likely false positives — surface them for review.

Usage:
    python scripts/audit_company_matches.py
    python scripts/audit_company_matches.py --since 2026-04-20
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news.store import db  # noqa: E402
from finance_news.nlp.companies import (  # noqa: E402
    _AMBIGUOUS_ALIASES,
    _norm_org_set,
    CompanyMatcher,
    load_companies_from_db,
    to_company,
)
from finance_news.nlp.entities import analyze  # noqa: E402


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def _snippet(text: str, needle: str, window: int = 80) -> str:
    m = re.search(re.escape(needle), text, flags=re.IGNORECASE)
    if not m:
        return ""
    lo = max(0, m.start() - window)
    hi = min(len(text), m.end() + window)
    return f"…{text[lo:hi].replace(chr(10), ' ')}…"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since",
                   help="ISO date; only audit articles published at/after.")
    args = p.parse_args(argv)

    companies = [to_company(c) for c in load_companies_from_db()]
    matcher = CompanyMatcher(companies)
    root_to_company = {c.ticker_root: c for c in companies}
    short_alias_by_root = {
        c.ticker_root: _norm(c.short_name) for c in companies if c.short_name
    }

    where = ["a.matched_tickers IS NOT NULL", "array_length(a.matched_tickers, 1) > 0"]
    params: list = []
    if args.since:
        where.append("a.published_at >= %s")
        params.append(datetime.fromisoformat(args.since))
    sql = (
        "SELECT url, title, text, matched_tickers "
        "FROM articles a WHERE " + " AND ".join(where)
    )

    suspicious: dict[str, list[dict]] = {}
    total = 0
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        for row in cur:
            for root in row["matched_tickers"] or []:
                alias = short_alias_by_root.get(root)
                if not alias or alias not in _AMBIGUOUS_ALIASES:
                    continue
                total += 1
                title = row.get("title") or ""
                body = row.get("text") or ""
                full = title + "\n" + body

                ticker_re = matcher._ticker_re_by_root.get(root)
                if ticker_re and ticker_re.search(full):
                    continue
                try:
                    ents = analyze(full)
                    org_texts = _norm_org_set(ents.get("doc"))
                except Exception:
                    org_texts = set()
                if any(alias in o for o in org_texts):
                    continue
                short = root_to_company[root].short_name or root
                suspicious.setdefault(short, []).append({
                    "url": row["url"],
                    "title": title,
                    "snippet": _snippet(body or title, alias),
                })

    print(f"  ambiguous-alias hits total: {total}")
    print(f"  likely false positives: {sum(len(v) for v in suspicious.values())}\n")
    for short, items in sorted(suspicious.items(), key=lambda kv: -len(kv[1])):
        print(f"[{short}]  {len(items)} suspicious")
        for it in items[:8]:
            print(f"  {it['url']}")
            print(f"    title: {it['title'][:110]}")
            if it["snippet"]:
                print(f"    ctx: {it['snippet'][:180]}")
        if len(items) > 8:
            print(f"  … and {len(items) - 8} more")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
