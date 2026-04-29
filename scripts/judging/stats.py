#!/usr/bin/env python3
"""Aggregate model-vs-human stats from the ``judgments`` table.

Three views:
  1. Confusion matrix — model sentiment (rows) vs human label (cols).
  2. Top tickers flagged ``bad_match`` (model said the article was about the
     ticker; humans disagreed).
  3. Agreement rate by sector (companies join → sector).

A judgment ``label`` outside {positive, neutral, negative} (i.e. ``skip`` or
``bad_match``) is excluded from the confusion matrix; ``skip`` is dropped
entirely from agreement stats.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news.store import db  # noqa: E402

SENTIMENT_LABELS = ("positive", "neutral", "negative")


def _print_table(title: str, header: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in header]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    print(title)
    print("-" * (sum(widths) + 3 * (len(header) - 1)))
    print("   ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
    for r in rows:
        print("   ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    print()


def confusion_matrix(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.sentiment AS model, j.label AS human, count(*) AS n
            FROM judgments j JOIN articles a ON a.url = j.article_url
            WHERE j.label IN ('positive','neutral','negative')
              AND a.sentiment IN ('positive','neutral','negative')
            GROUP BY a.sentiment, j.label
            ORDER BY a.sentiment, j.label
            """
        )
        cells = {(r["model"], r["human"]): r["n"] for r in cur.fetchall()}

    rows: list[list[str]] = []
    for model in SENTIMENT_LABELS:
        row: list[str] = [f"model={model}"]
        for human in SENTIMENT_LABELS:
            row.append(str(cells.get((model, human), 0)))
        rows.append(row)
    _print_table(
        "Confusion matrix (rows = model, cols = human)",
        [""] + [f"h={h}" for h in SENTIMENT_LABELS],
        rows,
    )


def bad_match_top(conn, limit: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.source_ticker AS ticker, count(*) AS n
            FROM judgments j JOIN articles a ON a.url = j.article_url
            WHERE j.label = 'bad_match' AND a.source_ticker IS NOT NULL
            GROUP BY a.source_ticker
            ORDER BY n DESC, a.source_ticker
            LIMIT %s
            """,
            (limit,),
        )
        rows = [[r["ticker"], r["n"]] for r in cur.fetchall()]
    _print_table(f"Top {limit} bad_match tickers", ["ticker", "n"], rows or [["—", "0"]])


def agreement_by_sector(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.sector,
                   count(*) FILTER (
                     WHERE j.label = a.sentiment
                       AND j.label IN ('positive','neutral','negative')
                   ) AS agreed,
                   count(*) FILTER (
                     WHERE j.label IN ('positive','neutral','negative')
                       AND a.sentiment IN ('positive','neutral','negative')
                   ) AS total
            FROM judgments j
            JOIN articles a  ON a.url = j.article_url
            LEFT JOIN companies c ON c.ticker_root = a.source_ticker
            GROUP BY c.sector
            ORDER BY total DESC NULLS LAST
            """
        )
        rows: list[list[str]] = []
        for r in cur.fetchall():
            total = r["total"] or 0
            agreed = r["agreed"] or 0
            rate = f"{agreed / total:.0%}" if total else "—"
            rows.append([r["sector"] or "(unknown)", agreed, total, rate])
    _print_table(
        "Agreement by sector",
        ["sector", "agreed", "total", "rate"],
        rows or [["—", 0, 0, "—"]],
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=10)
    args = p.parse_args(argv)

    with db.connect() as conn:
        confusion_matrix(conn)
        bad_match_top(conn, args.top)
        agreement_by_sector(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
