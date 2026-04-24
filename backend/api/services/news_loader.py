"""Query articles + aggregates from the DB."""
from __future__ import annotations

from collections import Counter
from typing import Optional

from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import Article


def rows(
    date: str,
    limit: int = 500,
    offset: int = 0,
    sentiment: Optional[str] = None,
    company: Optional[str] = None,
    site: Optional[str] = None,
) -> tuple[list[Article], int]:
    """Return (page, total) for a given date with optional filters."""
    with SessionLocal() as s:
        base = select(Article).where(Article.date == date)
        if sentiment:
            base = base.where(Article.sentiment == sentiment)
        if site:
            base = base.where(Article.site == site)
        if company:
            # JSON arrays: fall back to substring match on the serialized JSON.
            base = base.where(
                func.instr(func.json(Article.matched_companies), company) > 0
            )

        total = s.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()
        page = (
            s.execute(
                base.order_by(Article.published_at.desc(), Article.id.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return list(page), int(total)


def summary(date: str, top_n: int = 10) -> dict:
    with SessionLocal() as s:
        total = s.execute(
            select(func.count(Article.id)).where(Article.date == date)
        ).scalar_one()

        if total == 0:
            return {
                "date": date,
                "total": 0,
                "sentiment": [],
                "top_companies": [],
                "top_sites": [],
                "top_sectors": [],
            }

        sentiment_rows = s.execute(
            select(Article.sentiment, func.count(Article.id))
            .where(Article.date == date)
            .group_by(Article.sentiment)
            .order_by(func.count(Article.id).desc())
        ).all()

        site_rows = s.execute(
            select(Article.site, func.count(Article.id))
            .where(Article.date == date, Article.site != "")
            .group_by(Article.site)
            .order_by(func.count(Article.id).desc())
            .limit(top_n)
        ).all()

        # JSON arrays: load the columns and count in Python (small N).
        json_rows = s.execute(
            select(Article.matched_companies, Article.sectors).where(
                Article.date == date
            )
        ).all()

    companies_counter: Counter[str] = Counter()
    sectors_counter: Counter[str] = Counter()
    for companies, sectors in json_rows:
        companies_counter.update(companies or [])
        sectors_counter.update(sectors or [])

    return {
        "date": date,
        "total": int(total),
        "sentiment": [
            {"label": (label or "unknown"), "count": int(count)}
            for label, count in sentiment_rows
        ],
        "top_companies": [
            {"name": n, "count": c}
            for n, c in companies_counter.most_common(top_n)
        ],
        "top_sites": [
            {"name": (name or "—"), "count": int(count)}
            for name, count in site_rows
        ],
        "top_sectors": [
            {"name": n, "count": c}
            for n, c in sectors_counter.most_common(top_n)
        ],
    }
