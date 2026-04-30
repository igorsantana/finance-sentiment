"""Shared aggregations consumed by both the PNG renderer and the HTTP API.

Two row shapes flow in:

- The CSV-style dict produced by ``finance_news.render.dashboard.load_rows`` —
  pipe-joined strings for ``matched_companies``, ``sectors``, etc. ``_tilt``,
  ``_parse_pipe``, ``build_company_df`` and ``build_sector_df`` operate on
  this shape (kept here so ``finance_news.render.report`` keeps working
  byte-for-byte).
- Raw psycopg dict rows from ``db.fetch_articles_for_date``. ``build_report_payload``
  consumes those plus a ``sectors_lookup`` mapping ticker_root → company info,
  and produces the ``ReportPayload`` dict consumed by ``GET /api/reports/<date>``.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from finance_news.nlp.companies import translate_sector as _pt_sector

SP_TZ = ZoneInfo("America/Sao_Paulo")
SENTIMENT_KEYS = ("positive", "neutral", "negative")


def _parse_pipe(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split("|") if x.strip()]


def _tilt(pos: int, neg: int, total: int) -> float:
    return (pos - neg) / max(total, 1)


def build_company_df(rows: list[dict]) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    articles: dict[str, list[dict]] = defaultdict(list)
    use_matched = any(r.get("matched_companies") for r in rows)
    field = "matched_companies" if use_matched else "companies"
    for r in rows:
        companies = _parse_pipe(r.get(field) or "")
        sent = r.get("sentiment", "")
        if not companies or not sent:
            continue
        for c in companies:
            counts[c][sent] += 1
            articles[c].append(r)
    return {"counts": counts, "articles": articles}


def build_sector_df(rows: list[dict]) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    companies: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        sectors = _parse_pipe(r.get("sectors") or "")
        co_names = _parse_pipe(r.get("matched_companies") or r.get("companies") or "")
        sent = r.get("sentiment", "")
        if not sectors or not sent:
            continue
        for s in sectors:
            counts[s][sent] += 1
            for c in co_names:
                companies[s][c] += 1
    return {"counts": counts, "companies": companies}


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
