-- Base schema: extensions, schemas, and all foundational tables.
-- Fully idempotent (IF NOT EXISTS) so it is safe on existing databases.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS chatbot;

-- 1. Users
CREATE TABLE IF NOT EXISTS chatbot.users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Workspaces
CREATE TABLE IF NOT EXISTS chatbot.workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  owner_user_id UUID NOT NULL REFERENCES chatbot.users(id),
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Memberships
CREATE TABLE IF NOT EXISTS chatbot.memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES chatbot.workspaces(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES chatbot.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, user_id)
);

-- 4. Conversations
CREATE TABLE IF NOT EXISTS chatbot.conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES chatbot.workspaces(id) ON DELETE CASCADE,
  created_by_user_id UUID NOT NULL REFERENCES chatbot.users(id),
  title TEXT NOT NULL DEFAULT '',
  scenario_id TEXT NOT NULL DEFAULT 'chat_default',
  model_name TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. Messages
CREATE TABLE IF NOT EXISTS chatbot.messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES chatbot.conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'complete',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  tokens_in INT NOT NULL DEFAULT 0,
  tokens_out INT NOT NULL DEFAULT 0,
  embedding vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_message_status CHECK (status IN ('streaming', 'complete', 'failed'))
);

-- 6. Documents
CREATE TABLE IF NOT EXISTS public.documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT,
  content TEXT,
  source_url TEXT,
  doc_type TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. Document chunks (with generated tsvector for full-text search)
CREATE TABLE IF NOT EXISTS public.document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  embedding vector(1536),
  token_count INT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. Memories
CREATE TABLE IF NOT EXISTS public.memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  embedding vector(1536),
  memory_type TEXT NOT NULL DEFAULT 'fact',
  importance FLOAT NOT NULL DEFAULT 0.7,
  source_session_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backfill content_tsv if document_chunks existed without it
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'document_chunks'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'document_chunks'
      AND column_name = 'content_tsv'
  ) THEN
    ALTER TABLE public.document_chunks
      ADD COLUMN content_tsv tsvector
      GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;
  END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_conversations_workspace_created
  ON chatbot.conversations (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
  ON public.document_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_document_chunks_content_tsv
  ON public.document_chunks
  USING gin (content_tsv);

CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
  ON public.memories
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
