"""Daily OHLC fetcher with DB-backed caching.

Powers the per-company candle chart. Bars come from yfinance (free,
unlimited daily history) and land in the ``stock_ohlc`` table the first
time we see a window; subsequent calls for the same ticker hit the cache.

The window is ±10 trading days around the requested ``day``. We pull a
slightly wider calendar window (±21 days) to guarantee enough trading
days survive holidays/weekends, then trim to exactly 10 either side of
``day`` (or to whichever bars yfinance returned, when ``day`` itself is
near the edges of available history).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from finance_news.store import db

log = logging.getLogger("stocks")

CALENDAR_PADDING_DAYS = 21
DEFAULT_SPAN = 10
# Bars with all-NaN OHLC values (today's still-trading session before
# yfinance has filled it in) are rejected at insertion time — stale daily
# data is worse than missing data for a candle chart.
# We don't have a "dense enough" heuristic for the cache: long weekends
# and B3 holidays mean ±21 calendar days routinely yields 12-15 bars.
# Instead, we only refetch when the cache has zero bars in the window;
# everything else is a hit. Caller can force a refresh with ``warm_ticker``.


def _resolve_symbol(conn, ticker_root: str) -> str:
    """``PETR`` → ``PETR4.SA``. Falls back to ``<root>.SA`` if the
    companies table has no full ticker for the root.

    Index symbols starting with ``^`` (e.g. ``^BVSP``) are returned as-is
    since they are already valid yfinance symbols.
    """
    if ticker_root.startswith("^"):
        return ticker_root
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker FROM companies WHERE ticker_root = %s",
            (ticker_root,),
        )
        row = cur.fetchone()
    full = (row or {}).get("ticker") or ticker_root
    full = full.upper().strip()
    return full if full.endswith(".SA") else f"{full}.SA"


def _fetch_from_yfinance(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """yfinance ``Ticker.history`` → normalized bar dicts. Empty list on any
    failure or empty response (network error, unknown ticker, etc.)."""
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed")
        return []

    try:
        # ``end`` is exclusive in yfinance; bump by 1 day so the requested
        # day itself is included.
        hist = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
    except Exception as e:  # noqa: BLE001 — network / parsing soft-fail
        log.warning("%s: yfinance fetch failed: %s", symbol, e)
        return []

    if hist is None or hist.empty:
        return []

    bars: list[dict[str, Any]] = []
    for ts, row in hist.iterrows():
        bar_date = ts.date() if hasattr(ts, "date") else ts
        try:
            o, h, lo, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            if any(_isnan(v) for v in (o, h, lo, c)):
                # Today's bar before market close, or a holiday yfinance
                # included by mistake. Skip rather than poison the cache.
                continue
            bars.append({
                "bar_date": bar_date,
                "open": Decimal(str(round(o, 4))),
                "high": Decimal(str(round(h, 4))),
                "low": Decimal(str(round(lo, 4))),
                "close": Decimal(str(round(c, 4))),
                "volume": int(row["Volume"]) if not _isnan(row["Volume"]) else None,
            })
        except (KeyError, ValueError, TypeError) as e:
            log.debug("%s: skipping malformed row at %s: %s", symbol, bar_date, e)
    return bars


def _isnan(v: Any) -> bool:
    try:
        import math
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def _trim_to_span(bars: list[dict[str, Any]], day: date, span: int) -> list[dict[str, Any]]:
    """Return at most ``span`` bars on each side of ``day``. If ``day`` is
    not itself a trading day we anchor at the closest bar by date."""
    if not bars:
        return []
    bars = sorted(bars, key=lambda b: b["bar_date"])
    # Index of the bar closest to ``day`` (prefer the one on/before).
    anchor_idx = 0
    for i, b in enumerate(bars):
        if b["bar_date"] <= day:
            anchor_idx = i
        else:
            break
    lo = max(0, anchor_idx - span)
    hi = min(len(bars), anchor_idx + span + 1)
    return bars[lo:hi]


def fetch_ohlc_window(
    conn,
    ticker_root: str,
    day: date,
    *,
    span: int = DEFAULT_SPAN,
) -> list[dict[str, Any]]:
    """Daily bars centered on ``day``.

    First checks ``stock_ohlc`` for a dense-enough cached window; if the
    cache is sparse we hit yfinance, upsert, and re-read. Returns ≤
    ``2 * span + 1`` bars sorted by ``bar_date``. Empty list when the
    ticker has no data in either source.
    """
    start = day - timedelta(days=CALENDAR_PADDING_DAYS)
    end = day + timedelta(days=CALENDAR_PADDING_DAYS)

    cached = db.fetch_ohlc_range(conn, ticker_root=ticker_root, start=start, end=end)
    if cached:
        return _trim_to_span(_normalize_cached(cached), day, span)

    symbol = _resolve_symbol(conn, ticker_root)
    fresh = _fetch_from_yfinance(symbol, start, end)
    if fresh:
        db.upsert_ohlc(conn, ticker_root=ticker_root, bars=fresh)
        conn.commit()
        cached = db.fetch_ohlc_range(conn, ticker_root=ticker_root, start=start, end=end)

    return _trim_to_span(_normalize_cached(cached), day, span)


def _normalize_cached(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``fetch_ohlc_range`` returns Decimals; everything that consumes the
    bars will JSON-encode them, so leave them as Decimal for now (FastAPI
    handles Decimal). Just ensure the keys match what callers expect."""
    return rows


def fetch_ohlc_trailing(
    conn,
    ticker_root: str,
    end: date,
    *,
    days: int,
) -> list[dict[str, Any]]:
    """Daily bars in the trailing window ``[end - (days - 1), end]``.

    Hits the ``stock_ohlc`` cache first; on miss, pulls a wider calendar
    window from yfinance (`2 * days` calendar days back from ``end``)
    so weekends/holidays don't starve the cache, then re-reads.
    """
    start = end - timedelta(days=days - 1)
    fetch_start = end - timedelta(days=2 * days)

    cached = db.fetch_ohlc_range(conn, ticker_root=ticker_root, start=start, end=end)
    if cached:
        return _normalize_cached(cached)

    symbol = _resolve_symbol(conn, ticker_root)
    fresh = _fetch_from_yfinance(symbol, fetch_start, end)
    if fresh:
        db.upsert_ohlc(conn, ticker_root=ticker_root, bars=fresh)
        conn.commit()
        cached = db.fetch_ohlc_range(conn, ticker_root=ticker_root, start=start, end=end)
    return _normalize_cached(cached)


def warm_ticker(
    conn,
    ticker_root: str,
    day: date,
    *,
    span: int = DEFAULT_SPAN,
) -> Optional[int]:
    """Convenience for pipeline / scripts: force a yfinance roundtrip and
    return the number of bars upserted, or ``None`` on failure."""
    start = day - timedelta(days=CALENDAR_PADDING_DAYS)
    end = day + timedelta(days=CALENDAR_PADDING_DAYS)
    symbol = _resolve_symbol(conn, ticker_root)
    fresh = _fetch_from_yfinance(symbol, start, end)
    if not fresh:
        return None
    db.upsert_ohlc(conn, ticker_root=ticker_root, bars=fresh)
    conn.commit()
    return len(_trim_to_span(fresh, day, span))
