"""Per-publisher article discovery — the daily ingest's first stage.

The pipeline used to fan out one Google News + one DuckDuckGo query *per
company* (≈ 1 000 third-party requests per run, plus a fragile
``batchexecute`` decode pass for Google News URLs). That model fought
constantly with both providers' anti-abuse posture and broke whenever
Google rotated its undocumented internal wire format.

This module flips the axis: hit a small set of pt-BR finance publishers
*once each*, list everything they published in the target SP-day window,
dedup, and let ``CompanyMatcher`` fold the firehose back to the tracked
ticker_roots downstream.

Adapters land here (and not in ``finance_news.ingest``) so any future
diagnostic or backfill that needs to call discovery directly can reuse
the exact same surface as the production ingest. ``scripts/diagnostics/
probe_rss.py`` is the first such consumer — it runs every adapter once
and reports per-publisher health.

Adapter shape
-------------
Every adapter implements ``list_today(day) -> AdapterResult``. The result
carries ``DiscoveredArticle`` rows (url + title + excerpt + publisher +
publisher_host + published_at) plus per-adapter diagnostics (HTTP count,
elapsed time, error). Adapters soft-fail on network or layout drift so a
single bad publisher cannot abort the whole run.

Three adapter types cover every publisher in ``default_adapters()``:

* ``WordPressAdapter``  — the canonical ``/wp-json/wp/v2/posts`` endpoint
  with optional ``category_slugs`` filtering for publishers whose CMS
  mixes finance with lifestyle/sports (CNN Brasil, Forbes, Exame).
* ``RssListAdapter``    — one or more RSS/Atom feeds with explicit UA +
  ``Accept-Language`` so anti-bot interstitials don't masquerade as empty
  feeds (used for InvestNews and Bloomberg Línea).
* ``NewsSitemapAdapter`` — Google News sitemap XML (up to ~1000 URLs / 48h);
  primary listing for publishers that expose ``news-sitemap.xml``.
* ``ValorGloboAdapter`` / ``FolhaSearchAdapter`` — site-specific HTML
  scrapers; the legacy Globo/Folha RSS endpoints have been gone for years.

Live logging
------------
``run_adapters`` streams an INFO-level line per adapter *as each future
completes*, not at the end. That matters for the FastAPI SSE channel
that powers the web client's Logs panel — the operator sees adapters
report in (with article counts, HTTP costs, elapsed time, and any errors)
in roughly real time instead of staring at a silent screen for the
5-15 s discovery window.
"""
from __future__ import annotations

import html
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional, Protocol
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# Bare logger name (not __name__) so the SSE handler shows it as
# `discovery:` in the web UI's Logs panel, matching `ingest:` /
# `extract:` from the other pipeline stages.
log = logging.getLogger("discovery")

SP_TZ = ZoneInfo("America/Sao_Paulo")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
HTTP_TIMEOUT_S = 20

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(s: Optional[str]) -> str:
    if not s:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub("", s))).strip()


def _parse_dt(raw: Optional[str], assume_tz: ZoneInfo = SP_TZ) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
    except (ValueError, TypeError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt


def _in_sp_day(dt: Optional[datetime], day: date) -> bool:
    if dt is None:
        return False
    return dt.astimezone(SP_TZ).date() == day


# ---------- data classes ----------

@dataclass
class DiscoveredArticle:
    """Listing-stage record. ``excerpt`` and ``published_at`` are the bits
    the CompanyMatcher and SP-day filter need before we commit to a body
    fetch."""
    url: str
    title: str
    excerpt: str
    publisher: str
    publisher_host: str
    published_at: Optional[datetime]


@dataclass
class AdapterResult:
    publisher: str
    hostname: str
    articles: list[DiscoveredArticle] = field(default_factory=list)
    http_calls: int = 0
    error: Optional[str] = None
    elapsed_s: float = 0.0


class Adapter(Protocol):
    name: str
    hostname: str

    def list_today(self, day: date) -> AdapterResult: ...


# ---------- WordPress REST adapter ----------

@dataclass
class WordPressAdapter:
    """Generic ``/wp-json/wp/v2/posts`` adapter.

    Most pt-BR finance publishers run WordPress, so a single adapter
    handles InfoMoney, Money Times, Suno, Brazil Journal, Seu Dinheiro,
    NeoFeed, Exame, Estadão E-Investidor, BM&C News, IstoÉ Dinheiro,
    Capital Aberto, Capital Reset, and TradeMap.

    For publishers whose CMS mixes finance with lifestyle (CNN Brasil,
    Forbes, Exame), pass ``category_slugs=[...]``: the adapter resolves
    the slugs to numeric category IDs once on the first call and then
    filters posts via ``&categories=…``. Slugs that don't exist on the
    target CMS are silently skipped; if *every* slug is unknown, we
    fall through to unfiltered posts and warn.
    """
    name: str
    hostname: str
    base_url: Optional[str] = None
    per_page: int = 100
    category_slugs: list[str] = field(default_factory=list)
    _category_ids: Optional[list[int]] = field(default=None, init=False, repr=False)
    _categories_resolved: bool = field(default=False, init=False, repr=False)

    def _root(self) -> str:
        return (self.base_url or f"https://{self.hostname}").rstrip("/")

    def _endpoint(self) -> str:
        return f"{self._root()}/wp-json/wp/v2/posts"

    def _resolve_categories(self, result: AdapterResult) -> list[int]:
        """Resolve ``category_slugs`` → numeric IDs (cached on the adapter).

        We need the IDs because ``/wp-json/wp/v2/posts`` only filters via
        ``categories=<id,id,…>``. The slug → id map is stable per
        publisher; we resolve once and cache for the process lifetime.
        Errors are logged but do not abort: the adapter falls through to
        unfiltered posts so a slug typo can't break ingestion.
        """
        if self._categories_resolved:
            return self._category_ids or []
        ids: list[int] = []
        for slug in self.category_slugs:
            try:
                r = requests.get(
                    f"{self._root()}/wp-json/wp/v2/categories",
                    params={"slug": slug, "_fields": "id,slug"},
                    headers=HEADERS, timeout=HTTP_TIMEOUT_S,
                )
                result.http_calls += 1
                if r.status_code != 200:
                    log.debug("%s: categories?slug=%s -> HTTP %d",
                              self.name, slug, r.status_code)
                    continue
                payload = r.json()
                for entry in (payload or []):
                    cid = entry.get("id")
                    if isinstance(cid, int):
                        ids.append(cid)
            except Exception as e:
                log.debug("%s: category lookup for %r failed: %s",
                          self.name, slug, e)
        self._category_ids = ids
        self._categories_resolved = True
        if self.category_slugs and not ids:
            log.warning(
                "%s: none of category_slugs=%r resolved to ids — "
                "falling through to unfiltered listing",
                self.name, self.category_slugs,
            )
        return ids

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        start = datetime.combine(day, datetime.min.time(), tzinfo=SP_TZ)
        end = start + timedelta(days=1)
        base_params: dict[str, str | int] = {
            "after": start.isoformat(),
            "before": end.isoformat(),
            "per_page": self.per_page,
            "_fields": "id,date,date_gmt,title,link,excerpt",
            "orderby": "date",
            "order": "desc",
        }
        if self.category_slugs:
            cat_ids = self._resolve_categories(result)
            if cat_ids:
                base_params["categories"] = ",".join(str(i) for i in cat_ids)

        page = 1
        stop = False
        try:
            while not stop:
                params = {**base_params, "page": page}
                r = requests.get(
                    self._endpoint(), params=params,
                    headers=HEADERS, timeout=HTTP_TIMEOUT_S,
                )
                result.http_calls += 1
                if r.status_code != 200:
                    if page == 1:
                        result.error = f"HTTP {r.status_code}"
                    break
                payload = r.json()
                if not isinstance(payload, list):
                    if page == 1:
                        result.error = (
                            f"unexpected payload type: {type(payload).__name__}"
                        )
                    break
                if not payload:
                    break
                oldest_on_page: Optional[datetime] = None
                for post in payload:
                    link = post.get("link")
                    if not link:
                        continue
                    title = _strip_html((post.get("title") or {}).get("rendered"))
                    excerpt = _strip_html((post.get("excerpt") or {}).get("rendered"))
                    pub_gmt = post.get("date_gmt")
                    pub_local = post.get("date")
                    if pub_gmt:
                        raw = pub_gmt if pub_gmt.endswith("Z") else pub_gmt + "Z"
                        pub = _parse_dt(raw, assume_tz=ZoneInfo("UTC"))
                    elif pub_local:
                        pub = _parse_dt(pub_local, assume_tz=SP_TZ)
                    else:
                        pub = None
                    if pub is not None:
                        if oldest_on_page is None or pub < oldest_on_page:
                            oldest_on_page = pub
                    if pub is None or not _in_sp_day(pub, day):
                        continue
                    result.articles.append(DiscoveredArticle(
                        url=link, title=title, excerpt=excerpt,
                        publisher=self.name, publisher_host=self.hostname,
                        published_at=pub,
                    ))
                if len(payload) < self.per_page:
                    break
                if oldest_on_page is not None and oldest_on_page.astimezone(SP_TZ).date() < day:
                    break
                page += 1
                if page > 10:
                    break
        except Exception as e:
            result.error = repr(e)
        finally:
            result.elapsed_s = time.perf_counter() - t0
        return result


# ---------- RSS adapter ----------

def _fetch_feed_bytes(url: str) -> tuple[Optional[bytes], Optional[int], Optional[str]]:
    """Fetch raw feed bytes with explicit headers so the publisher sees a
    real pt-BR User-Agent (``feedparser.parse(url, ...)`` does not always
    forward ``request_headers`` and several pt-BR sites short-circuit on
    that). Returns ``(bytes, status, error)``.
    """
    try:
        r = requests.get(
            url, headers=HEADERS, timeout=HTTP_TIMEOUT_S, allow_redirects=True,
        )
    except Exception as e:
        return None, None, repr(e)
    if r.status_code >= 400:
        return None, r.status_code, f"HTTP {r.status_code}"
    return r.content, r.status_code, None


def _entry_published(entry) -> Optional[datetime]:
    for k in ("published", "updated", "created"):
        v = entry.get(k)
        if v:
            try:
                return dateparser.parse(v)
            except (ValueError, TypeError):
                continue
    return None


@dataclass
class RssListAdapter:
    """One or more RSS/Atom feeds for a single publisher.

    Used for outlets that don't expose ``/wp-json`` (InvestNews,
    Bloomberg Línea, …). Each feed costs one HTTP call; per-feed
    failures are logged but do not abort the adapter.
    """
    name: str
    hostname: str
    feed_urls: list[str]

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        seen: set[str] = set()
        feed_errors: list[str] = []
        for feed_url in self.feed_urls:
            payload, _status, error = _fetch_feed_bytes(feed_url)
            result.http_calls += 1
            if error or payload is None:
                feed_errors.append(f"{feed_url}: {error or 'no payload'}")
                continue
            try:
                parsed = feedparser.parse(payload)
            except Exception as e:
                feed_errors.append(f"{feed_url}: feedparser {e!r}")
                continue
            for entry in getattr(parsed, "entries", []) or []:
                link = entry.get("link")
                if not link or link in seen:
                    continue
                pub = _entry_published(entry)
                if pub is None or not _in_sp_day(pub, day):
                    continue
                title = _strip_html(entry.get("title"))
                excerpt = _strip_html(
                    entry.get("summary") or entry.get("description") or ""
                )
                seen.add(link)
                result.articles.append(DiscoveredArticle(
                    url=link, title=title, excerpt=excerpt,
                    publisher=self.name, publisher_host=self.hostname,
                    published_at=pub,
                ))
        result.elapsed_s = time.perf_counter() - t0
        if not result.articles and feed_errors and len(feed_errors) == len(self.feed_urls):
            result.error = feed_errors[0]
        return result


# ---------- Google News sitemap adapter ----------

_SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


@dataclass
class NewsSitemapAdapter:
    """Parse a publisher's Google News sitemap (``news-sitemap.xml``).

    Sitemaps list up to 1000 article URLs from roughly the last 48 hours
    with ``news:publication_date`` and ``news:title``. One GET replaces
    paginated WordPress REST calls and typically surfaces more URLs per
    publisher than ``per_page=100`` on ``/wp-json/wp/v2/posts``.
    """
    name: str
    hostname: str
    sitemap_url: str

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        try:
            r = requests.get(
                self.sitemap_url, headers=HEADERS,
                timeout=HTTP_TIMEOUT_S, allow_redirects=True,
            )
            result.http_calls += 1
            if r.status_code != 200:
                result.error = f"HTTP {r.status_code}"
                return result
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            result.error = f"XML parse: {e}"
            return result
        except Exception as e:
            result.error = repr(e)
            return result
        finally:
            result.elapsed_s = time.perf_counter() - t0

        for url_el in root.findall("sm:url", _SITEMAP_NS):
            loc_el = url_el.find("sm:loc", _SITEMAP_NS)
            if loc_el is None or not loc_el.text:
                continue
            link = loc_el.text.strip()
            news_el = url_el.find("news:news", _SITEMAP_NS)
            pub: Optional[datetime] = None
            title = ""
            if news_el is not None:
                pub_el = news_el.find("news:publication_date", _SITEMAP_NS)
                if pub_el is not None and pub_el.text:
                    pub = _parse_dt(pub_el.text.strip(), assume_tz=ZoneInfo("UTC"))
                title_el = news_el.find("news:title", _SITEMAP_NS)
                if title_el is not None and title_el.text:
                    title = _strip_html(title_el.text)
            if pub is None or not _in_sp_day(pub, day):
                continue
            result.articles.append(DiscoveredArticle(
                url=link, title=title, excerpt="",
                publisher=self.name, publisher_host=self.hostname,
                published_at=pub,
            ))
        return result


# ---------- site-specific HTML adapters ----------

@dataclass
class ValorGloboAdapter:
    """Valor Econômico — scrape the public ``ultimas-noticias`` listing.

    Globo's documented JSON feeds key off internal feed UUIDs that aren't
    public; the listing page is what their own UI consumes and is stable.
    Selectors target the standard Globo ``feed-post-*`` class system; if
    Globo restyles, the adapter soft-fails so the rest of the run keeps
    working.
    """
    name: str = "Valor Econômico"
    hostname: str = "valor.globo.com"
    listing_url: str = "https://valor.globo.com/ultimas-noticias/"

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        try:
            r = requests.get(self.listing_url, headers=HEADERS, timeout=HTTP_TIMEOUT_S)
            result.http_calls += 1
            if r.status_code != 200:
                result.error = f"HTTP {r.status_code}"
                return result
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            result.error = repr(e)
            return result
        finally:
            result.elapsed_s = time.perf_counter() - t0

        for post in soup.select("div.feed-post-body"):
            a = post.select_one("a.feed-post-link")
            if not a or not a.get("href"):
                continue
            url = a["href"]
            title = _strip_html(a.get_text())
            resumo = post.select_one(".feed-post-body-resumo")
            excerpt = _strip_html(resumo.get_text()) if resumo else ""
            time_el = post.select_one("span.feed-post-datetime")
            pub: Optional[datetime] = None
            if time_el and time_el.get_text():
                pub = _parse_dt(time_el.get_text().strip(), assume_tz=SP_TZ)
            if pub is not None and not _in_sp_day(pub, day):
                continue
            result.articles.append(DiscoveredArticle(
                url=url, title=title, excerpt=excerpt,
                publisher=self.name, publisher_host=self.hostname,
                published_at=pub,
            ))
        return result


@dataclass
class FolhaSearchAdapter:
    """Folha de S.Paulo Mercado — public search endpoint scoped to today.

    URL shape: ``search.folha.uol.com.br/?q=&site=mercado&periodo=hoje``.
    Folha's own front-end consumes this exact endpoint, so it's the
    stable public surface for Mercado listings.
    """
    name: str = "Folha de S.Paulo - Mercado"
    hostname: str = "www1.folha.uol.com.br"
    search_url: str = "https://search.folha.uol.com.br/"

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        params = {"q": "", "site": "mercado", "periodo": "hoje"}
        try:
            r = requests.get(
                self.search_url, params=params,
                headers=HEADERS, timeout=HTTP_TIMEOUT_S,
            )
            result.http_calls += 1
            if r.status_code != 200:
                result.error = f"HTTP {r.status_code}"
                return result
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            result.error = repr(e)
            return result
        finally:
            result.elapsed_s = time.perf_counter() - t0

        for art in soup.select("div.c-headline, li.c-headline, article.c-headline"):
            link_el = art.select_one("a.c-headline__url, a")
            if not link_el or not link_el.get("href"):
                continue
            url = link_el["href"]
            title_el = art.select_one(".c-headline__title")
            title = _strip_html(title_el.get_text()) if title_el else _strip_html(link_el.get_text())
            excerpt_el = art.select_one(".c-headline__standfirst, .c-headline__description")
            excerpt = _strip_html(excerpt_el.get_text()) if excerpt_el else ""
            time_el = art.select_one("time")
            pub: Optional[datetime] = None
            if time_el:
                raw = time_el.get("datetime") or time_el.get_text()
                pub = _parse_dt(raw, assume_tz=SP_TZ)
            if pub is not None and not _in_sp_day(pub, day):
                continue
            result.articles.append(DiscoveredArticle(
                url=url, title=title, excerpt=excerpt,
                publisher=self.name, publisher_host=self.hostname,
                published_at=pub,
            ))
        return result


# ---------- adapter set ----------

def _env_enabled(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def publisher_host_allowlist() -> set[str]:
    """Hosts from built-in adapters (used for social link filtering)."""
    hosts: set[str] = set()
    for a in publisher_adapters():
        h = getattr(a, "hostname", None)
        if h:
            hosts.add(h.lower().removeprefix("www."))
    return hosts


def publisher_adapters() -> list[Adapter]:
    """The full pt-BR finance discovery surface used by the production
    ingest.

    The roster is kept here — and not in ``finance_news.ingest`` — so any
    expansion (new publisher, new category filter) is picked up by both
    callers without divergence. Adapters are listed roughly in
    finance-relevance order so logs read naturally.
    """
    return [
        # --- Tier 1: news sitemaps (higher URL volume than WP REST alone) --
        NewsSitemapAdapter(
            "InfoMoney", "infomoney.com.br",
            "https://www.infomoney.com.br/news-sitemap.xml",
        ),
        NewsSitemapAdapter(
            "Brazil Journal", "braziljournal.com",
            "https://braziljournal.com/sitemap-news.xml",
        ),
        NewsSitemapAdapter(
            "E-Investidor", "einvestidor.estadao.com.br",
            "https://einvestidor.estadao.com.br/sitemap-news.xml",
        ),
        NewsSitemapAdapter(
            "CNN Brasil - Economia", "cnnbrasil.com.br",
            "https://admin.cnnbrasil.com.br/sitemap-news.xml",
        ),
        NewsSitemapAdapter(
            "G1 Economia", "g1.globo.com",
            "https://g1.globo.com/sitemap-news.xml",
        ),
        NewsSitemapAdapter(
            "UOL Economia", "economia.uol.com.br",
            "https://economia.uol.com.br/sitemap-news.xml",
        ),
        NewsSitemapAdapter(
            "Estadão Economia", "economia.estadao.com.br",
            "https://economia.estadao.com.br/sitemap-news.xml",
        ),
        NewsSitemapAdapter(
            "R7 Economia", "r7.com",
            "https://r7.com/sitemap-news.xml",
        ),
        # --- Tier 1 finance-focused, WordPress REST ----------------------
        WordPressAdapter("Money Times",        "moneytimes.com.br"),
        WordPressAdapter("Suno Notícias",      "suno.com.br"),
        WordPressAdapter("Seu Dinheiro",       "seudinheiro.com"),
        WordPressAdapter("Neofeed",            "neofeed.com.br"),
        WordPressAdapter("BM&C News",          "bmcnews.com.br"),
        WordPressAdapter("IstoÉ Dinheiro",     "istoedinheiro.com.br"),
        WordPressAdapter("Capital Aberto",     "capitalaberto.com.br"),
        WordPressAdapter("Empiricus",          "empiricus.com.br"),
        WordPressAdapter("Levante Investimentos", "levanteideias.com.br"),
        WordPressAdapter("Petronotícias",       "petronoticias.com.br"),
        WordPressAdapter("Megawhat",           "megawhat.com.br"),
        # --- Tier 1 mixed-content, finance categories only --------------
        WordPressAdapter(
            "Exame", "exame.com",
            category_slugs=["mercados", "invest", "economia",
                            "negocios", "financas-pessoais"],
        ),
        WordPressAdapter(
            "Forbes Brasil", "forbes.com.br",
            category_slugs=["forbes-money", "money", "negocios", "mercado"],
        ),
        # --- Tier 1 RSS / Tier 2 specialty -------------------------------
        RssListAdapter(
            "InvestNews", "investnews.com.br",
            feed_urls=["https://investnews.com.br/feed/"],
        ),
        RssListAdapter(
            "Bloomberg Línea Brasil", "bloomberglinea.com.br",
            feed_urls=[
                "https://www.bloomberglinea.com.br/arc/outboundfeeds/rss/?outputType=xml",
            ],
        ),
        RssListAdapter(
            "Investing.com Brasil", "br.investing.com",
            feed_urls=["https://br.investing.com/rss/news.rss"],
        ),
        RssListAdapter(
            "Yahoo Finanças", "br.financas.yahoo.com",
            feed_urls=[
                "https://br.financas.yahoo.com/rss/topstories",
            ],
        ),
        RssListAdapter(
            "B3 Comunicados", "b3.com.br",
            feed_urls=["https://www.b3.com.br/pt_br/rss/noticias/"],
        ),
        WordPressAdapter("Capital Reset",      "capitalreset.com"),
        WordPressAdapter("TradeMap",           "trademap.com.br"),
        # --- Site-specific scrapers --------------------------------------
        ValorGloboAdapter(),
        FolhaSearchAdapter(),
    ]


def default_adapters() -> list[Adapter]:
    """Full discovery surface: publishers + optional search/social adapters."""
    adapters: list[Adapter] = list(publisher_adapters())
    allowed = publisher_host_allowlist()
    try:
        from finance_news.store import db
        with db.connect() as conn:
            for row in db.fetch_publisher_hostnames(conn):
                allowed.add(row.lower().removeprefix("www."))
    except Exception as e:
        log.debug("Could not load publisher hostnames from DB: %s", e)

    if _env_enabled("GNEWS_DISCOVERY", default=True):
        from finance_news.net.search_feeds import google_news_adapters
        adapters.extend(google_news_adapters())

    if _env_enabled("DDG_DISCOVERY", default=True):
        from finance_news.net.search_feeds import duckduckgo_adapters
        adapters.extend(duckduckgo_adapters())

    if _env_enabled("SOCIAL_DISCOVERY", default=False):
        from finance_news.net.reddit import reddit_adapters
        adapters.extend(reddit_adapters(allowed))

    if _env_enabled("X_DISCOVERY", default=False):
        from finance_news.net.nitter import nitter_adapters
        adapters.extend(nitter_adapters(allowed))

    return adapters


# ---------- driver ----------

def run_adapters(
    adapters: list[Adapter],
    day: date,
    on_progress: Optional[callable] = None,
) -> list[AdapterResult]:
    """Fan ``adapters`` out via ThreadPoolExecutor and stream results.

    Each adapter does at most a handful of HTTP calls (typically one).
    ThreadPoolExecutor with ``max_workers=len(adapters)`` lets the run
    finish in roughly the latency of the slowest adapter rather than the
    sum — currently around 5-15 s end-to-end.

    A per-adapter INFO line is emitted as each future completes so the
    caller's log channel (and, transitively, the FastAPI SSE stream that
    feeds the web UI) keeps moving instead of going silent for the full
    discovery window.

    ``on_progress(completed, total)`` — optional callback invoked after
    each adapter completes, used by ``finance_news.ingest`` to keep the
    web client's progress bar in sync.
    """
    results: list[AdapterResult] = []
    if not adapters:
        return results

    total = len(adapters)
    log.info("Querying %d publisher(s) in parallel…", total)

    with ThreadPoolExecutor(max_workers=min(16, total)) as ex:
        futs = {ex.submit(a.list_today, day): a for a in adapters}
        completed = 0
        for fut in as_completed(futs):
            adapter = futs[fut]
            completed += 1
            try:
                r = fut.result()
            except Exception as e:
                log.warning(
                    "[%d/%d] %s — crashed: %s",
                    completed, total, adapter.name, e,
                )
                results.append(AdapterResult(
                    publisher=adapter.name,
                    hostname=getattr(adapter, "hostname", ""),
                    error=repr(e),
                ))
                if on_progress:
                    on_progress(completed, total)
                continue

            results.append(r)
            if r.error:
                log.warning(
                    "[%d/%d] %s — %s (%d HTTP, %.2fs)",
                    completed, total, adapter.name, r.error,
                    r.http_calls, r.elapsed_s,
                )
            else:
                log.info(
                    "[%d/%d] %s — %d article(s) (%d HTTP, %.2fs)",
                    completed, total, adapter.name,
                    len(r.articles), r.http_calls, r.elapsed_s,
                )
            if on_progress:
                on_progress(completed, total)
    return results


def dedup_articles(articles: list[DiscoveredArticle]) -> list[DiscoveredArticle]:
    """Stable URL-dedup. Preserves the first-seen entry so the publisher
    that listed an article first wins (matters when two outlets
    cross-publish syndicated wire copy)."""
    seen: set[str] = set()
    out: list[DiscoveredArticle] = []
    for a in articles:
        if a.url in seen:
            continue
        seen.add(a.url)
        out.append(a)
    return out


def discover_articles(
    day: date,
    adapters: Optional[list[Adapter]] = None,
    on_progress: Optional[callable] = None,
) -> tuple[list[DiscoveredArticle], list[AdapterResult]]:
    """Entry point for the daily ingest.

    Returns ``(deduped_articles, adapter_results)``. The raw adapter
    results carry the diagnostics we report to the operator (HTTP counts,
    elapsed time, errors) — callers are expected to surface them.
    ``on_progress`` is forwarded to ``run_adapters``.
    """
    adapters = adapters or default_adapters()
    results = run_adapters(adapters, day, on_progress=on_progress)
    raw: list[DiscoveredArticle] = []
    for r in results:
        raw.extend(r.articles)
    return dedup_articles(raw), results
