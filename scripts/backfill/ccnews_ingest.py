#!/usr/bin/env python3
"""Backfill articles for a past SP-day (out-of-band; does not replace daily ingest).

Two sources (pick with ``--source``):

* ``ccnews`` — stream Common Crawl News WARC files for the target date,
  filter to hostnames in the ``publishers`` table, extract HTML with
  trafilatura, pre-match, and upsert. Heavy (downloads WARC segments) but
  reaches the full CC-NEWS archive.

* ``gdelt`` — one broad GDELT DOC API query (BR + Portuguese, max 250
  articles) for the day, then pre-match. Fast and free; good for recent
  gaps when CC-NEWS WARC listing is slow.

* ``both`` — GDELT first, then CC-NEWS for anything still missing.

Usage:
    python scripts/backfill/ccnews_ingest.py --date 2026-05-10
    python scripts/backfill/ccnews_ingest.py --date 2026-05-10 --source gdelt
    make backfill DATE=2026-05-10
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news import logconfig
from finance_news.ingest import _fetch_and_pack, _host_key, _prematch, _today_sp
from finance_news.net import gdelt as gdelt_mod
from finance_news.net.discovery import DiscoveredArticle, dedup_articles
from finance_news.nlp.companies import CompanyMatcher, load_companies_from_db, to_company
from finance_news.store import db
from finance_news.store.publishers import publisher_from_url

log = logging.getLogger("backfill")
SP_TZ = ZoneInfo("America/Sao_Paulo")
CCNEWS_INDEX = "https://data.commoncrawl.org/crawl-data/CC-NEWS"
MAX_WARC_FILES = 6
MAX_ARTICLES_PER_WARC = 400


def _resolve_day(arg: Optional[str]) -> date:
    if arg:
        return date.fromisoformat(arg)
    return _today_sp()


def _load_publisher_hosts(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT hostname FROM publishers")
        rows = cur.fetchall()
    hosts: set[str] = set()
    for r in rows:
        h = (r["hostname"] or "").lower().strip()
        if h:
            hosts.add(h)
            if h.startswith("www."):
                hosts.add(h[4:])
    return hosts


def _host_matches(url: str, allowed: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host in allowed


def _list_ccnews_warc_urls(day: date) -> list[str]:
    import requests

    y, m = day.year, f"{day.month:02d}"
    index_url = f"{CCNEWS_INDEX}/{y}/{m}/"
    try:
        r = requests.get(index_url, timeout=60, headers={"User-Agent": "finance-news-backfill/1.0"})
        r.raise_for_status()
    except Exception as e:
        log.warning("CC-NEWS index %s failed: %s", index_url, e)
        return []
    prefix = day.strftime("%Y%m%d")
    pat = re.compile(r'href="(CC-NEWS-(\d{14})-\d+\.warc\.gz)"')
    urls: list[str] = []
    for m in pat.finditer(r.text):
        stamp = m.group(2)
        if stamp[:8] == prefix:
            urls.append(index_url + m.group(1))
    return urls[:MAX_WARC_FILES]


def _discover_from_ccnews(day: date, allowed_hosts: set[str]) -> list[DiscoveredArticle]:
    try:
        from warcio.archiveiterator import ArchiveIterator
        import requests
        import trafilatura
    except ImportError as e:
        log.error("CC-NEWS backfill requires warcio and trafilatura: %s", e)
        return []

    warc_urls = _list_ccnews_warc_urls(day)
    if not warc_urls:
        log.warning("No CC-NEWS WARC files found for %s", day)
        return []

    log.info("CC-NEWS — streaming %d WARC file(s) for %s", len(warc_urls), day)
    articles: list[DiscoveredArticle] = []
    seen: set[str] = set()

    for warc_url in warc_urls:
        if len(articles) >= MAX_WARC_FILES * MAX_ARTICLES_PER_WARC:
            break
        log.info("  fetching %s", warc_url.split("/")[-1])
        try:
            resp = requests.get(
                warc_url, stream=True, timeout=300,
                headers={"User-Agent": "finance-news-backfill/1.0"},
            )
            resp.raise_for_status()
        except Exception as e:
            log.warning("  WARC download failed: %s", e)
            continue

        n_file = 0
        for record in ArchiveIterator(resp.raw, arc2warc=True):
            if record.rec_type != "response":
                continue
            target = record.rec_headers.get_header("WARC-Target-URI")
            if not target or target in seen:
                continue
            if not _host_matches(target, allowed_hosts):
                continue
            try:
                html_bytes = record.content_stream().read()
            except Exception:
                continue
            if not html_bytes or len(html_bytes) < 500:
                continue
            try:
                text = trafilatura.extract(
                    html_bytes, url=target, include_comments=False,
                    favor_precision=True,
                )
            except Exception:
                text = None
            if not text or len(text) < 200:
                continue
            title = ""
            try:
                meta = trafilatura.extract_metadata(html_bytes, default_url=target)
                if meta and meta.title:
                    title = meta.title
            except Exception:
                pass
            pub_dt: Optional[datetime] = None
            warc_date = record.rec_headers.get_header("WARC-Date")
            if warc_date:
                try:
                    pub_dt = datetime.fromisoformat(
                        warc_date.replace("Z", "+00:00"),
                    )
                except ValueError:
                    pub_dt = None
            if pub_dt and pub_dt.astimezone(SP_TZ).date() != day:
                continue
            host = _host_key(target)
            seen.add(target)
            articles.append(DiscoveredArticle(
                url=target,
                title=title,
                excerpt=text[:280],
                publisher=host,
                publisher_host=host,
                published_at=pub_dt,
            ))
            n_file += 1
            if n_file >= MAX_ARTICLES_PER_WARC:
                break
        log.info("  kept %d article(s) from segment", n_file)

    return dedup_articles(articles)


def _run_backfill(day: date, source: str) -> int:
    logconfig.silence_third_party()
    company_rows = load_companies_from_db()
    if not company_rows:
        log.error("companies table is empty")
        return 0
    matcher = CompanyMatcher([to_company(c) for c in company_rows])

    discovered: list[DiscoveredArticle] = []
    if source in ("gdelt", "both"):
        log.info("GDELT bulk backfill for %s…", day)
        discovered.extend(gdelt_mod.discover_br_day_bulk(day))
    if source in ("ccnews", "both"):
        with db.connect() as conn:
            hosts = _load_publisher_hosts(conn)
        discovered.extend(_discover_from_ccnews(day, hosts))

    discovered = dedup_articles(discovered)
    log.info("Backfill listed %d unique URL(s)", len(discovered))

    candidates: list[tuple[DiscoveredArticle, list[str]]] = []
    for art in discovered:
        roots = _prematch(art, matcher)
        if roots:
            candidates.append((art, roots))
    log.info("Pre-match: %d/%d URLs mention tracked companies", len(candidates), len(discovered))
    if not candidates:
        return 0

    inserted = 0
    with db.connect() as conn:
        for art, roots in candidates:
            row = _fetch_and_pack(art, roots, day)
            if row is None:
                time.sleep(0.15)
                continue
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
            time.sleep(0.15)
        conn.commit()

    log.info("Backfill complete — %d new article(s) inserted for %s", inserted, day)
    return inserted


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Backfill articles for one SP day")
    p.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    p.add_argument(
        "--source",
        choices=("ccnews", "gdelt", "both"),
        default="both",
        help="ccnews=WARC stream, gdelt=API bulk, both=try GDELT then CC-NEWS",
    )
    args = p.parse_args(argv)
    day = _resolve_day(args.date)
    _run_backfill(day, args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
