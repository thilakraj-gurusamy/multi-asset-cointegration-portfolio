-- Phase 5: crypto module + paper-trading loop + dashboard (FRD Sections 8.1, 8.8, 9, 10, 12).

-- Widen asset_class to admit 'crypto' -- but ONLY on the Phase 1/2/3 tables (ingestion,
-- cointegration, health). Phase 4's tables (signals, trades, backtest_runs) are deliberately
-- LEFT UNCHANGED (still just 'fx'/'equity') so that any future code path that tried to wire
-- crypto into the production signal/risk pipeline would fail loudly at the database level,
-- not just by convention -- the "do NOT treat crypto as a production-weighted signal source"
-- rule from the Scope Decision (Section 3) is enforced structurally here, not just in code.
ALTER TABLE assets DROP CONSTRAINT assets_asset_class_check;
ALTER TABLE assets ADD CONSTRAINT assets_asset_class_check CHECK (asset_class IN ('fx', 'equity', 'crypto'));

ALTER TABLE ingestion_runs DROP CONSTRAINT ingestion_runs_asset_class_check;
ALTER TABLE ingestion_runs ADD CONSTRAINT ingestion_runs_asset_class_check CHECK (asset_class IN ('fx', 'equity', 'crypto'));

ALTER TABLE engle_granger_results DROP CONSTRAINT engle_granger_results_asset_class_check;
ALTER TABLE engle_granger_results ADD CONSTRAINT engle_granger_results_asset_class_check CHECK (asset_class IN ('fx', 'equity', 'crypto'));

ALTER TABLE johansen_results DROP CONSTRAINT johansen_results_asset_class_check;
ALTER TABLE johansen_results ADD CONSTRAINT johansen_results_asset_class_check CHECK (asset_class IN ('fx', 'equity', 'crypto'));

ALTER TABLE method_disagreements DROP CONSTRAINT method_disagreements_asset_class_check;
ALTER TABLE method_disagreements ADD CONSTRAINT method_disagreements_asset_class_check CHECK (asset_class IN ('fx', 'equity', 'crypto'));

ALTER TABLE relationship_health DROP CONSTRAINT relationship_health_asset_class_check;
ALTER TABLE relationship_health ADD CONSTRAINT relationship_health_asset_class_check CHECK (asset_class IN ('fx', 'equity', 'crypto'));

-- Live paper-trading state, persisted ACROSS cycles (unlike Phase 4's backtest, which holds
-- position state only in memory for the duration of one historical replay). asset_class is
-- deliberately restricted to 'fx'/'equity' here too -- crypto never opens a paper position.
CREATE TABLE IF NOT EXISTS paper_positions (
    relationship_key       TEXT NOT NULL,
    asset_class               TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    direction                   TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    entry_date                    DATE NOT NULL,
    entry_z                         DOUBLE PRECISION,
    entry_spread_value                DOUBLE PRECISION NOT NULL,
    position_units                      DOUBLE PRECISION NOT NULL,
    sizing_detail                         JSONB NOT NULL,
    last_mark_date                          DATE NOT NULL,
    last_spread                               DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (asset_class, relationship_key)
);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id              BIGSERIAL PRIMARY KEY,
    asset_class              TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    relationship_key           TEXT NOT NULL,
    direction                    TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    entry_date                     DATE NOT NULL,
    entry_z                          DOUBLE PRECISION,
    entry_spread_value                 DOUBLE PRECISION NOT NULL,
    position_units                       DOUBLE PRECISION NOT NULL,
    sizing_detail                           JSONB NOT NULL,
    exit_date                                 DATE NOT NULL,
    exit_z                                      DOUBLE PRECISION,
    exit_spread_value                             DOUBLE PRECISION NOT NULL,
    exit_reason                                     TEXT NOT NULL CHECK (exit_reason IN ('z_exit', 'health_halted_stop')),
    gross_pnl                                         DOUBLE PRECISION NOT NULL,
    transaction_cost                                    DOUBLE PRECISION NOT NULL,
    slippage_cost                                         DOUBLE PRECISION NOT NULL,
    net_pnl                                                 DOUBLE PRECISION NOT NULL,
    created_at                                                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_asset_class ON paper_trades (asset_class, entry_date);

-- One row per calendar day the paper-trading cycle actually ran the Phase 4 step -- the
-- dashboard's live P&L chart reads this directly.
CREATE TABLE IF NOT EXISTS paper_equity_curve (
    asset_class          TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    "date"                 DATE NOT NULL,
    equity                   DOUBLE PRECISION NOT NULL,
    peak_equity                DOUBLE PRECISION NOT NULL,  -- stored explicitly, not back-computed
                                                              -- from drawdown_pct, to reconstruct
                                                              -- DrawdownTracker state exactly across
                                                              -- cycles (a persisted process, unlike
                                                              -- the backtest's in-memory-only tracker)
    daily_pnl                   DOUBLE PRECISION NOT NULL,
    drawdown_pct                  DOUBLE PRECISION NOT NULL,
    halted                          BOOLEAN NOT NULL,
    PRIMARY KEY (asset_class, "date")
);

-- Cycle-level observability (Section 9): every paper-trading cycle, whether or not anything
-- traded, so the dashboard can show pipeline health/uptime directly, not just infer it from
-- the absence of errors elsewhere.
CREATE TABLE IF NOT EXISTS paper_cycle_log (
    cycle_id            BIGSERIAL PRIMARY KEY,
    started_at             TIMESTAMPTZ NOT NULL,
    finished_at              TIMESTAMPTZ,
    status                     TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    steps                        JSONB NOT NULL,   -- per-step outcome (ingest/cointegration/health/signals x {fx,equity,crypto})
    error_message                  TEXT,
    duration_seconds                 DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_paper_cycle_log_started ON paper_cycle_log (started_at DESC);
