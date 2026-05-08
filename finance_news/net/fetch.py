"""Thin trafilatura wrapper that pulls text + metadata for a single URL.

Inputs are direct publisher URLs — discovery happens in
``finance_news.net.discovery`` (per-publisher listings, no third-party
search index, no URL unwrapping). The legacy
``resolve_google_news_batch`` shim was removed when the Google News /
DDG ingest path was retired.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import trafilatura
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

# Common Portuguese words absent from English — used to gate article language.
_PT_TOKENS = frozenset([
    "não", "para", "com", "por", "das", "dos", "uma", "uns",
    "seu", "sua", "também", "isso", "esta", "este", "são",
    "muito", "mais", "foi", "será", "tem", "que", "mas",
    "pela", "pelo", "nos", "nas", "ao", "do", "da",
])
_PT_MIN_HITS = 5


def _is_portuguese(text: str) -> bool:
    words = text.lower().split()
    hits = sum(1 for w in words if w.strip(".,;:!?\"'()[]") in _PT_TOKENS)
    return hits >= _PT_MIN_HITS


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


def _extract(html: str, url: str) -> Optional[Article]:
    raw = trafilatura.extract(
        html,
        url=url,
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
    if not _is_portuguese(text):
        log.debug("skipping non-Portuguese article %s", url)
        return None
    return Article(
        url=data.get("url") or url,
        title=data.get("title"),
        text=text,
        published=_parse_date(data.get("date")),
        author=data.get("author"),
    )


def fetch_article_direct(url: str) -> Optional[Article]:
    """Fetch and extract an article from a direct publisher URL.

    Returns ``None`` (and the caller drops the article) when trafilatura
    can't pull HTML, the extracted body is shorter than 200 chars, or
    the body fails the Portuguese language gate.
    """
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        log.debug("no html for %s", url)
        return None
    return _extract(downloaded, url)


def fetch_cvm_article(url: str, title: Optional[str] = None) -> Optional[Article]:
    """Fetch a CVM filing document (PDF) and extract its text content.

    CVM's frmDownloadDocumento.aspx endpoints serve PDFs directly. Uses
    requests to download the raw bytes and pypdf for text extraction.
    """
    import io as _io

    import requests as _req

    try:
        r = _req.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception as e:
        log.debug("CVM PDF fetch failed %s: %s", url, e)
        return None

    if not r.content or r.content[:5] != b"%PDF-":
        return None

    try:
        from pypdf import PdfReader
        reader = PdfReader(_io.BytesIO(r.content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
    except Exception as e:
        log.debug("pypdf extraction failed %s: %s", url, e)
        return None

    if len(text) < 50:
        return None

    # CVM filings are Portuguese by nature — skip the language gate
    return Article(url=url, title=title, text=text, published=None, author=None)


def fetch_article(url: str) -> Optional[Article]:
    """Fetch a single article from a direct publisher URL.

    Equivalent to :func:`fetch_article_direct`; kept as the public name
    for any external one-off caller that imports ``fetch_article``.
    """
    return fetch_article_direct(url)
