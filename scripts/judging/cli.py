#!/usr/bin/env python3
"""Terminal TUI for human-judging articles.

One article per screen, single-key labels, writes into the ``judgments``
table. Re-labeling the same article is allowed (judgments has no unique
constraint on (article_url, judge)) but the default filter only shows
articles the current judge has not labeled yet.

Keys
----
  p  positive
  n  negative
  x  neutral
  b  bad_match     (the ticker match is wrong / article is not about it)
  s  skip          (recorded so we don't re-prompt this session)
  o  open URL in the default browser
  m  mark with a free-text note, then ask for a label
  u  undo last label (deletes the most recent judgment row in this session)
  q  quit
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import readchar

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from finance_news.store import db  # noqa: E402

LABEL_KEYS = {
    "p": "positive",
    "n": "negative",
    "x": "neutral",
    "b": "bad_match",
    "s": "skip",
}
LABEL_KEY_HELP = "[p]os [n]eg [x]neutral [b]ad_match [s]kip [o]pen [m]ark+note [u]ndo [q]uit"

logging.basicConfig(level=logging.WARNING)


def _default_judge() -> str:
    return os.environ.get("JUDGE_NAME") or os.environ.get("USER") or "anonymous"


def _clear() -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def _wrap(text: str, width: int = 100) -> str:
    return "\n".join(
        textwrap.fill(p, width=width) if p else ""
        for p in (text or "").splitlines()
    )


def _render(art: dict[str, Any], idx: int, total: int, last_action: str) -> None:
    _clear()
    print(f"[{idx + 1}/{total}]  {LABEL_KEY_HELP}")
    print("-" * 100)
    print(f"Title    : {art.get('title') or '(no title)'}")
    print(f"Site     : {art.get('site') or art.get('hostname') or '(unknown)'}")
    print(f"Ticker   : {art.get('source_ticker') or '-'}    "
          f"Matched: {', '.join(art.get('matched_tickers') or []) or '-'}")
    print(f"Model    : {art.get('sentiment') or '-'}    "
          f"Score: {art.get('sentiment_score') or '-'}")
    print(f"Published: {art.get('published_at') or '-'}    "
          f"Author: {art.get('author') or '-'}")
    print(f"URL      : {art.get('url')}")
    print(f"Conflicts: {', '.join(art.get('conflicts') or []) or '-'}")
    print("-" * 100)
    print(_wrap(art.get("summary") or art.get("text") or "")[:1800])
    print()
    if last_action:
        print(f"  → {last_action}")


def _prompt_notes() -> Optional[str]:
    sys.stdout.write("note> ")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.rstrip("\n")
    return line or None


def _record(
    conn, *, article_url: str, judge: str, label: str, notes: Optional[str]
) -> int:
    jid = db.insert_judgment(
        conn,
        article_url=article_url,
        judge=judge,
        label=label,
        notes=notes,
    )
    conn.commit()
    return jid


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--judge", default=_default_judge(),
                   help="Judge name (default: $JUDGE_NAME → $USER → 'anonymous')")
    p.add_argument("--ticker", help="Only show articles matching this ticker root.")
    p.add_argument("--sentiment", choices=("positive", "neutral", "negative"),
                   help="Only show articles the model labeled this way.")
    p.add_argument("--since",
                   help="ISO date/datetime; only articles published at/after.")
    p.add_argument("--only-matched", action="store_true",
                   help="Skip articles with no matched_tickers.")
    args = p.parse_args(argv)

    since: Optional[datetime] = None
    if args.since:
        since = datetime.fromisoformat(args.since)

    with db.connect() as conn:
        articles = list(db.iter_unjudged(
            conn,
            judge=args.judge,
            ticker=args.ticker.upper() if args.ticker else None,
            sentiment=args.sentiment,
            since=since,
            only_matched=args.only_matched,
        ))

    if not articles:
        print("Nothing to judge — all matching articles are already labeled.")
        return 0

    print(f"Judge: {args.judge}    {len(articles)} article(s) to review.")
    print("Press any key to start…", end="", flush=True)
    readchar.readkey()

    history: list[tuple[int, int]] = []  # (article_index, judgment_id)
    last_action = ""
    idx = 0
    with db.connect() as conn:
        while idx < len(articles):
            art = articles[idx]
            _render(art, idx, len(articles), last_action)
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                break
            key = (key or "").lower()

            if key == "q":
                break
            if key == "o":
                webbrowser.open(art["url"])
                last_action = f"opened {art['url']}"
                continue
            if key == "u":
                if not history:
                    last_action = "nothing to undo"
                    continue
                prev_idx, prev_jid = history.pop()
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM judgments WHERE id = %s", (prev_jid,))
                conn.commit()
                idx = prev_idx
                last_action = f"undid judgment #{prev_jid}"
                continue
            if key == "m":
                notes = _prompt_notes()
                sys.stdout.write("label (p/n/x/b)> ")
                sys.stdout.flush()
                lk = (readchar.readkey() or "").lower()
                if lk not in {"p", "n", "x", "b"}:
                    last_action = "mark cancelled"
                    continue
                label = LABEL_KEYS[lk]
                jid = _record(conn, article_url=art["url"], judge=args.judge,
                              label=label, notes=notes)
                history.append((idx, jid))
                last_action = f"recorded {label} (#{jid}) with note"
                idx += 1
                continue
            if key in LABEL_KEYS:
                label = LABEL_KEYS[key]
                jid = _record(conn, article_url=art["url"], judge=args.judge,
                              label=label, notes=None)
                history.append((idx, jid))
                last_action = f"recorded {label} (#{jid})"
                idx += 1
                continue
            last_action = f"unknown key: {key!r}"

    _clear()
    print(f"Done. {len(history)} judgment(s) recorded as {args.judge}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
