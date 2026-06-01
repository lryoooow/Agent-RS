CREATE TABLE IF NOT EXISTS public.document_ingest_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'parsing', 'chunking', 'embedding', 'inserting', 'complete', 'failed')),
  progress INT NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
  filename TEXT,
  doc_type TEXT,
  file_size BIGINT,
  text_length INT,
  chunk_count INT,
  embedding_batches INT,
  document_id UUID REFERENCES public.documents(id) ON DELETE SET NULL,
  error_code TEXT,
  error_message TEXT,
  stage_timings JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  temp_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_ingest_jobs_status_created
  ON public.document_ingest_jobs (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_ingest_jobs_document_id
  ON public.document_ingest_jobs (document_id);
