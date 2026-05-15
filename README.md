# Brazilian Finance News

A daily NLP pipeline over Portuguese-language financial news. For every
B3 company tracked by BrAPI it lists today's articles across a curated
set of pt-BR finance publishers (InfoMoney, Money Times, Suno, Brazil
Journal, Seu Dinheiro, Neofeed, Exame, Estadão E-Investidor, CNN
Brasil, Forbes, BM&C News, IstoÉ Dinheiro, Capital Aberto, InvestNews,
Bloomberg Línea, Empiricus, Levante, Petronotícias, Megawhat, Capital
Reset, TradeMap, Valor, Folha), runs NER +
sentiment + ticker matching on each article body, summarizes the day's
coverage per company via an LLM, and stores everything in Postgres. A
FastAPI + React/Vite web app surfaces the results; a terminal TUI is
bundled for human-judging articles against the model's sentiment label.

## Architecture

```
        ┌────────────┐    cron  ┌─────────────────────┐
        │  cron svc  │─────────▶│ python -m           │
        │ (TZ=BRT)   │  23:50   │  finance_news.      │
        └────────────┘          │  pipeline run       │
                                └──────────┬──────────┘
                                           │
                                           ▼
   ┌─────────────┐    psycopg3      ┌──────────────┐
   │   app svc   │◀────────────────▶│   db svc     │
   │ FastAPI     │                  │ Postgres 16  │
   └──────┬──────┘                  └──────────────┘
          │ HTTP
          ▼
   web/ (Vite + React)
```

Three Compose services:

- `db`     — `postgres:16-alpine`, named volume `pgdata`, `5432` exposed.
- `app`    — Python 3.11, spaCy `pt_core_news_lg` baked in, repo bind-mounted
             at `/app`, serves the FastAPI on `:8000`.
- `cron`   — Same image, runs `scripts/cron_loop.py` which fires
             `pipeline run` daily at 23:50 America/Sao_Paulo.

## Quickstart

```sh
cp .env.example .env       # set BRAPI_TOKEN, LLM_API_KEY (Groq)
make build                 # ~10 min on first run; pulls torch + pt_core_news_lg
make up                    # bring up db + app + cron
make migrate               # apply migrations/*.sql (idempotent)
make companies             # populate `companies` from BrAPI (all tickers)
make full                  # ingest + extract + summarize
make dev                   # backend (uvicorn --reload) + frontend (vite) with HMR
```

Open the web UI at http://localhost:5173 (`make dev`) — Vite proxies `/api`
to the FastAPI on `:8000`. Every operation also runs cleanly stand-alone:

```sh
make ingest        # fetch fresh articles for today (DB writes only)
make extract       # run NLP on rows where sentiment IS NULL
make status        # JSON: row counts + last 10 runs
make psql          # psql shell on the local DB
make judge         # interactive TUI; q to quit
make judge-stats   # confusion matrix, bad_match top-N, agreement by sector
make shell         # bash inside the app container
make backfill DATE=2026-05-10   # GDELT + CC-NEWS backfill for one SP day
make ps / make logs / make down / make nuke
```

## Schema

All tables in [`migrations/001_init.sql`](migrations/001_init.sql); seed data
for `publishers` in [`migrations/002_seed_publishers.sql`](migrations/002_seed_publishers.sql).
Apply via `make migrate`.

| Table              | Purpose                                                      |
|--------------------|--------------------------------------------------------------|
| `publishers`       | Hostname → display name + ownership + affiliations (TEXT[]). |
| `companies`        | Every B3 ticker from BrAPI; refreshed weekly.                |
| `articles`         | One row per fetched URL. `sentiment IS NULL` until extract.  |
| `judgments`        | Human labels keyed by `judge`; bypass the unique-per-article rule so re-judging is allowed. |
| `runs`             | One row per `kind ∈ {ingest, extract, full}` invocation.     |
| `schema_migrations`| Tracked by `scripts/migrate.py`.                              |

`articles` array columns (`subjects`, `companies_ner`, `persons`,
`countries`, `currencies`, `matched_tickers`, `conflicts`) are `TEXT[]`. A
GIN index on `matched_tickers` makes ticker-filtered queries fast.

## Code layout

```
finance_news/
  api.py             FastAPI: reports, companies, stocks, runs, SSE streams
  pipeline.py        run_ingest / run_extract / run_summarize / run_full
  ingest.py          publisher discovery + GDELT fallback + matcher → articles
  extract.py         NER + subjects + sentiment + matcher → update articles
  summaries.py       LLM-backed per-company day summaries (eager, top-N)
  stocks.py          yfinance OHLC window with DB-backed caching
  aggregations.py    build_report_payload (consumed by /api/reports/<date>)
  logconfig.py       silence_third_party() shared by every entrypoint
  nlp/
    analysis.py      SentimentAnalyzer + rank_subjects + detect_conflicts
    entities.py      spaCy NER wrapper
    companies.py     Company dataclass, CompanyMatcher, sector translation
    llm_summary.py   OpenAI-compatible client → {good[], bad[]}
  store/
    db.py            psycopg3 access layer (only place SQL lives)
    publishers.py    db.lookup_publisher + progressive-suffix fallback
  net/
    discovery.py     Per-publisher discovery — sitemaps / WordPress / RSS / HTML
    gdelt.py         GDELT DOC API fallback for companies with zero listing hits
    fetch.py         Article body fetcher (trafilatura)
    cvm.py           CVM Dados Abertos IPE filings → Candidate list
web/                 Vite + React frontend (charts, candle, summaries)
migrations/          SQL files, applied in lexical order
scripts/
  migrate.py         apply migrations/*.sql idempotently
  cron_loop.py       daily scheduler for the cron container
  companies/
    fetch_top.py     BrAPI → companies table
  judging/
    cli.py           interactive TUI
    stats.py         confusion matrix + bad_match top-N
  backfill/
    ccnews_ingest.py       GDELT bulk + CC-NEWS WARC backfill for one SP day
    rematch_companies.py   re-run CompanyMatcher over existing rows
    filter_sports_matches.py  drop sports-context false positives
  diagnostics/
    probe_rss.py     health-check every discovery adapter for today
    audit_matches.py flag likely false positives in matched_tickers
```

## Judging flow

```
make judge             # one article per screen
  p / n / x  → positive / negative / neutral
  b          → bad_match (the matched ticker is wrong)
  s          → skip (recorded so it isn't re-prompted)
  o          → open URL in browser
  m          → free-text note then label
  u          → undo last label (deletes the row)
  q          → quit

make judge-stats       # confusion matrix model vs human, etc.
```

Filters: `--judge`, `--ticker`, `--sentiment`, `--since`, `--only-matched`.
The default judge name comes from `$JUDGE_NAME`, falling back to `$USER`.

## Operational notes

- **Worker count** for ingest + extract is the `WORKERS` env var (default 4).
  spaCy and the HuggingFace pipeline release the GIL during native compute,
  so `ThreadPoolExecutor` gives real parallel speedup.
- **Models** are baked into the image (`pt_core_news_lg`) and cached in
  `/hf_cache` (named volume `hf_cache`) so transformer weights survive image
  rebuilds.
- **DB-level dedup**: every `articles` insert is `ON CONFLICT (url) DO NOTHING`.
  Re-running `make ingest` mid-day is safe.
- **No fallbacks**: if extract can't load the sentiment model the run fails
  loudly. We'd rather see an `error` row in `runs` than silent half-data.
