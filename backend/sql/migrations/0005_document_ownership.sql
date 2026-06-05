ALTER TABLE public.documents
  ADD COLUMN IF NOT EXISTS created_by_user_id TEXT NOT NULL DEFAULT '00000000-0000-4000-8000-000000000001';

CREATE INDEX IF NOT EXISTS idx_documents_owner_created
  ON public.documents (created_by_user_id, created_at DESC);

ALTER TABLE public.document_ingest_jobs
  ADD COLUMN IF NOT EXISTS created_by_user_id TEXT NOT NULL DEFAULT '00000000-0000-4000-8000-000000000001';

CREATE INDEX IF NOT EXISTS idx_document_ingest_jobs_owner_created
  ON public.document_ingest_jobs (created_by_user_id, created_at DESC);
