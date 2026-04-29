"""Thin trafilatura wrapper that pulls text + metadata for a single URL."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import trafilatura
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

_GOOGLE_NEWS_PREFIX = "https://news.google.com/"


def _resolve_google_news(url: str) -> Optional[str]:
    """Google News RSS links are client-side redirects; decode to publisher URL."""
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        log.debug("googlenewsdecoder not installed; cannot unwrap %s", url)
        return None
    try:
        result = gnewsdecoder(url, interval=1)
    except Exception as e:
        log.debug("gnewsdecoder failed for %s: %s", url, e)
        return None
    if isinstance(result, dict) and result.get("status") and result.get("decoded_url"):
        return result["decoded_url"]
    return None


@dataclass
class Article:
    url: str
    title: Optional[str]
    text: str
    published: Optional[datetime]
    author: Optional[str]


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return dateparser.parse(s)
    except (ValueError, TypeError):
        return None


def fetch_article(url: str) -> Optional[Article]:
    fetch_url = url
    if url.startswith(_GOOGLE_NEWS_PREFIX):
        resolved = _resolve_google_news(url)
        if not resolved:
            log.debug("could not unwrap google news url %s", url)
            return None
        fetch_url = resolved
    downloaded = trafilatura.fetch_url(fetch_url)
    if not downloaded:
        log.debug("no html for %s", fetch_url)
        return None
    raw = trafilatura.extract(
        downloaded,
        url=fetch_url,
        with_metadata=True,
        output_format="json",
        favor_precision=True,
        include_comments=False,
        include_tables=False,
        deduplicate=True,
    )
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    text = (data.get("text") or "").strip()
    if len(text) < 200:
        return None
    return Article(
        url=data.get("url") or fetch_url,
        title=data.get("title"),
        text=text,
        published=_parse_date(data.get("date")),
        author=data.get("author"),
    )


def is_today(article: Article, today: date) -> bool:
    return article.published is not None and article.published.date() == today
