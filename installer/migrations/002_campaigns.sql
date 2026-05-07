-- 002_campaigns.sql — per-campaign training scaffolding.
--
-- A campaign is a reusable bundle of: persona/script templates, success
-- definition, KB binding, and a few-shot pool mined from prior successful
-- calls. Multiple agents/deployments can point at the same campaign so
-- you don't repeat playbook work.
--
-- Wrapped per the conventions of 001 (DO/EXCEPTION for enums, IF NOT
-- EXISTS for tables/indexes, ALTER ... ADD COLUMN IF NOT EXISTS for
-- additive changes).

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE campaign_status AS ENUM ('draft', 'active', 'paused', 'archived');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE campaign_methodology AS ENUM (
        'spin', 'bant', 'meddpicc', 'consultative', 'value_based', 'custom'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- campaigns
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campaigns (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                 text NOT NULL,
    description          text NOT NULL DEFAULT '',
    methodology          campaign_methodology NOT NULL DEFAULT 'consultative',
    objective            text NOT NULL DEFAULT '',
    -- Disposition codes that count as a "success" for mining + metrics.
    success_dispos       text[] NOT NULL DEFAULT ARRAY['QUAL', 'XFER']::text[],
    -- Default persona/script that NEW agents in this campaign inherit.
    -- Existing agents merge campaign template under their own values.
    persona_template     jsonb NOT NULL DEFAULT '{}'::jsonb,
    script_template      jsonb NOT NULL DEFAULT '{}'::jsonb,
    kb_collection_id     uuid REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    -- Mined few-shot exchanges. Shape:
    -- [{user, agent, score, call_id, mined_at}, ...]
    few_shot_pool        jsonb NOT NULL DEFAULT '[]'::jsonb,
    few_shot_updated_at  timestamptz,
    status               campaign_status NOT NULL DEFAULT 'draft',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_tenant_status ON campaigns(tenant_id, status);

-- ---------------------------------------------------------------------------
-- Linkage to existing tables (nullable for backwards compat)
-- ---------------------------------------------------------------------------
-- NOTE: deployments.campaign_id already exists as the *ViciDial campaign
-- code* (text — e.g. 'SOLAR'). We use a different column name here for the
-- aipanel-campaign reference to avoid the collision.
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS campaign_id uuid
    REFERENCES campaigns(id) ON DELETE SET NULL;

ALTER TABLE deployments
    ADD COLUMN IF NOT EXISTS aipanel_campaign_id uuid
    REFERENCES campaigns(id) ON DELETE SET NULL;

ALTER TABLE calls
    ADD COLUMN IF NOT EXISTS campaign_id uuid
    REFERENCES campaigns(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_agents_campaign       ON agents(campaign_id);
CREATE INDEX IF NOT EXISTS idx_deployments_aip_camp  ON deployments(aipanel_campaign_id);
CREATE INDEX IF NOT EXISTS idx_calls_campaign        ON calls(campaign_id);
