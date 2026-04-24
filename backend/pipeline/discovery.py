"""RSS probing + homepage-crawl helpers to discover article URLs per site."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import feedparser
import requests
import tldextract
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
TIMEOUT = 15

RSS_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss.xml",
    "/feed/rss",
    "/index.xml",
    "/atom.xml",
    "/feed/atom",
]

EXCLUDE_PATH_TOKENS = (
    "/tag/",
    "/autor/",
    "/author/",
    "/categoria/",
    "/category/",
    "/page/",
    "/busca",
    "/search",
    "/assine",
    "/newsletter",
    "/sobre",
    "/contato",
    "/politica",
    "#",
)

SLUGGY = re.compile(r"(?:[a-z0-9]+-){2,}[a-z0-9]+")


@dataclass
class Candidate:
    url: str
    title: Optional[str] = None
    published: Optional[datetime] = None


def _same_site(a: str, b: str) -> bool:
    ea, eb = tldextract.extract(a), tldextract.extract(b)
    return (ea.domain, ea.suffix) == (eb.domain, eb.suffix)


def _fetch(url: str) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200 and r.content:
            return r
    except requests.RequestException as e:
        log.debug("fetch %s failed: %s", url, e)
    return None


def _parse_feed_date(entry) -> Optional[datetime]:
    for k in ("published", "updated", "created"):
        v = entry.get(k)
        if v:
            try:
                return dateparser.parse(v)
            except (ValueError, TypeError):
                continue
    return None


def discover_rss(site_url: str) -> list[Candidate]:
    """Probe common RSS paths + <link rel=alternate>. Return candidates or []."""
    tried: set[str] = set()
    feed_urls: list[str] = []

    # From homepage <link rel=alternate>
    r = _fetch(site_url)
    if r is not None:
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.find_all(
            "link", rel=lambda v: v and "alternate" in (v if isinstance(v, list) else [v])
        ):
            t = (link.get("type") or "").lower()
            if "rss" in t or "atom" in t or "xml" in t:
                href = link.get("href")
                if href:
                    feed_urls.append(urljoin(site_url, href))

    for p in RSS_PATHS:
        feed_urls.append(urljoin(site_url.rstrip("/") + "/", p.lstrip("/")))

    for fu in feed_urls:
        if fu in tried:
            continue
        tried.add(fu)
        try:
            parsed = feedparser.parse(fu, request_headers=HEADERS)
        except Exception as e:
            log.debug("feedparser error %s: %s", fu, e)
            continue
        if not parsed.entries:
            continue
        cands: list[Candidate] = []
        for entry in parsed.entries:
            link = entry.get("link")
            if not link:
                continue
            cands.append(
                Candidate(
                    url=link,
                    title=entry.get("title"),
                    published=_parse_feed_date(entry),
                )
            )
        if cands:
            log.info("RSS found for %s: %s (%d entries)", site_url, fu, len(cands))
            return cands
    return []


def discover_homepage(site_url: str, cap: int = 40) -> list[Candidate]:
    r = _fetch(site_url)
    if r is None:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    seen: set[str] = set()
    cands: list[Candidate] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        url = urljoin(site_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if not _same_site(url, site_url):
            continue
        path = parsed.path
        if any(tok in path for tok in EXCLUDE_PATH_TOKENS):
            continue
        if path.count("/") < 2:
            continue
        if not SLUGGY.search(path):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = (a.get_text() or "").strip() or None
        cands.append(Candidate(url=url, title=title))
        if len(cands) >= cap:
            break
    log.info("Homepage crawl %s: %d candidates", site_url, len(cands))
    return cands


def discover(site_url: str) -> tuple[str, list[Candidate]]:
    """Return ('rss'|'crawl', candidates). RSS first, then homepage fallback."""
    rss = discover_rss(site_url)
    if rss:
        return "rss", rss
    return "crawl", discover_homepage(site_url)


def google_news_feed(
    query: str, hl: str = "pt-BR", gl: str = "BR"
) -> list[Candidate]:
    """Query Google News RSS search and return candidates.

    Dates in Google News feeds are reliable; every entry carries a
    `published_parsed` from feedparser, so `filter_today()` works as-is.
    """
    ceid = f"{gl}:{hl.split('-')[0]}"
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )
    try:
        parsed = feedparser.parse(url, request_headers=HEADERS)
    except Exception as e:
        log.warning("google_news_feed %r failed: %s", query, e)
        return []
    cands: list[Candidate] = []
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue
        cands.append(
            Candidate(
                url=link,
                title=entry.get("title"),
                published=_parse_feed_date(entry),
            )
        )
    return cands


def filter_today(
    candidates: Iterable[Candidate], today: date
) -> list[Candidate]:
    """Keep candidates whose feed-reported date == today. Candidates without
    a feed date are kept so the fetch stage can re-check article metadata."""
    kept: list[Candidate] = []
    for c in candidates:
        if c.published is None:
            kept.append(c)
            continue
        if c.published.date() == today:
            kept.append(c)
    return kept
