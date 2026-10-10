-- Preserve the existing success name; interrupted execution is not ordinary failure.
ALTER TABLE public.tool_jobs DROP CONSTRAINT IF EXISTS tool_jobs_status_check;
ALTER TABLE public.tool_jobs ADD CONSTRAINT tool_jobs_status_check
  CHECK (status IN ('pending', 'running', 'complete', 'failed', 'cancelled', 'outcome_unknown'));
