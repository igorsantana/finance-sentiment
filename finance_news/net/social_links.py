"""Extract outbound news URLs from social post text for link-aggregation discovery."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

_SKIP_HOST_SUFFIXES = (
    "twitter.com", "x.com", "t.co", "nitter.net", "xcancel.com",
    "reddit.com", "redd.it", "youtube.com", "youtu.be",
    "instagram.com", "facebook.com", "fb.com", "tiktok.com",
    "telegram.org", "t.me",
)


def extract_http_urls(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?)\"'")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _normalize_host(host: str) -> str:
    h = (host or "").lower()
    return h[4:] if h.startswith("www.") else h


def is_skipped_social_host(url: str) -> bool:
    host = _normalize_host(urlparse(url).hostname or "")
    return any(host == s or host.endswith("." + s) for s in _SKIP_HOST_SUFFIXES)


def filter_news_urls(
    urls: Iterable[str],
    allowed_hosts: set[str],
) -> list[str]:
    """Keep URLs whose host is in ``allowed_hosts`` (normalized, no www.)."""
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or is_skipped_social_host(url):
            continue
        host = _normalize_host(urlparse(url).hostname or "")
        if not host or host not in allowed_hosts:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out
