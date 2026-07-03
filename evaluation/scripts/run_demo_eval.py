"""Headless field-extraction eval on the synthetic invoice set.

Runs the production extraction pipeline (extract_invoice_with_config) against a
folder of images + ground_truth.jsonl, then reports per-field accuracy with
Wilson 95% confidence intervals. No UI, no database, no supplier matching.

Scores invoice_number / invoice_date / total_amount. vendor_name is reported as
a soft "contains" metric because the ground truth bundles name + address.

Example:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
        python evaluation/scripts/run_demo_eval.py \
        --data-dir evaluation/invoices-donut-demo
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lib import (  # noqa: E402
    SCORED_FIELDS,
    compare_field,
    map_ground_truth,
    vendor_contains,
    wilson_ci,
)


def load_ground_truth(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "ground_truth.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"ground_truth.jsonl not found in {data_dir}")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def extract_one(image_path: Path) -> tuple[dict[str, Any], str]:
    """Return (extracted_data, error). Never raises so one bad row can't
    abort the whole run."""
    from app.services.invoice_extractor import extract_invoice

    try:
        return extract_invoice(image_path), ""
    except Exception:  # noqa: BLE001 - eval must survive per-row failures
        return {}, traceback.format_exc(limit=1).strip()


def score(records: list[dict[str, Any]], data_dir: Path, out_path: Path) -> dict[str, Any]:
    field_pass = {f: 0 for f in SCORED_FIELDS}
    field_total = {f: 0 for f in SCORED_FIELDS}  # denominator = rows that have a label
    vendor_pass = 0
    doc_pass = 0
    errors = 0
    total = len(records)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        header = ["file"]
        for f in SCORED_FIELDS:
            header += [f"{f}_expected", f"{f}_actual", f"{f}_ok"]
        header += ["vendor_ok", "doc_ok", "error"]
        writer.writerow(header)

        for idx, rec in enumerate(records, 1):
            gt = map_ground_truth(rec["ground_truth"]["gt_parse"])
            image_path = data_dir / rec["file"]
            print(f"[{idx}/{total}] {rec['file']}", flush=True)
            actual, error = extract_one(image_path)
            if error:
                errors += 1

            cells: list[str] = [rec["file"]]
            flags: dict[str, bool] = {}  # only fields that have a label
            for f in SCORED_FIELDS:
                exp = gt[f]
                act = actual.get(f, "") if not error else ""
                if not exp:  # no ground truth for this field -> not scored
                    cells += [exp, str(act), "-"]
                    continue
                field_total[f] += 1
                ok = False if error else compare_field(f, exp, act)
                flags[f] = ok
                field_pass[f] += int(ok)
                cells += [exp, str(act), "1" if ok else "0"]

            v_ok = False if error else vendor_contains(gt["vendor_name"], actual.get("vendor_name"))
            vendor_pass += int(v_ok)
            d_ok = (not error) and bool(flags) and all(flags.values())
            doc_pass += int(d_ok)
            cells += ["1" if v_ok else "0", "1" if d_ok else "0", error]
            writer.writerow(cells)

    return {
        "total": total,
        "errors": errors,
        "field_pass": field_pass,
        "field_total": field_total,
        "vendor_pass": vendor_pass,
        "doc_pass": doc_pass,
    }


def _line(label: str, k: int, n: int) -> str:
    pct = k / n * 100 if n else 0.0
    lo, hi = wilson_ci(k, n)
    return f"  {label:<16} {k:>3}/{n:<3} {pct:5.1f}%   95% CI [{lo * 100:4.1f}%, {hi * 100:4.1f}%]"


def report(stats: dict[str, Any], out_path: Path) -> None:
    n = stats["total"]
    print()
    print(f"per-row report -> {out_path.relative_to(REPO_ROOT)}")
    print(f"documents: {n}   extraction errors: {stats['errors']}")
    print("\nfield-level accuracy (95% Wilson CI):")
    for f in SCORED_FIELDS:
        print(_line(f, stats["field_pass"][f], stats["field_total"][f]))
    print("\ndocument-level (all scored fields correct):")
    print(_line("all_fields", stats["doc_pass"], n))
    print("\nsoft metric:")
    print(_line("vendor_contains", stats["vendor_pass"], n))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "evaluation" / "invoices-donut-demo")
    parser.add_argument("--limit", type=int, default=0, help="cap number of documents (0 = all)")
    parser.add_argument("--credentials", type=Path, help="path to GC service-account JSON")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "evaluation" / "runs")
    args = parser.parse_args()

    if args.credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(args.credentials.resolve())

    # Initialize a local (gitignored) DB so LLM-call telemetry can be logged.
    from app.config import ensure_directories
    from app.database import init_db

    ensure_directories()
    init_db()

    data_dir = args.data_dir.resolve()
    records = load_ground_truth(data_dir)
    if args.limit:
        records = records[: args.limit]
    if not records:
        print("no records to evaluate")
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out_dir / f"demo_eval_{timestamp}.tsv"

    stats = score(records, data_dir, out_path)
    report(stats, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
