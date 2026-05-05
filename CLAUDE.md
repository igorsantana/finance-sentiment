# Trends & Advisor page (staged)

## Context

Today the report page is keyed to a single day (Gráficos + Empresa tabs operate on `reportDate`). We want a multi-day analytics surface: rolling 3/7/14-day windows of overall sentiment + per-company sentiment+price, plus a two-paragraph LLM "investment advisor" narrative tying it together.

This becomes a new top-level section in the Sidebar: **Análise** (sibling of `pipeline` / `report`). The selected window (3/7/14 days) ends on the most recent day with articles. Per-company views drive off the same combobox pattern as the Empresa tab. The advisor narrative reuses the OpenAI-compatible client at [finance_news/nlp/llm_summary.py](finance_news/nlp/llm_summary.py) and is cached per `(window_days, end_date, ticker_root|null)` in a new table so we don't pay LLM cost on every page load.

Locked decisions:
- **Window endpoints**: `[end_date - (window-1) .. end_date]` SP-inclusive, where `end_date` defaults to the latest article SP-day.
- **Cadence**: advisor narrative generated lazily on first request per `(window, end_date, ticker)` and cached. Pipeline does not pre-generate (windows shift daily; pre-generation would be wasteful).
- **Stock data**: per-company chart reuses `fetch_ohlc_window`/`stock_ohlc` (already trims to ±10 trading days; we'll add a trailing-N-day variant).
- **Soft-fail**: advisor card shows `EmptyTile` ("análise temporariamente indisponível") on 503; the rest of the page must render.
- **No new chart libs**: recharts only. Bundle delta ≤ 25 kB gzipped at the end of stage 8.

Window options exposed to the user: `3 | 7 | 14`.

## Shared groundwork (reused across stages)

- Migration runner: `python scripts/migrate.py` ([scripts/migrate.py](scripts/migrate.py)) — idempotent, picks up new files in `migrations/` lexically.
- DB layer: [finance_news/store/db.py](finance_news/store/db.py) — every helper goes here, keyword-only.
- Per-day shape: [finance_news/aggregations.py](finance_news/aggregations.py) `build_report_payload` — extend with a rolling-window sibling.
- LLM client: [finance_news/nlp/llm_summary.py](finance_news/nlp/llm_summary.py) `_client()` + `summarize_company_day` shape.
- Stock fetch: [finance_news/stocks.py](finance_news/stocks.py) `fetch_ohlc_window`.
- API style: [finance_news/api.py](finance_news/api.py) — 400 on bad date / window, 404 when window has no data, 503 on LLM unavailability.
- FE chart primitives: [_chart-axis.tsx](web/src/components/charts/_chart-axis.tsx), [ChartCard.tsx](web/src/components/charts/ChartCard.tsx), [SentimentVsPriceChart.tsx](web/src/components/charts/SentimentVsPriceChart.tsx).
- FE fetch pattern: hooks under `web/src/hooks/use*.ts` — `AbortController`, `{data, loading, error}`.
- FE date helper: [web/src/lib/date.ts](web/src/lib/date.ts) `formatPtBr`.
- View switching: [Sidebar.tsx](web/src/components/Sidebar.tsx) + [App.tsx](web/src/App.tsx).
- Combobox primitive: [web/src/components/ui/combobox.tsx](web/src/components/ui/combobox.tsx).

---

## Execution — one stage per turn (stop after each, wait for verify)

### Stage 1 — DB schema + helpers (BE only)

Migration `migrations/004_advisor_narratives.sql` (new):
```sql
CREATE TABLE IF NOT EXISTS advisor_narratives (
    window_days   INT  NOT NULL,
    end_date      DATE NOT NULL,
    ticker_root   TEXT NOT NULL DEFAULT '',  -- '' = market-wide
    paragraphs    TEXT[] NOT NULL,           -- exactly 2 entries
    article_count INT  NOT NULL,
    model         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (window_days, end_date, ticker_root)
);
```

[finance_news/store/db.py](finance_news/store/db.py) — append helpers (keyword-only, mirroring existing style):
- `fetch_articles_in_window(conn, *, start, end, ticker_root=None) -> list[dict]` — `[start, end]` inclusive in SP-time, optional `%s = ANY(matched_tickers)` filter.
- `fetch_daily_sentiment_window(conn, *, start, end, ticker_root=None) -> list[dict]` — per-day positive/neutral/negative + avg_score (parameterized by window endpoints, optional ticker filter).
- `latest_article_date(conn) -> date | None` — `MAX((published_at AT TIME ZONE 'America/Sao_Paulo')::date)` over `articles`. Powers the default `end_date`.
- `upsert_advisor_narrative(conn, *, window_days, end_date, ticker_root, paragraphs, article_count, model)`.
- `fetch_advisor_narrative(conn, *, window_days, end_date, ticker_root) -> dict | None`.

**Verify**:
- `python scripts/migrate.py` adds the table; re-run is a no-op.
- Quick psql round-trip: `INSERT … advisor_narratives`, `fetch_advisor_narrative` returns the row.
- Pipeline still boots (`docker compose restart app && curl /api/health` → 200).

---

### Stage 2 — Window aggregation (BE only)

`finance_news/aggregations.py` — new function `build_window_payload(rows, sectors_lookup, *, start, end) -> dict`:
- Reuses the per-day building blocks of `build_report_payload` but produces a window shape:
  ```ts
  {
    window: { start, end, days },
    counts: { total, publishers, bySentiment },
    topCompanies: [...],         // same shape as today
    sentimentByPublisher: [...],
    sectorMatrix: [...],
    topSubjects: [...],
    topTickers: [...],
    daily: Array<{ date, positive, neutral, negative, total, net }>  // per-SP-day series
  }
  ```
- `daily[]` powers the rolling sentiment line; computed by grouping `rows` on SP-date.
- Hourly + scoreHistogram are **dropped** from the window shape (less useful at multi-day scale, keeps payload lean).

**Verify**: import from a REPL inside the app container; pass `rows = fetch_articles_in_window(...)` for a 7-day span — payload has `daily` length ≤ 7 and counts that match `len(rows)`.

---

### Stage 3 — Overall trends API (BE only)

`GET /api/trends/overall?window=7&end=2026-05-04` →
```ts
{
  window: { start, end, days },
  counts, topCompanies, sentimentByPublisher,
  sectorMatrix, topSubjects, topTickers, daily
}
```
- Defaults: `window=7`, `end = latest_article_date()`.
- Validation: `window ∈ {3, 7, 14}`, `end` valid ISO. 400 on either failure. 404 when the window has zero articles.
- Implementation calls `db.fetch_articles_in_window(start, end)` + `build_window_payload`, then `payload["window"] = {...}`.

**Verify**:
- `curl '/api/trends/overall?window=7' | jq '.window, .counts.total, (.daily | length)'` → reasonable numbers.
- `curl '/api/trends/overall?window=10'` → 400.
- `curl '/api/trends/overall?window=7&end=1900-01-01'` → 404.

---

### Stage 4 — Per-company trends API (BE only)

`GET /api/trends/company/{ticker_root}?window=7&end=...` →
```ts
{
  ticker, name, window: { start, end, days },
  counts: { total, bySentiment },
  daily: Array<{ date, positive, neutral, negative, total, net, avgScore, close|null }>,
  topPublishers: [...],
  topSubjects: [...],
  correlation: number | null     // Pearson r(close, net) over overlapping days
}
```
- Reuses `db.fetch_daily_sentiment_window(..., ticker_root=root)` for sentiment.
- New helper in [finance_news/stocks.py](finance_news/stocks.py): `fetch_ohlc_trailing(conn, ticker_root, end, days) -> list[Bar]` — pulls from cache if dense, else yfinance for `[end - 2*days .. end]` calendar window, trim to bars within `[start..end]`. Cache table is unchanged.
- Joins sentiment series (per SP-day) with bars (per trading day). `close` is `null` on weekends/holidays.
- `correlation` Pearson r over days that have both `total > 0` and `close is not null`. Factor `_pearson` out of [finance_news/api.py](finance_news/api.py) into a small util module if not already shared.
- 400 / 404 mirrors stage 3.

**Verify**:
- `curl '/api/trends/company/PETR?window=14' | jq '.daily | length, .correlation'` → ~14, finite number.
- Unknown ticker → 404; bad window → 400.

---

### Stage 5 — LLM advisor narrative (BE only)

`finance_news/nlp/advisor.py` (new):
- `summarize_market_window(window, daily, top_companies, sector_matrix, end) -> dict | None` — PT-BR system prompt: *"Você é um assessor de investimentos…"*, asks for **exactly two paragraphs** in JSON `{"paragraphs": ["...", "..."]}`. First paragraph = market read (sentiment trend, sector leaders/laggards). Second paragraph = actionable observations (without giving direct buy/sell advice — say "atenção a", "monitorar", etc.). Cap each paragraph at ~600 chars.
- `summarize_company_window(ticker, name, daily, ohlc, top_subjects, articles_sample) -> dict | None` — same shape, focused on one ticker. Two paragraphs: (1) momentum + sentiment vs price correlation, (2) what to watch in the next sessions (catalysts surfaced in subjects/headlines).
- Soft-fail mirrors `summarize_company_day`: returns `None` on connection / parse / empty errors.

[finance_news/api.py](finance_news/api.py):
- `GET /api/advisor/overall?window=7&end=...` and `GET /api/advisor/company/{ticker_root}?window=7&end=...`:
  1. Look up cached narrative via `db.fetch_advisor_narrative`. Hit → return.
  2. Miss → call the relevant `summarize_*_window` with the same data shape stages 3/4 already build (factor into a helper so the API code stays thin).
  3. On success → `db.upsert_advisor_narrative(...)`; return `{ paragraphs, articleCount, model, generatedAt }`.
  4. On LLM `None` → **503** with a clear `detail` message; **don't poison the cache**.

**Verify**:
- First call to `curl '/api/advisor/overall?window=7'` populates the cache; second call is sub-50 ms (`SELECT count(*) FROM advisor_narratives` increases by exactly 1).
- Rotate `LLM_API_KEY` to garbage and restart `app` → 503; cache row count unchanged.

---

### Stage 6 — FE data layer + Análise page skeleton

[web/src/api.ts](web/src/api.ts):
- Types: `WindowOverall`, `WindowCompany`, `AdvisorNarrative`. Functions: `getTrendsOverall(window, end?, signal?)`, `getTrendsCompany(ticker, window, end?, signal?)`, `getAdvisor(scope: "overall" | { ticker }, window, end?, signal?)`.
- Hooks: `useTrendsOverall`, `useTrendsCompany`, `useAdvisor` — same `AbortController` shape as the existing hooks.

`web/src/components/AnalysisView.tsx` (new):
- Header with two controls:
  - Window toggle (3 / 7 / 14) — same visual as `ViewMode` toggle in [ReportView.tsx](web/src/components/ReportView.tsx).
  - Scope toggle (Mercado / Empresa); when "Empresa" is active, render the existing `Combobox` populated from the latest 7d top tickers (cheap fetch via `getTrendsOverall(7)`).
- Renders skeleton cards only at this stage (real charts in stages 7-8).

[web/src/components/Sidebar.tsx](web/src/components/Sidebar.tsx) + [App.tsx](web/src/App.tsx):
- Add `Section = "pipeline" | "report" | "analysis"`. New sidebar entry **Análise** above Reports.
- App routes `analysis` → `<AnalysisView />`.

**Verify**: `cd web && npx tsc --noEmit && npm run build` clean. Clicking **Análise** renders the toggles and a couple of skeleton cards.

---

### Stage 7 — Mercado (overall) charts

In `AnalysisView`, when scope="overall":
1. **Sentiment over time** — `<LineChart>` of `daily[].net` with light positive/negative shading. Reuse axis defaults.
2. **Volume over time** — `<BarChart>` of `daily[].total` stacked by sentiment (mirrors [HourlyTimeline.tsx](web/src/components/charts/HourlyTimeline.tsx)).
3. **Setores** — reuse `SectorHeatmap` directly with the window's `sectorMatrix`.
4. **Veículos** — reuse `SentimentByPublisher`.
5. **Top tickers** — reuse `TopTickers`.

Components reused; one new `WindowSentimentLine.tsx` drops into [web/src/components/charts/](web/src/components/charts/). Loading: per-card skeleton.

**Verify**: Switching window 3 → 7 → 14 reflows charts; aborts in-flight requests cleanly. `git status` shows only the files for this stage.

---

### Stage 8 — Empresa (per-company) charts + advisor narrative + polish

When scope="company":
1. Combobox feeds `selectedTicker`. Default = `topTickers[0]` from a 7d overall fetch.
2. **Sentimento × Cotação no período** — adapt [SentimentVsPriceChart.tsx](web/src/components/charts/SentimentVsPriceChart.tsx) to take a generic `points: { date, close, net, total, ... }[]` (today it takes `SentimentSeries`); both endpoints can feed it. Selected day shading dropped (no single anchor day in window mode).
3. **Volume × Sentimento** — bars stacked by sentiment, by SP-day (reuse stage-7 component).
4. **Top assuntos / veículos** — reuse `TopSubjects` + `SentimentByPublisher`.

Below all charts (both scopes), **Análise do assessor** card:
- Calls `useAdvisor(scope, window, end)`.
- Renders two `<p>` blocks with mono-monospace prose, plus a tiny footer line "modelo: <name> · gerado em <pt-BR>". Loading: skeleton lines. Error / 503: `EmptyTile` with "análise temporariamente indisponível".

Polish:
- All windows share one `formatPtBr` for date axes.
- `cd web && npx tsc --noEmit && npm run build` clean. Bundle delta ≤ 25 kB gzipped (no new chart libs).

**Verify**:
- Mercado view: window toggle changes line chart smoothly; advisor card shows 2 paragraphs; refresh → cache hit (sub-50 ms server time).
- Empresa view: pick PETR → sentiment+price chart with `r` in subtitle; advisor narrative differs from market scope.
- Set `LLM_API_KEY` to garbage → advisor card shows EmptyTile, charts still work.
- Sidebar **Análise** survives the existing reattach flow on refresh.

---

## Rules

- One stage per turn. Stop after each and summarize.
- Don't touch files outside the current stage's scope.
- Every stage leaves the app in a runnable state — no broken intermediate commits.
- All chart fills/strokes use `hsl(var(--…))` strings or `SENTIMENT_COLORS` constants — palette stays single-sourced in [index.css](web/src/index.css).
- LLM client must soft-fail; the rest of the page cannot regress because of advisor failure.
