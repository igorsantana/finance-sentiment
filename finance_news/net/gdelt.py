"""GDELT 2.0 DOC API — per-company fallback for long-tail B3 coverage.

After the per-publisher listing fan-out, some tracked companies still
have zero pre-matches. This module fires one GDELT ``ArtList`` query per
such company, restricted to Brazilian Portuguese sources, and returns
``DiscoveredArticle`` rows for the ingest pipeline.

Rate limits
-----------
GDELT rate-limits the DOC API during peak load. We treat the fallback as
best-effort: concurrency capped at ``GDELT_MAX_WORKERS`` (default 2),
``GDELT_SLEEP_S`` between requests, exponential backoff on HTTP 429.
Failures for individual companies never abort the ingest run.

Query shape
-----------
``sourcelang:portuguese sourcecountry:BR ("Company Name" OR TICKER)``

Backfill
--------
The same surface works for historical dates via ``startdatetime`` /
``enddatetime`` (UTC, YYYYMMDDHHMMSS).
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo
import requests

from finance_news.net.discovery import DiscoveredArticle

log = logging.getLogger("gdelt")

SP_TZ = ZoneInfo("America/Sao_Paulo")
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_RECORDS = 250
GDELT_MAX_WORKERS = 2
GDELT_SLEEP_S = 0.55
GDELT_TIMEOUT_S = 45
GDELT_MAX_RETRIES = 3
# Log ingest progress every N completed per-company queries (when enabled).
GDELT_PROGRESS_INTERVAL = 25


@dataclass
class GdeltCompanyQuery:
    ticker_root: str
    query_terms: list[str]


def _sp_day_bounds_utc(day: date) -> tuple[str, str]:
    """Return GDELT ``startdatetime`` / ``enddatetime`` for one SP calendar day."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=SP_TZ)
    end = start + timedelta(days=1)
    return (
        start.astimezone(ZoneInfo("UTC")).strftime("%Y%m%d%H%M%S"),
        end.astimezone(ZoneInfo("UTC")).strftime("%Y%m%d%H%M%S"),
    )


def build_company_query(company: dict[str, Any]) -> Optional[GdeltCompanyQuery]:
    """Build GDELT query terms from a ``companies`` table row."""
    root = (company.get("ticker_root") or "").strip().upper()
    if not root:
        return None
    terms: list[str] = []
    short = (company.get("short_name") or "").strip()
    long_ = (company.get("long_name") or "").strip()
    if short and len(short) >= 3:
        terms.append(f'"{short}"')
    if long_ and long_.lower() != short.lower() and len(long_) >= 4:
        terms.append(f'"{long_}"')
    ticker = (company.get("ticker") or "").strip().upper()
    if ticker and len(ticker) >= 4:
        terms.append(ticker)
    if not terms:
        terms.append(root)
    return GdeltCompanyQuery(ticker_root=root, query_terms=terms)


def _gdelt_query_string(q: GdeltCompanyQuery) -> str:
    term_clause = " OR ".join(q.query_terms)
    return (
        f"sourcelang:portuguese sourcecountry:BR ({term_clause})"
    )


def _parse_seendate(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(raw.strip())
    except (ValueError, TypeError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def _fetch_artlist(
    q: GdeltCompanyQuery,
    day: date,
) -> tuple[list[DiscoveredArticle], Optional[str]]:
    """One GDELT ArtList request. Returns (articles, error)."""
    start_dt, end_dt = _sp_day_bounds_utc(day)
    params = {
        "query": _gdelt_query_string(q),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(GDELT_MAX_RECORDS),
        "startdatetime": start_dt,
        "enddatetime": end_dt,
    }
    last_err: Optional[str] = None
    for attempt in range(GDELT_MAX_RETRIES):
        try:
            r = requests.get(
                GDELT_DOC_URL, params=params, timeout=GDELT_TIMEOUT_S,
            )
        except Exception as e:
            last_err = repr(e)
            time.sleep(GDELT_SLEEP_S * (attempt + 1))
            continue
        if r.status_code == 429:
            last_err = "HTTP 429 rate limited"
            time.sleep(GDELT_SLEEP_S * (2 ** attempt))
            continue
        if r.status_code != 200:
            last_err = f"HTTP {r.status_code}"
            break
        try:
            payload = r.json()
        except Exception as e:
            last_err = f"JSON: {e}"
            break
        articles = _articles_from_payload(payload, q, day)
        return articles, None
    return [], last_err


def _articles_from_payload(
    payload: dict[str, Any],
    q: GdeltCompanyQuery,
    day: date,
) -> list[DiscoveredArticle]:
    rows = payload.get("articles") or []
    out: list[DiscoveredArticle] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or "").strip()
        if not url or url in seen:
            continue
        pub = _parse_seendate(row.get("seendate"))
        if pub is None:
            continue
        if pub.astimezone(SP_TZ).date() != day:
            continue
        title = (row.get("title") or "").strip()
        domain = (row.get("domain") or "gdelt").strip()
        seen.add(url)
        out.append(DiscoveredArticle(
            url=url,
            title=title,
            excerpt="",
            publisher=f"GDELT ({domain})",
            publisher_host=domain.lower(),
            published_at=pub,
        ))
    return out


def discover_for_companies(
    companies: list[dict[str, Any]],
    day: date,
    *,
    max_workers: int = GDELT_MAX_WORKERS,
    progress_interval: int = GDELT_PROGRESS_INTERVAL,
) -> tuple[list[DiscoveredArticle], int, int]:
    """Query GDELT for each company row. Returns (articles, ok_count, fail_count)."""
    queries: list[GdeltCompanyQuery] = []
    for c in companies:
        q = build_company_query(c)
        if q:
            queries.append(q)
    if not queries:
        return [], 0, 0

    total = len(queries)
    log.info(
        "GDELT per-company — querying %d company(ies) with %d worker(s) "
        "(~%.0f–%.0f min at 2 workers if API is slow)…",
        total,
        max_workers,
        total * GDELT_SLEEP_S / max(1, max_workers) / 60,
        total * GDELT_TIMEOUT_S / max(1, max_workers) / 60,
    )
    all_articles: list[DiscoveredArticle] = []
    ok_n = fail_n = 0
    done = 0
    workers = max(1, min(max_workers, len(queries)))
    interval = max(1, progress_interval)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_artlist, q, day): q for q in queries}
        for fut in as_completed(futs):
            q = futs[fut]
            time.sleep(GDELT_SLEEP_S)
            try:
                articles, err = fut.result()
            except Exception as e:
                articles, err = [], repr(e)
            done += 1
            if err:
                fail_n += 1
                log.debug("GDELT %s: %s", q.ticker_root, err)
            else:
                ok_n += 1
                if articles:
                    log.info(
                        "GDELT %s — %d article(s)",
                        q.ticker_root, len(articles),
                    )
                all_articles.extend(articles)
            if done == 1 or done % interval == 0 or done == total:
                log.info(
                    "GDELT per-company progress — %d/%d done "
                    "(%d OK, %d failed, %d article(s) collected)",
                    done, total, ok_n, fail_n, len(all_articles),
                )

    return all_articles, ok_n, fail_n


def discover_br_day_bulk(
    day: date,
    *,
    extra_keyword: str = "",
    max_records: int = GDELT_MAX_RECORDS,
) -> list[DiscoveredArticle]:
    """Single broad GDELT query for all BR Portuguese articles on ``day``.

    Used by the CC-News backfill script as a lighter-weight alternative
    when WARC files are unavailable. Capped at ``max_records`` (250).
    """
    start_dt, end_dt = _sp_day_bounds_utc(day)
    query = "sourcelang:portuguese sourcecountry:BR"
    if extra_keyword:
        query = f'{query} "{extra_keyword}"'
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(min(max_records, GDELT_MAX_RECORDS)),
        "startdatetime": start_dt,
        "enddatetime": end_dt,
    }
    log.info("GDELT bulk ArtList request for %s (BR Portuguese)…", day.isoformat())
    try:
        r = requests.get(GDELT_DOC_URL, params=params, timeout=GDELT_TIMEOUT_S)
        if r.status_code != 200:
            log.warning("GDELT bulk day query: HTTP %d", r.status_code)
            return []
        payload = r.json()
    except Exception as e:
        log.warning("GDELT bulk day query failed: %s", e)
        return []
    dummy = GdeltCompanyQuery(ticker_root="", query_terms=[])
    return _articles_from_payload(payload, dummy, day)


# Extra bulk keyword queries (each capped at 250 records).
GDELT_BULK_KEYWORDS = ("", "ações", "bolsa OR B3", "dividendos")


def discover_br_day_bulk_all(day: date) -> list[DiscoveredArticle]:
    """Run broad + keyword GDELT bulk queries; dedupe by URL."""
    seen: set[str] = set()
    out: list[DiscoveredArticle] = []
    keywords = os.environ.get("GDELT_BULK_KEYWORDS", "")
    if keywords.strip():
        kw_list = [k.strip() for k in keywords.split("|")]
    else:
        kw_list = list(GDELT_BULK_KEYWORDS)
    for kw in kw_list:
        batch = discover_br_day_bulk(day, extra_keyword=kw)
        for art in batch:
            if art.url not in seen:
                seen.add(art.url)
                out.append(art)
        if kw:
            log.info("GDELT bulk keyword %r — %d new article(s) this batch", kw, len(batch))
    return out
