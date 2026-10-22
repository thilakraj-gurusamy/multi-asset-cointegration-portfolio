-- Phase 2: cointegration engine outputs (FRD Section 8.2). Raw per-rolling-window results
-- only. Deliberately NO health-status columns (healthy/warning/halted), no drift-tracking
-- columns, no gating logic anywhere here -- that is Phase 3 (FRD Section 8.5), which will
-- read these rows and compute drift/thresholds on top of them.

CREATE TABLE IF NOT EXISTS adf_results (
    result_id       BIGSERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES assets(asset_id),
    "interval"      TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    series_type     TEXT NOT NULL CHECK (series_type IN ('levels', 'first_diff')),
    test_statistic  DOUBLE PRECISION,
    p_value         DOUBLE PRECISION,
    n_obs           INTEGER,
    lags_used       INTEGER,
    is_stationary   BOOLEAN NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_id, "interval", window_start, window_end, series_type)
);

CREATE INDEX IF NOT EXISTS idx_adf_asset_window ON adf_results (asset_id, "interval", window_end);

-- Engle-Granger is run in BOTH regressand directions per pair, per window -- results are not
-- invariant to which series is the regressand (FRD Section 8.2), so both directions are
-- persisted as separate rows rather than collapsed into one.
CREATE TABLE IF NOT EXISTS engle_granger_results (
    result_id              BIGSERIAL PRIMARY KEY,
    asset_class             TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    "interval"               TEXT NOT NULL,
    window_start              TIMESTAMPTZ NOT NULL,
    window_end                 TIMESTAMPTZ NOT NULL,
    regressand_asset_id         INTEGER NOT NULL REFERENCES assets(asset_id),
    regressor_asset_id           INTEGER NOT NULL REFERENCES assets(asset_id),
    test_statistic                 DOUBLE PRECISION,
    p_value                          DOUBLE PRECISION,
    hedge_ratio                       DOUBLE PRECISION,
    half_life_days                     DOUBLE PRECISION,
    is_significant_5pct                  BOOLEAN NOT NULL,  -- diagnostic read of the EG p-value
                                                              -- itself; NOT a Phase 3 trading gate
    computed_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, "interval", window_start, window_end, regressand_asset_id, regressor_asset_id)
);

CREATE INDEX IF NOT EXISTS idx_eg_pair_window
    ON engle_granger_results (regressand_asset_id, regressor_asset_id, window_end);

-- Covers both bivariate Johansen (run specifically to compare against Engle-Granger on the
-- same pair) and 3+-asset baskets (FRD's actual Johansen requirement).
CREATE TABLE IF NOT EXISTS johansen_results (
    result_id              BIGSERIAL PRIMARY KEY,
    asset_class              TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    "interval"                 TEXT NOT NULL,
    window_start                TIMESTAMPTZ NOT NULL,
    window_end                    TIMESTAMPTZ NOT NULL,
    basket_key                      TEXT NOT NULL,       -- sorted, comma-joined symbols
    asset_ids                         INTEGER[] NOT NULL,
    n_assets                            INTEGER NOT NULL,
    lag_order                             INTEGER NOT NULL,     -- selected via AIC on the VAR
    deterministic_term                     TEXT NOT NULL,       -- explicitly chosen + recorded
    trace_stat_rank0                         DOUBLE PRECISION,
    trace_crit_95_rank0                        DOUBLE PRECISION,
    cointegration_rank                           INTEGER NOT NULL,   -- from the trace test at 95%
    cointegrating_vectors                          JSONB,             -- list of vectors
    adjustment_speeds                                JSONB,           -- alpha matrix, rank >= 1 only
    half_life_days_primary                             DOUBLE PRECISION,
    computed_at                                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, "interval", window_start, window_end, basket_key)
);

CREATE INDEX IF NOT EXISTS idx_johansen_basket_window ON johansen_results (basket_key, window_end);

-- Comparison of Engle-Granger vs Johansen on the SAME bivariate case, same window. Flags
-- disagreement for reporting -- this is a diagnostic comparison, not a health/trading gate.
CREATE TABLE IF NOT EXISTS method_disagreements (
    disagreement_id           BIGSERIAL PRIMARY KEY,
    asset_class                 TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    "interval"                    TEXT NOT NULL,
    window_start                   TIMESTAMPTZ NOT NULL,
    window_end                       TIMESTAMPTZ NOT NULL,
    asset_id_a                         INTEGER NOT NULL REFERENCES assets(asset_id),
    asset_id_b                           INTEGER NOT NULL REFERENCES assets(asset_id),
    engle_granger_result_id                BIGINT REFERENCES engle_granger_results(result_id),
    johansen_result_id                       BIGINT REFERENCES johansen_results(result_id),
    eg_significant_at_5pct                     BOOLEAN NOT NULL,
    johansen_rank_at_least_1                     BOOLEAN NOT NULL,
    disagree                                       BOOLEAN NOT NULL,
    computed_at                                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, "interval", window_start, window_end, asset_id_a, asset_id_b)
);

CREATE INDEX IF NOT EXISTS idx_disagreements_window ON method_disagreements (window_end, disagree);
