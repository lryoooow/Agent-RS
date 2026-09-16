-- Transactional outbox: document commits and graph updates survive process restarts.
CREATE TABLE IF NOT EXISTS public.knowledge_graph_jobs (
    document_id uuid PRIMARY KEY,
    user_id text NOT NULL,
    action text NOT NULL DEFAULT 'sync' CHECK (action IN ('sync', 'delete')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','indexing','ready','failed')),
    version bigint NOT NULL DEFAULT 1,
    attempts integer NOT NULL DEFAULT 0,
    error_code text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_graph_jobs_status ON public.knowledge_graph_jobs(status, updated_at);
CREATE OR REPLACE FUNCTION public.enqueue_knowledge_graph() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE doc_id uuid; owner_id text; operation text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        doc_id := OLD.id; owner_id := OLD.created_by_user_id; operation := 'delete';
    ELSE
        doc_id := NEW.id; owner_id := NEW.created_by_user_id; operation := 'sync';
    END IF;
    INSERT INTO public.knowledge_graph_jobs(document_id,user_id,action)
    VALUES(doc_id,owner_id,operation)
    ON CONFLICT(document_id) DO UPDATE SET action=EXCLUDED.action, user_id=EXCLUDED.user_id,
      status='pending', attempts=0, error_code=NULL, version=knowledge_graph_jobs.version+1, updated_at=now();
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS knowledge_graph_document_change ON public.documents;
CREATE TRIGGER knowledge_graph_document_change AFTER INSERT OR UPDATE OF content,title OR DELETE
    ON public.documents FOR EACH ROW EXECUTE FUNCTION public.enqueue_knowledge_graph();
INSERT INTO public.knowledge_graph_jobs(document_id,user_id)
SELECT id,created_by_user_id FROM public.documents ON CONFLICT DO NOTHING;
