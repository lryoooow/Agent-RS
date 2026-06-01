CREATE TABLE IF NOT EXISTS public.embedding_retry (
  id BIGSERIAL PRIMARY KEY,
  message_id UUID NOT NULL REFERENCES chatbot.messages(id) ON DELETE CASCADE,
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  last_attempt_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embedding_retry_created
  ON public.embedding_retry (created_at);
