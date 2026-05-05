"""Re-run the company matcher against already-extracted articles.

The forward pipeline only matches at extract time, so when the matcher's
ambiguity gate is tightened (e.g., adding ``suzano`` to ``_AMBIGUOUS_ALIASES``
or refining the context score) historical rows keep their stale
``matched_tickers``. This backfill replays the matcher using stored
``companies_ner`` as the ORG signal — no spaCy / HF models loaded.

Usage::

    python -m scripts.backfill.rematch_companies [--dry-run]
        [--since YYYY-MM-DD] [--limit N] [--batch 500]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from finance_news import logconfig
from finance_news.nlp.companies import (
    CompanyMatcher,
    _norm,
    load_companies_from_db,
    to_company,
)
from finance_news.store import db

log = logging.getLogger("backfill.rematch")


def _iter_candidates(conn, since: date | None, limit: int | None, batch: int):
    where = ["matched_tickers IS NOT NULL"]
    params: list = []
    if since is not None:
        where.append("published_at >= %s")
        params.append(since)
    sql = f"""
        SELECT url, title, text, companies_ner, matched_tickers
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
                   help="Print proposed changes without updating.")
    p.add_argument("--since", type=date.fromisoformat, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--batch", type=int, default=500)
    args = p.parse_args(argv)

    logconfig.silence_third_party()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    matcher = CompanyMatcher([to_company(r) for r in load_companies_from_db()])

    scanned = 0
    changed = 0
    updated = 0
    with db.connect() as conn:
        for row in _iter_candidates(conn, args.since, args.limit, args.batch):
            scanned += 1
            text = (row.get("title") or "") + "\n" + (row.get("text") or "")
            org_texts = {_norm(o) for o in (row.get("companies_ner") or []) if o}
            new_tickers = sorted({
                m.ticker_root for m in matcher.match(text, org_texts=org_texts)
            })
            old_tickers = sorted(row.get("matched_tickers") or [])
            if new_tickers == old_tickers:
                continue
            changed += 1
            if args.dry_run:
                print(f"{row['url']}\told={','.join(old_tickers)}\tnew={','.join(new_tickers)}")
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE articles SET matched_tickers = %s WHERE url = %s",
                    (new_tickers, row["url"]),
                )
            conn.commit()
            updated += 1

    log.info("scanned=%d changed=%d updated=%d (dry_run=%s)",
             scanned, changed, updated, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
