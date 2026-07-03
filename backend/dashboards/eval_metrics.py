"""Aggregate eval-run TSVs into structured metrics.

Reads the per-row TSV produced by ``backend/evals/run_eval.py`` and computes
breakdowns by field / dataset / supplier so the Streamlit dashboard and CI
gate can consume one JSON instead of re-parsing the TSV every time.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


EXTRACTION_FIELDS = ("PO_number", "invoice_number", "invoice_date", "total_amount")
SUPPLIER_FIELDS = ("vendor_code", "document_is_invoice", "special_document_matched", "document_type")


@dataclass
class FieldStat:
    correct: int = 0
    total: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


@dataclass
class GroupStat:
    name: str
    rows: int = 0
    overall_pass: int = 0
    error_count: int = 0
    field_stats: dict[str, FieldStat] = field(default_factory=dict)

    @property
    def overall_accuracy(self) -> float:
        return self.overall_pass / self.rows if self.rows else 0.0

    @property
    def error_rate(self) -> float:
        return self.error_count / self.rows if self.rows else 0.0


def detect_stage(headers: list[str]) -> str:
    if "supplier_overall_ok" in headers:
        return "supplier"
    if "overall_ok" in headers and any(f"{f}_ok" in headers for f in EXTRACTION_FIELDS):
        return "extraction"
    raise ValueError("unrecognized eval TSV header")


def aggregate(tsv_path: Path) -> dict[str, Any]:
    """Read a run TSV and return a JSON-serializable metrics dict."""
    with tsv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        headers = reader.fieldnames or []

    stage = detect_stage(headers)
    fields = EXTRACTION_FIELDS if stage == "extraction" else SUPPLIER_FIELDS
    overall_key = "overall_ok" if stage == "extraction" else "supplier_overall_ok"

    overall = GroupStat(name="overall")
    by_dataset: dict[str, GroupStat] = {}
    by_supplier: dict[str, GroupStat] = {}
    bad_cases: list[dict[str, Any]] = []
    error_classes: dict[str, int] = {}

    for f in fields:
        overall.field_stats[f] = FieldStat()

    for row in rows:
        overall.rows += 1
        dataset = row.get("dataset", "") or "(none)"
        vendor = row.get("vendor_code", "") or "(none)"
        ds_stat = by_dataset.setdefault(dataset, GroupStat(name=dataset))
        sup_stat = by_supplier.setdefault(vendor, GroupStat(name=vendor))
        ds_stat.rows += 1
        sup_stat.rows += 1

        passed = row.get(overall_key, "0") == "1"
        if passed:
            overall.overall_pass += 1
            ds_stat.overall_pass += 1
            sup_stat.overall_pass += 1

        error_text = (row.get("error") or "").strip()
        if error_text:
            overall.error_count += 1
            ds_stat.error_count += 1
            sup_stat.error_count += 1
            err_class = _classify_error(error_text)
            error_classes[err_class] = error_classes.get(err_class, 0) + 1

        for fld in fields:
            flag_key = f"{fld}_ok"
            ok = row.get(flag_key, "0") == "1"
            for stat in (overall, ds_stat, sup_stat):
                fs = stat.field_stats.setdefault(fld, FieldStat())
                fs.total += 1
                if ok:
                    fs.correct += 1

        if not passed:
            bad_cases.append(_bad_case_payload(row, stage, fields))

    return {
        "stage": stage,
        "source_tsv": str(tsv_path.name),
        "row_count": overall.rows,
        "overall_accuracy": overall.overall_accuracy,
        "error_count": overall.error_count,
        "error_rate": overall.error_rate,
        "error_classes": dict(sorted(error_classes.items(), key=lambda kv: -kv[1])),
        "fields": {
            name: {"correct": fs.correct, "total": fs.total, "accuracy": fs.accuracy}
            for name, fs in overall.field_stats.items()
        },
        "by_dataset": [_group_payload(g) for g in by_dataset.values()],
        "by_supplier": [_group_payload(g) for g in by_supplier.values()],
        "bad_cases": bad_cases,
    }


def _group_payload(stat: GroupStat) -> dict[str, Any]:
    return {
        "name": stat.name,
        "rows": stat.rows,
        "overall_accuracy": stat.overall_accuracy,
        "error_count": stat.error_count,
        "error_rate": stat.error_rate,
        "fields": {
            name: {"correct": fs.correct, "total": fs.total, "accuracy": fs.accuracy}
            for name, fs in stat.field_stats.items()
        },
    }


def _bad_case_payload(row: dict[str, str], stage: str, fields: tuple[str, ...]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "document_no": row.get("document_no", ""),
        "dataset": row.get("dataset", ""),
        "vendor_code": row.get("vendor_code", ""),
        "error": row.get("error", ""),
        "fields": {},
    }
    for f in fields:
        payload["fields"][f] = {
            "expected": row.get(f"{f}_expected", ""),
            "actual": row.get(f"{f}_actual", ""),
            "ok": row.get(f"{f}_ok", "0") == "1",
        }
    if stage == "supplier":
        payload["vendor_name_expected"] = row.get("vendor_name_expected", "")
        payload["vendor_name_actual"] = row.get("vendor_name_actual", "")
    return payload


def _classify_error(text: str) -> str:
    head = text.split(":", 1)[0].strip()
    if not head:
        return "unknown"
    return head[:80]


def write_aggregate(tsv_path: Path, output_path: Path | None = None) -> Path:
    """Compute aggregate metrics for a TSV and write them as JSON."""
    metrics = aggregate(tsv_path)
    target = output_path or tsv_path.with_suffix(".aggregate.json")
    target.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="aggregate an eval-run TSV into JSON metrics")
    parser.add_argument("tsv", type=Path, help="path to a run TSV produced by run_eval")
    parser.add_argument("--output", type=Path, help="output JSON path (default: <tsv>.aggregate.json)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="non-zero exits with code 1 if overall accuracy < threshold (CI gate)",
    )
    args = parser.parse_args()

    if not args.tsv.exists():
        print(f"missing TSV: {args.tsv}", file=sys.stderr)
        return 2

    metrics = aggregate(args.tsv)
    target = args.output or args.tsv.with_suffix(".aggregate.json")
    target.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target}")
    print(f"overall_accuracy: {metrics['overall_accuracy']:.3f}  rows: {metrics['row_count']}  errors: {metrics['error_count']}")

    if args.threshold > 0 and metrics["overall_accuracy"] < args.threshold:
        print(f"FAIL: accuracy {metrics['overall_accuracy']:.3f} < {args.threshold}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
