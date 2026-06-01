CREATE TABLE IF NOT EXISTS chatbot.schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE chatbot.messages
  ADD COLUMN IF NOT EXISTS embedding vector(1536),
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'complete',
  ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_message_status'
      AND conrelid = 'chatbot.messages'::regclass
  ) THEN
    ALTER TABLE chatbot.messages
      ADD CONSTRAINT ck_message_status
      CHECK (status IN ('streaming', 'complete', 'failed'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_messages_embedding_ivfflat
  ON chatbot.messages
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_messages_conv_created
  ON chatbot.messages (conversation_id, created_at);
