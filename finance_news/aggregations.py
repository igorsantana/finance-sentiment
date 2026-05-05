"""Shared aggregations consumed by the HTTP API.

``build_report_payload`` consumes raw psycopg dict rows from
``db.fetch_articles_for_date`` plus a ``sectors_lookup`` mapping
ticker_root → company info, and produces the ``ReportPayload`` dict
consumed by ``GET /api/reports/<date>``.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from finance_news.nlp.companies import translate_sector as _pt_sector

SP_TZ = ZoneInfo("America/Sao_Paulo")
SENTIMENT_KEYS = ("positive", "neutral", "negative")


def _tilt(pos: int, neg: int, total: int) -> float:
    return (pos - neg) / max(total, 1)


def build_report_payload(
    rows: list[dict[str, Any]],
    sectors_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Pre-aggregated payload for ``GET /api/reports/<date>``.

    ``rows`` are raw psycopg dict rows from ``articles``. ``sectors_lookup``
    maps ``ticker_root -> {short_name, sector}`` (built from the ``companies``
    table) so we can resolve tickers to display names + sector buckets without
    a second DB roundtrip per row.
    """
    total = len(rows)
    publishers = len({r.get("site") for r in rows if r.get("site")})

    by_sentiment = {k: 0 for k in SENTIMENT_KEYS}
    for r in rows:
        s = r.get("sentiment")
        if s in by_sentiment:
            by_sentiment[s] += 1

    company_counts: dict[str, Counter] = defaultdict(Counter)
    publisher_counts: dict[str, Counter] = defaultdict(Counter)
    sector_counts: dict[str, Counter] = defaultdict(Counter)
    sector_company_counts: dict[str, Counter] = defaultdict(Counter)
    hourly = [{"hour": h, "positive": 0, "neutral": 0, "negative": 0} for h in range(24)]
    subject_counter: Counter = Counter()
    ticker_counter: Counter = Counter()
    currency_counter: Counter = Counter()
    histogram = [
        {"bucketStart": i / 10, "bucketEnd": (i + 1) / 10, "count": 0}
        for i in range(10)
    ]

    for r in rows:
        sent = r.get("sentiment")
        site = r.get("site")
        tickers = list(r.get("matched_tickers") or [])
        names: list[str] = []
        sectors_for_row: set[str] = set()
        for t in tickers:
            entry = sectors_lookup.get(t)
            if not entry:
                continue
            short_name = entry.get("short_name")
            sector = entry.get("sector")
            if short_name:
                names.append(short_name)
            if sector:
                sectors_for_row.add(sector)

        if sent in by_sentiment:
            for n in names:
                company_counts[n][sent] += 1
            if site:
                publisher_counts[site][sent] += 1
            for sector in sectors_for_row:
                sector_counts[sector][sent] += 1
                for n in names:
                    sector_company_counts[sector][n] += 1

        for t in tickers:
            ticker_counter[t] += 1

        for s in (r.get("subjects") or []):
            subject_counter[s] += 1

        for c in (r.get("currencies") or []):
            currency_counter[c] += 1

        published = r.get("published_at")
        if published is not None and sent in by_sentiment:
            hour = published.astimezone(SP_TZ).hour
            hourly[hour][sent] += 1

        score = r.get("sentiment_score")
        if score is not None:
            idx = int(float(score) * 10)
            if idx < 0:
                idx = 0
            elif idx > 9:
                idx = 9
            histogram[idx]["count"] += 1

    top_companies = []
    for name, c in company_counts.items():
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        tot = pos + neu + neg
        top_companies.append({
            "name": name,
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "total": tot,
            "tilt": _tilt(pos, neg, tot),
        })
    top_companies.sort(key=lambda x: (x["total"], x["tilt"]), reverse=True)
    top_companies = top_companies[:20]

    sentiment_by_publisher = []
    for site, c in publisher_counts.items():
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        sentiment_by_publisher.append({
            "site": site,
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "total": pos + neu + neg,
        })
    sentiment_by_publisher.sort(key=lambda x: x["total"], reverse=True)
    sentiment_by_publisher = sentiment_by_publisher[:25]

    sector_matrix = []
    for sector, c in sector_counts.items():
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        tot = pos + neu + neg
        top_co = [n for n, _ in sector_company_counts[sector].most_common(2)]
        sector_matrix.append({
            "sector": _pt_sector(sector),
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "tilt": _tilt(pos, neg, tot),
            "topCompanies": top_co,
        })
    sector_matrix.sort(key=lambda x: x["tilt"], reverse=True)

    top_subjects = [{"subject": s, "count": n} for s, n in subject_counter.most_common(15)]
    top_tickers = [{"ticker": t, "count": n} for t, n in ticker_counter.most_common(15)]
    currencies = [{"currency": c, "count": n} for c, n in currency_counter.most_common()]

    return {
        "counts": {
            "total": total,
            "publishers": publishers,
            "bySentiment": by_sentiment,
        },
        "topCompanies": top_companies,
        "sentimentByPublisher": sentiment_by_publisher,
        "sectorMatrix": sector_matrix,
        "hourly": hourly,
        "topSubjects": top_subjects,
        "topTickers": top_tickers,
        "scoreHistogram": histogram,
        "currencies": currencies,
    }


def build_window_payload(
    rows: list[dict[str, Any]],
    sectors_lookup: dict[str, dict[str, Any]],
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    """Multi-day variant of ``build_report_payload`` for the trends page.

    Aggregates the same way over the whole window, plus a ``daily[]``
    series grouped by SP-date so the FE can draw the rolling sentiment
    line. Drops ``hourly`` and ``scoreHistogram`` (less useful at multi-
    day scale; keeps the payload lean).
    """
    total = len(rows)
    publishers = len({r.get("site") for r in rows if r.get("site")})

    by_sentiment = {k: 0 for k in SENTIMENT_KEYS}
    for r in rows:
        s = r.get("sentiment")
        if s in by_sentiment:
            by_sentiment[s] += 1

    company_counts: dict[str, Counter] = defaultdict(Counter)
    publisher_counts: dict[str, Counter] = defaultdict(Counter)
    sector_counts: dict[str, Counter] = defaultdict(Counter)
    sector_company_counts: dict[str, Counter] = defaultdict(Counter)
    subject_counter: Counter = Counter()
    ticker_counter: Counter = Counter()
    daily_counts: dict[date, Counter] = defaultdict(Counter)

    for r in rows:
        sent = r.get("sentiment")
        site = r.get("site")
        tickers = list(r.get("matched_tickers") or [])
        names: list[str] = []
        sectors_for_row: set[str] = set()
        for t in tickers:
            entry = sectors_lookup.get(t)
            if not entry:
                continue
            short_name = entry.get("short_name")
            sector = entry.get("sector")
            if short_name:
                names.append(short_name)
            if sector:
                sectors_for_row.add(sector)

        if sent in by_sentiment:
            for n in names:
                company_counts[n][sent] += 1
            if site:
                publisher_counts[site][sent] += 1
            for sector in sectors_for_row:
                sector_counts[sector][sent] += 1
                for n in names:
                    sector_company_counts[sector][n] += 1

        for t in tickers:
            ticker_counter[t] += 1
        for s in (r.get("subjects") or []):
            subject_counter[s] += 1

        published = r.get("published_at")
        if published is not None and sent in by_sentiment:
            day = published.astimezone(SP_TZ).date()
            if start <= day <= end:
                daily_counts[day][sent] += 1

    top_companies = []
    for name, c in company_counts.items():
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        tot = pos + neu + neg
        top_companies.append({
            "name": name,
            "positive": pos, "neutral": neu, "negative": neg,
            "total": tot, "tilt": _tilt(pos, neg, tot),
        })
    top_companies.sort(key=lambda x: (x["total"], x["tilt"]), reverse=True)
    top_companies = top_companies[:20]

    sentiment_by_publisher = []
    for site, c in publisher_counts.items():
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        sentiment_by_publisher.append({
            "site": site,
            "positive": pos, "neutral": neu, "negative": neg,
            "total": pos + neu + neg,
        })
    sentiment_by_publisher.sort(key=lambda x: x["total"], reverse=True)
    sentiment_by_publisher = sentiment_by_publisher[:25]

    sector_matrix = []
    for sector, c in sector_counts.items():
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        tot = pos + neu + neg
        top_co = [n for n, _ in sector_company_counts[sector].most_common(2)]
        sector_matrix.append({
            "sector": _pt_sector(sector),
            "positive": pos, "neutral": neu, "negative": neg,
            "tilt": _tilt(pos, neg, tot),
            "topCompanies": top_co,
        })
    sector_matrix.sort(key=lambda x: x["tilt"], reverse=True)

    daily = []
    cur = start
    while cur <= end:
        c = daily_counts.get(cur, Counter())
        pos, neu, neg = c["positive"], c["neutral"], c["negative"]
        tot = pos + neu + neg
        daily.append({
            "date": cur.isoformat(),
            "positive": pos, "neutral": neu, "negative": neg,
            "total": tot,
            "net": _tilt(pos, neg, tot),
        })
        cur = cur.fromordinal(cur.toordinal() + 1)

    top_subjects = [{"subject": s, "count": n} for s, n in subject_counter.most_common(15)]
    top_tickers = [{"ticker": t, "count": n} for t, n in ticker_counter.most_common(15)]

    return {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days + 1,
        },
        "counts": {
            "total": total,
            "publishers": publishers,
            "bySentiment": by_sentiment,
        },
        "topCompanies": top_companies,
        "sentimentByPublisher": sentiment_by_publisher,
        "sectorMatrix": sector_matrix,
        "topSubjects": top_subjects,
        "topTickers": top_tickers,
        "daily": daily,
    }
