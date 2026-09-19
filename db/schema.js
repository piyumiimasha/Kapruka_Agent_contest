// db/schema.js
// Raw SQL schema for Postgres + pgvector
// Run with: psql $DATABASE_URL -f schema.sql
// Or execute via db/migrate.js

export const schema = `
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────
-- Users (semantic memory / user profile)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id    TEXT UNIQUE NOT NULL,         -- anonymous identifier from JWT
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Semantic profile stored as structured JSONB for fast key lookups
-- Shape: { preferred_city, currency, budget_min, budget_max,
--          past_recipients: [], dislikes: [], interests: [] }
CREATE TABLE IF NOT EXISTS user_profiles (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  profile       JSONB NOT NULL DEFAULT '{}',
  updated_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- ─────────────────────────────────────────
-- Episodes (episodic memory)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS episodes (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  summary       TEXT NOT NULL,               -- human-readable episode summary
  metadata      JSONB NOT NULL DEFAULT '{}', -- { order_id, city, amount, category, outcome }
  embedding     vector(1536),                -- OpenRouter text-embedding-3-small
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search on episodes
CREATE INDEX IF NOT EXISTS episodes_embedding_idx
  ON episodes USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Index for fast user episode lookups
CREATE INDEX IF NOT EXISTS episodes_user_id_idx
  ON episodes(user_id);

-- ─────────────────────────────────────────
-- Conversation logs (optional audit trail)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_logs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id    TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content       TEXT NOT NULL,
  agent         TEXT,                        -- which agent produced this turn
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS logs_user_session_idx
  ON conversation_logs(user_id, session_id);

-- ─────────────────────────────────────────
-- Auto-update updated_at trigger
-- ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS \$\$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
\$\$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE TRIGGER profiles_updated_at
  BEFORE UPDATE ON user_profiles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
`;

// Default empty profile shape — used when creating a new user
export const DEFAULT_PROFILE = {
  preferred_city:   null,
  currency:         "LKR",
  budget_min:       null,
  budget_max:       null,
  past_recipients:  [],
  dislikes:         [],
  interests:        [],
};
