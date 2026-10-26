"""Read-only SQL queries backing the dashboard (FRD Section 9: observability -- live P&L,
per-relationship health status, and pipeline failures/data gaps, surfaced visibly rather than
left in logs only). Kept separate from app.py so the queries themselves are testable without
importing Streamlit.

Every function takes an open psycopg2 connection and returns a pandas DataFrame (or a small
dict of scalars) -- nothing here mutates the database.
"""
from __future__ import annotations

import pandas as pd


def get_paper_equity_curve(conn, asset_class: str) -> pd.DataFrame:
    return pd.read_sql_query(
        'SELECT "date", equity, daily_pnl, drawdown_pct, halted FROM paper_equity_curve '
        "WHERE asset_class = %(asset_class)s ORDER BY \"date\" ASC",
        conn, params={"asset_class": asset_class},
    )


def get_paper_summary(conn, asset_class: str) -> dict:
    curve = get_paper_equity_curve(conn, asset_class)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM paper_positions WHERE asset_class = %s", (asset_class,))
        open_positions = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM paper_trades WHERE asset_class = %s", (asset_class,))
        total_trades = cur.fetchone()[0]
        cur.execute(
            "SELECT coalesce(sum(net_pnl), 0) FROM paper_trades WHERE asset_class = %s", (asset_class,)
        )
        realized_pnl = cur.fetchone()[0]

    if curve.empty:
        return {
            "equity": None, "drawdown_pct": 0.0, "halted": False,
            "open_positions": open_positions, "total_trades": total_trades, "realized_pnl": realized_pnl,
            "last_date": None,
        }
    latest = curve.iloc[-1]
    return {
        "equity": latest["equity"], "drawdown_pct": latest["drawdown_pct"], "halted": bool(latest["halted"]),
        "open_positions": open_positions, "total_trades": total_trades, "realized_pnl": realized_pnl,
        "last_date": latest["date"],
    }


def get_open_positions(conn, asset_class: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT relationship_key, direction, entry_date, entry_z, position_units, last_mark_date, last_spread "
        "FROM paper_positions WHERE asset_class = %(asset_class)s ORDER BY entry_date DESC",
        conn, params={"asset_class": asset_class},
    )


def get_recent_paper_trades(conn, asset_class: str, limit: int = 20) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT relationship_key, direction, entry_date, exit_date, exit_reason, net_pnl "
        "FROM paper_trades WHERE asset_class = %(asset_class)s ORDER BY exit_date DESC LIMIT %(limit)s",
        conn, params={"asset_class": asset_class, "limit": limit},
    )


def get_latest_health_status(conn, asset_class: str) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT DISTINCT ON (relationship_key)
               relationship_key, relationship_type, overall_status, p_value, p_value_is_proxy,
               hedge_ratio_drift_pct, half_life_days, window_end
        FROM relationship_health
        WHERE asset_class = %(asset_class)s
        ORDER BY relationship_key, window_end DESC
        """,
        conn, params={"asset_class": asset_class},
    )


def get_health_status_summary(conn, asset_class: str) -> dict:
    latest = get_latest_health_status(conn, asset_class)
    if latest.empty:
        return {"healthy": 0, "warning": 0, "halted": 0}
    counts = latest["overall_status"].value_counts().to_dict()
    return {"healthy": counts.get("healthy", 0), "warning": counts.get("warning", 0), "halted": counts.get("halted", 0)}


def get_recent_quality_events(conn, limit: int = 30) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT detected_at, event_type, severity, details FROM data_quality_events "
        "ORDER BY detected_at DESC LIMIT %(limit)s",
        conn, params={"limit": limit},
    )


def get_recent_health_transitions(conn, asset_class: str | None = None, only_halted: bool = False, limit: int = 30) -> pd.DataFrame:
    where = []
    params: dict = {"limit": limit}
    if asset_class:
        where.append("asset_class = %(asset_class)s")
        params["asset_class"] = asset_class
    if only_halted:
        where.append("new_status = 'halted'")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return pd.read_sql_query(
        f"SELECT asset_class, relationship_key, window_end, previous_status, new_status, reason "
        f"FROM health_status_transitions {where_sql} ORDER BY window_end DESC LIMIT %(limit)s",
        conn, params=params,
    )


def get_recent_cycle_log(conn, limit: int = 20) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT cycle_id, started_at, finished_at, status, duration_seconds, error_message, steps "
        "FROM paper_cycle_log ORDER BY started_at DESC LIMIT %(limit)s",
        conn, params={"limit": limit},
    )


def get_backtest_comparison(conn, asset_class: str) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT DISTINCT ON (strategy_variant)
               strategy_variant, start_date, end_date, total_return_pct, annualized_sharpe,
               max_drawdown_pct, num_trades, portfolio_halted_during_run
        FROM backtest_runs
        WHERE asset_class = %(asset_class)s
        ORDER BY strategy_variant, created_at DESC
        """,
        conn, params={"asset_class": asset_class},
    )


def get_crypto_vs_core_instability(conn) -> pd.DataFrame:
    """The headline instability-quantification comparison (FRD Section 8.1): hedge-ratio
    drift magnitude for every basket, across all three asset classes, side by side.
    """
    return pd.read_sql_query(
        """
        SELECT asset_class, relationship_key,
               max(hedge_ratio_drift_pct) AS max_drift_pct,
               avg(hedge_ratio_drift_pct) AS avg_drift_pct,
               count(*) AS windows
        FROM relationship_health
        WHERE relationship_type = 'basket'
        GROUP BY asset_class, relationship_key
        ORDER BY max_drift_pct DESC
        """,
        conn,
    )
