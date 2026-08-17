# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""SQLite schema for the uncertainty ledger.

Five tables, all foreign-keyed back to ``queries``:

* ``queries``   -- one row per prompt.
* ``answers``   -- one row per (query, model, tier) completion.
* ``uq_scores`` -- one row per (answer, method) score.
* ``outcomes``  -- at most one row per answer; populated when ground
                  truth or a human verdict arrives.
* ``policy_decisions`` -- one row per guard / router decision.

Schema is idempotent: ``CREATE TABLE IF NOT EXISTS`` everywhere. Schema
version is tracked in the ``_ledger_meta`` table so future migrations
can be gated.
"""

from __future__ import annotations

SCHEMA_VERSION = 3

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS _ledger_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_hash  TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT 'generic',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_queries_hash   ON queries(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_queries_domain ON queries(domain);

CREATE TABLE IF NOT EXISTS answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id    INTEGER NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    backend     TEXT NOT NULL,
    tier        TEXT,
    answer      TEXT NOT NULL,
    latency_ms  REAL,
    cost        REAL DEFAULT 0.0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_answers_query ON answers(query_id);

CREATE TABLE IF NOT EXISTS uq_scores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id  INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    method     TEXT NOT NULL,
    value      REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_uq_answer_method ON uq_scores(answer_id, method);

CREATE TABLE IF NOT EXISTS outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id     INTEGER NOT NULL UNIQUE REFERENCES answers(id) ON DELETE CASCADE,
    ground_truth  TEXT,
    human_verdict TEXT,
    correct       INTEGER NOT NULL CHECK (correct IN (0, 1)),
    labelled_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id  INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    decision   TEXT NOT NULL,
    threshold  REAL NOT NULL,
    passed     INTEGER NOT NULL CHECK (passed IN (0, 1)),
    reason     TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_policy_answer ON policy_decisions(answer_id);

-- ------------------------------------------------------------------------
-- CEC (Continuous Effective Challenge) tables -- schema v2 additive migration.
-- ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS cec_meta_predictions (
    claim_id             TEXT PRIMARY KEY,
    predicted_confidence REAL NOT NULL,
    horizon_days         INTEGER NOT NULL,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS cec_meta_outcomes (
    claim_id     TEXT PRIMARY KEY,
    held_up      INTEGER NOT NULL CHECK (held_up IN (0, 1)),
    recorded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY(claim_id) REFERENCES cec_meta_predictions(claim_id)
);
CREATE INDEX IF NOT EXISTS idx_cec_meta_outcomes_held_up ON cec_meta_outcomes(held_up);

-- ------------------------------------------------------------------------
-- Context Autopilot tables -- schema v3 additive migration.
-- ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS context_window_observations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    turn_id             INTEGER NOT NULL,
    input_tokens        INTEGER NOT NULL,
    cumulative_tokens   INTEGER NOT NULL,
    model_max_context   INTEGER NOT NULL,
    headroom_ratio      REAL NOT NULL,
    observed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_context_obs_session ON context_window_observations(session_id);
CREATE INDEX IF NOT EXISTS idx_context_obs_session_turn ON context_window_observations(session_id, turn_id);

CREATE TABLE IF NOT EXISTS context_ejections (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    ejected_turn_id     INTEGER NOT NULL,
    ejection_score      REAL NOT NULL,
    similarity_term     REAL NOT NULL,
    age_term            REAL NOT NULL,
    usefulness_term     REAL NOT NULL,
    threshold_at_eject  REAL NOT NULL,
    ejected_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_context_ejections_session ON context_ejections(session_id);

CREATE TABLE IF NOT EXISTS context_recall_flags (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    later_turn_id       INTEGER NOT NULL,
    referenced_eject_id INTEGER NOT NULL REFERENCES context_ejections(id),
    similarity_score    REAL NOT NULL,
    flagged_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_context_recall_session ON context_recall_flags(session_id);
"""


__all__ = ["SCHEMA_SQL", "SCHEMA_VERSION"]
