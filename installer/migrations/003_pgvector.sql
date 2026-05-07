-- 003_pgvector.sql — enable pgvector + create kb_chunks for RAG.
--
-- Embedding dim is fixed at 1024 (BAAI/bge-m3 native size). Switching
-- embed model later means a follow-up migration that ALTERs the column
-- and re-embeds — bgec-m3 is the deliberate choice for v1 because it's
-- multilingual + competitive on retrieval benchmarks.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_chunks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     uuid NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    kb_id           uuid NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    chunk_text      text NOT NULL,
    chunk_tokens    integer NOT NULL DEFAULT 0,
    embedding       vector(1024) NOT NULL,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Cosine similarity is the standard for sentence embeddings; HNSW gives
-- sub-100ms recall at 100k+ chunks per KB. lists=100 is a reasonable
-- starting point that the operator can tune (REINDEX with lists=sqrt(N)).
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding
    ON kb_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_document    ON kb_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb          ON kb_chunks(kb_id);

-- Track total chunk count + last-ingest time on the parent document so
-- the UI can show "ready (123 chunks)" without a count(*) per row.
ALTER TABLE kb_documents
    ADD COLUMN IF NOT EXISTS bytes_total integer DEFAULT 0,
    ADD COLUMN IF NOT EXISTS error_msg   text;
