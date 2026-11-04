CREATE TABLE IF NOT EXISTS public.ontology_definitions (
    user_id text PRIMARY KEY,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    overlay jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
