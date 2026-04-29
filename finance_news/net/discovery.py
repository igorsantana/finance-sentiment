"""Google News RSS discovery — the only stream we keep.

The old site-stream helpers (``discover_rss``, ``discover_homepage``,
``discover``, plus ``RSS_PATHS`` / ``EXCLUDE_PATH_TOKENS`` / ``SLUGGY``) were
deleted with Stage 6 along with ``sources.csv``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional
from urllib.parse import quote_plus

import feedparser
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}


@dataclass
class Candidate:
    url: str
    title: Optional[str] = None
    published: Optional[datetime] = None


def _parse_feed_date(entry) -> Optional[datetime]:
    for k in ("published", "updated", "created"):
        v = entry.get(k)
        if v:
            try:
                return dateparser.parse(v)
            except (ValueError, TypeError):
                continue
    return None


def google_news_feed(
    query: str, hl: str = "pt-BR", gl: str = "BR"
) -> list[Candidate]:
    """Query Google News RSS search and return candidates.

    Dates in Google News feeds are reliable; every entry carries a
    ``published_parsed`` from feedparser, so ``filter_today()`` works as-is.
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
