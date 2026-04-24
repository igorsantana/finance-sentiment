"""Stage 1: discover candidates (sites + companies), fetch articles, write JSONL."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import tldextract

from . import discovery, fetch, logconfig  # noqa: F401


def _env_workers(default: int = 4) -> int:
    raw = os.environ.get("WORKERS")
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default

log = logging.getLogger("ingest")

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_CSV = ROOT / "sources.csv"
COMPANIES_CSV = ROOT / "data" / "companies.csv"
OUT_PATH = ROOT / "data" / "raw" / "raw_articles.jsonl"

SP_TZ = ZoneInfo("America/Sao_Paulo")
PER_SITE_ARTICLE_CAP = 25
PER_COMPANY_ARTICLE_CAP = 8
INTER_ARTICLE_SLEEP = 1.0


def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [
        {"name": r["Nome"], "url": r["Link para o Site"].strip()}
        for r in rows
        if r.get("Link para o Site")
    ]


def read_companies(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _today_sp() -> date:
    return datetime.now(SP_TZ).date()


# --- Publisher resolution (for Google News-sourced articles) -----------------
# Fallbacks for common PT-BR publishers that may surface via Google News but
# aren't in sources.csv. Keys are hostnames minus a leading "www.".
_KNOWN_PUBLISHERS = {
    "g1.globo.com": "G1",
    "uol.com.br": "UOL",
    "economia.uol.com.br": "UOL Economia",
    "cnnbrasil.com.br": "CNN Brasil",
    "r7.com": "R7",
    "terra.com.br": "Terra Economia",
    "noticias.uol.com.br": "UOL",
    "oantagonista.com.br": "O Antagonista",
    "istoe.com.br": "IstoÉ",
    "valorinveste.globo.com": "Valor Investe",
    "extra.globo.com": "Extra",
    "ge.globo.com": "Globo Esporte",
}


def _host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def build_publisher_map(sources: list[dict]) -> dict[str, str]:
    """hostname → display name, derived from sources.csv + known publishers."""
    m: dict[str, str] = dict(_KNOWN_PUBLISHERS)
    for s in sources:
        key = _host_key(s["url"])
        if key:
            m[key] = s["name"]
    return m


def publisher_from_url(url: str, pub_map: dict[str, str]) -> str:
    """Look up the display name for an article URL.

    Matches progressively shorter hostnames (strip leftmost subdomain labels)
    so that e.g. `m.valor.globo.com` still resolves to `valor.globo.com`.
    Falls back to the registered-domain label title-cased (via tldextract so
    compound suffixes like `.com.br` don't confuse the logic).
    """
    host = _host_key(url)
    if not host:
        return "Publicação desconhecida"
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in pub_map:
            return pub_map[candidate]
    ext = tldextract.extract(url)
    if ext.domain:
        return ext.domain.capitalize()
    return host.capitalize()


# --- Site stream -------------------------------------------------------------
def process_site(site: dict, today: date) -> list[dict]:
    name, url = site["name"], site["url"]
    log.info("==> site %s (%s)", name, url)
    try:
        mode, cands = discovery.discover(url)
    except Exception as e:
        log.debug("%s: discovery failed: %s", name, e)
        return []
    cands = discovery.filter_today(cands, today)[:PER_SITE_ARTICLE_CAP]
    log.info("%s: %d candidates after today-filter (mode=%s)", name, len(cands), mode)

    out: list[dict] = []
    for c in cands:
        try:
            art = fetch.fetch_article(c.url)
        except Exception as e:
            log.debug("%s: fetch failed %s: %s", name, c.url, e)
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
            "site": name,
            "source_kind": "site",
            "source_key": name,
            "url": art.url,
            "title": art.title or c.title,
            "author": art.author,
            "published": pub.isoformat(),
            "text": art.text,
        })
        time.sleep(INTER_ARTICLE_SLEEP)
    log.info("%s: kept %d articles", name, len(out))
    return out


# --- Company stream ----------------------------------------------------------
def _company_query(company: dict) -> str:
    """Build a Google News search query for a single company row.

    Preference order: short_name (tight match) → long_name → ticker. Using
    quoted short/long names keeps precision high; the ticker catches
    market-report articles that reference codes but not full names.
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


def process_company(company: dict, today: date, pub_map: dict[str, str]) -> list[dict]:
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
    log.info("%s: %d candidates after today-filter", ticker, len(cands))

    out: list[dict] = []
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
            "site": publisher_from_url(art.url, pub_map),
            "source_kind": "company",
            "source_key": ticker,
            "source_company_ticker": ticker,
            "source_company_name": short,
            "url": art.url,
            "title": art.title or c.title,
            "author": art.author,
            "published": pub.isoformat(),
            "text": art.text,
        })
        time.sleep(INTER_ARTICLE_SLEEP)
    log.info("%s: kept %d articles", ticker, len(out))
    return out


# --- CLI ---------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser()
    p.add_argument(
        "--mode", choices=("sites", "companies", "both"), default="both",
        help="Which discovery streams to run (default: both).",
    )
    p.add_argument("--only", help="Site-stream filter: substring match on site name.")
    p.add_argument("--ticker", help="Company-stream filter: exact ticker (e.g. PETR4).")
    p.add_argument("--sources", type=Path, default=SOURCES_CSV)
    p.add_argument("--companies-file", type=Path, default=COMPANIES_CSV,
                   dest="companies_file")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument(
        "--workers", type=int, default=None,
        help=(
            "Parallel worker threads for site/company tasks. "
            "Overrides WORKERS env var (default 4)."
        ),
    )
    p.add_argument(
        "--date",
        help="ISO date override (YYYY-MM-DD). Default: today in America/Sao_Paulo.",
    )
    args = p.parse_args(argv)

    target_day = date.fromisoformat(args.date) if args.date else _today_sp()
    log.info("Target day: %s  |  mode=%s", target_day, args.mode)

    # Build task list per mode.
    tasks: list[tuple[str, dict]] = []  # (kind, payload)

    # Publisher map is built from all sources (not just the filtered subset)
    # so company-stream articles resolve even when --only narrows the sites.
    all_sources = read_sources(args.sources) if args.sources.exists() else []
    pub_map = build_publisher_map(all_sources)

    if args.mode in ("sites", "both"):
        sites = all_sources
        if args.only:
            q = args.only.lower()
            sites = [s for s in sites if q in s["name"].lower()]
            if not sites:
                log.error("No site matched --only=%r", args.only)
                return 2
        tasks.extend(("site", s) for s in sites)

    if args.mode in ("companies", "both"):
        if not args.companies_file.exists():
            log.error(
                "Companies file missing: %s — run scripts/fetch_top_companies.py first.",
                args.companies_file,
            )
            return 2
        companies = read_companies(args.companies_file)
        if args.ticker:
            t = args.ticker.upper()
            companies = [c for c in companies if c["ticker"].upper() == t]
            if not companies:
                log.error("No company matched --ticker=%r", args.ticker)
                return 2
        tasks.extend(("company", c) for c in companies)

    if not tasks:
        log.error("No tasks to run.")
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # URL dedupe across re-runs AND across the two streams within this run.
    seen_urls: set[str] = set()
    if args.out.exists():
        with args.out.open(encoding="utf-8") as f:
            for line in f:
                try:
                    seen_urls.add(json.loads(line)["url"])
                except Exception:
                    pass

    workers = args.workers if args.workers and args.workers > 0 else _env_workers()
    log.info("Using %d ingest worker(s)", workers)
    written = 0
    with args.out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(
        max_workers=workers
    ) as ex:
        futures = {}
        for kind, payload in tasks:
            if kind == "site":
                fut = ex.submit(process_site, payload, target_day)
            else:
                fut = ex.submit(process_company, payload, target_day, pub_map)
            futures[fut] = (kind, payload)

        for fut in as_completed(futures):
            kind, payload = futures[fut]
            label = (
                payload.get("name") if kind == "site"
                else payload.get("ticker", "?")
            )
            try:
                articles = fut.result()
            except Exception as e:
                log.debug("%s:%s crashed: %s", kind, label, e)
                continue
            for art in articles:
                if art["url"] in seen_urls:
                    continue
                seen_urls.add(art["url"])
                f.write(json.dumps(art, ensure_ascii=False) + "\n")
                f.flush()
                written += 1

    log.info("Wrote %d new article(s) to %s", written, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
