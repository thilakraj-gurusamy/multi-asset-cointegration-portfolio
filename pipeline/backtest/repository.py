"""Storage/reads for Phase 4. Reads Phase 1 (bars), Phase 2 (engle_granger_results,
johansen_results), and Phase 3 (relationship_health); writes the new Phase 4 tables.

IMPORTANT ordering subtlety (confirmed against live data, not assumed): a basket's
`basket_key` in johansen_results is ALPHABETICALLY sorted for lookup purposes, but its
`cointegrating_vectors` are in the ORIGINAL config basket order, and `asset_ids` is stored in
that SAME original order -- so symbols for a basket must be recovered via `asset_ids` joined
to `assets`, never by splitting `basket_key` (that would silently misalign weights to the
wrong symbols).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

import psycopg2
import psycopg2.extras


class BacktestRepository:
    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = True

    def close(self) -> None:
        self._conn.close()

    # ---- discovery: what does Phase 3 actually monitor for this asset class? ----

    def list_pair_relationship_keys(self, asset_class: str, interval: str) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT relationship_key FROM relationship_health
                WHERE asset_class = %s AND "interval" = %s AND relationship_type = 'pair'
                """,
                (asset_class, interval),
            )
            return [r[0] for r in cur.fetchall()]

    def list_basket_relationship_keys(self, asset_class: str, interval: str) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT relationship_key FROM relationship_health
                WHERE asset_class = %s AND "interval" = %s AND relationship_type = 'basket'
                """,
                (asset_class, interval),
            )
            return [r[0] for r in cur.fetchall()]

    # ---- Phase 2 fits, in walk-forward order ----

    def get_pair_windows(self, asset_class: str, interval: str, relationship_key: str, start: datetime, end: datetime) -> list[dict]:
        symbol_a, symbol_b = relationship_key.split(",")
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT eg.window_start, eg.window_end, eg.hedge_ratio
                FROM engle_granger_results eg
                JOIN assets a1 ON a1.asset_id = eg.regressand_asset_id
                JOIN assets a2 ON a2.asset_id = eg.regressor_asset_id
                WHERE eg.asset_class = %s AND eg."interval" = %s
                  AND a1.symbol = %s AND a2.symbol = %s
                  AND eg.window_end >= %s AND eg.window_end <= %s
                ORDER BY eg.window_end ASC
                """,
                (asset_class, interval, symbol_a, symbol_b, start, end),
            )
            rows = [{"window_start": r[0], "window_end": r[1], "hedge_ratio": r[2]} for r in cur.fetchall()]
        for row in rows:
            row["legs"] = [symbol_a, symbol_b]
            row["weights"] = [1.0, -row["hedge_ratio"]]
        return rows

    def get_basket_windows(self, asset_class: str, interval: str, relationship_key: str, start: datetime, end: datetime) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT jr.window_start, jr.window_end, jr.cointegration_rank, jr.cointegrating_vectors, jr.asset_ids
                FROM johansen_results jr
                WHERE jr.asset_class = %s AND jr."interval" = %s AND jr.basket_key = %s AND jr.n_assets > 2
                  AND jr.window_end >= %s AND jr.window_end <= %s
                ORDER BY jr.window_end ASC
                """,
                (asset_class, interval, relationship_key, start, end),
            )
            raw_rows = cur.fetchall()

        all_asset_ids = sorted({aid for row in raw_rows for aid in row[4]})
        symbol_by_id = self._symbols_for_ids(all_asset_ids)

        rows = []
        for window_start, window_end, rank, vectors, asset_ids in raw_rows:
            legs = [symbol_by_id[aid] for aid in asset_ids]
            weights = vectors[0] if (rank is not None and rank >= 1 and vectors) else None
            rows.append(
                {"window_start": window_start, "window_end": window_end, "cointegration_rank": rank, "legs": legs, "weights": weights}
            )
        return rows

    def _symbols_for_ids(self, asset_ids: list[int]) -> dict[int, str]:
        if not asset_ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute("SELECT asset_id, symbol FROM assets WHERE asset_id = ANY(%s)", (asset_ids,))
            return dict(cur.fetchall())

    # ---- Phase 3 health, by window ----

    def get_health_by_window_end(self, asset_class: str, interval: str, relationship_key: str) -> dict[datetime, str]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT window_end, overall_status FROM relationship_health
                WHERE asset_class = %s AND "interval" = %s AND relationship_key = %s
                """,
                (asset_class, interval, relationship_key),
            )
            return dict(cur.fetchall())

    # ---- Phase 1 prices ----

    def get_price_series(self, symbol: str, asset_class: str, interval: str, start: datetime, end: datetime) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT b."time", b.close, b.volume
                FROM bars b
                JOIN assets a ON a.asset_id = b.asset_id
                WHERE a.symbol = %s AND a.asset_class = %s AND b."interval" = %s
                  AND b."time" >= %s AND b."time" <= %s
                ORDER BY b."time" ASC
                """,
                (symbol, asset_class, interval, start, end),
            )
            return [{"time": r[0], "close": r[1], "volume": r[2]} for r in cur.fetchall()]

    # ---- Phase 4 writes ----

    def create_backtest_run(
        self, asset_class: str, strategy_variant: str, start: date, end: date, params: dict, starting_equity: float
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO backtest_runs (asset_class, strategy_variant, start_date, end_date, params, starting_equity)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING run_id
                """,
                (asset_class, strategy_variant, start, end, json.dumps(params), starting_equity),
            )
            return cur.fetchone()[0]

    def finalize_backtest_run(self, run_id: int, final_equity: float, total_return_pct: float, sharpe: float, max_drawdown_pct: float, num_trades: int, halted: bool) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE backtest_runs SET final_equity = %s, total_return_pct = %s, annualized_sharpe = %s,
                       max_drawdown_pct = %s, num_trades = %s, portfolio_halted_during_run = %s
                WHERE run_id = %s
                """,
                (final_equity, total_return_pct, sharpe, max_drawdown_pct, num_trades, halted, run_id),
            )

    def insert_signal(self, run_id: Optional[int], asset_class: str, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signals (run_id, asset_class, relationship_key, "date", window_start, window_end,
                                      z_score, health_status, weights, z_entry, z_exit, action)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id, asset_class, record["relationship_key"], record["date"], record["window_start"],
                    record["window_end"], record["z_score"], record["health_status"], json.dumps(record["weights"]),
                    record["z_entry"], record["z_exit"], record["action"],
                ),
            )

    def insert_trade(self, run_id: int, asset_class: str, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trades (run_id, asset_class, relationship_key, direction, entry_date, entry_z,
                                     entry_spread_value, position_units, sizing_detail, exit_date, exit_z,
                                     exit_spread_value, exit_reason, gross_pnl, transaction_cost, slippage_cost, net_pnl)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id, asset_class, record["relationship_key"], record["direction"], record["entry_date"],
                    record["entry_z"], record["entry_spread_value"], record["position_units"],
                    json.dumps(record["sizing_detail"]), record["exit_date"], record["exit_z"],
                    record["exit_spread_value"], record["exit_reason"], record["gross_pnl"],
                    record["transaction_cost"], record["slippage_cost"], record["net_pnl"],
                ),
            )

    def insert_equity_curve_point(self, run_id: int, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO portfolio_equity_curve (run_id, "date", equity, daily_pnl, drawdown_pct, halted)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (run_id, record["date"], record["equity"], record["daily_pnl"], record["drawdown_pct"], record["halted"]),
            )

    def get_latest_bar_date(self, asset_class: str, interval: str) -> Optional[datetime]:
        """Latest bar actually available across the whole asset class -- used as "today" for
        the paper-trading cycle instead of wall-clock date, since a provider's daily candle for
        the current calendar day may not have published yet (or a market may be closed).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT max(b."time") FROM bars b
                JOIN assets a ON a.asset_id = b.asset_id
                WHERE a.asset_class = %s AND b."interval" = %s
                """,
                (asset_class, interval),
            )
            row = cur.fetchone()
            return row[0] if row else None

    # ---- Phase 5: paper trading (live, persisted ACROSS cycles -- unlike the backtest's
    # in-memory-only open_positions dict, which starts flat every run) ----

    def get_open_position(self, asset_class: str, relationship_key: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT direction, entry_date, entry_z, entry_spread_value, position_units,
                       sizing_detail, last_mark_date, last_spread
                FROM paper_positions WHERE asset_class = %s AND relationship_key = %s
                """,
                (asset_class, relationship_key),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = ["direction", "entry_date", "entry_z", "entry_spread_value", "position_units",
                    "sizing_detail", "last_mark_date", "last_spread"]
            return dict(zip(cols, row))

    def save_open_position(self, asset_class: str, relationship_key: str, position: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_positions
                    (asset_class, relationship_key, direction, entry_date, entry_z, entry_spread_value,
                     position_units, sizing_detail, last_mark_date, last_spread)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, relationship_key)
                DO UPDATE SET last_mark_date = EXCLUDED.last_mark_date, last_spread = EXCLUDED.last_spread
                """,
                (
                    asset_class, relationship_key, position["direction"], position["entry_date"],
                    position["entry_z"], position["entry_spread_value"], position["position_units"],
                    json.dumps(position["sizing_detail"]), position["last_mark_date"], position["last_spread"],
                ),
            )

    def delete_open_position(self, asset_class: str, relationship_key: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM paper_positions WHERE asset_class = %s AND relationship_key = %s",
                (asset_class, relationship_key),
            )

    def insert_paper_trade(self, asset_class: str, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_trades
                    (asset_class, relationship_key, direction, entry_date, entry_z, entry_spread_value,
                     position_units, sizing_detail, exit_date, exit_z, exit_spread_value, exit_reason,
                     gross_pnl, transaction_cost, slippage_cost, net_pnl)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    asset_class, record["relationship_key"], record["direction"], record["entry_date"],
                    record["entry_z"], record["entry_spread_value"], record["position_units"],
                    json.dumps(record["sizing_detail"]), record["exit_date"], record["exit_z"],
                    record["exit_spread_value"], record["exit_reason"], record["gross_pnl"],
                    record["transaction_cost"], record["slippage_cost"], record["net_pnl"],
                ),
            )

    def get_latest_paper_equity(self, asset_class: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT "date", equity, peak_equity, drawdown_pct, halted FROM paper_equity_curve
                WHERE asset_class = %s ORDER BY "date" DESC LIMIT 1
                """,
                (asset_class,),
            )
            row = cur.fetchone()
            return dict(zip(["date", "equity", "peak_equity", "drawdown_pct", "halted"], row)) if row else None

    def insert_paper_equity_point(self, asset_class: str, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_equity_curve (asset_class, "date", equity, peak_equity, daily_pnl, drawdown_pct, halted)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, "date")
                DO UPDATE SET equity = EXCLUDED.equity, peak_equity = EXCLUDED.peak_equity,
                              daily_pnl = EXCLUDED.daily_pnl, drawdown_pct = EXCLUDED.drawdown_pct,
                              halted = EXCLUDED.halted
                """,
                (
                    asset_class, record["date"], record["equity"], record["peak_equity"],
                    record["daily_pnl"], record["drawdown_pct"], record["halted"],
                ),
            )

    def start_cycle_log(self, started_at: datetime) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO paper_cycle_log (started_at, status, steps) VALUES (%s, 'running', '{}') RETURNING cycle_id",
                (started_at,),
            )
            return cur.fetchone()[0]

    def finish_cycle_log(self, cycle_id: int, finished_at: datetime, status: str, steps: dict, error_message: Optional[str], duration_seconds: float) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE paper_cycle_log SET finished_at = %s, status = %s, steps = %s,
                       error_message = %s, duration_seconds = %s
                WHERE cycle_id = %s
                """,
                (finished_at, status, json.dumps(steps), error_message, duration_seconds, cycle_id),
            )
