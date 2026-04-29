"""Resolve a URL to its publisher display name via the ``publishers`` table.

Wraps ``db.lookup_publisher`` with the progressive-suffix fallback that the
old ``ingest.publisher_from_url`` did (``a.b.c`` → ``b.c`` → ``c``) and a
final tldextract-based fallback for hostnames the table doesn't know.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

import tldextract

from finance_news.store import db


def host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def lookup_progressive(conn, hostname: str) -> Optional[dict[str, Any]]:
    """Walk hostname suffixes (longest → shortest) and return the first
    publisher row that matches. ``None`` if nothing in the table matches."""
    if not hostname:
        return None
    parts = hostname.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        row = db.lookup_publisher(conn, candidate)
        if row:
            return row
    return None


def publisher_from_url(conn, url: str) -> str:
    """Display name for an article URL.

    Matches progressively shorter hostnames so e.g. ``m.valor.globo.com``
    still resolves to ``valor.globo.com``. Falls back to the registered-domain
    label (capitalized) so callers always get *something* renderable.
    """
    host = host_key(url)
    row = lookup_progressive(conn, host)
    if row:
        return row["display_name"]
    ext = tldextract.extract(url)
    if ext.domain:
        return ext.domain.capitalize()
    return host.capitalize() or "Publicação desconhecida"
