# Brazilian Finance News — Daily Scraper + Web App

Pulls today's main finance articles from the 15 Portuguese-language sites in
`sources.csv`, plus Google News coverage per top-150 B3 company, and serves
the results through a FastAPI backend with a small React frontend. A
scheduler re-runs the whole pipeline every day at **23:50
America/Sao_Paulo**.

## Layout

```
sources.csv                       input: name, year, url, type
backend/
  pipeline/                       the daily scraper + NER + sentiment pipeline
    discovery.py                  RSS probing + Google News search + homepage link heuristics
    fetch.py                      trafilatura wrapper (text + metadata)
    entities.py                   spaCy NER + country/currency dictionaries
    analysis.py                   FinBERT-PT-BR sentiment + subject ranking + conflicts
    companies.py                  Top-150 loader + alias matcher
    ingest.py                     Stage 1 — sites + companies discovery → JSONL
    extract.py                    Stage 2 — NER + sentiment + company match → daily CSV + DB upsert
    dashboard.py                  Stage 3 — render daily PNG dashboard
    report.py                     Stage 3b — render company + sector report PNG
  api/                            FastAPI server + APScheduler cron
    main.py                       app factory, lifespan (scheduler start/stop)
    db.py / models.py / schemas.py  SQLAlchemy engine, ORM, Pydantic
    scheduler.py                  daily cron at 23:50 America/Sao_Paulo
    routes/                       /api/dates, /api/news, /api/summary, /api/files, /api/runs
    services/                     catalog, news queries, subprocess pipeline runner
  scripts/
    fetch_top_companies.py        BrAPI.dev → data/companies.csv (weekly refresh)
    backfill_db.py                load existing news_*.csv into data/app.db
    probe_rss.py                  validate per-company Google News coverage
    audit_company_matches.py      diagnose false-positive company matches
web/                              Vite + React + TypeScript frontend skeleton
data/
  companies.csv                   top-150 B3 companies by market cap
  app.db                          SQLite — source of truth for the API
  raw/raw_articles.jsonl          ingest output / extract input
  news_YYYY-MM-DD.csv             extract deliverable (also kept as audit log)
  images/YYYY-MM-DD/dashboard.png offline dashboard image
  images/YYYY-MM-DD/report.png    company + sector report
  logs/run_<id>.log               pipeline run output (one per scheduled/manual run)
run.sh                            companies refresh → ingest → extract → dashboard → report
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download pt_core_news_lg

# Free token for BrAPI.dev (top-150 company list). Sign up at https://brapi.dev.
export BRAPI_TOKEN=<your-token>
python backend/scripts/fetch_top_companies.py   # writes data/companies.csv

# Frontend (optional — Node 18+)
(cd web && npm install)
```

The API will auto-create `data/app.db` on first start. If you already have
`data/news_*.csv` files from previous pipeline runs, import them once:

```bash
python backend/scripts/backfill_db.py
```

## Run the web app

Backend:
```bash
uvicorn backend.api.main:app --reload --port 8000
```

Frontend (in a second terminal):
```bash
cd web && npm run dev
```

Open **http://localhost:5173** — the Vite dev server proxies `/api` to
`http://localhost:8000`.

Useful endpoints (full schema at `http://localhost:8000/docs`):

| endpoint | returns |
|---|---|
| `GET /api/health` | `{status, scheduler, next_run, db}` |
| `GET /api/dates` | available dates with article counts + artifact flags |
| `GET /api/news/{date}` | article rows (filters: `sentiment`, `company`, `site`; paginated) |
| `GET /api/summary/{date}` | sentiment mix + top companies/sites/sectors |
| `GET /api/files/{date}/{csv\|dashboard\|report}` | raw CSV or PNG download |
| `POST /api/runs` | kick the pipeline on demand (body: `{date?, stages?}`) |
| `GET /api/runs` / `GET /api/runs/{id}` | run history + per-stage status |

### Scheduled runs

When the backend is running, APScheduler fires the full pipeline every day
at 23:50 America/Sao_Paulo. Each run is a background `subprocess` — models
are only loaded in the worker, so HTTP requests stay responsive. State is
persisted in the `runs` table and the log ends up at
`data/logs/run_<id>.log`.

To force a run now:
```bash
curl -X POST http://localhost:8000/api/runs -H 'content-type: application/json' -d '{}'
```

## Run the pipeline directly (CLI)

End-to-end:
```bash
./run.sh
```

Individually:
```bash
python -m backend.pipeline.ingest                    # both streams (default)
python -m backend.pipeline.ingest --mode sites       # only sources.csv
python -m backend.pipeline.ingest --mode companies   # only Google News per ticker
python -m backend.pipeline.ingest --only InfoMoney   # single-site smoke test
python -m backend.pipeline.ingest --ticker PETR4     # single-ticker smoke test
python -m backend.pipeline.extract                   # NER + sentiment + company match + DB upsert
python -m backend.pipeline.extract --companies-only  # drop articles w/o top-150 match
python -m backend.pipeline.dashboard                 # render PNG dashboard
python -m backend.pipeline.report                    # render company + sector PNG

python backend/scripts/fetch_top_companies.py        # refresh companies.csv
python backend/scripts/probe_rss.py                  # validate per-company feeds
python backend/scripts/probe_rss.py --limit 20 --verbose
python backend/scripts/audit_company_matches.py      # diagnose suspicious matches
```

## Configuration

| env var | default | notes |
|---|---|---|
| `WORKERS` | 4 | Parallel worker threads for ingest + extract |
| `BRAPI_TOKEN` | — | Required by `fetch_top_companies.py` |

`.env` is loaded automatically (both by `run.sh` and by each pipeline stage
via python-dotenv).

### Company-centric discovery

The pipeline runs **two parallel streams**, merged and deduplicated by URL:

- **Site stream** — every outlet in `sources.csv`, via their RSS feeds. Gives
  broad macro coverage (politics, regulation, commodities).
- **Company stream** — for each of the top-150 B3 companies (by market cap,
  via BrAPI.dev), a Google News RSS query `"<short_name>" OR "<long_name>" OR
  <ticker>` aggregates PT-BR coverage from dozens of outlets we don't poll
  directly. Yields targeted per-company articles.

Every article carries `matched_companies`, `matched_tickers`, and `sectors`
(empty when no top-150 mention was found). Use `--companies-only` in extract
to keep only company-tagged articles.

### Dashboard

`backend/pipeline/dashboard.py` reads `data/news_<date>.csv` and writes
`data/images/<date>/dashboard.png` — a single-page offline image with:

- Header: article + source counts and the positive/neutral/negative mix.
- Donut of overall sentiment.
- Top companies mentioned, bars colored by net sentiment (green = net
  positive, red = net negative, gray = mixed/neutral).
- Top countries mentioned.
- Sentiment by publisher (stacked horizontal bar).

Uses matplotlib + seaborn with the `Agg` backend so it works on headless
machines.

## Output

`data/news_YYYY-MM-DD.csv` columns (same fields are also stored in the
`articles` table of `data/app.db`):

| column        | notes                                              |
|---------------|----------------------------------------------------|
| site          | Publication name from `sources.csv`                |
| title         | Article headline                                   |
| url           | Canonical article URL                              |
| published_at  | ISO 8601 timestamp                                 |
| companies     | `ORG` entities, pipe-separated                     |
| countries     | Country names in PT, pipe-separated                |
| currencies    | ISO 4217 codes (BRL, USD, EUR…), pipe-separated    |
| matched_companies | Top-150 companies mentioned (pipe-separated)   |
| matched_tickers | Ticker roots of matched companies                |
| sectors       | BrAPI sectors for matched companies                |
| source_kind   | `site` or `company` — which stream surfaced it     |
| source_key    | Site name (site stream) or ticker (company stream) |
| author        | From article metadata (may be empty)               |
| subjects      | Top-ranked `ORG`/`PER` subjects, pipe-separated    |
| sentiment     | `positive` / `neutral` / `negative`                |
| sentiment_score | Model confidence in [0, 1]                       |
| persons       | Distinct `PER` entities, pipe-separated            |
| conflicts     | `publisher_subject:…` / `author_self_reference:…`  |
| summary       | First 280 chars of article text                    |

### Analysis module

`backend/pipeline/analysis.py` answers three questions per article:

1. **Who/what is it about?** — `ORG`/`PER` entities scored by position (title
   ×5, lead ×3, body ×1) and frequency. Top-3 become `subjects`.
2. **Overall sentiment** — `lucas-leme/FinBERT-PT-BR` (BERTimbau fine-tuned on
   PT-BR financial news). Falls back to `cardiffnlp/twitter-xlm-roberta-base-
   sentiment` if the primary model fails to download. Runs locally on
   CPU/MPS; no API calls.
3. **Author + conflict** — author comes from trafilatura metadata. Conflicts
   fire when a subject entity belongs to the publisher's corporate family
   (`PUBLISHER_AFFILIATIONS` map) or when the author's name matches a
   subject — flagged as `publisher_subject:…` or `author_self_reference:…`.

## Design notes

- **Discovery:** RSS is tried first (homepage `<link rel=alternate>` + common
  paths like `/feed`, `/rss`). Sites without a working feed fall back to a
  homepage crawl that keeps only hyphenated-slug URLs on the same domain.
- **Today-filter:** An article is kept only if its feed date or trafilatura
  metadata date equals today (America/Sao_Paulo). Undated items are dropped.
- **Resilience:** Each site runs in its own thread; failures are logged and
  the run continues. `raw_articles.jsonl` is append-only so re-running is
  safe (URL dedupe in both stages, and URL-keyed upsert into `app.db`).
- **Entity extraction:** spaCy `pt_core_news_lg` supplies `ORG`/`LOC`
  entities; countries are post-filtered by a curated PT country list, and
  currencies use regex over ISO codes, PT names, and symbols-adjacent-to-
  numbers. Governmental and media "orgs" are filtered via a stopword list.
- **Web process isolation:** the FastAPI process never imports spaCy or
  transformers. Scheduled and manual pipeline runs spawn a child process
  (`python -m backend.pipeline.<stage>`), so models load only in the worker
  and HTTP handlers stay responsive.
