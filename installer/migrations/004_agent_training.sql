-- 004_agent_training.sql — operator-curated training examples per agent.
--
-- Each row in `training_examples` is a JSON object of one of two shapes:
--
--   { "id": "...", "kind": "manual",
--     "user": "...", "agent": "...", "notes": "...",
--     "added_at": "...", "added_by": "..." }
--
--   { "id": "...", "kind": "call",
--     "call_id": "...", "user": "...", "agent": "...",
--     "recording_path": "s3://...", "notes": "...",
--     "added_at": "...", "added_by": "..." }
--
-- These ride into the LLM prompt as in-context examples in addition to
-- the campaign few-shot pool, scoped to the specific agent. Operators
-- curate them either by typing pairs directly or by marking a recorded
-- call as exemplary on the call detail page.

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS training_examples jsonb NOT NULL DEFAULT '[]'::jsonb;
