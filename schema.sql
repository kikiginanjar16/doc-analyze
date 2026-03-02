BEGIN;

CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NULL,
    application TEXT NULL,
    reference_id TEXT NULL,
    document_id TEXT NULL,
    user_prompt TEXT NULL,
    detected_type TEXT NULL,
    used_vision BOOLEAN NOT NULL DEFAULT FALSE,
    max_pages INTEGER NOT NULL,
    max_slides INTEGER NOT NULL,
    markdown TEXT NOT NULL,
    meta_json JSONB NOT NULL,
    webhook_url TEXT NULL,
    webhook_status TEXT NOT NULL DEFAULT 'not_requested',
    webhook_attempts INTEGER NOT NULL DEFAULT 0,
    last_webhook_error TEXT NULL,
    last_webhook_at TIMESTAMPTZ NULL
);

ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS application TEXT NULL;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS reference_id TEXT NULL;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS document_id TEXT NULL;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS user_prompt TEXT NULL;

CREATE TABLE IF NOT EXISTS analysis_chunks (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, chunk_index)
);

COMMIT;
