"""Fetch the top-150 Brazilian listed companies by market cap from BrAPI.dev.

Run weekly (not daily). Writes `data/companies.csv` with:
    ticker, ticker_root, short_name, long_name, sector, market_cap

Requires env var BRAPI_TOKEN (free signup at https://brapi.dev).
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("fetch_top_companies")

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "companies.csv"
BRAPI_URL = "https://brapi.dev/api/quote/list"

# Suffixes to strip when deriving short_name from the long corporate name.
_NAME_SUFFIX_RE = re.compile(
    r"\s+(?:s\.?\s*a\.?|s/a|holding(?:s)?|participa[çc][õo]es|cia\.?|companhia)\b.*$",
    re.IGNORECASE,
)
_TICKER_CLASS_RE = re.compile(r"^([A-Z]{4})\d{1,2}$")


def ticker_root(ticker: str) -> str:
    m = _TICKER_CLASS_RE.match(ticker.strip().upper())
    return m.group(1) if m else ticker.strip().upper()


def short_name(long_name: str) -> str:
    name = (long_name or "").strip()
    name = _NAME_SUFFIX_RE.sub("", name)
    return name.strip(" .,-") or long_name


def fetch(token: str, limit: int = 150) -> list[dict]:
    params = {
        "sortBy": "market_cap_basic",
        "sortOrder": "desc",
        "limit": limit,
        "token": token,
    }
    r = requests.get(BRAPI_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    stocks = data.get("stocks") or data.get("results") or []
    if not stocks:
        raise RuntimeError(f"BrAPI returned no stocks: {data!r}")
    return stocks


def collapse_by_root(stocks: list[dict]) -> list[dict]:
    """Two tickers (ON/PN) may share a root; keep highest market_cap per root."""
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


def write_csv(stocks: list[dict], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in stocks:
        ticker = (s.get("stock") or "").strip().upper()
        long_name = (s.get("name") or "").strip()
        if not ticker or not long_name:
            continue
        rows.append({
            "ticker": ticker,
            "ticker_root": ticker_root(ticker),
            "short_name": short_name(long_name),
            "long_name": long_name,
            "sector": (s.get("sector") or "").strip(),
            "market_cap": int(float(s.get("market_cap") or 0)),
        })
    rows.sort(key=lambda r: r["market_cap"], reverse=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["ticker", "ticker_root", "short_name",
                        "long_name", "sector", "market_cap"],
        )
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=150)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if not token:
        log.error(
            "BRAPI_TOKEN env var is required. Get one for free at "
            "https://brapi.dev and export it: `export BRAPI_TOKEN=...`"
        )
        return 2

    log.info("Fetching top-%d from BrAPI by market cap…", args.limit)
    raw = fetch(token, args.limit)
    log.info("Got %d raw tickers", len(raw))
    collapsed = collapse_by_root(raw)
    log.info("Collapsed to %d distinct ticker roots", len(collapsed))
    n = write_csv(collapsed, args.out)
    log.info("Wrote %d rows → %s", n, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
