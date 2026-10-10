-- Reuse an equivalent valid non-partial B-tree index, including a leading-column index.
-- On large installations pre-create it CONCURRENTLY before this transactional migration.
DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_am am ON am.oid = c.relam
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attname = 'document_id'
        WHERE i.indrelid = 'public.document_chunks'::regclass
          AND i.indisvalid AND i.indisready AND i.indpred IS NULL AND i.indexprs IS NULL
          AND i.indkey[0] = a.attnum AND am.amname = 'btree'
    ) THEN
        CREATE INDEX idx_document_chunks_document_id ON public.document_chunks (document_id);
    END IF;
END
$migration$;
