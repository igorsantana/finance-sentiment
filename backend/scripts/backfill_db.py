"""Import every data/news_<date>.csv into data/app.db.

Safe to re-run: uses the same URL-keyed upsert as the extract stage.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.db import init_db, upsert_articles  # noqa: E402

DATE_RE = re.compile(r"news_(\d{4}-\d{2}-\d{2})\.csv$")

LIST_COLUMNS = (
    "subjects", "matched_companies", "matched_tickers", "sectors",
    "companies", "persons", "countries", "currencies", "conflicts",
)


def _row_to_record(row: dict, date: str) -> dict:
    rec = {
        "date": date,
        "site": row.get("site", ""),
        "source_kind": row.get("source_kind", ""),
        "source_key": row.get("source_key", ""),
        "title": row.get("title", ""),
        "url": row.get("url", ""),
        "published_at": row.get("published_at", ""),
        "author": row.get("author") or None,
        "sentiment": row.get("sentiment", ""),
        "sentiment_score": float(row["sentiment_score"]) if row.get("sentiment_score") else None,
        "summary": row.get("summary", ""),
    }
    for col in LIST_COLUMNS:
        raw = row.get(col, "") or ""
        rec[col] = [x for x in raw.split("|") if x]
    return rec


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = p.parse_args(argv)

    init_db()
    csvs = sorted(args.data_dir.glob("news_*.csv"))
    if not csvs:
        print("no news_*.csv files found", file=sys.stderr)
        return 2

    total = 0
    for path in csvs:
        m = DATE_RE.search(path.name)
        if not m:
            continue
        date = m.group(1)
        with path.open(encoding="utf-8") as f:
            records = [_row_to_record(r, date) for r in csv.DictReader(f)]
        n = upsert_articles(records)
        total += n
        print(f"  {path.name}: {n} rows")

    print(f"upserted {total} article(s) across {len(csvs)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
