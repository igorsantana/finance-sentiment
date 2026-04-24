"""SQLAlchemy engine, session factory, and DB helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from .models import Article, Base

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "app.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, future=True, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(engine, "connect")
def _enable_fk(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def upsert_articles(rows: Iterable[dict]) -> int:
    """Insert-or-update articles keyed on URL. Returns row count processed."""
    payload = list(rows)
    if not payload:
        return 0
    stmt = sqlite_insert(Article).values(payload)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in Article.__table__.columns
        if c.name not in ("id", "url")
    }
    stmt = stmt.on_conflict_do_update(index_elements=[Article.url], set_=update_cols)
    with SessionLocal() as s:
        s.execute(stmt)
        s.commit()
    return len(payload)


def get_session() -> Session:
    return SessionLocal()
