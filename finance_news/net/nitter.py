"""X/Twitter discovery via Nitter mirrors (e.g. XCancel) — RSS search + accounts."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
import requests

from finance_news.net.discovery import (
    AdapterResult,
    DiscoveredArticle,
    HEADERS,
    HTTP_TIMEOUT_S,
    SP_TZ,
    _in_sp_day,
    _strip_html,
)
from finance_news.net.social_links import extract_http_urls, filter_news_urls

log = logging.getLogger("discovery")

DEFAULT_NITTER_BASE = "https://xcancel.com"
DEFAULT_SEARCH_QUERIES = [
    "B3 OR Ibovespa",
    "ações OR dividendos",
    "PETR4 OR VALE3 OR ITUB4",
]
DEFAULT_ACCOUNTS = (
    "InfoMoney",
    "BrazilJournal",
    "SunoResearch",
)

INTER_NITTER_SLEEP_S = 1.0


def _nitter_bases() -> list[str]:
    primary = os.environ.get("NITTER_BASE_URL", DEFAULT_NITTER_BASE).rstrip("/")
    fallbacks = os.environ.get("NITTER_FALLBACK_URLS", "")
    bases = [primary]
    for b in fallbacks.split(","):
        b = b.strip().rstrip("/")
        if b and b not in bases:
            bases.append(b)
    return bases


def _fetch_rss(url: str) -> tuple[Optional[bytes], Optional[str]]:
    last_err: Optional[str] = None
    try:
        r = requests.get(
            url, headers=HEADERS, timeout=HTTP_TIMEOUT_S,
            allow_redirects=True,
        )
        if r.status_code == 429:
            return None, "HTTP 429"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.content, None
    except Exception as e:
        return None, repr(e)


def _parse_nitter_rss(
    payload: bytes,
    day: date,
    publisher_label: str,
    allowed_hosts: set[str],
) -> list[DiscoveredArticle]:
    out: list[DiscoveredArticle] = []
    seen: set[str] = set()
    try:
        parsed = feedparser.parse(payload)
    except Exception:
        return out
    for entry in getattr(parsed, "entries", []) or []:
        title = _strip_html(entry.get("title"))
        summary = _strip_html(
            entry.get("summary") or entry.get("description") or ""
        )
        text_blob = f"{title} {summary}"
        pub: Optional[datetime] = None
        if getattr(entry, "published_parsed", None):
            try:
                pub = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC"))
            except (TypeError, ValueError):
                pass
        if pub is not None and not _in_sp_day(pub, day):
            continue
        link = (entry.get("link") or "").strip()
        urls = extract_http_urls(text_blob)
        if link:
            urls.insert(0, link)
        for news_url in filter_news_urls(urls, allowed_hosts):
            if news_url in seen:
                continue
            seen.add(news_url)
            out.append(DiscoveredArticle(
                url=news_url,
                title=title or news_url,
                excerpt=summary[:500],
                publisher=publisher_label,
                publisher_host="x.com",
                published_at=pub,
            ))
    return out


@dataclass
class NitterSearchAdapter:
    query: str
    allowed_hosts: set[str]
    name: str = ""
    hostname: str = "x.com"

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"X/Nitter search ({self.query[:36]})"

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        bases = _nitter_bases()
        last_err: Optional[str] = None
        for base in bases:
            rss_url = (
                f"{base}/search/rss?f=tweets&q={quote_plus(self.query)}"
            )
            payload, err = _fetch_rss(rss_url)
            result.http_calls += 1
            time.sleep(INTER_NITTER_SLEEP_S)
            if payload:
                result.articles = _parse_nitter_rss(
                    payload, day, self.name, self.allowed_hosts,
                )
                result.elapsed_s = time.perf_counter() - t0
                return result
            last_err = err
        result.error = last_err or "all Nitter instances failed"
        result.elapsed_s = time.perf_counter() - t0
        return result


@dataclass
class NitterAccountAdapter:
    handle: str
    allowed_hosts: set[str]
    name: str = ""
    hostname: str = "x.com"

    def __post_init__(self) -> None:
        h = self.handle.lstrip("@")
        if not self.name:
            self.name = f"X/@{h}"

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        handle = self.handle.lstrip("@")
        last_err: Optional[str] = None
        for base in _nitter_bases():
            rss_url = f"{base}/{handle}/rss"
            payload, err = _fetch_rss(rss_url)
            result.http_calls += 1
            time.sleep(INTER_NITTER_SLEEP_S)
            if payload:
                result.articles = _parse_nitter_rss(
                    payload, day, self.name, self.allowed_hosts,
                )
                result.elapsed_s = time.perf_counter() - t0
                return result
            last_err = err
        result.error = last_err or "all Nitter instances failed"
        result.elapsed_s = time.perf_counter() - t0
        return result


def nitter_adapters(allowed_hosts: set[str]) -> list:
    adapters: list = []
    max_search = int(os.environ.get("X_MAX_SEARCH_QUERIES", "12") or "12")
    queries_raw = os.environ.get("X_SEARCH_QUERIES", "")
    if queries_raw.strip():
        queries = [q.strip() for q in queries_raw.split("|") if q.strip()]
    else:
        queries = list(DEFAULT_SEARCH_QUERIES)
    for q in queries[:max_search]:
        adapters.append(NitterSearchAdapter(q, allowed_hosts=allowed_hosts))
    accounts_raw = os.environ.get("X_CURATED_ACCOUNTS", ",".join(DEFAULT_ACCOUNTS))
    for acc in accounts_raw.split(","):
        acc = acc.strip()
        if acc:
            adapters.append(NitterAccountAdapter(acc, allowed_hosts=allowed_hosts))
    return adapters
