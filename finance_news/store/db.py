"""Postgres access layer.

This is the only module that talks to the database. Everything else goes
through these helpers so SQL stays in one place and we never accidentally
build queries with string interpolation.

All queries are parameterized. Rows are returned as ``dict``s via
``psycopg.rows.dict_row``; insert/update helpers return either ``None`` or
the newly assigned id.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return dsn


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection with dict rows. Commits on clean exit."""
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        yield conn


# ---------- companies ----------

def upsert_company(
    conn: psycopg.Connection,
    *,
    ticker_root: str,
    ticker: str,
    short_name: Optional[str],
    long_name: Optional[str],
    sector: Optional[str],
    market_cap: Optional[int],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies
                (ticker_root, ticker, short_name, long_name, sector, market_cap, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (ticker_root) DO UPDATE SET
                ticker     = EXCLUDED.ticker,
                short_name = EXCLUDED.short_name,
                long_name  = EXCLUDED.long_name,
                sector     = EXCLUDED.sector,
                market_cap = EXCLUDED.market_cap,
                fetched_at = now()
            """,
            (ticker_root, ticker, short_name, long_name, sector, market_cap),
        )


# ---------- publishers ----------

def lookup_publisher(
    conn: psycopg.Connection, hostname: str
) -> Optional[dict[str, Any]]:
    """Exact-hostname lookup. The progressive-suffix fallback that ingest
    needs (`a.b.c` → `b.c` → `c`) lives in ``finance_news.publishers``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM publishers WHERE hostname = %s",
            (hostname,),
        )
        return cur.fetchone()


# ---------- articles ----------

def upsert_article(
    conn: psycopg.Connection,
    *,
    url: str,
    title: Optional[str],
    text: Optional[str],
    author: Optional[str],
    site: Optional[str],
    hostname: Optional[str],
    published_at: Optional[datetime],
    source_ticker: Optional[str],
) -> bool:
    """Insert a freshly fetched article. Returns True if a row was inserted,
    False if the URL already existed (DB-level dedup)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articles
                (url, title, text, author, site, hostname,
                 published_at, source_ticker, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (url) DO NOTHING
            """,
            (url, title, text, author, site, hostname, published_at, source_ticker),
        )
        return cur.rowcount == 1


def iter_unextracted(
    conn: psycopg.Connection,
    *,
    for_date: Optional[date] = None,
    batch_size: int = 200,
) -> Iterator[dict[str, Any]]:
    """Stream articles that still need sentiment analysis. ``for_date``
    narrows to articles whose published date matches in America/Sao_Paulo —
    the cron's reference TZ."""
    sql = (
        "SELECT url, title, text, author, hostname, site, "
        "published_at, source_ticker "
        "FROM articles WHERE sentiment IS NULL"
    )
    params: list[Any] = []
    if for_date is not None:
        sql += " AND (published_at AT TIME ZONE 'America/Sao_Paulo')::date = %s"
        params.append(for_date)
    sql += " ORDER BY published_at DESC NULLS LAST"
    with conn.cursor(name="iter_unextracted") as cur:
        cur.itersize = batch_size
        cur.execute(sql, params)
        for row in cur:
            yield row


def update_extraction(
    conn: psycopg.Connection,
    *,
    url: str,
    sentiment: str,
    sentiment_score: Optional[float],
    subjects: list[str],
    companies_ner: list[str],
    persons: list[str],
    countries: list[str],
    currencies: list[str],
    matched_tickers: list[str],
    conflicts: list[str],
    summary: Optional[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE articles SET
                sentiment        = %s,
                sentiment_score  = %s,
                subjects         = %s,
                companies_ner    = %s,
                persons          = %s,
                countries        = %s,
                currencies       = %s,
                matched_tickers  = %s,
                conflicts        = %s,
                summary          = %s,
                extracted_at     = now()
            WHERE url = %s
            """,
            (
                sentiment,
                sentiment_score,
                subjects,
                companies_ner,
                persons,
                countries,
                currencies,
                matched_tickers,
                conflicts,
                summary,
                url,
            ),
        )


def fetch_articles_for_date(
    conn: psycopg.Connection, day: date
) -> list[dict[str, Any]]:
    """Articles whose published date matches ``day`` in America/Sao_Paulo
    (the pipeline's reference TZ — Postgres' session TZ defaults to UTC,
    which would silently shift evening articles into the next day)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM articles
            WHERE (published_at AT TIME ZONE 'America/Sao_Paulo')::date = %s
            ORDER BY published_at DESC
            """,
            (day,),
        )
        return cur.fetchall()


# ---------- judgments ----------

def insert_judgment(
    conn: psycopg.Connection,
    *,
    article_url: str,
    judge: str,
    label: str,
    notes: Optional[str] = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO judgments(article_url, judge, label, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (article_url, judge, label, notes),
        )
        return cur.fetchone()["id"]


def iter_unjudged(
    conn: psycopg.Connection,
    *,
    judge: str,
    ticker: Optional[str] = None,
    sentiment: Optional[str] = None,
    since: Optional[datetime] = None,
    only_matched: bool = False,
) -> Iterator[dict[str, Any]]:
    """Articles that ``judge`` has not labeled yet, with optional filters."""
    clauses: list[str] = [
        "NOT EXISTS (SELECT 1 FROM judgments j "
        "WHERE j.article_url = a.url AND j.judge = %(judge)s)"
    ]
    params: dict[str, Any] = {"judge": judge}
    if ticker:
        clauses.append("(%(ticker)s = ANY(a.matched_tickers) OR a.source_ticker = %(ticker)s)")
        params["ticker"] = ticker
    if sentiment:
        clauses.append("a.sentiment = %(sentiment)s")
        params["sentiment"] = sentiment
    if since:
        clauses.append("a.published_at >= %(since)s")
        params["since"] = since
    if only_matched:
        clauses.append("array_length(a.matched_tickers, 1) > 0")

    sql = (
        "SELECT * FROM articles a WHERE "
        + " AND ".join(clauses)
        + " ORDER BY a.published_at DESC NULLS LAST"
    )
    with conn.cursor(name="iter_unjudged") as cur:
        cur.execute(sql, params)
        for row in cur:
            yield row


# ---------- runs ----------

def record_run_start(conn: psycopg.Connection, kind: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runs(kind, status) VALUES (%s, 'running') RETURNING id",
            (kind,),
        )
        run_id = cur.fetchone()["id"]
    conn.commit()
    return run_id


def record_run_end(
    conn: psycopg.Connection,
    *,
    run_id: int,
    status: str,
    n_fetched: Optional[int] = None,
    n_extracted: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET
                finished_at = now(),
                status      = %s,
                n_fetched   = %s,
                n_extracted = %s,
                error       = %s
            WHERE id = %s
            """,
            (status, n_fetched, n_extracted, error, run_id),
        )
    conn.commit()
