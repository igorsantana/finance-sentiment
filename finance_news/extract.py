"""Stage 2: load raw_articles.jsonl, run NER + currency regex, write final CSV."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from . import analysis, companies as companies_mod, entities, logconfig  # noqa: F401

log = logging.getLogger("extract")

ROOT = Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "data" / "raw_articles.jsonl"
OUT_DIR = ROOT / "data"
COMPANIES_CSV = ROOT / "data" / "companies.csv"

SP_TZ = ZoneInfo("America/Sao_Paulo")

COLUMNS = [
    "site", "source_kind", "source_key",
    "title", "url", "published_at", "author",
    "subjects", "sentiment", "sentiment_score",
    "matched_companies", "matched_tickers", "sectors",
    "companies", "persons", "countries", "currencies",
    "conflicts", "summary",
]


def _summary(text: str, n: int = 280) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:n]


def _env_workers(default: int = 4) -> int:
    raw = os.environ.get("WORKERS")
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default


def _process_article(art: dict, matcher, sentiment) -> Optional[dict]:
    """Run NER + subjects + sentiment + matcher for a single article.

    Returns the row dict, or None on fatal NER error (we drop the article).
    spaCy's `nlp()` and HuggingFace pipelines release the GIL during the
    heavy native compute, so ThreadPoolExecutor gives real parallel speedup.
    """
    title = art.get("title") or ""
    body = art.get("text") or ""
    text = title + "\n" + body
    url = art["url"]
    try:
        ents = entities.analyze(text)
    except Exception as e:
        log.debug("NER failed on %s: %s", url, e)
        return None

    try:
        subjects = analysis.rank_subjects(
            ents["doc"], title, ents["companies"], ents["persons"]
        )
    except Exception as e:
        log.debug("subject ranking failed on %s: %s", url, e)
        subjects = []

    try:
        sent = sentiment.predict(title, body)
    except Exception as e:
        log.debug("sentiment failed on %s: %s", url, e)
        sent = analysis.SentimentResult(label="", score=0.0)

    author = art.get("author") or ""
    conflicts = analysis.detect_conflicts(
        art.get("site", ""), author, subjects
    )

    matches = matcher.match(text, doc=ents.get("doc"))
    matched_names = [m.short_name for m in matches]
    matched_tickers = [m.ticker_root for m in matches]
    sectors = sorted({m.sector for m in matches if m.sector})

    return {
        "row": {
            "site": art.get("site", ""),
            "source_kind": art.get("source_kind", ""),
            "source_key": art.get("source_key", ""),
            "title": title,
            "url": url,
            "published_at": art.get("published") or "",
            "author": author,
            "subjects": "|".join(subjects),
            "sentiment": sent.label,
            "sentiment_score": f"{sent.score:.4f}" if sent.score else "",
            "matched_companies": "|".join(matched_names),
            "matched_tickers": "|".join(matched_tickers),
            "sectors": "|".join(sectors),
            "companies": "|".join(ents["companies"]),
            "persons": "|".join(ents["persons"]),
            "countries": "|".join(ents["countries"]),
            "currencies": "|".join(ents["currencies"]),
            "conflicts": "|".join(conflicts),
            "summary": _summary(body),
        },
        "has_matches": bool(matches),
    }


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, default=IN_PATH)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--companies-file", type=Path, default=COMPANIES_CSV,
                   dest="companies_file")
    p.add_argument("--companies-only", action="store_true",
                   help="Drop articles that don't mention any top-150 company.")
    p.add_argument(
        "--workers", type=int, default=None,
        help=(
            "Parallel worker threads for NER + sentiment. "
            "Overrides WORKERS env var (default 4)."
        ),
    )
    p.add_argument(
        "--date",
        help="Label used in the output filename. Default: today in America/Sao_Paulo.",
    )
    args = p.parse_args(argv)

    if not args.in_path.exists():
        log.error("Input file missing: %s", args.in_path)
        return 2

    day = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(SP_TZ).date()
    )
    out_path = args.out_dir / f"news_{day.isoformat()}.csv"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    workers = args.workers if args.workers and args.workers > 0 else _env_workers()
    log.info("Using %d extraction worker(s)", workers)

    # Warm up spaCy and sentiment models ONCE on the main thread before
    # spawning workers — otherwise every thread races to load and we pay
    # the model-load cost N times (and can OOM).
    entities.get_nlp()
    sentiment = analysis.SentimentAnalyzer()
    sentiment._load()  # force eager load

    company_list = companies_mod.load_companies(args.companies_file)
    matcher = companies_mod.CompanyMatcher(company_list)
    if company_list:
        log.info("Loaded %d companies for matching", len(company_list))
    else:
        log.info(
            "No companies loaded from %s — matched_companies will be empty",
            args.companies_file,
        )

    # Read and dedupe articles upfront so the pool has a clean task list.
    seen_urls: set[str] = set()
    articles: list[dict] = []
    with args.in_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                art = json.loads(line)
            except json.JSONDecodeError:
                log.debug("line %d: bad JSON, skipping", i)
                continue
            if art["url"] in seen_urls:
                continue
            seen_urls.add(art["url"])
            articles.append(art)

    log.info("Processing %d article(s) with %d worker(s)", len(articles), workers)

    rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_process_article, a, matcher, sentiment): a for a in articles}
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if result is None:
                continue
            if args.companies_only and not result["has_matches"]:
                continue
            rows.append(result["row"])
            if done % 25 == 0:
                log.info("processed %d/%d articles…", done, len(articles))

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    log.info("Wrote %d row(s) to %s", len(rows), out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
