DROP INDEX IF EXISTS idx_node_join_tokens_active;
DROP TABLE IF EXISTS node_join_tokens;
ALTER TABLE nodes DROP COLUMN IF EXISTS drained_at;
-- node_role enum values added in upgrade are NOT removed (PostgreSQL
-- doesn't support DROP VALUE) — they remain harmless if unused.
