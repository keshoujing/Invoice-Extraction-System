"""Headless supplier-identification eval on the synthetic invoice set.

Builds a synthetic supplier master from the dataset sellers, loads it into the
production SupplierMatcher (in memory, no DB), then runs the real supplier
preview pipeline (extract_supplier_preview) on each invoice image and checks
whether it resolves to the correct vendor_code.

Note: synthetic Faker names are mostly distinct, so disambiguation is easier
than a real supplier book with near-duplicate names -- expect an optimistic
number. This measures the extract -> match pipeline, not the learning flywheel.

Example:
    python evaluation/scripts/run_supplier_eval.py \
        --data-dir evaluation/invoices-donut-demo \
        --credentials /path/to/sa.json
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

from eval_lib import flatten_gt, wilson_ci  # noqa: E402
from supplier_master import build_master, expected_code  # noqa: E402


def load_records(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "ground_truth.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"ground_truth.jsonl not found in {data_dir}")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def seller_of(record: dict[str, Any]) -> str:
    return str(flatten_gt(record["ground_truth"]["gt_parse"]).get("seller", "") or "")


def load_sellers(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as fh:
        sellers = [seller_of(json.loads(line)) for line in fh if line.strip()]
    return [s for s in sellers if s]


def run_one(image_path: Path, matcher: Any) -> tuple[dict[str, Any], str]:
    """Run the supplier preview pipeline; never raise (one bad row can't abort)."""
    from app.services.supplier_preview_extractor import extract_supplier_preview

    try:
        return extract_supplier_preview(image_path, matcher), ""
    except Exception:  # noqa: BLE001 - eval must survive per-row failures
        return {}, traceback.format_exc(limit=1).strip()


def evaluate(
    records: list[dict[str, Any]],
    data_dir: Path,
    out_path: Path,
    extra_sellers: list[str] | None = None,
) -> dict[str, Any]:
    from app.services.supplier_matcher import SupplierMatcher

    # Scored suppliers come first so they keep stable codes; distractors follow.
    sellers = [seller_of(r) for r in records] + list(extra_sellers or [])
    master, by_name = build_master(sellers)
    matcher = SupplierMatcher(source=lambda: master)
    print(f"supplier master: {len(master)} distinct suppliers (incl. distractors)", flush=True)

    id_pass = 0
    errors = 0
    total = len(records)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(
            ["file", "expected_code", "expected_name", "actual_code", "actual_name",
             "candidates", "confidence", "method", "id_ok", "error"]
        )
        for idx, rec in enumerate(records, 1):
            seller = seller_of(rec)
            exp = expected_code(seller, by_name)
            image_path = data_dir / rec["file"]
            print(f"[{idx}/{total}] {rec['file']}", flush=True)
            data, error = run_one(image_path, matcher)
            if error:
                errors += 1
            actual_code = str(data.get("vendor_code", "")) if not error else ""
            ok = bool(exp) and actual_code == exp
            id_pass += int(ok)
            writer.writerow([
                rec["file"], exp, master[int(exp) - 50001][1] if exp else "",
                actual_code, str(data.get("vendor_name", "")) if not error else "",
                " | ".join(data.get("supplier_raw_candidates", []) or []) if not error else "",
                data.get("vendor_match_confidence", "") if not error else "",
                data.get("vendor_match_method", "") if not error else "",
                "1" if ok else "0", error,
            ])

    return {"total": total, "errors": errors, "id_pass": id_pass, "master_size": len(master)}


def report(stats: dict[str, Any], out_path: Path) -> None:
    n, k = stats["total"], stats["id_pass"]
    lo, hi = wilson_ci(k, n)
    pct = k / n * 100 if n else 0.0
    print()
    print(f"per-row report -> {out_path.relative_to(REPO_ROOT)}")
    print(f"documents: {n}   master: {stats['master_size']} suppliers   errors: {stats['errors']}")
    print("\nsupplier identification accuracy (correct vendor_code):")
    print(f"  {k}/{n}  {pct:.1f}%   95% Wilson CI [{lo * 100:.1f}%, {hi * 100:.1f}%]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "evaluation" / "invoices-donut-demo")
    parser.add_argument("--limit", type=int, default=0, help="cap number of documents (0 = all)")
    parser.add_argument("--credentials", type=Path, help="path to GC service-account JSON")
    parser.add_argument("--extra-sellers", type=Path, help="ground_truth.jsonl of extra suppliers to load as distractors")
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
    records = load_records(data_dir)
    if args.limit:
        records = records[: args.limit]
    if not records:
        print("no records to evaluate")
        return 1

    extra_sellers = load_sellers(args.extra_sellers) if args.extra_sellers else []

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out_dir / f"supplier_eval_{timestamp}.tsv"

    stats = evaluate(records, data_dir, out_path, extra_sellers=extra_sellers)
    report(stats, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
