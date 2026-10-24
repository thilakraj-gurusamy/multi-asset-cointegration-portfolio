-- Phase 3: relationship-health / decay monitoring (FRD Section 8.5) -- the project's core
-- differentiator. Consumes Phase 2's per-window outputs; adds what Phase 2 deliberately did
-- NOT compute: hedge-ratio drift between successive windows, and the healthy/warning/halted
-- classification itself.

-- Additive enrichment of Phase 2's johansen_results: the 90%/99% trace critical values were
-- already computed internally by coint_johansen in Phase 2 but not persisted. Needed here to
-- build a continuous pseudo-p-value for basket relationships, since Johansen has no native
-- p-value the way Engle-Granger does. Phase 2's own methodology/behaviour is unchanged.
ALTER TABLE johansen_results ADD COLUMN IF NOT EXISTS trace_crit_90_rank0 DOUBLE PRECISION;
ALTER TABLE johansen_results ADD COLUMN IF NOT EXISTS trace_crit_99_rank0 DOUBLE PRECISION;

-- One row per (relationship, window): the full health computation and classification, logged
-- in full even when nothing changed -- this table alone is the audit trail satisfying
-- "log every health-status change with the exact inputs and parameters" (Section 9), since
-- every window's inputs are here regardless of whether the status moved.
CREATE TABLE IF NOT EXISTS relationship_health (
    health_id                  BIGSERIAL PRIMARY KEY,
    asset_class                  TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    "interval"                     TEXT NOT NULL,
    relationship_key                 TEXT NOT NULL,       -- e.g. "EUR/USD,GBP/USD" or a basket_key
    relationship_type                  TEXT NOT NULL CHECK (relationship_type IN ('pair', 'basket')),
    source_method                        TEXT NOT NULL CHECK (source_method IN ('engle_granger', 'johansen')),
    window_start                           TIMESTAMPTZ NOT NULL,
    window_end                               TIMESTAMPTZ NOT NULL,
    p_value                                    DOUBLE PRECISION NOT NULL,
    p_value_is_proxy                             BOOLEAN NOT NULL,   -- true for Johansen-basket pseudo-p-value
    hedge_ratio_or_vector                          JSONB NOT NULL,    -- scalar (pairs) or vector (baskets)
    hedge_ratio_drift_pct                            DOUBLE PRECISION, -- NULL on a relationship's first window
    half_life_days                                     DOUBLE PRECISION,
    p_value_status                                       TEXT NOT NULL CHECK (p_value_status IN ('healthy','warning','halted')),
    hedge_ratio_drift_status                               TEXT CHECK (hedge_ratio_drift_status IN ('healthy','warning','halted')),
    half_life_status                                        TEXT NOT NULL CHECK (half_life_status IN ('healthy','warning','halted')),
    overall_status                                            TEXT NOT NULL CHECK (overall_status IN ('healthy','warning','halted')),
    computed_at                                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, "interval", relationship_key, window_end)
);

CREATE INDEX IF NOT EXISTS idx_rel_health_latest
    ON relationship_health (asset_class, "interval", relationship_key, window_end DESC);

-- A row only when overall_status actually CHANGES from the relationship's immediately
-- preceding window -- the specific "event" the observability hook and position-review flag
-- react to, separate from the full per-window log above.
CREATE TABLE IF NOT EXISTS health_status_transitions (
    transition_id         BIGSERIAL PRIMARY KEY,
    asset_class             TEXT NOT NULL,
    "interval"                TEXT NOT NULL,
    relationship_key           TEXT NOT NULL,
    relationship_type            TEXT NOT NULL,
    window_end                     TIMESTAMPTZ NOT NULL,
    previous_status                  TEXT,     -- NULL if this relationship had no prior window
    new_status                         TEXT NOT NULL CHECK (new_status IN ('healthy','warning','halted')),
    reason                                JSONB NOT NULL,   -- which sub-metric(s) drove it + their values
    computed_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, "interval", relationship_key, window_end)
);

CREATE INDEX IF NOT EXISTS idx_transitions_window ON health_status_transitions (window_end, new_status);

-- No position-management system exists yet -- that is Phase 4. This is the hook/audit trail
-- Phase 4 will query once it creates real positions ("has this relationship's position been
-- flagged for review?"). For now there is nothing to flag beyond the relationship itself, so
-- position_id stays NULL until Phase 4 exists.
CREATE TABLE IF NOT EXISTS position_review_flags (
    flag_id              BIGSERIAL PRIMARY KEY,
    asset_class            TEXT NOT NULL,
    "interval"               TEXT NOT NULL,
    relationship_key          TEXT NOT NULL,
    window_end                  TIMESTAMPTZ NOT NULL,
    position_id                   BIGINT,
    reason                           JSONB NOT NULL,
    flagged_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at                         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_review_flags_open ON position_review_flags (relationship_key, resolved_at);
