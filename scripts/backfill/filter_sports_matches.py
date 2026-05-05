"""Re-run the sports-context filter against already-extracted articles.

Forward extraction (``finance_news/extract.py``) only touches rows where
``sentiment IS NULL``, so historical false-positives like "Superliga Gerdau"
articles attached to GGBR persist until this script runs.

Usage::

    python -m scripts.backfill.filter_sports_matches [--dry-run]
        [--since YYYY-MM-DD] [--limit N] [--batch 500]

The filter is a pure function (``finance_news.nlp.sports_filter``); no
models load. Idempotent — re-running won't re-flag rows whose
``matched_tickers`` is already empty.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from finance_news import logconfig
from finance_news.nlp.sports_filter import detect_sports_context
from finance_news.store import db

log = logging.getLogger("backfill.sports")


def _iter_candidates(conn, since: date | None, limit: int | None, batch: int):
    """Page through articles that still have at least one matched ticker."""
    where = ["matched_tickers IS NOT NULL", "cardinality(matched_tickers) > 0"]
    params: list = []
    if since is not None:
        where.append("published_at >= %s")
        params.append(since)
    sql = f"""
        SELECT url, title, text, subjects, matched_tickers, conflicts,
               companies_ner
        FROM articles
        WHERE {' AND '.join(where)}
        ORDER BY published_at DESC
        LIMIT %s OFFSET %s
    """
    offset = 0
    yielded = 0
    while True:
        page_limit = batch
        if limit is not None:
            remaining = limit - yielded
            if remaining <= 0:
                return
            page_limit = min(batch, remaining)
        with conn.cursor() as cur:
            cur.execute(sql, (*params, page_limit, offset))
            rows = cur.fetchall()
        if not rows:
            return
        for r in rows:
            yield r
            yielded += 1
        offset += len(rows)
        if len(rows) < page_limit:
            return


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Print flagged URLs without updating.")
    p.add_argument("--since", type=date.fromisoformat, default=None,
                   help="Only consider articles published on/after this ISO date.")
    p.add_argument("--limit", type=int, default=None,
                   help="Stop after scanning N articles.")
    p.add_argument("--batch", type=int, default=500,
                   help="Page size for the candidate query.")
    args = p.parse_args(argv)

    logconfig.silence_third_party()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    scanned = 0
    flagged = 0
    updated = 0
    with db.connect() as conn:
        for row in _iter_candidates(conn, args.since, args.limit, args.batch):
            scanned += 1
            verdict = detect_sports_context(
                row.get("title") or "",
                row.get("text") or "",
                row.get("subjects") or [],
                row.get("companies_ner") or [],
            )
            if not verdict.is_sports:
                continue
            flagged += 1
            old_tickers = row.get("matched_tickers") or []
            existing_conflicts = list(row.get("conflicts") or [])
            if "sports_context" not in existing_conflicts:
                existing_conflicts.append("sports_context")
            if args.dry_run:
                print(f"{row['url']}\t{','.join(old_tickers)}\t{','.join(verdict.reasons)}")
                continue
            db.clear_matched_tickers(
                conn,
                url=row["url"],
                conflicts=existing_conflicts,
            )
            conn.commit()
            updated += 1

    log.info("scanned=%d flagged=%d updated=%d (dry_run=%s)",
             scanned, flagged, updated, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
