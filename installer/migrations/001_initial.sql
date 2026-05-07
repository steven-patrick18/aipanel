-- 001_initial.sql — initial aipanel schema.
--
-- Applied by installer/lib/migrate.sh inside a single transaction. The
-- migration runner records success in the schema_migrations table; this
-- file should not need IF NOT EXISTS for tables in normal use, but uses
-- it anyway so that an operator who manually runs the file twice does not
-- get a hard failure.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Enums (PG has no CREATE TYPE IF NOT EXISTS — wrap each in DO/EXCEPTION)
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'operator', 'viewer');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE agent_status AS ENUM ('draft', 'ready', 'archived');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE voice_status AS ENUM ('pending', 'training', 'ready', 'error');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE kb_doc_status AS ENUM ('pending', 'processing', 'ready', 'error');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE deployment_status AS ENUM ('stopped', 'starting', 'running', 'error');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE node_role AS ENUM ('primary', 'secondary');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- tenants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    settings    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           text NOT NULL UNIQUE,
    password_hash   text NOT NULL,
    role            user_role NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);

-- ---------------------------------------------------------------------------
-- knowledge_bases (defined before agents — agents references it)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            text NOT NULL,
    description     text,
    embedding_model text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_tenant_id ON knowledge_bases(tenant_id);

-- ---------------------------------------------------------------------------
-- kb_documents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_documents (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id         uuid NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename      text NOT NULL,
    content_hash  text NOT NULL,
    chunk_count   integer NOT NULL DEFAULT 0,
    status        kb_doc_status NOT NULL DEFAULT 'pending',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_documents_kb_id ON kb_documents(kb_id);

-- ---------------------------------------------------------------------------
-- voices (defined before agents — agents references it)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            text NOT NULL,
    sample_path     text,
    embedding_path  text,
    status          voice_status NOT NULL DEFAULT 'pending',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_voices_tenant_id ON voices(tenant_id);

-- ---------------------------------------------------------------------------
-- agents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name              text NOT NULL,
    persona           jsonb NOT NULL DEFAULT '{}'::jsonb,
    voice_id          uuid REFERENCES voices(id) ON DELETE SET NULL,
    language          text NOT NULL DEFAULT 'en',
    script            jsonb NOT NULL DEFAULT '{}'::jsonb,
    scenario_tree     jsonb NOT NULL DEFAULT '{}'::jsonb,
    kb_collection_id  uuid REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    status            agent_status NOT NULL DEFAULT 'draft',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agents_tenant_status   ON agents(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_voice_id        ON agents(voice_id);
CREATE INDEX IF NOT EXISTS idx_agents_kb_collection   ON agents(kb_collection_id);

-- ---------------------------------------------------------------------------
-- vicidial_servers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vicidial_servers (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                text NOT NULL,
    asterisk_host       text NOT NULL,
    asterisk_port       integer NOT NULL DEFAULT 5038,
    web_url             text NOT NULL,
    ami_user            text NOT NULL,
    ami_pass_encrypted  text NOT NULL,
    web_user_admin      text NOT NULL,
    web_pass_encrypted  text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vicidial_servers_tenant_id ON vicidial_servers(tenant_id);

-- ---------------------------------------------------------------------------
-- deployments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deployments (
    id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id                   uuid NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    vicidial_server_id         uuid NOT NULL REFERENCES vicidial_servers(id) ON DELETE RESTRICT,
    vici_user                  text NOT NULL,
    vici_pass_encrypted        text NOT NULL,
    phone_login                text NOT NULL,
    phone_pass_encrypted       text NOT NULL,
    campaign_id                text NOT NULL,
    allowed_transfer_ingroups  text[] NOT NULL DEFAULT ARRAY[]::text[],
    dispo_mapping              jsonb NOT NULL DEFAULT '{}'::jsonb,
    status                     deployment_status NOT NULL DEFAULT 'stopped',
    last_heartbeat_at          timestamptz,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_deployments_status              ON deployments(status);
CREATE INDEX IF NOT EXISTS idx_deployments_tenant_status       ON deployments(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_deployments_agent_id            ON deployments(agent_id);
CREATE INDEX IF NOT EXISTS idx_deployments_vicidial_server_id  ON deployments(vicidial_server_id);

-- ---------------------------------------------------------------------------
-- calls
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calls (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_id   uuid NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
    vici_uniqueid   text NOT NULL UNIQUE,
    vici_lead_id    text,
    phone_number    text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    duration_sec    integer,
    outcome         text,
    dispo_code      text,
    transfer_target text,
    transcript_path text,
    recording_path  text
);
-- vici_uniqueid is UNIQUE (implicit btree).
CREATE INDEX IF NOT EXISTS idx_calls_deployment_started ON calls(deployment_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- call_events — partitioned by month on ts.
-- PG requires partition-key columns to be part of the primary key, hence
-- PK = (id, ts). The application can still treat id as the natural row key.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS call_events (
    id          uuid NOT NULL DEFAULT gen_random_uuid(),
    call_id     uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    ts          timestamptz NOT NULL,
    event_type  text NOT NULL,
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE INDEX IF NOT EXISTS idx_call_events_call_ts ON call_events(call_id, ts);

-- Default partition catches any timestamp without a dedicated monthly
-- partition. A maintenance job (later prompt) creates rolling monthly
-- partitions and detaches the default once it sees stable traffic.
CREATE TABLE IF NOT EXISTS call_events_default
    PARTITION OF call_events DEFAULT;

-- ---------------------------------------------------------------------------
-- nodes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname           text NOT NULL UNIQUE,
    role               node_role NOT NULL,
    services           text[] NOT NULL DEFAULT ARRAY[]::text[],
    status             text NOT NULL DEFAULT 'unknown',
    last_heartbeat_at  timestamptz,
    joined_at          timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- audit_log — high-volume; bigserial PK, indexed by ts and FKs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id           bigserial PRIMARY KEY,
    ts           timestamptz NOT NULL DEFAULT now(),
    user_id      uuid REFERENCES users(id)   ON DELETE SET NULL,
    tenant_id    uuid REFERENCES tenants(id) ON DELETE SET NULL,
    action       text NOT NULL,
    target_type  text,
    target_id    uuid,
    payload      jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id   ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_id ON audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts        ON audit_log(ts DESC);
