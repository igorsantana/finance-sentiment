#!/usr/bin/env python3
"""Apply pending SQL migrations from ``migrations/`` in lexical order.

Idempotent: each applied file is recorded in ``schema_migrations`` and skipped
on subsequent runs. Each migration runs in its own transaction.
"""
from __future__ import annotations

import sys
from pathlib import Path

from finance_news.store.db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def applied_versions(cur) -> set[str]:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute("SELECT version FROM schema_migrations")
    return {row["version"] for row in cur.fetchall()}


def main() -> int:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"no migrations found in {MIGRATIONS_DIR}")
        return 0

    with connect() as conn:
        with conn.cursor() as cur:
            done = applied_versions(cur)
        conn.commit()

        for path in files:
            version = path.stem
            if version in done:
                print(f"skip  {version}")
                continue
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
            print(f"apply {version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
