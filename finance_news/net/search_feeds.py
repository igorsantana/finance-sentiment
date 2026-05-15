"""Aggregate Google News RSS + DuckDuckGo News discovery (thematic queries)."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
from dateutil import parser as dateparser

from finance_news.net.discovery import (
    AdapterResult,
    DiscoveredArticle,
    HEADERS,
    HTTP_TIMEOUT_S,
    SP_TZ,
    _in_sp_day,
    _strip_html,
)
from finance_news.net.fetch import (
    GNEWS_PREFIX,
    resolve_google_news_urls,
)

log = logging.getLogger("discovery")

# Thematic queries — not per-company (~8–10 requests/day).
DEFAULT_GNEWS_QUERIES = [
    'when:1d (B3 OR Ibovespa OR "bolsa de valores")',
    'when:1d (ações OR dividendos OR "resultado trimestral")',
    'when:1d (economia OR mercado OR finanças) site:valor.globo.com',
    'when:1d (PETR4 OR VALE3 OR ITUB4 OR BBDC4)',
    'when:1d (small caps OR "ações brasileiras")',
]

DEFAULT_DDG_QUERIES = [
    "B3 Ibovespa bolsa Brasil",
    "ações dividendos resultado trimestral",
    "PETR4 Vale Itaú mercado",
    "economia financeira Brasil hoje",
]

INTER_DDG_SLEEP_S = 1.0


def _env_queries(name: str, defaults: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(defaults)
    return [q.strip() for q in raw.split("|") if q.strip()]


def _entry_published(entry) -> Optional[datetime]:
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC"))
        except (TypeError, ValueError):
            pass
    for k in ("published", "updated", "created"):
        v = entry.get(k)
        if v:
            try:
                return dateparser.parse(v)
            except (ValueError, TypeError):
                continue
    return None


def google_news_rss(query: str, hl: str = "pt-BR", gl: str = "BR") -> list[DiscoveredArticle]:
    ceid = f"{gl}:{hl.split('-')[0]}"
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )
    try:
        parsed = feedparser.parse(url, request_headers=HEADERS)
    except Exception as e:
        log.warning("Google News RSS %r failed: %s", query[:60], e)
        return []
    out: list[DiscoveredArticle] = []
    for entry in getattr(parsed, "entries", []) or []:
        link = entry.get("link")
        if not link:
            continue
        pub = _entry_published(entry)
        out.append(DiscoveredArticle(
            url=link,
            title=_strip_html(entry.get("title")),
            excerpt=_strip_html(entry.get("summary") or ""),
            publisher="Google News",
            publisher_host="news.google.com",
            published_at=pub,
        ))
    return out


def duckduckgo_news(query: str, max_results: int = 25) -> list[DiscoveredArticle]:
    try:
        from ddgs import DDGS
    except ImportError:
        log.warning("ddgs not installed — pip install ddgs")
        return []
    try:
        results = DDGS(timeout=15).news(
            query, region="br-pt", max_results=max_results,
        ) or []
    except Exception as e:
        log.debug("DDG news %r failed: %s", query[:40], e)
        return []
    out: list[DiscoveredArticle] = []
    for r in results:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        pub: Optional[datetime] = None
        if r.get("date"):
            try:
                pub = dateparser.parse(r["date"])
            except (ValueError, TypeError):
                pass
        host = (url.split("/")[2] if "://" in url else "").lower()
        if host.startswith("www."):
            host = host[4:]
        out.append(DiscoveredArticle(
            url=url,
            title=_strip_html(r.get("title")),
            excerpt=_strip_html(r.get("body") or ""),
            publisher="DuckDuckGo News",
            publisher_host=host or "unknown",
            published_at=pub,
        ))
    return out


@dataclass
class GoogleNewsSearchAdapter:
    """One adapter instance per thematic Google News RSS query."""
    query: str
    name: str = ""
    hostname: str = "news.google.com"

    def __post_init__(self) -> None:
        if not self.name:
            short = self.query[:48] + ("…" if len(self.query) > 48 else "")
            self.name = f"Google News ({short})"

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        try:
            raw = google_news_rss(self.query)
            result.http_calls = 1
            gn_urls = [a.url for a in raw if a.url.startswith(GNEWS_PREFIX)]
            resolved = resolve_google_news_urls(gn_urls) if gn_urls else {}
            for art in raw:
                if art.url.startswith(GNEWS_PREFIX):
                    real = resolved.get(art.url)
                    if not real:
                        continue
                    art = DiscoveredArticle(
                        url=real,
                        title=art.title,
                        excerpt=art.excerpt,
                        publisher=self.name,
                        publisher_host=art.publisher_host,
                        published_at=art.published_at,
                    )
                pub = art.published_at
                if pub is not None and not _in_sp_day(pub, day):
                    continue
                if pub is None:
                    result.articles.append(art)
                elif _in_sp_day(pub, day):
                    result.articles.append(art)
        except Exception as e:
            result.error = repr(e)
        finally:
            result.elapsed_s = time.perf_counter() - t0
        return result


@dataclass
class DuckDuckGoNewsAdapter:
    """One adapter per thematic DDG news query (direct publisher URLs)."""
    query: str
    max_results: int = 25
    name: str = ""
    hostname: str = "duckduckgo.com"

    def __post_init__(self) -> None:
        if not self.name:
            short = self.query[:40] + ("…" if len(self.query) > 40 else "")
            self.name = f"DDG News ({short})"

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        try:
            raw = duckduckgo_news(self.query, max_results=self.max_results)
            result.http_calls = 1
            time.sleep(INTER_DDG_SLEEP_S)
            for art in raw:
                pub = art.published_at
                if pub is not None and not _in_sp_day(pub, day):
                    continue
                result.articles.append(art)
        except Exception as e:
            result.error = repr(e)
        finally:
            result.elapsed_s = time.perf_counter() - t0
        return result


def google_news_adapters() -> list[GoogleNewsSearchAdapter]:
    max_q = int(os.environ.get("GNEWS_MAX_QUERIES", "10") or "10")
    queries = _env_queries("GNEWS_QUERIES", DEFAULT_GNEWS_QUERIES)[:max_q]
    return [GoogleNewsSearchAdapter(q) for q in queries]


def duckduckgo_adapters() -> list[DuckDuckGoNewsAdapter]:
    max_q = int(os.environ.get("DDG_MAX_QUERIES", "8") or "8")
    max_res = int(os.environ.get("DDG_MAX_RESULTS", "25") or "25")
    queries = _env_queries("DDG_QUERIES", DEFAULT_DDG_QUERIES)[:max_q]
    return [DuckDuckGoNewsAdapter(q, max_results=max_res) for q in queries]
