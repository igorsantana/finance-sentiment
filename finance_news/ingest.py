"""Company-stream ingest: query Google News per tracked company, fetch the
articles, write them into the ``articles`` table.

URL dedup is handled at the DB level via ``ON CONFLICT (url) DO NOTHING`` —
no in-memory ``seen_urls`` set, no JSONL sidecar. The legacy site-stream
(``process_site``, ``read_sources``, ``--mode``) was removed in this rewrite.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Callable, Optional

ProgressFn = Callable[[str, int, int], None]
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news import logconfig
from finance_news.net import discovery, fetch
from finance_news.nlp.companies import load_companies_from_db
from finance_news.store import db
from finance_news.store.publishers import publisher_from_url

log = logging.getLogger("ingest")

SP_TZ = ZoneInfo("America/Sao_Paulo")
PER_COMPANY_ARTICLE_CAP = 8
INTER_ARTICLE_SLEEP = 1.0


def _env_workers(default: int = 4) -> int:
    raw = os.environ.get("WORKERS")
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default


def _today_sp() -> date:
    return datetime.now(SP_TZ).date()


def _host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _company_query(company: dict[str, Any]) -> str:
    """Google News query for a single company row.

    Preference order: short_name (tight match) → long_name → ticker. Quoted
    short/long names keep precision high; the bare ticker catches market
    reports that reference codes but not full names.
    """
    terms: list[str] = []
    short = (company.get("short_name") or "").strip()
    long_ = (company.get("long_name") or "").strip()
    ticker = (company.get("ticker") or "").strip().upper()
    root = (company.get("ticker_root") or "").strip().upper()
    if short:
        terms.append(f'"{short}"')
    if long_ and long_.lower() != short.lower():
        terms.append(f'"{long_}"')
    if ticker:
        terms.append(ticker)
    if root and root != ticker:
        terms.append(root)
    return " OR ".join(terms)


def process_company(company: dict[str, Any], today: date) -> list[dict[str, Any]]:
    ticker = (company.get("ticker") or "").strip().upper()
    short = company.get("short_name") or company.get("long_name") or ticker
    query = _company_query(company)
    if not query:
        return []
    log.info("==> company %s (%s) query=%r", ticker, short, query)
    try:
        cands = discovery.google_news_feed(query)
    except Exception as e:
        log.debug("%s: google news failed: %s", ticker, e)
        return []
    cands = discovery.filter_today(cands, today)[:PER_COMPANY_ARTICLE_CAP]
    log.info("%s: %d candidates after %s-filter", ticker, len(cands), today)

    out: list[dict[str, Any]] = []
    for c in cands:
        try:
            art = fetch.fetch_article(c.url)
        except Exception as e:
            log.debug("%s: fetch failed %s: %s", ticker, c.url, e)
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        if art is None:
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        pub = c.published or art.published
        if pub is None or pub.date() != today:
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        out.append({
            "url": art.url,
            "title": art.title or c.title,
            "text": art.text,
            "author": art.author,
            "hostname": _host_key(art.url),
            "published_at": pub,
            "source_ticker": company.get("ticker_root"),
        })
        time.sleep(INTER_ARTICLE_SLEEP)
    log.info("%s: kept %d articles", ticker, len(out))
    return out


def run(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Ingest one full pass. Returns the number of new article rows inserted."""
    logconfig.silence_third_party()
    day = target_date or _today_sp()
    companies = load_companies_from_db()
    if not companies:
        log.error("companies table is empty — run scripts/fetch_top_companies.py")
        return 0

    workers = _env_workers()
    total = len(companies)
    log.info("Target day: %s | %d companies | %d worker(s)",
             day, total, workers)
    if progress:
        progress("ingest", 0, total)

    inserted = 0
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_company, c, day): c for c in companies}
        # Threads return article dicts; the main thread owns the DB connection
        # so we don't have to share psycopg connections across workers.
        with db.connect() as conn:
            for fut in as_completed(futures):
                company = futures[fut]
                ticker = company.get("ticker", "?")
                done += 1
                try:
                    arts = fut.result()
                except Exception as e:
                    log.warning("%s crashed: %s", ticker, e)
                    if progress:
                        progress("ingest", done, total)
                    continue
                for art in arts:
                    site = publisher_from_url(conn, art["url"])
                    if db.upsert_article(
                        conn,
                        url=art["url"],
                        title=art["title"],
                        text=art["text"],
                        author=art["author"],
                        site=site,
                        hostname=art["hostname"],
                        published_at=art["published_at"],
                        source_ticker=art["source_ticker"],
                    ):
                        inserted += 1
                if progress:
                    progress("ingest", done, total)
            conn.commit()

    log.info("Ingest complete — %d new article(s) inserted", inserted)
    return inserted


if __name__ == "__main__":
    # Thin shim so ``python -m finance_news.ingest`` keeps working for cron
    # and any external caller.
    from finance_news.pipeline import run_ingest
    run_ingest()
