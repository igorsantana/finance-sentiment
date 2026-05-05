-- 004_advisor_narratives.sql
-- Cache for LLM-generated "investment advisor" narratives keyed by
-- (window_days, end_date, ticker_root). ``ticker_root = ''`` is the
-- market-wide narrative; non-empty values are per-company.

CREATE TABLE IF NOT EXISTS advisor_narratives (
    window_days   INT  NOT NULL,
    end_date      DATE NOT NULL,
    ticker_root   TEXT NOT NULL DEFAULT '',
    paragraphs    TEXT[] NOT NULL,
    article_count INT  NOT NULL,
    model         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (window_days, end_date, ticker_root)
);

CREATE INDEX IF NOT EXISTS idx_advisor_end_date
    ON advisor_narratives(end_date);
