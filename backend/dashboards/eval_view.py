"""Streamlit Eval tab — aggregated metrics from evaluation/runs/*.tsv."""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from dashboards.eval_metrics import aggregate, detect_stage


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
MANIFEST_PATH = REPO_ROOT / "evaluation" / "eval_manifest.tsv"
GENERATED_DIR = REPO_ROOT / "evaluation" / "generated"
RUNS_DIR = REPO_ROOT / "evaluation" / "runs"


def render() -> None:
    st.header("Eval Run")
    st.caption(f"Source: `{RUNS_DIR}`")

    _render_run_controls()

    runs = _list_runs()
    if not runs:
        st.warning("`evaluation/runs/` has no TSV files yet. You can run an eval above.")
        return

    labels = [_label(p) for p in runs]
    selected = st.sidebar.selectbox("Run", labels)
    run_path = runs[labels.index(selected)]

    try:
        metrics = aggregate(run_path)
    except Exception as exc:
        st.error(f"Unable to parse TSV：{exc}")
        return

    _render_summary(metrics)
    _render_field_table(metrics)
    _render_grouped(metrics, "by_dataset", "Per dataset")
    _render_grouped(metrics, "by_supplier", "Per supplier (top 20 by row count)", limit=20)
    _render_error_classes(metrics)
    _render_bad_cases(metrics)


def _list_runs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    return [path for path in sorted(RUNS_DIR.glob("*.tsv"), reverse=True) if _is_parseable_run(path)]


def _is_parseable_run(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            headers = next(reader, [])
        detect_stage(headers)
    except Exception:
        return False
    return True


def _list_manifest_options() -> list[str]:
    paths = [MANIFEST_PATH]
    if GENERATED_DIR.exists():
        paths.extend(sorted(GENERATED_DIR.glob("*.tsv"), reverse=True))
    labels: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            label = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            label = str(path)
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def _repo_path(raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("path is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("path must stay inside this repo") from exc
    return path


def _build_eval_command(
    *,
    stage: str,
    full: bool,
    limit: int,
    only: str,
    dataset: str,
    vendor: str,
    manifest: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "evals.run_eval",
        "--stage",
        stage,
        "--manifest",
        str(manifest),
    ]
    if full:
        command.append("--full")
    else:
        command.extend(["--limit", str(max(1, int(limit)))])
    if only.strip():
        command.extend(["--only", only.strip()])
    if dataset.strip():
        command.extend(["--dataset", dataset.strip()])
    if vendor.strip():
        command.extend(["--vendor", vendor.strip()])
    return command


def _build_hitl_refresh_command(*, split: str, limit: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "evals.refresh_from_review_labels",
        "--split",
        split,
        "--limit",
        str(max(1, int(limit))),
    ]


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _render_run_controls() -> None:
    with st.expander("Run eval from dashboard", expanded=False):
        st.caption("Runs the same backend CLI commands, then reads the generated TSV from `evaluation/runs/`.")
        manifest_options = _list_manifest_options()
        with st.form("run-eval-form"):
            col_stage, col_scope, col_limit = st.columns([1, 1, 1])
            stage = col_stage.selectbox("Stage", ["extraction", "supplier", "both"], index=0, key="eval-run-stage")
            full = col_scope.checkbox("Run full manifest", value=False, key="eval-run-full")
            limit = col_limit.number_input("Limit", min_value=1, value=10, step=1, disabled=full, key="eval-run-limit")
            selected_manifest = st.selectbox("Manifest", manifest_options, key="eval-run-manifest")
            custom_manifest = st.text_input(
                "Custom manifest path",
                placeholder="optional repo-relative TSV path",
                key="eval-run-custom-manifest",
            )
            col_only, col_dataset, col_vendor = st.columns(3)
            only = col_only.text_input("Only document_no", key="eval-run-only")
            dataset = col_dataset.text_input("Dataset", key="eval-run-dataset")
            vendor = col_vendor.text_input("Vendor code", key="eval-run-vendor")
            run_clicked = st.form_submit_button("Run eval", type="primary")

        if run_clicked:
            manifest_text = custom_manifest.strip() or selected_manifest
            try:
                manifest = _repo_path(manifest_text)
                if not manifest.exists():
                    raise ValueError(f"manifest does not exist: {manifest.relative_to(REPO_ROOT)}")
                command = _build_eval_command(
                    stage=stage,
                    full=full,
                    limit=int(limit),
                    only=only,
                    dataset=dataset,
                    vendor=vendor,
                    manifest=manifest,
                )
                with st.spinner("Running eval..."):
                    result = _run_command(command)
                _render_command_result(result)
            except Exception as exc:
                st.error(str(exc))

    with st.expander("Refresh HITL manifest", expanded=False):
        st.caption("Builds `evaluation/generated/review_golden_<split>.tsv` from corrected HITL confirmations.")
        with st.form("refresh-hitl-manifest-form"):
            split = st.selectbox("Split", ["mini", "main"], index=0, key="hitl-refresh-split")
            limit = st.number_input("Limit", min_value=1, value=50, step=10, key="hitl-refresh-limit")
            refresh_clicked = st.form_submit_button("Refresh from HITL corrections", type="primary")

        if refresh_clicked:
            command = _build_hitl_refresh_command(split=split, limit=int(limit))
            with st.spinner("Refreshing HITL manifest..."):
                result = _run_command(command)
            _render_command_result(result)


def _render_command_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode == 0:
        st.success("Command completed")
    elif result.returncode == 2:
        st.warning("Eval completed with failing rows")
    else:
        st.error(f"Command failed with exit code {result.returncode}")

    if result.stdout.strip():
        st.code(result.stdout, language="text")
    if result.stderr.strip():
        st.code(result.stderr, language="text")


def _label(path: Path) -> str:
    suffix = "supplier" if "_supplier" in path.stem else "extraction"
    return f"{path.stem}  ({suffix})"


def _render_summary(metrics: dict[str, Any]) -> None:
    cols = st.columns(4)
    cols[0].metric("Stage", metrics["stage"])
    cols[1].metric("Rows", metrics["row_count"])
    cols[2].metric("Overall accuracy", f"{metrics['overall_accuracy'] * 100:.2f}%")
    cols[3].metric(
        "Errors",
        f"{metrics['error_count']}",
        delta=f"{metrics['error_rate'] * 100:.2f}%" if metrics["error_count"] else None,
        delta_color="inverse",
    )


def _render_field_table(metrics: dict[str, Any]) -> None:
    st.subheader("Field-level accuracy")
    rows = []
    for name, stat in metrics["fields"].items():
        rows.append(
            {
                "field": name,
                "correct": stat["correct"],
                "total": stat["total"],
                "accuracy": stat["accuracy"],
            }
        )
    df = pd.DataFrame(rows).sort_values("accuracy")
    st.dataframe(df, use_container_width=True, hide_index=True)
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("accuracy:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            y=alt.Y("field:N", sort="-x"),
            color=alt.Color("accuracy:Q", scale=alt.Scale(scheme="redyellowgreen", domain=[0, 1]), legend=None),
            tooltip=["field", "correct", "total", alt.Tooltip("accuracy:Q", format=".2%")],
        )
        .properties(height=240)
    )
    st.altair_chart(chart, use_container_width=True)


def _render_grouped(metrics: dict[str, Any], key: str, title: str, *, limit: int | None = None) -> None:
    st.subheader(title)
    groups = list(metrics.get(key, []))
    if not groups:
        st.write("(no data)")
        return
    rows = [
        {
            "name": g["name"],
            "rows": g["rows"],
            "accuracy": g["overall_accuracy"],
            "errors": g["error_count"],
        }
        for g in groups
    ]
    df = pd.DataFrame(rows).sort_values("rows", ascending=False)
    if limit:
        df = df.head(limit)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_error_classes(metrics: dict[str, Any]) -> None:
    classes = metrics.get("error_classes") or {}
    if not classes:
        return
    st.subheader("Error classes")
    df = pd.DataFrame([{"error_class": k, "count": v} for k, v in classes.items()])
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_bad_cases(metrics: dict[str, Any]) -> None:
    bad_cases = metrics.get("bad_cases") or []
    if not bad_cases:
        st.success("No failed cases — every row passed.")
        return

    st.subheader(f"Bad cases ({len(bad_cases)})")
    field_keys = list(next(iter(bad_cases))["fields"].keys()) if bad_cases else []
    flat_rows = []
    for case in bad_cases:
        row = {
            "document_no": case["document_no"],
            "dataset": case["dataset"],
            "vendor_code": case["vendor_code"],
            "error": case["error"],
        }
        for fk in field_keys:
            cell = case["fields"][fk]
            row[f"{fk}_expected"] = cell["expected"]
            row[f"{fk}_actual"] = cell["actual"]
            row[f"{fk}_ok"] = cell["ok"]
        flat_rows.append(row)
    df = pd.DataFrame(flat_rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
