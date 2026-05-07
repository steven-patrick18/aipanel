-- 002_campaigns.down.sql — revert 002_campaigns.sql.

ALTER TABLE calls       DROP COLUMN IF EXISTS campaign_id;
ALTER TABLE deployments DROP COLUMN IF EXISTS aipanel_campaign_id;
ALTER TABLE agents      DROP COLUMN IF EXISTS campaign_id;

DROP TABLE IF EXISTS campaigns CASCADE;

DROP TYPE IF EXISTS campaign_methodology;
DROP TYPE IF EXISTS campaign_status;
