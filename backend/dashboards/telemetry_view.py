"""Streamlit Telemetry tab — live data from the llm_calls table."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from app.config import DB_PATH


WINDOW_OPTIONS: dict[str, int | None] = {
    "Last 24 hours": 1,
    "Last 7 days": 7,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 365 days": 365,
    "All time": None,
}


def render() -> None:
    st.header("LLM Telemetry")
    st.caption(f"Source: `{DB_PATH}` — table `llm_calls`")

    if not Path(DB_PATH).exists():
        st.warning("The database file does not exist yet. Start the backend and trigger one LLM call first.")
        return

    df = _load_calls()
    if df.empty:
        st.info("No LLM call records yet. Process one invoice in the backend, then check again.")
        return

    window_label = st.sidebar.selectbox("Time window", list(WINDOW_OPTIONS.keys()), index=2)
    days = WINDOW_OPTIONS[window_label]
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        df = df[df["ts"] >= cutoff]

    if df.empty:
        st.info(f"No call records in this time window ({window_label}).")
        return

    _render_summary(df)
    _render_cost_trend(df)
    _render_breakdowns(df)
    _render_failures(df)
    _render_recent_calls(df)


def _load_calls() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM llm_calls ORDER BY ts DESC", conn)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    return df.dropna(subset=["ts"])


def _render_summary(df: pd.DataFrame) -> None:
    total_calls = len(df)
    total_cost = float(df["cost_usd"].sum() or 0.0)
    success = int(df["success"].sum() or 0)
    failure = total_calls - success
    avg_latency = float(df["latency_ms"].mean() or 0.0)
    p95_latency = float(df["latency_ms"].quantile(0.95)) if total_calls else 0.0
    failure_rate = (failure / total_calls) if total_calls else 0.0
    avg_cost = (total_cost / total_calls) if total_calls else 0.0

    cols = st.columns(5)
    cols[0].metric("Total calls", f"{total_calls:,}")
    cols[1].metric("Total cost", f"${total_cost:.4f}")
    cols[2].metric("Avg cost / call", f"${avg_cost:.5f}")
    cols[3].metric("p95 latency", f"{p95_latency:.0f} ms")
    cols[4].metric("Failure rate", f"{failure_rate * 100:.2f}%")
    st.caption(f"Success: {success}   Failure: {failure}   Avg latency: {avg_latency:.0f} ms")


def _render_cost_trend(df: pd.DataFrame) -> None:
    st.subheader("Daily cost & call volume")
    daily = (
        df.assign(day=df["ts"].dt.tz_convert("UTC").dt.date)
        .groupby("day", as_index=False)
        .agg(cost_usd=("cost_usd", "sum"), call_count=("id", "count"))
    )
    if daily.empty:
        st.write("(no data)")
        return
    cost_chart = (
        alt.Chart(daily)
        .mark_bar(color="#3b82f6")
        .encode(x=alt.X("day:T", title="Day"), y=alt.Y("cost_usd:Q", title="Cost (USD)"))
        .properties(height=200)
    )
    count_chart = (
        alt.Chart(daily)
        .mark_line(color="#ef4444", point=True)
        .encode(x="day:T", y=alt.Y("call_count:Q", title="Calls"))
        .properties(height=200)
    )
    st.altair_chart(cost_chart, use_container_width=True)
    st.altair_chart(count_chart, use_container_width=True)


def _render_breakdowns(df: pd.DataFrame) -> None:
    st.subheader("Cost breakdown")
    dim = st.selectbox(
        "Group by",
        ("model", "stage", "supplier_code", "tag", "prompt_version", "provider"),
        index=0,
    )
    grouped = (
        df.groupby(dim, dropna=False)
        .agg(
            cost_usd=("cost_usd", "sum"),
            call_count=("id", "count"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            latency_ms_avg=("latency_ms", "mean"),
            success_count=("success", "sum"),
        )
        .reset_index()
        .sort_values("cost_usd", ascending=False)
    )
    grouped[dim] = grouped[dim].fillna("(none)").replace("", "(none)")
    grouped["failure_count"] = grouped["call_count"] - grouped["success_count"]
    grouped["avg_cost_usd"] = grouped["cost_usd"] / grouped["call_count"].replace(0, pd.NA)
    grouped["latency_ms_avg"] = grouped["latency_ms_avg"].round(0)
    grouped["avg_cost_usd"] = grouped["avg_cost_usd"].round(6)

    cols_show = [dim, "call_count", "cost_usd", "avg_cost_usd", "input_tokens", "output_tokens", "latency_ms_avg", "failure_count"]
    st.dataframe(grouped[cols_show], use_container_width=True, hide_index=True)

    bar = (
        alt.Chart(grouped.head(10))
        .mark_bar()
        .encode(
            x=alt.X("cost_usd:Q", title="Cost (USD)"),
            y=alt.Y(f"{dim}:N", sort="-x", title=dim),
            tooltip=[dim, "call_count", "cost_usd", "avg_cost_usd"],
        )
        .properties(height=240)
    )
    st.altair_chart(bar, use_container_width=True)


def _render_failures(df: pd.DataFrame) -> None:
    failures = df[df["success"] == 0]
    if failures.empty:
        return
    st.subheader(f"Failures ({len(failures)})")
    grouped = (
        failures.groupby("error_class", dropna=False)
        .agg(count=("id", "count"))
        .reset_index()
        .sort_values("count", ascending=False)
    )
    st.dataframe(grouped, use_container_width=True, hide_index=True)
    with st.expander("recent failure rows"):
        st.dataframe(
            failures[["ts", "model", "stage", "error_class", "error_message", "supplier_code", "file_hash"]].head(50),
            use_container_width=True,
            hide_index=True,
        )


def _render_recent_calls(df: pd.DataFrame) -> None:
    st.subheader("Recent calls")
    show_cols = [
        "ts", "model", "stage", "input_tokens", "output_tokens", "cost_usd",
        "latency_ms", "success", "error_class", "supplier_code", "tag", "file_hash",
    ]
    st.dataframe(df[show_cols].head(100), use_container_width=True, hide_index=True)
