"""Pydantic response models for the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: str
    site: str
    source_kind: str
    source_key: str
    title: str
    url: str
    published_at: str
    author: Optional[str] = None
    sentiment: str
    sentiment_score: Optional[float] = None
    summary: str
    subjects: list[str] = []
    matched_companies: list[str] = []
    matched_tickers: list[str] = []
    sectors: list[str] = []
    companies: list[str] = []
    persons: list[str] = []
    countries: list[str] = []
    currencies: list[str] = []
    conflicts: list[str] = []


class NewsPage(BaseModel):
    date: str
    count: int
    total: int
    limit: int
    offset: int
    rows: list[ArticleOut]


class DateEntry(BaseModel):
    date: str
    article_count: int
    has_csv: bool
    has_dashboard: bool
    has_report: bool


class SentimentBucket(BaseModel):
    label: str
    count: int


class NamedCount(BaseModel):
    name: str
    count: int


class SummaryOut(BaseModel):
    date: str
    total: int
    sentiment: list[SentimentBucket]
    top_companies: list[NamedCount]
    top_sites: list[NamedCount]
    top_sectors: list[NamedCount]


class StageOut(BaseModel):
    name: str
    status: Literal["pending", "running", "success", "failed", "skipped"]
    exit_code: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class RunOut(BaseModel):
    run_id: str
    trigger: str
    target_date: str
    status: Literal["pending", "running", "success", "failed"]
    started_at: str
    finished_at: Optional[str] = None
    stages: list[StageOut]
    log_path: str


class RunCreate(BaseModel):
    date: Optional[str] = None
    stages: Optional[list[str]] = None


class HealthOut(BaseModel):
    status: str
    scheduler: str
    next_run: Optional[str] = None
    db: str
