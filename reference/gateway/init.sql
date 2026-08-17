-- Schema for persisting lub GuardResults.
-- Written by the INSTITUTION, not shipped by lub.

CREATE TABLE IF NOT EXISTS lub_results (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    question    TEXT NOT NULL,
    result_json JSONB NOT NULL
);

CREATE INDEX idx_lub_results_ts ON lub_results (ts DESC);
