"""Match companies and score sentiment on ``social_posts`` rows."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news import logconfig
from finance_news.nlp import analysis
from finance_news.nlp.companies import CompanyMatcher, load_companies_from_db, to_company
from finance_news.store import db

log = logging.getLogger("social")
ProgressFn = Callable[[str, int, int], None]
SP_TZ = ZoneInfo("America/Sao_Paulo")


def run_social_extract(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Run matcher + sentiment on pending social posts. Returns rows updated."""
    logconfig.silence_third_party()
    day = target_date or datetime.now(SP_TZ).date()

    company_rows = load_companies_from_db()
    matcher = CompanyMatcher([to_company(c) for c in company_rows])
    sentiment = analysis.SentimentAnalyzer()
    sentiment._load()

    with db.connect() as conn:
        posts = db.iter_unextracted_social(conn, for_date=day)
    if not posts:
        log.info("No pending social posts for %s", day)
        return 0

    total = len(posts)
    log.info("Social extract — %d post(s)", total)
    if progress:
        progress("social_extract", 0, total)

    updated = 0
    with db.connect() as conn:
        for i, post in enumerate(posts):
            text = post.get("text") or ""
            matches, _ = matcher.match(text, title=text[:200])
            matched = sorted({m.ticker_root for m in matches})
            try:
                sent = sentiment.predict(text[:200], text)
            except Exception:
                sent = analysis.SentimentResult(label="neutral", score=0.0)
            db.update_social_extraction(
                conn,
                post_id=post["id"],
                matched_tickers=matched,
                sentiment=sent.label or "neutral",
                sentiment_score=float(sent.score) if sent.score else None,
            )
            updated += 1
            if progress:
                progress("social_extract", i + 1, total)
        conn.commit()

    log.info("Social extract complete — %d row(s) updated", updated)
    return updated
