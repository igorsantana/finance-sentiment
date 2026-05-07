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
import unicodedata
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
INTER_SOURCE_SLEEP = 1.0    # DDG: 4 workers × 1s ≤ 4 req/sec globally
_GNEWS_PREFIX = "https://news.google.com/"


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

    # Google News RSS candidates (wrapped URLs, need batch decode)
    try:
        gn_cands = discovery.google_news_feed(query)
    except Exception as e:
        log.debug("%s: google news failed: %s", ticker, e)
        gn_cands = []

    # DuckDuckGo News candidates (direct publisher URLs, no decode needed)
    ddg_cands: list[discovery.Candidate] = []
    try:
        ddg_cands = discovery.duckduckgo_news_feed(query)
        time.sleep(INTER_SOURCE_SLEEP)
    except Exception as e:
        log.debug("%s: ddg failed: %s", ticker, e)

    # Merge: DDG direct URLs first so dedup prefers them over wrapped GNews URLs
    all_cands = discovery.filter_today(ddg_cands + gn_cands, today)
    seen: set[str] = set()
    merged: list[discovery.Candidate] = []
    for c in all_cands:
        if c.url not in seen:
            seen.add(c.url)
            merged.append(c)
    merged = merged[:PER_COMPANY_ARTICLE_CAP]
    log.info("%s: %d merged candidates (ddg=%d gnews=%d)",
             ticker, len(merged), len(ddg_cands), len(gn_cands))
    if not merged:
        return []

    # Partition: GNews-wrapped URLs need one batch decode POST; DDG URLs are already real
    gnews_batch = [c for c in merged if c.url.startswith(_GNEWS_PREFIX)]
    direct_batch = [c for c in merged if not c.url.startswith(_GNEWS_PREFIX)]

    resolved_map: dict[str, str | None] = {}
    if gnews_batch:
        decoded = fetch.resolve_google_news_batch([c.url for c in gnews_batch])
        resolved_map = {c.url: r for c, r in zip(gnews_batch, decoded)}
        log.info("%s: %d/%d GNews URLs decoded",
                 ticker, sum(1 for v in resolved_map.values() if v), len(gnews_batch))

    # Unified (candidate, real_url) pairs — GNews first then DDG direct
    pairs: list[tuple[discovery.Candidate, str | None]] = (
        [(c, resolved_map[c.url]) for c in gnews_batch] +
        [(c, c.url) for c in direct_batch]
    )

    out: list[dict[str, Any]] = []
    for c, real_url in pairs:
        if real_url is None:
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        try:
            art = fetch.fetch_article_direct(real_url)
        except Exception as e:
            log.debug("%s: fetch failed %s: %s", ticker, real_url, e)
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        if art is None:
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        pub = c.published or art.published
        if pub is None:
            time.sleep(INTER_ARTICLE_SLEEP)
            continue
        pub_aware = pub if pub.tzinfo else pub.replace(tzinfo=ZoneInfo("UTC"))
        if pub_aware.astimezone(SP_TZ).date() != today:
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


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()


def run_cvm_ingest(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Fetch CVM Dados Abertos (Fatos Relevantes / Comunicados) and store articles.

    Single-threaded — CVM has tens of filings per day, not hundreds.
    Returns the number of new rows inserted.
    """
    logconfig.silence_third_party()
    from finance_news.net.cvm import cvm_candidates_for_date
    from finance_news.net.fetch import fetch_cvm_article
    from finance_news.store.publishers import publisher_from_url

    day = target_date or _today_sp()
    year = day.year

    raw_companies = load_companies_from_db()
    cvm_lookup: dict[str, str] = {}
    for c in raw_companies:
        for name in [c.get("long_name"), c.get("short_name")]:
            if name:
                cvm_lookup[_norm(name)] = c["ticker_root"]

    pairs = cvm_candidates_for_date(day, year)
    if progress:
        progress("cvm", 0, len(pairs))

    inserted = 0
    with db.connect() as conn:
        for i, (row, cand) in enumerate(pairs):
            try:
                art = fetch_cvm_article(cand.url, title=cand.title)
            except Exception as e:
                log.debug("CVM fetch failed %s: %s", cand.url, e)
                time.sleep(INTER_ARTICLE_SLEEP)
                if progress:
                    progress("cvm", i + 1, len(pairs))
                continue
            if art is None:
                time.sleep(INTER_ARTICLE_SLEEP)
                if progress:
                    progress("cvm", i + 1, len(pairs))
                continue

            pub = cand.published or art.published
            if pub is None:
                time.sleep(INTER_ARTICLE_SLEEP)
                if progress:
                    progress("cvm", i + 1, len(pairs))
                continue

            pub_aware = pub if pub.tzinfo else pub.replace(tzinfo=ZoneInfo("UTC"))
            source_ticker = cvm_lookup.get(_norm(row.get("Nome_Companhia", "")))
            site = publisher_from_url(conn, art.url)

            if db.upsert_article(
                conn,
                url=art.url,
                title=art.title or cand.title,
                text=art.text,
                author=art.author,
                site=site,
                hostname=_host_key(art.url),
                published_at=pub_aware,
                source_ticker=source_ticker,
            ):
                inserted += 1

            time.sleep(INTER_ARTICLE_SLEEP)
            if progress:
                progress("cvm", i + 1, len(pairs))

        conn.commit()

    log.info("CVM ingest complete — %d new article(s) inserted", inserted)
    return inserted


if __name__ == "__main__":
    # Thin shim so ``python -m finance_news.ingest`` keeps working for cron
    # and any external caller.
    from finance_news.pipeline import run_ingest
    run_ingest()
