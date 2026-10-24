-- Phase 4: signal generation, risk management, walk-forward backtest (FRD Sections 8.6-8.8).

-- One row per signal EVALUATION, not just per trade -- including suppressed ones. This is
-- what proves the health gate actually blocks entries (Section 12 / Phase 4 review checklist),
-- since a reviewer can see "a z>2 crossing happened here, but was suppressed by warning/halted"
-- rather than just an absence of a trade with no explanation.
CREATE TABLE IF NOT EXISTS signals (
    signal_id            BIGSERIAL PRIMARY KEY,
    run_id                 BIGINT,                    -- set once backtest_runs exists for this run
    asset_class              TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    relationship_key           TEXT NOT NULL,
    "date"                       DATE NOT NULL,
    window_start                  TIMESTAMPTZ,          -- the governing in-sample fit window
    window_end                      TIMESTAMPTZ,
    z_score                           DOUBLE PRECISION,
    health_status                      TEXT NOT NULL,
    weights                              JSONB NOT NULL,   -- the fixed in-sample weights used
    z_entry                                DOUBLE PRECISION NOT NULL,
    z_exit                                    DOUBLE PRECISION NOT NULL,
    action                                      TEXT NOT NULL CHECK (action IN
                                                   ('enter_long','enter_short','exit_z',
                                                    'exit_health_halted','hold','no_action',
                                                    'suppressed_warning','suppressed_halted')),
    computed_at                                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_run ON signals (run_id, "date");
CREATE INDEX IF NOT EXISTS idx_signals_relationship ON signals (relationship_key, "date");

-- Full position lifecycle: one row per completed (or still-open-at-backtest-end) trade.
CREATE TABLE IF NOT EXISTS trades (
    trade_id              BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT NOT NULL,
    asset_class               TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    relationship_key           TEXT NOT NULL,
    direction                    TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    entry_date                     DATE NOT NULL,
    entry_z                          DOUBLE PRECISION,
    entry_spread_value                 DOUBLE PRECISION NOT NULL,
    position_units                       DOUBLE PRECISION NOT NULL,
    sizing_detail                          JSONB NOT NULL,   -- vol-target / leverage-cap /
                                                               -- liquidity-cap units, which bound
    exit_date                                DATE,
    exit_z                                     DOUBLE PRECISION,
    exit_spread_value                            DOUBLE PRECISION,
    exit_reason                                    TEXT CHECK (exit_reason IN
                                                       ('z_exit', 'health_halted_stop', 'end_of_backtest')),
    gross_pnl                                        DOUBLE PRECISION,
    transaction_cost                                   DOUBLE PRECISION,
    slippage_cost                                        DOUBLE PRECISION,
    net_pnl                                                DOUBLE PRECISION,
    created_at                                               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trades_run ON trades (run_id);
CREATE INDEX IF NOT EXISTS idx_trades_relationship ON trades (relationship_key, entry_date);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id                BIGSERIAL PRIMARY KEY,
    asset_class             TEXT NOT NULL CHECK (asset_class IN ('fx', 'equity')),
    strategy_variant          TEXT NOT NULL CHECK (strategy_variant IN
                                ('walk_forward_health_gated', 'naive_static_eg', 'buy_and_hold')),
    start_date                  DATE NOT NULL,
    end_date                      DATE NOT NULL,
    params                          JSONB NOT NULL,
    starting_equity                  DOUBLE PRECISION NOT NULL,
    final_equity                       DOUBLE PRECISION,
    total_return_pct                     DOUBLE PRECISION,
    annualized_sharpe                      DOUBLE PRECISION,
    max_drawdown_pct                         DOUBLE PRECISION,
    num_trades                                 INTEGER,
    portfolio_halted_during_run                  BOOLEAN,
    created_at                                     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Daily equity curve per run -- the audit trail for the drawdown-halt behavior (Phase 5's
-- dashboard will plot this directly) and for recomputing metrics independently later.
CREATE TABLE IF NOT EXISTS portfolio_equity_curve (
    run_id             BIGINT NOT NULL REFERENCES backtest_runs(run_id),
    "date"               DATE NOT NULL,
    equity                 DOUBLE PRECISION NOT NULL,
    daily_pnl                DOUBLE PRECISION NOT NULL,
    drawdown_pct               DOUBLE PRECISION NOT NULL,
    halted                       BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, "date")
);
