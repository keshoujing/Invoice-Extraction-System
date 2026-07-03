"""Streamlit dashboard entry point.

Run from the repo root:
    cd backend
    .venv/bin/streamlit run dashboards/streamlit_app.py

Two tabs:
    - Telemetry: live LLM call data from the llm_calls table
    - Eval:      aggregated metrics from evaluation/runs/*.tsv
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dashboards import eval_view, telemetry_view  # noqa: E402


def main() -> None:
    st.set_page_config(page_title="Invoice Archive AI — Dashboard", layout="wide")
    st.sidebar.title("Invoice Archive AI")
    page = st.sidebar.radio("View", ("Telemetry", "Eval"))
    if page == "Telemetry":
        telemetry_view.render()
    else:
        eval_view.render()


if __name__ == "__main__":
    main()
