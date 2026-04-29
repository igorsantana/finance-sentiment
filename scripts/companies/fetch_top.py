#!/usr/bin/env python3
"""Fetch every Brazilian listed company tracked by BrAPI.dev and upsert it
into the ``companies`` table.

BrAPI's free tier silently broke the bulk ``/api/quote/list`` endpoint and
caps batched ``/api/quote/<sym1,sym2,…>`` calls at three symbols per
request. To get the full universe we:

  1. Hit ``/api/available`` for every symbol BrAPI knows (~1800).
  2. Filter to B3-shaped tickers (``^[A-Z]{4}\\d{1,2}$``) and collapse by
     ticker root (PETR3 + PETR4 → PETR).
  3. Fan out parallel ``/api/quote/<a,b,c>`` requests in batches of 3 to
     pull short_name / long_name. ``market_cap`` and ``sector`` are not
     exposed on the free tier, so they're stored as NULL.

Run weekly. Requires ``BRAPI_TOKEN`` and ``DATABASE_URL``. Pass ``--limit
N`` to cap the fetch.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news.store import db

log = logging.getLogger("fetch_top_companies")

BRAPI_AVAILABLE = "https://brapi.dev/api/available"
BRAPI_QUOTE = "https://brapi.dev/api/quote/"
BRAPI_LIST = "https://brapi.dev/api/quote/list"

_NAME_SUFFIX_RE = re.compile(
    r"\s+(?:s\.?\s*a\.?|s/a|holding(?:s)?|participa[çc][õo]es|cia\.?|companhia)\b.*$",
    re.IGNORECASE,
)
_TICKER_CLASS_RE = re.compile(r"^([A-Z]{4})\d{1,2}$")
_BATCH = 3   # BrAPI free-tier ceiling — anything bigger silently returns 0.
_WORKERS = 8


def ticker_root(ticker: str) -> str:
    m = _TICKER_CLASS_RE.match(ticker.strip().upper())
    return m.group(1) if m else ticker.strip().upper()


def short_name(long_name: str) -> str:
    name = (long_name or "").strip()
    name = _NAME_SUFFIX_RE.sub("", name)
    return name.strip(" .,-") or long_name


def _try_quote_list(token: str, limit: Optional[int]) -> list[dict]:
    """Fast path. If a paid plan re-enables ``/api/quote/list`` we'll pick
    up the full payload (with market_cap + sector) in one request."""
    params = {
        "sortBy": "market_cap_basic",
        "sortOrder": "desc",
        "limit": limit if limit and limit > 0 else 500,
        "token": token,
    }
    try:
        r = requests.get(BRAPI_LIST, params=params, timeout=60)
        r.raise_for_status()
        return r.json().get("stocks") or []
    except requests.RequestException as e:
        log.debug("quote/list failed: %s", e)
        return []


def _b3_symbols(token: str) -> list[str]:
    r = requests.get(BRAPI_AVAILABLE, params={"token": token}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    out: list[str] = []
    for sym in payload.get("stocks", []):
        if _TICKER_CLASS_RE.match(sym):
            out.append(sym)
    return out


def _representative_per_root(symbols: Iterable[str]) -> list[str]:
    """Pick one ticker per root. Prefer ON (3) > PN (4) > Unit (11) > others."""
    pref = {"3": 0, "4": 1, "11": 2}
    by_root: dict[str, str] = {}
    rank: dict[str, int] = {}
    for s in symbols:
        m = _TICKER_CLASS_RE.match(s)
        if not m:
            continue
        root = m.group(1)
        cls = s[len(root):]
        score = pref.get(cls, 99)
        if root not in by_root or score < rank[root]:
            by_root[root] = s
            rank[root] = score
    return sorted(by_root.values())


def _fetch_quote_batch(token: str, batch: list[str]) -> list[dict]:
    url = BRAPI_QUOTE + ",".join(batch)
    try:
        r = requests.get(url, params={"token": token}, timeout=30)
        r.raise_for_status()
        return r.json().get("results") or []
    except requests.RequestException as e:
        log.debug("quote batch %s failed: %s", batch, e)
        return []


def _enrich(token: str, symbols: list[str]) -> list[dict]:
    """Parallel fan-out over /api/quote/<batch-of-3>."""
    batches = [symbols[i:i + _BATCH] for i in range(0, len(symbols), _BATCH)]
    log.info("Enriching %d symbols across %d batches…", len(symbols), len(batches))
    rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        futs = {ex.submit(_fetch_quote_batch, token, b): b for b in batches}
        for fut in as_completed(futs):
            done += 1
            for q in fut.result():
                sym = (q.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                rows.append({
                    "stock": sym,
                    "name": (q.get("longName") or q.get("shortName") or "").strip(),
                    "short_name": (q.get("shortName") or "").strip(),
                    "sector": q.get("sector") or "",
                    "market_cap": q.get("marketCap") or 0,
                })
            if done % 50 == 0:
                log.info("  …%d/%d batches", done, len(batches))
    return rows


def collapse_by_root(stocks: list[dict]) -> list[dict]:
    """Same root + multiple share classes → keep the highest market_cap."""
    by_root: dict[str, dict] = {}
    for s in stocks:
        ticker = (s.get("stock") or "").strip().upper()
        if not ticker:
            continue
        root = ticker_root(ticker)
        mcap = float(s.get("market_cap") or 0)
        prev = by_root.get(root)
        if prev is None or mcap > float(prev.get("market_cap") or 0):
            by_root[root] = s
    return list(by_root.values())


def write_db(stocks: list[dict]) -> int:
    n = 0
    with db.connect() as conn:
        for s in stocks:
            ticker = (s.get("stock") or "").strip().upper()
            long_name = (s.get("name") or "").strip()
            sn = (s.get("short_name") or "").strip() or short_name(long_name)
            if not ticker:
                continue
            db.upsert_company(
                conn,
                ticker_root=ticker_root(ticker),
                ticker=ticker,
                short_name=sn or ticker_root(ticker),
                long_name=long_name or sn or ticker,
                sector=(s.get("sector") or "").strip() or None,
                market_cap=int(float(s.get("market_cap") or 0)) or None,
            )
            n += 1
        conn.commit()
    return n


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0,
                   help="Cap the fetch at N ticker roots. 0 (default) = no cap.")
    args = p.parse_args(argv)

    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if not token:
        log.error("BRAPI_TOKEN env var is required (https://brapi.dev).")
        return 2

    # Fast path: if /quote/list is alive, use it (one request, full data).
    raw = _try_quote_list(token, args.limit)
    if raw:
        log.info("quote/list returned %d stocks; using fast path.", len(raw))
    else:
        log.info("quote/list empty — falling back to /available + /quote.")
        symbols = _b3_symbols(token)
        log.info("BrAPI knows %d B3-shaped tickers", len(symbols))
        chosen = _representative_per_root(symbols)
        log.info("Collapsed to %d ticker roots", len(chosen))
        if args.limit > 0:
            chosen = chosen[: args.limit]
        raw = _enrich(token, chosen)

    log.info("Got %d raw tickers", len(raw))
    collapsed = collapse_by_root(raw)
    log.info("Collapsed to %d distinct ticker roots", len(collapsed))
    n = write_db(collapsed)
    log.info("Upserted %d companies", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
