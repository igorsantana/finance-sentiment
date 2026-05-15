-- Social posts (X/Nitter etc.) — separate from news articles.

CREATE TABLE IF NOT EXISTS social_posts (
    id                BIGSERIAL PRIMARY KEY,
    platform          TEXT NOT NULL,
    external_id       TEXT NOT NULL,
    url               TEXT,
    author_handle     TEXT,
    text              TEXT NOT NULL,
    posted_at         TIMESTAMPTZ,
    matched_tickers   TEXT[] NOT NULL DEFAULT '{}',
    sentiment         TEXT,
    sentiment_score   REAL,
    raw_payload       JSONB,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    extracted_at      TIMESTAMPTZ,
    UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS social_posts_posted_at_idx
    ON social_posts(posted_at DESC);

CREATE INDEX IF NOT EXISTS social_posts_matched_tickers_gin
    ON social_posts USING GIN(matched_tickers);

CREATE INDEX IF NOT EXISTS social_posts_pending_extract_idx
    ON social_posts(posted_at) WHERE sentiment IS NULL;
