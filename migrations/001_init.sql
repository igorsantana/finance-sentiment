-- 001_init.sql -- initial schema for finance_news
-- All array columns are TEXT[] (not JSON) so we can use GIN indexes and
-- Postgres array operators directly from psycopg.

CREATE TABLE IF NOT EXISTS publishers (
    hostname      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    founded_year  INT,
    ownership     TEXT,
    homepage      TEXT,
    affiliations  TEXT[] NOT NULL DEFAULT '{}',
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    ticker_root   TEXT PRIMARY KEY,
    ticker        TEXT NOT NULL,
    short_name    TEXT,
    long_name     TEXT,
    sector        TEXT,
    market_cap    BIGINT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS articles (
    url               TEXT PRIMARY KEY,
    title             TEXT,
    text              TEXT,
    author            TEXT,
    site              TEXT,
    hostname          TEXT,
    published_at      TIMESTAMPTZ,
    source_ticker     TEXT REFERENCES companies(ticker_root),
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- analysis (NULL until extract):
    sentiment         TEXT,
    sentiment_score   REAL,
    subjects          TEXT[],
    companies_ner     TEXT[],
    persons           TEXT[],
    countries         TEXT[],
    currencies        TEXT[],
    matched_tickers   TEXT[],
    conflicts         TEXT[],
    summary           TEXT,
    extracted_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS articles_published_at_idx
    ON articles(published_at DESC);

CREATE INDEX IF NOT EXISTS articles_pending_extract_idx
    ON articles(published_at) WHERE sentiment IS NULL;

CREATE INDEX IF NOT EXISTS articles_source_ticker_idx
    ON articles(source_ticker);

CREATE INDEX IF NOT EXISTS articles_matched_tickers_gin
    ON articles USING GIN(matched_tickers);

CREATE TABLE IF NOT EXISTS judgments (
    id            BIGSERIAL PRIMARY KEY,
    article_url   TEXT NOT NULL REFERENCES articles(url) ON DELETE CASCADE,
    judge         TEXT NOT NULL,
    label         TEXT NOT NULL CHECK (label IN ('positive','neutral','negative','skip','bad_match')),
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS judgments_article_idx
    ON judgments(article_url);

CREATE TABLE IF NOT EXISTS runs (
    id            BIGSERIAL PRIMARY KEY,
    kind          TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL,
    n_fetched     INT,
    n_extracted   INT,
    error         TEXT
);
