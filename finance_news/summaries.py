"""Eager per-(company, day) good/bad-points summarization step.

Runs after ``extract`` in the daily pipeline. For each of
the day's top-N most-mentioned companies, gathers the matching articles
and asks the local LLM (Stage 2's ``llm_summary``) for a strict-JSON
good/bad bullet list, then upserts into ``company_day_summaries``.

Idempotent: a re-run skips tickers that already have a row for the same
date. Soft on LLM failures — ``llm_summary.summarize_company_day`` returns
``None`` on connection / parse / empty errors and we log + continue.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Callable, Optional

from finance_news.nlp.companies import load_companies_from_db
from finance_news.nlp.llm_summary import summarize_company_day
from finance_news.store import db

log = logging.getLogger("summaries")
ProgressFn = Callable[[str, int, int], None]


def run_summaries(
    target_date: date,
    *,
    top_n: int = 20,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Generate missing summaries for ``target_date``. Returns rows inserted."""
    with db.connect() as conn:
        rows = db.fetch_articles_for_date(conn, target_date)
        if not rows:
            log.info("No articles for %s — skipping summaries.", target_date)
            if progress:
                progress("summarize", 0, 0)
            return 0

        by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            for t in (r.get("matched_tickers") or []):
                by_ticker[t].append(r)

        counts = Counter({t: len(arts) for t, arts in by_ticker.items()})
        top = [t for t, _ in counts.most_common(top_n)]
        if not top:
            log.info("No matched tickers for %s — skipping summaries.", target_date)
            if progress:
                progress("summarize", 0, 0)
            return 0

        company_map = {c["ticker_root"]: c for c in load_companies_from_db()}
        total = len(top)
        if progress:
            progress("summarize", 0, total)

        inserted = 0
        for i, ticker in enumerate(top, start=1):
            if db.fetch_company_summary(
                conn, ticker_root=ticker, summary_date=target_date
            ):
                log.info("%s: summary already cached, skipping", ticker)
                if progress:
                    progress("summarize", i, total)
                continue

            articles = by_ticker[ticker]
            name = ((company_map.get(ticker) or {}).get("short_name")) or ticker
            log.info("%s (%s): summarizing %d article(s)", ticker, name, len(articles))
            result = summarize_company_day(name, ticker, articles)
            if result is None:
                if progress:
                    progress("summarize", i, total)
                continue

            db.upsert_company_summary(
                conn,
                ticker_root=ticker,
                summary_date=target_date,
                good=result["good"],
                bad=result["bad"],
                article_count=len(articles),
                model=result["model"],
            )
            conn.commit()
            inserted += 1
            if progress:
                progress("summarize", i, total)

        log.info("Summaries complete — %d new for %s", inserted, target_date)
        return inserted
