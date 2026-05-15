"""Ingest X/Twitter posts via Nitter RSS into ``social_posts`` (not ``articles``)."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news import logconfig
from finance_news.net.discovery import HEADERS, HTTP_TIMEOUT_S, SP_TZ, _in_sp_day, _strip_html
from finance_news.net.nitter import DEFAULT_ACCOUNTS, DEFAULT_SEARCH_QUERIES, _nitter_bases
from finance_news.store import db

log = logging.getLogger("social")
ProgressFn = Callable[[str, int, int], None]

INTER_SLEEP_S = 1.0


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _external_id(entry, fallback_url: str) -> str:
    gid = entry.get("id") or entry.get("guid")
    if gid:
        return str(gid)[:256]
    return hashlib.sha256(fallback_url.encode()).hexdigest()[:32]


def _author_from_entry(entry) -> Optional[str]:
    author = entry.get("author") or ""
    m = re.search(r"@(\w+)", author)
    return m.group(1) if m else None


def _fetch_nitter_rss(path: str) -> tuple[Optional[bytes], Optional[str]]:
    last_err: Optional[str] = None
    for base in _nitter_bases():
        url = f"{base.rstrip('/')}/{path.lstrip('/')}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT_S)
            if r.status_code == 200:
                return r.content, None
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = repr(e)
        time.sleep(INTER_SLEEP_S)
    return None, last_err


def _parse_tweets(payload: bytes, day: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    parsed = feedparser.parse(payload)
    for entry in getattr(parsed, "entries", []) or []:
        title = _strip_html(entry.get("title"))
        summary = _strip_html(entry.get("summary") or entry.get("description") or "")
        text = summary or title
        if not text:
            continue
        pub: Optional[datetime] = None
        if getattr(entry, "published_parsed", None):
            try:
                pub = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC"))
            except (TypeError, ValueError):
                pass
        if pub is not None and not _in_sp_day(pub, day):
            continue
        link = (entry.get("link") or "").strip()
        out.append({
            "external_id": _external_id(entry, link or text),
            "url": link or None,
            "author_handle": _author_from_entry(entry),
            "text": text,
            "posted_at": pub,
        })
    return out


def run_social_ingest(
    target_date: Optional[date] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Fetch tweets from Nitter RSS; store in ``social_posts``. Returns rows inserted."""
    if not _env_enabled("X_SOCIAL_INGEST", default=False):
        log.info("X_SOCIAL_INGEST disabled — skipping social ingest")
        return 0

    logconfig.silence_third_party()
    day = target_date or datetime.now(SP_TZ).date()
    log.info("Social ingest — date=%s", day)

    tasks: list[tuple[str, str]] = []
    max_search = int(os.environ.get("X_MAX_SEARCH_QUERIES", "12") or "12")
    queries_raw = os.environ.get("X_SEARCH_QUERIES", "")
    queries = (
        [q.strip() for q in queries_raw.split("|") if q.strip()]
        if queries_raw.strip()
        else list(DEFAULT_SEARCH_QUERIES)
    )
    for q in queries[:max_search]:
        tasks.append(("search", q))
    accounts_raw = os.environ.get("X_CURATED_ACCOUNTS", ",".join(DEFAULT_ACCOUNTS))
    for acc in accounts_raw.split(","):
        acc = acc.strip().lstrip("@")
        if acc:
            tasks.append(("account", acc))

    if not tasks:
        return 0

    if progress:
        progress("social", 0, len(tasks))

    inserted = 0
    with db.connect() as conn:
        for i, (kind, value) in enumerate(tasks):
            if kind == "search":
                path = f"search/rss?f=tweets&q={quote_plus(value)}"
            else:
                path = f"{value}/rss"
            payload, err = _fetch_nitter_rss(path)
            if not payload:
                log.warning("Nitter %s %r failed: %s", kind, value, err)
                if progress:
                    progress("social", i + 1, len(tasks))
                continue
            tweets = _parse_tweets(payload, day)
            for tw in tweets:
                if db.upsert_social_post(
                    conn,
                    platform="x",
                    external_id=tw["external_id"],
                    url=tw["url"],
                    author_handle=tw["author_handle"],
                    text=tw["text"],
                    posted_at=tw["posted_at"],
                ):
                    inserted += 1
            log.info("Social %s %r — %d tweet(s), %d new", kind, value, len(tweets), inserted)
            if progress:
                progress("social", i + 1, len(tasks))
            time.sleep(INTER_SLEEP_S)
        conn.commit()

    log.info("Social ingest complete — %d new post(s)", inserted)
    return inserted
