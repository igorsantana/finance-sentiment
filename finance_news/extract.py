"""Run NER + subjects + sentiment + ticker matching on every article whose
``sentiment`` column is still NULL, and update the row in place.

No CSV input, no CSV output, no ``--companies-only`` filter (every article
already comes from the company stream). Worker count is read from the
``WORKERS`` env var only.
"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Callable, Optional

ProgressFn = Callable[[str, int, int], None]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news import logconfig
from finance_news.nlp import analysis, entities
from finance_news.nlp.sports_filter import detect_sports_context
from finance_news.nlp.companies import (
    Company,
    CompanyMatcher,
    load_companies_from_db,
    to_company,
)
from finance_news.nlp.relevance import CompanyRelevanceScorer
from finance_news.store import db

log = logging.getLogger("extract")


def _summary(text: str, n: int = 280) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    return collapsed[:n]


def _env_workers(default: int = 4) -> int:
    raw = os.environ.get("WORKERS")
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default


def _process_article(
    art: dict[str, Any],
    matcher: CompanyMatcher,
    sentiment,
    scorer: Optional[CompanyRelevanceScorer] = None,
) -> Optional[dict[str, Any]]:
    """Compute the analysis fields for one article. Returns the kwargs for
    ``db.update_extraction`` or ``None`` if NER itself failed (we leave the
    row in the pending state so the next run can retry).

    spaCy and the HuggingFace pipeline release the GIL during native compute,
    so a ThreadPoolExecutor gives real parallel speedup.
    """
    title = art.get("title") or ""
    body = art.get("text") or ""
    text = title + "\n" + body
    url = art["url"]

    try:
        ents = entities.analyze(text)
    except Exception as e:
        log.debug("NER failed on %s: %s", url, e)
        return None

    try:
        subjects = analysis.rank_subjects(
            ents["doc"], title, ents["companies"], ents["persons"]
        )
    except Exception as e:
        log.debug("subject ranking failed on %s: %s", url, e)
        subjects = []

    try:
        sent = sentiment.predict(title, body)
    except Exception as e:
        log.debug("sentiment failed on %s: %s", url, e)
        sent = analysis.SentimentResult(label="", score=0.0)

    sent_emb = sentiment.embed(title, body)

    conflicts = analysis.detect_conflicts(
        art.get("hostname") or "", art.get("author") or "", subjects
    )
    matches, rel_emb = matcher.match(
        text, doc=ents.get("doc"), relevance_scorer=scorer, title=title
    )
    matched_tickers = sorted({m.ticker_root for m in matches})

    if matched_tickers:
        verdict = detect_sports_context(title, body, subjects, ents["companies"])
        if verdict.is_sports:
            log.info(
                "sports_context dropped %s for %s (%s)",
                matched_tickers, url, ",".join(verdict.reasons[:3]),
            )
            conflicts = list(conflicts) + ["sports_context"]
            matched_tickers = []

    return {
        "url": url,
        "sentiment": sent.label or "",
        "sentiment_score": float(sent.score) if sent.score else None,
        "subjects": subjects,
        "companies_ner": ents["companies"],
        "persons": ents["persons"],
        "countries": ents["countries"],
        "currencies": ents["currencies"],
        "matched_tickers": matched_tickers,
        "conflicts": conflicts,
        "summary": _summary(body),
        "relevance_embedding": rel_emb,
        "sentiment_embedding": sent_emb,
    }


def run(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Extract one full pass. Returns the number of rows updated."""
    logconfig.silence_third_party()
    workers = _env_workers()
    log.info("Using %d extraction worker(s)", workers)

    # Warm up spaCy + sentiment ONCE on the main thread before fanning out;
    # otherwise every worker races to load and we pay the model-load cost N
    # times (and can OOM).
    entities.get_nlp()
    sentiment = analysis.SentimentAnalyzer()
    sentiment._load()

    company_rows = load_companies_from_db()
    companies = [to_company(c) for c in company_rows]
    matcher = CompanyMatcher(companies)
    log.info("Loaded %d companies for matching", len(company_rows))

    scorer = CompanyRelevanceScorer(companies)
    scorer._load()

    with db.connect() as read_conn:
        articles = list(db.iter_unextracted(read_conn, for_date=target_date))
    if not articles:
        log.info("No pending articles.")
        if progress:
            progress("extract", 0, 0)
        return 0

    total = len(articles)
    log.info("Processing %d article(s) with %d worker(s)", total, workers)
    if progress:
        progress("extract", 0, total)

    updates: list[dict[str, Any]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_process_article, a, matcher, sentiment, scorer): a
            for a in articles
        }
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if result is not None:
                updates.append(result)
            if progress:
                progress("extract", done, total)
            if done % 25 == 0:
                log.info("processed %d/%d articles…", done, total)

    with db.connect() as conn:
        for u in updates:
            db.update_extraction(conn, **u)
        conn.commit()

    log.info("Extract complete — %d row(s) updated", len(updates))
    return len(updates)


if __name__ == "__main__":
    from finance_news.pipeline import run_extract
    run_extract()
