-- 003_company_summaries_and_ohlc.sql
-- Per-company-per-day NLP summaries and cached daily OHLC bars.
--
-- ``company_day_summaries`` stores the LLM-generated good/bad bullet lists
-- for each (ticker_root, summary_date). ``stock_ohlc`` caches yfinance
-- daily candles so we don't re-fetch on every UI request.

CREATE TABLE IF NOT EXISTS company_day_summaries (
    ticker_root   TEXT NOT NULL,
    summary_date  DATE NOT NULL,
    good_points   TEXT[] NOT NULL,
    bad_points    TEXT[] NOT NULL,
    article_count INT  NOT NULL,
    model         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker_root, summary_date)
);

CREATE INDEX IF NOT EXISTS idx_summaries_date
    ON company_day_summaries(summary_date);

CREATE TABLE IF NOT EXISTS stock_ohlc (
    ticker_root  TEXT NOT NULL,
    bar_date     DATE NOT NULL,
    open         NUMERIC(12,4) NOT NULL,
    high         NUMERIC(12,4) NOT NULL,
    low          NUMERIC(12,4) NOT NULL,
    close        NUMERIC(12,4) NOT NULL,
    volume       BIGINT,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker_root, bar_date)
);
