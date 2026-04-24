"""Enumerate available dates by joining DB counts with on-disk artifacts."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import Article

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = ROOT / "data"


def _artifact_flags(date: str) -> tuple[bool, bool, bool]:
    csv = (DATA_DIR / f"news_{date}.csv").is_file()
    dash = (DATA_DIR / "images" / date / "dashboard.png").is_file()
    rep = (DATA_DIR / "images" / date / "report.png").is_file()
    return csv, dash, rep


def available_dates() -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(
            select(Article.date, func.count(Article.id))
            .group_by(Article.date)
            .order_by(Article.date.desc())
        ).all()
    out: list[dict] = []
    for date, count in rows:
        csv, dash, rep = _artifact_flags(date)
        out.append({
            "date": date,
            "article_count": int(count),
            "has_csv": csv,
            "has_dashboard": dash,
            "has_report": rep,
        })
    return out
