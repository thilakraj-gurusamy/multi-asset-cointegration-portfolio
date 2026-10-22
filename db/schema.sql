-- Phase 1 schema: raw ingested bars + derived fields + ingestion/quality bookkeeping.
-- Designed so Phase 2+ (cointegration relationships, signals, trades) can join against
-- assets.asset_id and bars by (asset_id, interval, time) without a schema rewrite.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS assets (
    asset_id        SERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    asset_class     TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    sector          TEXT,
    source          TEXT NOT NULL,
    source_ticker   TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, asset_class)
);

CREATE TABLE IF NOT EXISTS bars (
    "time"          TIMESTAMPTZ NOT NULL,
    asset_id        INTEGER NOT NULL REFERENCES assets(asset_id),
    "interval"      TEXT NOT NULL CHECK ("interval" IN ('1hour', '1day')),
    open            DOUBLE PRECISION NOT NULL,
    high            DOUBLE PRECISION NOT NULL,
    low             DOUBLE PRECISION NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    volume          DOUBLE PRECISION,              -- NULL for FX: no consolidated FX volume
    source          TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_id, "interval", "time")
);

SELECT create_hypertable('bars', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_bars_asset_interval_time ON bars (asset_id, "interval", "time" DESC);

-- Derived fields kept alongside raw data for auditability (FRD Section 8.4).
-- Deliberately limited to simple return/rolling bookkeeping in Phase 1 -- NOT the
-- cointegration/half-life/hedge-ratio outputs, which are Phase 2/3 scope.
CREATE TABLE IF NOT EXISTS derived_bar_stats (
    "time"            TIMESTAMPTZ NOT NULL,
    asset_id          INTEGER NOT NULL REFERENCES assets(asset_id),
    "interval"        TEXT NOT NULL CHECK ("interval" IN ('1hour', '1day')),
    log_return        DOUBLE PRECISION,
    rolling_mean_20   DOUBLE PRECISION,
    rolling_std_20    DOUBLE PRECISION,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_id, "interval", "time")
);

SELECT create_hypertable('derived_bar_stats', 'time', if_not_exists => TRUE);

-- Tracks the last successfully ingested bar per (asset, interval) so incremental pulls
-- know where to resume -- required for "scheduled incremental pulls" (FRD Section 8.1/8.4).
CREATE TABLE IF NOT EXISTS ingestion_watermarks (
    asset_id            INTEGER NOT NULL REFERENCES assets(asset_id),
    "interval"          TEXT NOT NULL,
    last_ingested_time  TIMESTAMPTZ,
    PRIMARY KEY (asset_id, "interval")
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    asset_class     TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    "interval"      TEXT NOT NULL,
    source          TEXT NOT NULL,
    run_type        TEXT NOT NULL CHECK (run_type IN ('backfill', 'incremental')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed', 'partial')),
    rows_ingested   INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT
);

-- Every feed-downtime / malformed-payload / data-gap / rate-limit event, logged rather than
-- silently skipped (FRD Section 8.4, Section 9 observability).
CREATE TABLE IF NOT EXISTS data_quality_events (
    event_id        BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES ingestion_runs(run_id),
    asset_id        INTEGER REFERENCES assets(asset_id),
    event_type      TEXT NOT NULL CHECK (event_type IN ('feed_downtime', 'malformed_payload', 'data_gap', 'rate_limit', 'other')),
    severity        TEXT NOT NULL CHECK (severity IN ('warning', 'error', 'critical')),
    details         JSONB,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dqe_asset_time ON data_quality_events (asset_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_dqe_run ON data_quality_events (run_id);
