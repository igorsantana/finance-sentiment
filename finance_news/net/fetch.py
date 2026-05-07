"""Thin trafilatura wrapper that pulls text + metadata for a single URL."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import trafilatura
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

_GOOGLE_NEWS_PREFIX = "https://news.google.com/"
# Flipped to True on the first run that gets zero successful decodes from
# batchexecute (Google soft-block). Avoids firing 400+ useless POSTs per run.
_gnews_decode_blocked: bool = False

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


def resolve_google_news_batch(urls: list[str]) -> list[Optional[str]]:
    """Decode Google News article URLs in one batchexecute POST (no per-article GET).

    Uses decoderv4 which batches all IDs into a single request, avoiding the
    per-article GET→POST sequence that triggers Google rate limiting.
    Returns a parallel list of resolved URLs; None entries mean decode failed.

    A module-level circuit breaker (_gnews_decode_blocked) is set after the
    first all-empty response, preventing further batchexecute calls for the
    rest of the process lifetime when Google is soft-blocking.
    """
    global _gnews_decode_blocked
    if not urls:
        return []
    if _gnews_decode_blocked:
        return [None] * len(urls)
    try:
        from googlenewsdecoder import decoderv4
    except ImportError:
        log.warning("googlenewsdecoder not installed")
        return [None] * len(urls)
    try:
        results = decoderv4(urls)
    except Exception as e:
        log.warning("decoderv4 batch failed: %s", e)
        return [None] * len(urls)
    out: list[Optional[str]] = []
    for r in results:
        if isinstance(r, dict) and r.get("status") and r.get("url"):
            out.append(r["url"])
        else:
            if isinstance(r, dict) and r.get("error"):
                log.debug("decoderv4 error: %s", r["error"])
            out.append(None)
    if urls and not any(out):
        log.warning("GNews batchexecute returned no URLs — soft-blocked; skipping decode for this run")
        _gnews_decode_blocked = True
    return out


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
    """Fetch an article from a direct publisher URL (already decoded from Google News)."""
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
    """Fetch a single article, resolving Google News URLs if needed.

    Prefer calling resolve_google_news_batch() + fetch_article_direct() for
    bulk ingestion — this one-at-a-time path exists for ad-hoc use only.
    """
    if url.startswith(_GOOGLE_NEWS_PREFIX):
        resolved = resolve_google_news_batch([url])[0]
        if not resolved:
            log.debug("could not unwrap google news url %s", url)
            return None
        url = resolved
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        log.debug("no html for %s", url)
        return None
    return _extract(downloaded, url)
