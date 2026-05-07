-- 001_initial.down.sql — revert 001_initial.sql.
--
-- Drops in reverse dependency order. Wrapped in a single transaction by
-- the migration runner. All DROPs use IF EXISTS so a partially-applied
-- forward migration can still be rolled back cleanly.

-- ---------------------------------------------------------------------------
-- Tables (children first)
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS audit_log              CASCADE;
DROP TABLE IF EXISTS nodes                  CASCADE;

-- call_events partitions are dropped automatically with the parent.
DROP TABLE IF EXISTS call_events            CASCADE;
DROP TABLE IF EXISTS calls                  CASCADE;
DROP TABLE IF EXISTS deployments            CASCADE;
DROP TABLE IF EXISTS vicidial_servers       CASCADE;
DROP TABLE IF EXISTS agents                 CASCADE;
DROP TABLE IF EXISTS voices                 CASCADE;
DROP TABLE IF EXISTS kb_documents           CASCADE;
DROP TABLE IF EXISTS knowledge_bases        CASCADE;
DROP TABLE IF EXISTS users                  CASCADE;
DROP TABLE IF EXISTS tenants                CASCADE;

-- ---------------------------------------------------------------------------
-- Enums (after all tables that reference them are gone)
-- ---------------------------------------------------------------------------
DROP TYPE IF EXISTS node_role;
DROP TYPE IF EXISTS deployment_status;
DROP TYPE IF EXISTS kb_doc_status;
DROP TYPE IF EXISTS voice_status;
DROP TYPE IF EXISTS agent_status;
DROP TYPE IF EXISTS user_role;

-- pgcrypto extension intentionally left installed; other migrations may
-- still depend on gen_random_uuid().
