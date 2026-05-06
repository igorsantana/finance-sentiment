-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Article embeddings
ALTER TABLE articles
  ADD COLUMN IF NOT EXISTS relevance_embedding vector(384),
  ADD COLUMN IF NOT EXISTS sentiment_embedding vector(768);

-- Approximate nearest-neighbour indexes (IVFFlat; effective once rows are populated)
CREATE INDEX IF NOT EXISTS articles_relevance_emb_idx
  ON articles USING ivfflat (relevance_embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE INDEX IF NOT EXISTS articles_sentiment_emb_idx
  ON articles USING ivfflat (sentiment_embedding vector_cosine_ops)
  WITH (lists = 100);
