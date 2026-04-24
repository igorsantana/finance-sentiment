"""Diagnostic: flag likely false-positives in matched_companies.

Reads a news_*.csv (with matched_companies column) and joins it against
raw_articles.jsonl on URL. For every row where an ambiguous alias appears in
matched_companies but the raw article body contains no ticker/ticker_root
occurrence (case-sensitive), print a warning with the body snippet around
the offending match.

Usage:
    python scripts/audit_company_matches.py
    python scripts/audit_company_matches.py --csv data/news_2026-04-23.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finance_news.companies import (  # noqa: E402
    _AMBIGUOUS_ALIASES, _norm_org_set, CompanyMatcher, load_companies,
)
from finance_news.entities import analyze  # noqa: E402

DATA_DIR = ROOT / "data"
RAW_JSONL = DATA_DIR / "raw" / "raw_articles.jsonl"
SP_TZ = ZoneInfo("America/Sao_Paulo")


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
    snippet = text[lo:hi].replace("\n", " ")
    return f"…{snippet}…"


def _load_jsonl(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                art = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = art.get("url")
            if url:
                out[url] = art
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, help="news CSV to audit (default: today)")
    p.add_argument("--jsonl", type=Path, default=RAW_JSONL)
    p.add_argument("--companies-file", type=Path,
                   default=DATA_DIR / "companies.csv")
    args = p.parse_args(argv)

    csv_path = args.csv
    if csv_path is None:
        day = datetime.now(SP_TZ).date().isoformat()
        csv_path = DATA_DIR / f"news_{day}.csv"
    if not csv_path.exists():
        print(f"error: {csv_path} not found", file=sys.stderr)
        return 2

    companies = load_companies(args.companies_file)
    matcher = CompanyMatcher(companies)
    # Build short_name → ticker_regex map via matcher internals.
    short_to_root = {c.short_name: c.ticker_root for c in companies}
    root_to_company = {c.ticker_root: c for c in companies}
    norm_short_to_root = {_norm(c.short_name): c.ticker_root for c in companies}

    raw_by_url = _load_jsonl(args.jsonl)

    suspicious: dict[str, list[dict]] = {}  # short_name → rows
    total_ambiguous_hits = 0

    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            matched = [x.strip() for x in (row.get("matched_companies") or "").split("|") if x.strip()]
            if not matched:
                continue
            for short in matched:
                root = short_to_root.get(short) or norm_short_to_root.get(_norm(short))
                if root is None:
                    continue
                alias_key = _norm(short)
                if alias_key not in _AMBIGUOUS_ALIASES:
                    continue
                total_ambiguous_hits += 1

                art = raw_by_url.get(row.get("url", ""))
                body = (art or {}).get("text") or ""
                title = row.get("title") or ""
                full = title + "\n" + body

                ticker_re = matcher._ticker_re_by_root.get(root)
                has_ticker = bool(ticker_re and ticker_re.search(full))
                if has_ticker:
                    continue

                # Re-run NER to check ORG evidence (same signal the matcher
                # uses). Only articles with neither ticker nor ORG evidence
                # are genuine false positives.
                try:
                    ents = analyze(full)
                    org_texts = _norm_org_set(ents.get("doc"))
                except Exception:
                    org_texts = set()
                if any(alias_key in o for o in org_texts):
                    continue

                suspicious.setdefault(short, []).append({
                    "url": row.get("url", ""),
                    "title": title,
                    "snippet": _snippet(body or title, alias_key),
                })

    print(f"Audit of {csv_path}")
    print(f"  ambiguous-alias hits total: {total_ambiguous_hits}")
    print(f"  likely false positives: {sum(len(v) for v in suspicious.values())}")
    print()
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
