# Brazilian Finance News — Daily Scraper

Pulls today's main finance articles from the 15 Portuguese-language sites in
`sources.csv` and writes one CSV per day with the companies, countries, and
currencies mentioned in each article.

## Layout

```
sources.csv                       input: name, year, url, type
finance_news/
  discovery.py                    RSS probing + Google News search + homepage link heuristics
  fetch.py                        trafilatura wrapper (text + metadata)
  entities.py                     spaCy NER + country/currency dictionaries
  analysis.py                     FinBERT-PT-BR sentiment + subject ranking + conflicts
  companies.py                    Top-150 loader + alias matcher
  ingest.py                       Stage 1 — sites + companies discovery → JSONL
  extract.py                      Stage 2 — NER + sentiment + company match → daily CSV
  dashboard.py                    Stage 3 — render daily PNG dashboard
scripts/
  fetch_top_companies.py          BrAPI.dev → data/companies.csv (weekly refresh)
  probe_rss.py                    Validate per-company Google News coverage
data/
  companies.csv                   top-150 B3 companies by market cap
  raw_articles.jsonl              ingest output / extract input
  news_YYYY-MM-DD.csv             extract deliverable
  dashboard_YYYY-MM-DD.png        offline dashboard image
run.sh                            companies refresh → ingest → extract → dashboard
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download pt_core_news_lg

# Free token for BrAPI.dev (top-150 company list). Sign up at https://brapi.dev.
export BRAPI_TOKEN=tPcuXeo9A8ef82DvdgBnB1
python scripts/fetch_top_companies.py   # writes data/companies.csv
```

## Run

End-to-end:
```bash
./run.sh
```

Individually:
```bash
python -m finance_news.ingest                       # both streams (default)
python -m finance_news.ingest --mode sites          # only sources.csv
python -m finance_news.ingest --mode companies      # only Google News per ticker
python -m finance_news.ingest --only InfoMoney      # single-site smoke test
python -m finance_news.ingest --ticker PETR4        # single-ticker smoke test
python -m finance_news.extract                      # NER + sentiment + company match
python -m finance_news.extract --companies-only     # drop articles w/o top-150 match
python -m finance_news.dashboard                    # render PNG dashboard

python scripts/fetch_top_companies.py               # refresh companies.csv
python scripts/probe_rss.py                         # validate per-company feeds
python scripts/probe_rss.py --limit 20 --verbose    # inspect a sample
```

### Company-centric discovery

The pipeline runs **two parallel streams**, merged and deduplicated by URL:

- **Site stream** — every outlet in `sources.csv`, via their RSS feeds. Gives
  broad macro coverage (politics, regulation, commodities).
- **Company stream** — for each of the top-150 B3 companies (by market cap,
  via BrAPI.dev), a Google News RSS query `"<short_name>" OR "<long_name>" OR
  <ticker>` aggregates PT-BR coverage from dozens of outlets we don't poll
  directly. Yields targeted per-company articles.

Every article in the output CSV carries `matched_companies`, `matched_tickers`,
and `sectors` columns (empty when no top-150 mention was found). Use
`--companies-only` in extract to filter to just company-tagged articles.

### Dashboard

`finance_news/dashboard.py` reads `data/news_<date>.csv` and writes
`data/dashboard_<date>.png` — a single-page offline image with:

- Header: article + source counts and the positive/neutral/negative mix.
- Donut of overall sentiment.
- Top companies mentioned, bars colored by net sentiment (green = net positive
  coverage, red = net negative, gray = mixed/neutral).
- Top countries mentioned.
- Sentiment by publisher (stacked horizontal bar, sorted by tilt).
- Currencies mentioned.
- Callouts of the day's most confidently positive and negative headlines.

Uses matplotlib + seaborn; renders with the `Agg` backend so it works on
headless machines.

## Output

`data/news_YYYY-MM-DD.csv` columns:

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

`finance_news/analysis.py` answers three questions per article:

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
  safe (URL dedupe in both stages).
- **Entity extraction:** spaCy `pt_core_news_lg` supplies `ORG`/`LOC`
  entities; countries are post-filtered by a curated PT country list, and
  currencies use regex over ISO codes, PT names, and symbols-adjacent-to-
  numbers. Governmental and media "orgs" are filtered via a stopword list.
