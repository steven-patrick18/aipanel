-- 005_node_join.sql — single-use tokens for joining a new node to the cluster.
--
-- Workflow:
--   1. Admin generates a token via the Cluster page or `aipanelctl node token-create`.
--   2. Operator runs `install.sh --join=<token> --primary=<url>` on the new box.
--   3. install.sh POSTs the token to /api/v1/cluster/join on the primary.
--   4. Primary verifies the token, marks it consumed, returns the cluster
--      config the new node needs to wire itself up (DSN, Redis URL, etc).
--   5. New node registers in the existing `nodes` table and starts heartbeating.

-- Extend node_role enum so new boxes can specialise. Existing
-- 'primary' / 'secondary' values stay valid for backwards compat.
DO $$ BEGIN
    ALTER TYPE node_role ADD VALUE IF NOT EXISTS 'gpu';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TYPE node_role ADD VALUE IF NOT EXISTS 'app';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TYPE node_role ADD VALUE IF NOT EXISTS 'sip';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TYPE node_role ADD VALUE IF NOT EXISTS 'mixed';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Drain marker — set when an operator pauses a node before removing it.
ALTER TABLE nodes
    ADD COLUMN IF NOT EXISTS drained_at timestamptz;

CREATE TABLE IF NOT EXISTS node_join_tokens (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- SHA-256 of the secret. The plaintext token is shown to the admin
    -- exactly once at creation; only its hash hits the DB.
    token_hash          text NOT NULL UNIQUE,
    role                text NOT NULL,        -- gpu | app | sip | mixed
    label               text NOT NULL DEFAULT '',
    created_by          uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    consumed_at         timestamptz,
    consumed_by_node    uuid REFERENCES nodes(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_node_join_tokens_active
    ON node_join_tokens(expires_at)
    WHERE consumed_at IS NULL;
