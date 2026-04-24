"""GET /api/news/{date} and /api/summary/{date}."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..schemas import ArticleOut, NewsPage, SummaryOut
from ..services import news_loader
from ._common import validate_date

router = APIRouter()


@router.get("/news/{date}", response_model=NewsPage)
def get_news(
    date: str,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    sentiment: Optional[str] = None,
    company: Optional[str] = None,
    site: Optional[str] = None,
) -> dict:
    validate_date(date)
    page, total = news_loader.rows(
        date, limit=limit, offset=offset,
        sentiment=sentiment, company=company, site=site,
    )
    return {
        "date": date,
        "count": len(page),
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": [ArticleOut.model_validate(a) for a in page],
    }


@router.get("/summary/{date}", response_model=SummaryOut)
def get_summary(date: str) -> dict:
    validate_date(date)
    out = news_loader.summary(date)
    if out["total"] == 0:
        raise HTTPException(status_code=404, detail=f"no articles for {date}")
    return out
