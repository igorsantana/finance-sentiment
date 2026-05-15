"""Reddit link-aggregation discovery (r/investimentos, r/b3)."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from finance_news.net.discovery import (
    AdapterResult,
    DiscoveredArticle,
    HEADERS,
    HTTP_TIMEOUT_S,
    SP_TZ,
    _in_sp_day,
    _strip_html,
)
from finance_news.net.social_links import extract_http_urls, filter_news_urls

log = logging.getLogger("discovery")

DEFAULT_SUBREDDITS = ("investimentos", "b3")


@dataclass
class RedditListingAdapter:
    """Fetch hot posts from BR finance subreddits; emit linked news URLs."""
    subreddit: str
    sort: str = "hot"
    limit: int = 50
    allowed_hosts: set[str] = None  # type: ignore[assignment]
    name: str = ""
    hostname: str = "reddit.com"

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"Reddit r/{self.subreddit}"
        if self.allowed_hosts is None:
            self.allowed_hosts = set()

    def list_today(self, day: date) -> AdapterResult:
        result = AdapterResult(publisher=self.name, hostname=self.hostname)
        t0 = time.perf_counter()
        url = f"https://www.reddit.com/r/{self.subreddit}/{self.sort}.json"
        params = {"limit": self.limit, "raw_json": "1"}
        try:
            r = requests.get(
                url, params=params, headers={
                    **HEADERS,
                    "User-Agent": "finance_news/1.0 (BR finance ingest)",
                },
                timeout=HTTP_TIMEOUT_S,
            )
            result.http_calls = 1
            if r.status_code != 200:
                result.error = f"HTTP {r.status_code}"
                return result
            payload = r.json()
        except Exception as e:
            result.error = repr(e)
            return result
        finally:
            result.elapsed_s = time.perf_counter() - t0

        children = (
            payload.get("data", {}).get("children") or []
        )
        seen: set[str] = set()
        for child in children:
            data = child.get("data") or {}
            title = _strip_html(data.get("title"))
            selftext = data.get("selftext") or ""
            link = (data.get("url") or "").strip()
            created = data.get("created_utc")
            pub: Optional[datetime] = None
            if created is not None:
                pub = datetime.fromtimestamp(float(created), tz=ZoneInfo("UTC"))
            if pub is not None and not _in_sp_day(pub, day):
                continue

            candidates: list[str] = []
            if link and "reddit.com" not in link and "redd.it" not in link:
                candidates.append(link)
            candidates.extend(extract_http_urls(selftext))
            candidates.extend(extract_http_urls(title))

            for news_url in filter_news_urls(candidates, self.allowed_hosts):
                if news_url in seen:
                    continue
                seen.add(news_url)
                result.articles.append(DiscoveredArticle(
                    url=news_url,
                    title=title,
                    excerpt=_strip_html(selftext)[:500],
                    publisher=self.name,
                    publisher_host=self.hostname,
                    published_at=pub,
                ))
        return result


def reddit_adapters(allowed_hosts: set[str]) -> list[RedditListingAdapter]:
    subs = os.environ.get("REDDIT_SUBREDDITS", ",".join(DEFAULT_SUBREDDITS))
    sub_list = [s.strip() for s in subs.split(",") if s.strip()]
    return [
        RedditListingAdapter(sub, allowed_hosts=allowed_hosts)
        for sub in sub_list
    ]
