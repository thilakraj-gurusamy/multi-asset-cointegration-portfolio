"""Phase 5 dashboard (FRD Section 8.8/9): surfaces live paper P&L, current health status per
monitored pair/basket, and observability signals (pipeline failures, data gaps, health
breaches) visibly -- not buried in logs only. Crypto is shown in its own clearly-labeled
section, kept separate from the FX/equity core per the Scope Decision (Section 3): it is an
instability DEMONSTRATION, never folded into the P&L/signal view as an equal asset class.

Run with: streamlit run dashboard/app.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import queries
from pipeline.config import load_settings

st.set_page_config(page_title="Multi-Asset Portfolio — Live Dashboard", layout="wide")

STATUS_COLOR = {"healthy": "#1a9850", "warning": "#fee08b", "halted": "#d73027"}


@st.cache_resource
def get_connection():
    settings = load_settings(require_api_keys=False)
    return psycopg2.connect(settings.database_url)


@st.cache_data(ttl=60)
def load(asset_class: str | None = None):
    conn = get_connection()
    data = {}
    for ac in (["fx", "equity"] if asset_class is None else [asset_class]):
        data[ac] = {
            "equity_curve": queries.get_paper_equity_curve(conn, ac),
            "summary": queries.get_paper_summary(conn, ac),
            "open_positions": queries.get_open_positions(conn, ac),
            "recent_trades": queries.get_recent_paper_trades(conn, ac),
            "health": queries.get_latest_health_status(conn, ac),
            "health_summary": queries.get_health_status_summary(conn, ac),
            "backtest": queries.get_backtest_comparison(conn, ac),
        }
    data["crypto_health"] = queries.get_latest_health_status(conn, "crypto")
    data["crypto_health_summary"] = queries.get_health_status_summary(conn, "crypto")
    data["instability"] = queries.get_crypto_vs_core_instability(conn)
    data["quality_events"] = queries.get_recent_quality_events(conn)
    data["transitions"] = queries.get_recent_health_transitions(conn, only_halted=True)
    data["cycle_log"] = queries.get_recent_cycle_log(conn)
    return data


def _style_status(df: pd.DataFrame, column: str = "overall_status") -> "pd.io.formats.style.Styler":
    def _color(val):
        return f"background-color: {STATUS_COLOR.get(val, '#eeeeee')}"
    return df.style.map(_color, subset=[column]) if column in df.columns else df.style


st.title("Multi-Asset Portfolio — Live Dashboard")
st.caption(
    "Paper trading only -- simulated fills, no brokerage connection, no real orders, "
    "under any configuration."
)

col_refresh, _ = st.columns([1, 5])
if col_refresh.button("Refresh now"):
    st.cache_data.clear()

data = load()

tab_pnl, tab_health, tab_crypto, tab_backtest, tab_obs = st.tabs(
    ["Live Paper P&L", "Relationship Health", "Crypto Instability", "Backtest Results", "Observability"]
)

with tab_pnl:
    for ac in ("fx", "equity"):
        st.subheader(ac.upper())
        summary = data[ac]["summary"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Equity", f"${summary['equity']:,.0f}" if summary["equity"] is not None else "n/a")
        c2.metric("Drawdown", f"{summary['drawdown_pct']:.2f}%")
        c3.metric("Halted", "YES" if summary["halted"] else "no")
        c4.metric("Open positions", summary["open_positions"])
        c5.metric("Realized P&L (all trades)", f"${summary['realized_pnl']:,.0f}")

        curve = data[ac]["equity_curve"]
        if not curve.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=curve["date"], y=curve["equity"], mode="lines+markers", name="Equity"))
            fig.update_layout(height=250, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No paper-trading equity history yet -- run `python -m pipeline.paper_trading.cycle`.")

        oc1, oc2 = st.columns(2)
        with oc1:
            st.caption("Open positions")
            st.dataframe(data[ac]["open_positions"], use_container_width=True, hide_index=True)
        with oc2:
            st.caption("Recent closed trades")
            st.dataframe(data[ac]["recent_trades"], use_container_width=True, hide_index=True)
        st.divider()

with tab_health:
    st.caption(
        "Every monitored pair/basket's MOST RECENT health classification. "
        "healthy = green, warning = yellow, halted = red."
    )
    for ac in ("fx", "equity"):
        st.subheader(ac.upper())
        summary = data[ac]["health_summary"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Healthy", summary["healthy"])
        c2.metric("Warning", summary["warning"])
        c3.metric("Halted", summary["halted"])
        health_df = data[ac]["health"]
        if not health_df.empty:
            st.dataframe(_style_status(health_df), use_container_width=True, hide_index=True)
        else:
            st.info("No health data yet for this asset class.")

with tab_crypto:
    st.warning(
        "Crypto is a stretch module to DEMONSTRATE AND QUANTIFY cointegration instability "
        "(FRD Section 8.1) -- it is NOT a production-weighted signal source and never reaches "
        "the paper-trading P&L above. Shown separately on purpose."
    )
    summary = data["crypto_health_summary"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Healthy", summary["healthy"])
    c2.metric("Warning", summary["warning"])
    c3.metric("Halted", summary["halted"])

    st.caption("Latest health status per crypto relationship")
    crypto_health_df = data["crypto_health"]
    if not crypto_health_df.empty:
        st.dataframe(_style_status(crypto_health_df), use_container_width=True, hide_index=True)

    st.subheader("Hedge-ratio drift magnitude: crypto vs. FX vs. equities")
    st.caption(
        "The concrete instability-quantification evidence: how violently each basket's "
        "cointegrating relationship swings between consecutive rolling windows."
    )
    instability_df = data["instability"]
    if not instability_df.empty:
        fig = go.Figure(
            go.Bar(
                x=instability_df["relationship_key"] + " (" + instability_df["asset_class"] + ")",
                y=instability_df["max_drift_pct"],
            )
        )
        fig.update_layout(yaxis_title="Max hedge-ratio drift (%)", height=350)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(instability_df, use_container_width=True, hide_index=True)

with tab_backtest:
    st.caption("Phase 4 walk-forward backtest results (historical, not live) -- for context alongside the live loop above.")
    for ac in ("fx", "equity"):
        st.subheader(ac.upper())
        bt_df = data[ac]["backtest"]
        if not bt_df.empty:
            st.dataframe(bt_df, use_container_width=True, hide_index=True)
        else:
            st.info("No backtest runs recorded yet -- run `python -m pipeline.backtest.run`.")

with tab_obs:
    st.subheader("Pipeline cycle log")
    st.dataframe(data["cycle_log"], use_container_width=True, hide_index=True)

    st.subheader("Recent halted-relationship transitions")
    st.dataframe(data["transitions"], use_container_width=True, hide_index=True)

    st.subheader("Recent data-quality events (feed downtime, malformed payloads, gaps)")
    st.dataframe(data["quality_events"], use_container_width=True, hide_index=True)
