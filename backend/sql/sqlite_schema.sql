-- SQLite schema for Agent-RS local storage backend.
-- Single-file, zero-server equivalent of the PostgreSQL schema in migrations/.
-- Applied via executescript() at startup (see app/db/sqlite_pool.py); fully
-- idempotent (IF NOT EXISTS) so it is safe to run on every boot.
--
-- Type mapping vs PostgreSQL:
--   UUID            -> TEXT          (repos generate uuid4() strings explicitly)
--   JSONB           -> TEXT          (json.dumps/loads; parse_jsonb handles strings)
--   TIMESTAMPTZ     -> TEXT          (CURRENT_TIMESTAMP => 'YYYY-MM-DD HH:MM:SS' UTC)
--   vector(1536)    -> TEXT          (encode_vector/decode_vector "[...]" form)
--   BOOLEAN         -> INTEGER       (0/1)
--   BIGSERIAL       -> INTEGER PK AUTOINCREMENT
-- Schema namespaces public./agent_rs. are stripped (one SQLite namespace).
-- Full-text search: the PG generated `content_tsv` column has no SQLite analog,
-- so it is replaced by an external-content FTS5 table + sync triggers below.

-- 1. Users
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL DEFAULT 'disabled',
  name TEXT NOT NULL DEFAULT '',
  email_verified INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users (lower(email));

-- 2. Workspaces
CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  owner_user_id TEXT NOT NULL REFERENCES users(id),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Memberships
CREATE TABLE IF NOT EXISTS memberships (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (workspace_id, user_id)
);

-- 4. Conversations
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  created_by_user_id TEXT NOT NULL REFERENCES users(id),
  title TEXT NOT NULL DEFAULT '',
  scenario_id TEXT NOT NULL DEFAULT 'chat_default',
  model_name TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conversations_workspace_created
  ON conversations (workspace_id, created_at DESC);

-- 5. Messages
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('streaming', 'complete', 'failed')),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  embedding TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_conv_created
  ON messages (conversation_id, created_at);

-- 6. Sessions
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);

-- 7. Documents
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  title TEXT,
  content TEXT,
  source_url TEXT,
  doc_type TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_by_user_id TEXT NOT NULL DEFAULT '00000000-0000-4000-8000-000000000001',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_documents_owner_created
  ON documents (created_by_user_id, created_at DESC);

-- 8. Document chunks (embedding as TEXT; full-text via FTS5 table below)
CREATE TABLE IF NOT EXISTS document_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  embedding TEXT,
  token_count INTEGER,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document
  ON document_chunks (document_id);

-- 8b. FTS5 full-text index over document_chunks.content (replaces tsvector).
-- External-content table keyed on the implicit rowid; trigram tokenizer covers
-- Chinese (substring match). Queries <3 chars fall back to LIKE in the repo.
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
  content,
  content='document_chunks',
  content_rowid='rowid',
  tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS document_chunks_ai AFTER INSERT ON document_chunks BEGIN
  INSERT INTO document_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS document_chunks_ad AFTER DELETE ON document_chunks BEGIN
  INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS document_chunks_au AFTER UPDATE ON document_chunks BEGIN
  INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
  INSERT INTO document_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

-- 9. Memories (embedding as TEXT; brute-force cosine in repo)
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  embedding TEXT,
  memory_type TEXT NOT NULL DEFAULT 'fact',
  importance REAL NOT NULL DEFAULT 0.7,
  source_session_id TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_user_created
  ON memories (user_id, created_at DESC);

-- 10. Document ingest jobs
CREATE TABLE IF NOT EXISTS document_ingest_jobs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'parsing', 'chunking', 'embedding', 'inserting', 'complete', 'failed')),
  progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
  filename TEXT,
  doc_type TEXT,
  file_size INTEGER,
  text_length INTEGER,
  chunk_count INTEGER,
  embedding_batches INTEGER,
  document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
  error_code TEXT,
  error_message TEXT,
  stage_timings TEXT NOT NULL DEFAULT '{}',
  metadata TEXT NOT NULL DEFAULT '{}',
  temp_path TEXT,
  created_by_user_id TEXT NOT NULL DEFAULT '00000000-0000-4000-8000-000000000001',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_document_ingest_jobs_status_created
  ON document_ingest_jobs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_document_ingest_jobs_document_id
  ON document_ingest_jobs (document_id);
CREATE INDEX IF NOT EXISTS idx_document_ingest_jobs_owner_created
  ON document_ingest_jobs (created_by_user_id, created_at DESC);

-- 11. Embedding retry queue
CREATE TABLE IF NOT EXISTS embedding_retry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  last_attempt_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_embedding_retry_created
  ON embedding_retry (created_at);
