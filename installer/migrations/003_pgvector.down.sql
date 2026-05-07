-- 003_pgvector.down.sql — revert.

DROP TABLE IF EXISTS kb_chunks CASCADE;

ALTER TABLE kb_documents DROP COLUMN IF EXISTS bytes_total;
ALTER TABLE kb_documents DROP COLUMN IF EXISTS error_msg;

-- Keep the extension installed; other features may rely on it later.
