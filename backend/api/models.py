"""SQLAlchemy ORM models backing the API."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    site: Mapped[str] = mapped_column(String, default="")
    source_kind: Mapped[str] = mapped_column(String, default="")
    source_key: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    published_at: Mapped[str] = mapped_column(String, default="")
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sentiment: Mapped[str] = mapped_column(String(16), default="")
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")

    subjects: Mapped[list] = mapped_column(JSON, default=list)
    matched_companies: Mapped[list] = mapped_column(JSON, default=list)
    matched_tickers: Mapped[list] = mapped_column(JSON, default=list)
    sectors: Mapped[list] = mapped_column(JSON, default=list)
    companies: Mapped[list] = mapped_column(JSON, default=list)
    persons: Mapped[list] = mapped_column(JSON, default=list)
    countries: Mapped[list] = mapped_column(JSON, default=list)
    currencies: Mapped[list] = mapped_column(JSON, default=list)
    conflicts: Mapped[list] = mapped_column(JSON, default=list)

    __table_args__ = (
        Index("ix_articles_date_sentiment", "date", "sentiment"),
    )


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    target_date: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    started_at: Mapped[str] = mapped_column(String, default="")
    finished_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    log_path: Mapped[str] = mapped_column(String, default="")
