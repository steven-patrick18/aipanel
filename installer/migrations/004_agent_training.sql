-- 004_agent_training.sql — operator-uploaded training recordings per agent.
--
-- Each row in `training_recordings` is a JSON object describing one
-- audio file the operator uploaded as conversation material:
--
--   { "id": "...", "filename": "...", "content_type": "audio/wav",
--     "size_bytes": 123456, "label": "...",
--     "storage_path": "s3://aipanel-recordings/training/...",
--     "status": "queued|transcribing|ready|error",
--     "transcript": "..." | null,
--     "uploaded_at": "...", "uploaded_by": "..." }
--
-- The transcription pipeline (faster-whisper → turn-pair extraction)
-- writes the resulting `{user, agent}` pairs into the agent's
-- few-shot pool, so the LLM learns from real human conversations.

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS training_recordings jsonb NOT NULL DEFAULT '[]'::jsonb;
