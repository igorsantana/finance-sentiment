"""Daily ingest — per-publisher discovery + CompanyMatcher fold.

The previous per-company Google News + DuckDuckGo loop was retired in
favour of fanning out across a curated set of pt-BR finance publishers
once per run (see ``finance_news.net.discovery``). Two architectural
wins:

* No third-party search-index dependency. Everything we hit is a
  direct publisher endpoint (WordPress REST, RSS, or the publisher's
  own listing page). No Google News URL decoding, no DDG rate limits.
* Per-publisher cost is constant in the number of tracked companies.
  Adding a 1 000th company adds matcher CPU, not HTTP calls.

Pipeline shape (per run):

    discovery.discover_articles(day)   # ~25 adapters (sitemaps + WP + RSS + HTML)
        ↓
    pre-match (title + excerpt)        # drop articles that don't mention
                                       #   any tracked company
        ↓
    GDELT fallback (optional)          # one BR-pt query per company still at 0 hits
        ↓
    fetch bodies (ThreadPoolExecutor)
        ↓
    SP-day check + Portuguese gate (in fetch._extract)
        ↓
    upsert_article(... source_ticker = first matched ticker_root)

The downstream extract stage (``finance_news.extract``) re-runs the
matcher over the full body and authoritatively populates
``articles.matched_tickers``. ``source_ticker`` here is just a
backwards-compatibility breadcrumb for "what surfaced this article".

Logs are deliberately verbose: each stage emits an INFO line on entry
and exit, the discovery module reports each publisher's result as it
completes, and the body-fetch loop streams a percent-progress line every
~10 % of the way through. The FastAPI SSE channel forwards every INFO
record straight to the web client's Logs panel, so the operator sees
the run move in real time.

CVM ingest (``run_cvm_ingest``) remains a separate flow — it works off
regulatory filings, not news, and is orthogonal to publisher discovery.
"""
from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ProgressFn = Callable[[str, int, int], None]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news import logconfig
from finance_news.net import discovery
from finance_news.net.fetch import fetch_article_direct
from finance_news.net import gdelt as gdelt_discovery
from finance_news.nlp.companies import (
    CompanyMatcher,
    load_companies_from_db,
    to_company,
)
from finance_news.store import db
from finance_news.store.publishers import publisher_from_url

log = logging.getLogger("ingest")

SP_TZ = ZoneInfo("America/Sao_Paulo")

# Soft pacing for body fetches. Each publisher sees roughly
# (n_articles_for_that_publisher / WORKERS) requests in flight at once;
# at WORKERS=4 and the typical ~30 articles/day per publisher that's a
# trickle. The sleep here is just so we never hammer a single host
# with a tight loop.
INTER_FETCH_SLEEP_S = 0.25

# GDELT per-company fallback for tickers with zero publisher-listing hits.
# Set GDELT_FALLBACK=0 to disable. GDELT_MAX_WORKERS caps concurrent API calls.
GDELT_FALLBACK_ENABLED = os.environ.get("GDELT_FALLBACK", "1").strip().lower() not in (
    "0", "false", "no", "off",
)

# strict | finance_hosts | all_listed
INGEST_PREMATCH_MODE = os.environ.get("INGEST_PREMATCH_MODE", "finance_hosts").strip().lower()

_FINANCE_KW_RE = re.compile(
    r"\b(bolsa|b3|ibovespa|ações|acao|acoes|dividendos|mercado|"
    r"financeir|economia|investiment|ticker|cvm|bovespa)\b",
    re.IGNORECASE,
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default


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


# ---------- pre-match stage ----------

def _prematch(
    article: discovery.DiscoveredArticle,
    matcher: CompanyMatcher,
) -> list[str]:
    """Run the matcher over ``title + " " + excerpt`` and return a list
    of matched ``ticker_root``s (possibly empty).

    This is a coarse triage so we don't waste a body fetch on articles
    that clearly don't mention any tracked company. The downstream
    extract stage re-runs the matcher over the full body — anything that
    only surfaces a company in paragraph 4 will be picked up there, but
    it'll only be picked up *if* the article body was stored, which
    means the title-or-excerpt match already passed.

    Without a spaCy ``doc``, ambiguous aliases (``vale``, ``rumo``, …)
    are rejected by the context gate inside ``CompanyMatcher.match`` —
    that's the conservative behaviour we want for headline-only
    matching.
    """
    text_parts = [p for p in (article.title, article.excerpt) if p]
    if not text_parts:
        return []
    text = " ".join(text_parts)
    matches, _emb = matcher.match(text, title=article.title or "")
    return [m.ticker_root for m in matches]


def _title_has_finance_keyword(title: str) -> bool:
    return bool(_FINANCE_KW_RE.search(title or ""))


def _should_fetch_candidate(
    article: discovery.DiscoveredArticle,
    matcher: CompanyMatcher,
    allow_hosts: set[str],
) -> tuple[bool, list[str]]:
    """Decide whether to body-fetch ``article``; return (fetch?, matched_roots)."""
    roots = _prematch(article, matcher)
    mode = INGEST_PREMATCH_MODE
    if mode == "all_listed":
        return True, roots
    if roots:
        return True, roots
    if mode == "strict":
        return False, []
    host = article.publisher_host.lower().removeprefix("www.")
    if mode == "finance_hosts" and host in allow_hosts:
        return True, roots
    if mode == "finance_hosts" and _title_has_finance_keyword(article.title):
        return True, roots
    return False, roots


# ---------- body fetch stage ----------

def _fetch_and_pack(
    article: discovery.DiscoveredArticle,
    matched_roots: list[str],
    day: date,
) -> Optional[dict[str, Any]]:
    """Fetch the article body and assemble the row we'll upsert.

    Returns ``None`` (and the caller drops the article) when:
    * the body fetch fails (network / 4xx / 5xx),
    * trafilatura can't extract usable text,
    * the article is not in Portuguese,
    * the published date doesn't fall in the target SP day.

    The published-at preferred source is the listing-stage timestamp
    (``article.published_at``) because the publisher's listing carries
    the canonical publication time; we fall back to whatever
    trafilatura parsed out of the article HTML when the listing didn't
    expose a date.
    """
    try:
        art = fetch_article_direct(article.url)
    except Exception as e:
        log.debug("fetch failed %s: %s", article.url, e)
        return None
    if art is None:
        return None
    pub = article.published_at or art.published
    if pub is None:
        return None
    pub_aware = pub if pub.tzinfo else pub.replace(tzinfo=ZoneInfo("UTC"))
    if pub_aware.astimezone(SP_TZ).date() != day:
        return None
    return {
        "url": art.url,
        "title": art.title or article.title,
        "text": art.text,
        "author": art.author,
        "hostname": _host_key(art.url),
        "published_at": pub_aware,
        # Pre-match said this URL mentions ≥1 tracked company; pick the
        # first as a backwards-compatibility breadcrumb for the existing
        # ``source_ticker`` column. The full set lands in
        # ``matched_tickers`` after the extract stage runs.
        "source_ticker": matched_roots[0] if matched_roots else None,
    }


# ---------- driver ----------

def run(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Ingest one full pass. Returns the number of new article rows inserted."""
    logconfig.silence_third_party()
    day = target_date or _today_sp()

    company_rows = load_companies_from_db()
    if not company_rows:
        log.error("companies table is empty — run scripts/companies/fetch_top.py")
        return 0

    matcher = CompanyMatcher([to_company(c) for c in company_rows])
    workers = _env_workers()
    allow_hosts = discovery.publisher_host_allowlist()
    try:
        with db.connect() as conn:
            for h in db.fetch_publisher_hostnames(conn):
                allow_hosts.add(h.lower().removeprefix("www."))
    except Exception as e:
        log.debug("publisher allowlist from DB skipped: %s", e)
    log.info(
        "Starting ingest — date=%s, %d companies, %d worker(s), prematch=%s",
        day, len(company_rows), workers, INGEST_PREMATCH_MODE,
    )

    # --- Stage 1: discovery ----------------------------------------------
    # The TopBar in the web UI only knows the "ingest" / "extract" /
    # "summarize" stage IDs, so we report discovery progress as ingest
    # progress (the operator sees the bar move during the listing fanout
    # instead of staring at 0 % for ~10 s).
    adapter_count = len(discovery.default_adapters())
    if progress:
        progress("ingest", 0, adapter_count)

    def _on_adapter_done(completed: int, total: int) -> None:
        if progress:
            progress("ingest", completed, total)

    t_disc = time.perf_counter()
    discovered, adapter_results = discovery.discover_articles(
        day, on_progress=_on_adapter_done,
    )
    disc_s = time.perf_counter() - t_disc
    n_listed_raw = sum(len(r.articles) for r in adapter_results)
    n_failed = sum(1 for r in adapter_results if r.error)
    n_ok = len(adapter_results) - n_failed
    n_listed = len(discovered)
    log.info(
        "Discovery done — %d article(s) listed, %d unique after dedup, %.2fs · "
        "%d publisher(s) OK, %d with errors",
        n_listed_raw, n_listed, disc_s, n_ok, n_failed,
    )
    log.info("Funnel — listed: %d", n_listed)

    # --- Stage 2: pre-match / fetch gate ---------------------------------
    log.info(
        "Pre-matching %d article(s) (mode=%s)…",
        n_listed, INGEST_PREMATCH_MODE,
    )
    candidates: list[tuple[discovery.DiscoveredArticle, list[str]]] = []
    for art in discovered:
        fetch_ok, roots = _should_fetch_candidate(art, matcher, allow_hosts)
        if fetch_ok:
            candidates.append((art, roots))
    n_prematch = len(candidates)
    log.info(
        "Pre-match done — %d/%d article(s) selected for body fetch",
        n_prematch, n_listed,
    )
    log.info("Funnel — listed: %d → pre-matched: %d", n_listed, n_prematch)

    # --- Stage 2b: GDELT fallback for companies with zero listing hits ------
    covered_roots: set[str] = set()
    for _art, roots in candidates:
        covered_roots.update(roots)
    uncovered = [
        c for c in company_rows
        if c.get("ticker_root") and c["ticker_root"] not in covered_roots
    ]
    if uncovered and GDELT_FALLBACK_ENABLED:
        log.info(
            "GDELT fallback — %d company(ies) had no publisher-listing hits",
            len(uncovered),
        )
        seen_urls = {art.url for art, _ in candidates}
        gdelt_added = 0

        # Phase 1: bulk day queries (broad + keywords; caps at 250 each).
        bulk = gdelt_discovery.discover_br_day_bulk_all(day)
        log.info("GDELT bulk — %d article(s), pre-matching…", len(bulk))
        for art in bulk:
            if art.url in seen_urls:
                continue
            fetch_ok, roots = _should_fetch_candidate(art, matcher, allow_hosts)
            if fetch_ok:
                seen_urls.add(art.url)
                candidates.append((art, roots))
                gdelt_added += 1

        covered_roots = set()
        for _art, roots in candidates:
            covered_roots.update(roots)
        still_uncovered = [
            c for c in company_rows
            if c.get("ticker_root") and c["ticker_root"] not in covered_roots
        ]

        # Phase 2: optional per-company queries (slow — off by default).
        max_per_company = _env_int("GDELT_MAX_PER_COMPANY", 0)
        if still_uncovered and max_per_company > 0:
            batch = still_uncovered[:max_per_company]
            log.info(
                "GDELT per-company — %d of %d still uncovered "
                "(GDELT_MAX_PER_COMPANY=%d)",
                len(batch), len(still_uncovered), max_per_company,
            )
            gdelt_articles, gd_ok, gd_fail = gdelt_discovery.discover_for_companies(
                batch,
                day,
                max_workers=_env_int(
                    "GDELT_MAX_WORKERS", gdelt_discovery.GDELT_MAX_WORKERS,
                ),
            )
            log.info(
                "GDELT per-company done — %d article(s), %d OK / %d failed",
                len(gdelt_articles), gd_ok, gd_fail,
            )
            for art in gdelt_articles:
                if art.url in seen_urls:
                    continue
                fetch_ok, roots = _should_fetch_candidate(art, matcher, allow_hosts)
                if fetch_ok:
                    seen_urls.add(art.url)
                    candidates.append((art, roots))
                    gdelt_added += 1
        elif still_uncovered:
            log.info(
                "GDELT per-company skipped — %d still uncovered "
                "(set GDELT_MAX_PER_COMPANY>0 to enable; bulk-only is default)",
                len(still_uncovered),
            )

        if gdelt_added:
            log.info("GDELT fallback added %d new pre-matched candidate(s)", gdelt_added)
        else:
            log.info("GDELT fallback — no new pre-matched candidates")
    elif uncovered and not GDELT_FALLBACK_ENABLED:
        log.info(
            "GDELT fallback disabled — %d company(ies) still without listing hits",
            len(uncovered),
        )

    n_candidates = len(candidates)
    if not candidates:
        log.info("Nothing to fetch — exiting.")
        log.info(
            "Funnel — listed: %d → pre-matched: %d → fetched: 0 → inserted: 0",
            n_listed, n_prematch,
        )
        if progress:
            progress("ingest", 1, 1)
        return 0

    # --- Stage 3: body fetch ---------------------------------------------
    total = n_candidates
    log.info("Fetching article bodies — %d candidate(s) with %d worker(s)…",
             total, workers)
    if progress:
        progress("ingest", 0, total)

    # Stream a percent-progress log roughly every 10 % of the way through.
    # Floor at 5 so very small runs still emit at least a couple of lines.
    progress_log_every = max(5, total // 10)

    inserted = 0
    done = 0
    rows_to_write: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_fetch_and_pack, art, roots, day): art
            for art, roots in candidates
        }
        for fut in as_completed(futures):
            art = futures[fut]
            done += 1
            try:
                row = fut.result()
            except Exception as e:
                log.debug("worker crashed for %s: %s", art.url, e)
                row = None
            if row is not None:
                rows_to_write.append(row)
            if progress:
                progress("ingest", done, total)
            if done % progress_log_every == 0 and done < total:
                pct = round(done * 100 / total)
                log.info(
                    "  %d/%d (%d%%) processed · %d with text so far",
                    done, total, pct, len(rows_to_write),
                )
            time.sleep(INTER_FETCH_SLEEP_S)

    n_fetched = len(rows_to_write)
    log.info(
        "Body fetch done — %d/%d candidate(s) yielded text",
        n_fetched, total,
    )
    log.info(
        "Funnel — listed: %d → pre-matched: %d → fetched: %d",
        n_listed, n_prematch, n_fetched,
    )

    # --- Stage 4: persist ------------------------------------------------
    # Single-thread the DB write so we don't share connections between
    # workers; all the heavy lifting is done.
    if rows_to_write:
        log.info("Persisting %d article(s) to database…", len(rows_to_write))
    with db.connect() as conn:
        for row in rows_to_write:
            site = publisher_from_url(conn, row["url"])
            if db.upsert_article(
                conn,
                url=row["url"],
                title=row["title"],
                text=row["text"],
                author=row["author"],
                site=site,
                hostname=row["hostname"],
                published_at=row["published_at"],
                source_ticker=row["source_ticker"],
            ):
                inserted += 1
        conn.commit()

    duplicates = n_fetched - inserted
    log.info(
        "Funnel — listed: %d → pre-matched: %d → fetched: %d → inserted: %d",
        n_listed, n_prematch, n_fetched, inserted,
    )
    if duplicates > 0:
        log.info(
            "Ingest complete — %d new article(s) inserted, %d duplicate(s) skipped",
            inserted, duplicates,
        )
    else:
        log.info("Ingest complete — %d new article(s) inserted", inserted)
    return inserted


# ---------- CVM ingest (unchanged) ----------

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
                time.sleep(INTER_FETCH_SLEEP_S)
                if progress:
                    progress("cvm", i + 1, len(pairs))
                continue
            if art is None:
                time.sleep(INTER_FETCH_SLEEP_S)
                if progress:
                    progress("cvm", i + 1, len(pairs))
                continue

            pub = cand.published or art.published
            if pub is None:
                time.sleep(INTER_FETCH_SLEEP_S)
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

            time.sleep(INTER_FETCH_SLEEP_S)
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
